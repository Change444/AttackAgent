# Plan: LLM Feedback Loop + Primitive Parameterization

**状态：** 已审批，待实施
**优先级：** P3（最关键能力缺口，让平台开始解真实 CTF）
**架构文档版本：** 3.3

---

## Context

AttackAgent 当前最大的瓶颈是 **LLM 看不到执行结果**。规划器只读观测的标签（如 "http-response"）和计数（"已有观察: 3 个"），而不是实际的 HTTP 响应内容、发现的端点、凭据等。同时，9 个原语中 6 个完全忽略 `step.parameters`，所有操作参数都来自 `instance.metadata`，LLM 无法指定具体请求路径/方法/body。

**目标：** 让 LLM 进入迭代推理闭环（看到执行结果 → 调整策略 → 再规划），并让原语接受 LLM 提供的具体参数。这两项改动配合后，平台可开始解基础 web 类 CTF 题目。

---

## Phase 1: Observation Summarizer（新模块）

**新增文件:** `attack_agent/observation_summarizer.py`

创建 `ObservationSummarizer` 类，将观测 payload 总结为有限长度的文本供 LLM prompt 使用：

- `ObservationSummarizerConfig`: max_total_chars=2000, max_per_observation_chars=400, max_observations=5
- 按 kind 分派不同总结逻辑：
  - `http-response`: 提取 status_code, url, method, endpoints路径, forms, auth_clues, cookies; text 截断到 200 字符
  - `browser-page`: 提取 title, url, comments, links, forms; rendered_text 截断
  - `session-materialized`: 提取 login_url, status_code, session_type, valid, cookies_obtained
  - 其他 kind 用 generic 总结（top-level keys + text 截断）
- 按 novelty/confidence 排序，取前 5 个观测
- 输出格式：`[http-response] http://127.0.0.1:8000/login POST 200\nendpoints: /login, /admin\nforms: ...`

**配置:** 在 `ModelConfig` (config.py) 添加 `observation_summary_budget_chars: int = 2000`

**文件状态:** 代码已写（observation_summarizer.py, config.py 已修改），测试已写（test_observation_summarizer.py），待运行验证

---

## Phase 2: Primitive Parameterization（runtime.py）

**修改文件:** `attack_agent/runtime.py`

### 2.1 `_resolve_http_request_specs()` (line 348)

当前: metadata absent → return [] → fallback to `_consume_metadata`
改动: metadata absent + `step.parameters` 有 method/path/url → 从 step.parameters 构造 spec dict
现有 metadata 路径不变，但构造 resolved specs 后用 `step.parameters`（排除 required_tags）覆盖 metadata 默认值

### 2.2 `_resolve_browser_inspect_specs()` (line 390)

同上模式: metadata absent + step.parameters 有 path/url → 构造 spec；metadata present → merge step.parameters overrides

### 2.3 `_resolve_session_materialize_specs()` (line 921)

当前: 仅读 metadata，不读 step.parameters
改动: metadata absent + step.parameters 有 login_url/username → 构造 spec；metadata present → merge step.parameters overrides

### 2.4 `_resolve_artifact_scan_specs()` (line 428)

同上模式

### 2.5 `_resolve_binary_inspect_specs()` (line 465 附近)

同上模式

### 2.6 PrimitiveRegistry input_schema (line 1388-1400)

将 placeholder `{"request": "dict"}` 替换为具体参数描述:
```python
PrimitiveActionSpec("http-request", "network/http",
    {"method": "str(GET/POST)", "path": "str", "url": "str", "headers": "dict",
     "json": "dict", "form": "dict", "query": "dict", "timeout": "float"},
    {"observations": "list"}, 1.0, "low")
# 类似更新所有 9 个 spec
```

### 合并优先级规则

`step.parameters` > `metadata defaults` > `hardcoded defaults`

当 metadata 不存在且 step.parameters 不足以构造有效 spec → return [] → `_consume_metadata` 兜底（向后兼容）

---

## Phase 3: ConstraintAwareReasoner 改动

**修改文件:** `attack_agent/constraint_aware_reasoner.py`

### 3.1 `_extract_current_state()` (line 191-205)

替换计数输出为实际内容:
```python
# 旧: parts.append(f"已有观察: {len(record.observations)} 个")
# 新:
if record.observations:
    summary = self._summarizer.summarize_observations(record.observations)
    parts.append(f"已有观察详情:\n{summary}")
# 添加 world_state highlights
ws = record.world_state
if ws.endpoints:
    parts.append(f"已知端点: {'; '.join(f'{e.method} {e.path}' for e in ws.endpoints.values())}")
if ws.credentials:
    parts.append(f"已知凭据: ...")
if ws.findings:
    parts.append(f"已知发现: ...")
```

### 3.2 PRIMITIVE_DESCRIPTIONS (line 99-109)

扩展为含参数文档的描述:
```python
"http-request": "发送HTTP请求。参数: method(GET/POST等), path, headers, json, form, query, url, timeout",
"session-materialize": "物化会话(登录)。参数: login_url, method, form_fields, username, password, headers",
# ... 类似更新所有 9 个
```

### 3.3 CONSTRAINT_AWARE_PROMPT (line 17-59)

`parameters: {{}}` 替换为含参数示例的格式:
```json
"parameters": {{
    "根据工具说明填入具体参数，没有需要的参数时留空{{}}"
}}
```
并增加一个示例 step 展示 http-request 带参数

### 3.4 `_parse_plan_response()` (line 207-246)

添加 `_PRIMITIVE_PARAM_KEYS` 常量，验证 LLM 输出的 parameters keys：
- strip unknown keys（而非拒绝），避免 LLM 幻觉参数导致运行时错误

### 3.5 ConstraintAwareReasoner.__init__

添加 `summarizer` 参数（可选，默认 `ObservationSummarizer()`）

---

## Phase 4: APG Planner 改动

**修改文件:** `attack_agent/reasoning.py`, `attack_agent/apg.py`

### 4.1 ReasoningContext (reasoning.py line 19-30)

添加 `observation_summaries: list[str] = field(default_factory=list)` 字段

### 4.2 LLMReasoner.choose_program() payload (reasoning.py line 104-133)

将 `context.observation_summaries` 加入 payload dict

### 4.3 APGPlanner (apg.py)

- `__init__` 添加 `summarizer` 参数（可选）
- `plan()` 查询字符串中注入 `summarizer.summarize_observations(record.observations)`
- 构建 `ReasoningContext` 时填充 `observation_summaries` 字段

### 4.4 build_episode_entry() (apg.py line 404-424)

- `feature_text` 加入观测内容摘要（改善 EpisodeMemory 检索质量）
- `summary` 从 `{goal} -> {status}` 扩展为含关键发现的一行摘要
- 添加 `summarizer` 参数

### 4.5 StateGraphService (state_graph.py line 31-36)

- 添加 `observation_summarizer = ObservationSummarizer()` 成员
- `record_program()` 调用时传入 summarizer

---

## Phase 5: EnhancedAPG + Config 集成

**修改文件:** `attack_agent/enhanced_apg.py`, `attack_agent/config.py`, `attack_agent/platform.py`, `attack_agent/dispatcher.py`

- EnhancedAPGPlanner 共享 summarizer 实例到子规划器
- config.py: ModelConfig 添加 `observation_summary_budget_chars`（已在 Phase 1 完成）
- platform.py/dispatcher.py: 初始化时从 agent_config.model 读取 budget，构造 ObservationSummarizerConfig

---

## Phase 6: 安全壳参数验证

**修改文件:** `attack_agent/constraints.py`

添加 `_check_parameter_scope()` 方法：
- 验证 step.parameters 中的 url/path/login_url 是否在 allowed_hostpatterns 范围内
- 发现外部 URL → critical 级 ConstraintViolation，阻止执行

---

## Phase 7: FAMILY_PROGRAMS 参数化（保守）

**修改文件:** `attack_agent/apg.py`

为 observation_gate 的 http-request 步骤添加 `method: "GET"` 默认参数；
为 action_template 的 session-materialize 步骤添加 `method: "POST"` 默认参数。
这不会破坏 metadata 路径（merge 时 metadata 会覆盖），但 metadata absent 时给了原语基本参数。

---

## 测试计划

### 新文件: `tests/test_observation_summarizer.py`
- 各 kind 的总结测试（http-response, browser-page, session-materialized, unknown kind）
- 预算截断测试
- 空 observations 测试
- 多观测排序+限制测试

**状态:** 已创建，待运行验证

### 修改现有测试:
- `test_constraint_aware_reasoner.py`: 验证 `_extract_current_state()` 输出含观测内容摘要
- `test_real_primitives.py`: 为每个 `_resolve_*_specs()` 添加 step.parameters override 测试
  - metadata absent + step.parameters 构造 spec
  - step.parameters override metadata 默认值
  - 空 step.parameters + 有 metadata → 行为不变（向后兼容）
- `test_constraints.py`: 验证 `_check_parameter_scope()` 阻止外部 URL
- `test_apg_engine.py`: 验证 enriched episode entry

### 回归: 全部 182 个测试必须在每个 phase 后通过

---

## 实施顺序

1. Phase 1 → Observation Summarizer 新模块 + config 字段（代码已写，待验证）
2. Phase 2 → Runtime _resolve_*_specs() 参数化 + PrimitiveRegistry schema
3. Phase 3 → ConstraintAwareReasoner 改动（依赖 Phase 1 summarizer）
4. Phase 4 → ReasoningContext + APGPlanner + build_episode_entry 改动
5. Phase 5 → EnhancedAPG + Platform/Dispatcher 集成
6. Phase 6 → 安全壳参数验证
7. Phase 7 → FAMILY_PROGRAMS 保守参数化

每个 Phase 完成后：运行测试 → 更新 ARCHITECTURE.md 和 CLAUDE.md

---

## 关键文件清单

| 文件 | Phase | 改动类型 |
|------|-------|----------|
| `attack_agent/observation_summarizer.py` | 1 | 新增 |
| `attack_agent/config.py` | 1 | 修改（ModelConfig 加字段） |
| `attack_agent/runtime.py` | 2 | 修改（6 个 _resolve 函数 + PrimitiveRegistry） |
| `attack_agent/constraint_aware_reasoner.py` | 3 | 修改（_extract_current_state, PRIMITIVE_DESCRIPTIONS, prompt, _parse_plan_response） |
| `attack_agent/reasoning.py` | 4 | 修改（ReasoningContext, LLMReasoner payload） |
| `attack_agent/apg.py` | 4, 7 | 修改（APGPlanner, build_episode_entry, FAMILY_PROGRAMS） |
| `attack_agent/state_graph.py` | 4 | 修改（StateGraphService 加 summarizer） |
| `attack_agent/enhanced_apg.py` | 5 | 修改（共享 summarizer） |
| `attack_agent/platform.py` | 5 | 修改（初始化集成） |
| `attack_agent/dispatcher.py` | 5 | 修改（初始化集成） |
| `attack_agent/constraints.py` | 6 | 修改（_check_parameter_scope） |
| `tests/test_observation_summarizer.py` | 1 | 新增 |
| `tests/test_real_primitives.py` | 2 | 修改（添加参数化测试） |
| `tests/test_constraint_aware_reasoner.py` | 3 | 修改 |
| `tests/test_constraints.py` | 6 | 修改 |
| `tests/test_apg_engine.py` | 4 | 修改 |