# AttackAgent — CLAUDE.md

## Project Overview

AttackAgent 是一个面向授权靶场和 CTF 竞赛的渗透测试 Agent。核心设计理念是**约束推理**而非候选选择——通过框架引导模型做出正确决策，同时不限制模型创造力。采用双路径架构（结构化 + 自由探索），外部安全壳确保操作在授权范围内。

**技术栈：** Python 3.10+，标准库为主，最小化外部依赖。

## Quick Start

```bash
# 运行全部测试（182 个）
python -m unittest discover tests/

# CLI 启动（纯规则模式）
python -m attack_agent --config config/settings.json --max-cycles 12

# CLI 启动（对接 HTTP 靶场）
python -m attack_agent --provider-url http://127.0.0.1:8080

# CLI 启动（接入 LLM）
python -m attack_agent --config config/settings.json --model openai --verbose

# 纯规则模式（无需 LLM，Python API）
python -c "
from attack_agent.platform import CompetitionPlatform
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.platform_models import ChallengeDefinition
provider = InMemoryCompetitionProvider([
    ChallengeDefinition(id='c1', name='Test', category='web',
                        difficulty='easy', target='http://127.0.0.1:8000',
                        description='test'),
])
platform = CompetitionPlatform(provider)
platform.solve_all()
"

# 接入 LLM（Python API）
pip install attack-agent[openai]   # 或 pip install openai>=1.0
# 设置 OPENAI_API_KEY 后传入 model 参数即可启用双路径规划
```

## Architecture (5-Layer)

```
控制层  CompetitionPlatform — solve_all(), run_cycle()
调度层  Dispatcher + LightweightSecurityShell — 状态机驱动，安全壳验证
规划层  EnhancedAPGPlanner — 双路径：结构化(APGPlanner) / 自由探索(ConstraintAwareReasoner)
执行层  WorkerRuntime + PrimitiveAdapter + HttpSessionManager — 9 个原语执行
状态层  StateGraphService — 单一真实源，事件日志
```

## Key Modules

| 模块 | 文件 | 职责 |
|------|------|------|
| CompetitionPlatform | `platform.py` | 主入口，协调 5 层交互 |
| CLI 入口 | `__main__.py` | `python -m attack_agent` 命令行接口 |
| Dispatcher | `dispatcher.py` | 状态机调度，集成安全壳 |
| EnhancedAPGPlanner | `enhanced_apg.py` | 双路径规划，路径选择/切换 |
| ConstraintAwareReasoner | `constraint_aware_reasoner.py` | 约束感知推理，生成自由攻击计划 |
| PathSelectionStrategy | `path_selection.py` | 根据置信度/复杂度选择路径 |
| DynamicPatternComposer | `dynamic_pattern_composer.py` | 从成功案例发现攻击模式 |
| SemanticRetrievalEngine | `semantic_retrieval.py` | TF-IDF 混合检索历史经验 |
| LightweightSecurityShell | `constraints.py` | 轻量级安全壳，执行前验证 + `_check_parameter_scope()` 验证 `step.parameters` URL |
| WorkerRuntime | `runtime.py` | 执行 ActionProgram，9 个原语 |
| HttpSessionManager | `runtime.py` | Cookie 持久化，redirect 跟随 |
| CodeSandbox | `apg.py` | 受限 Python 执行环境 |
| AttackAgentConfig | `config.py` | JSON + dataclass 配置管理 |
| Model Adapters | `model_adapter.py` | OpenAI/Anthropic 适配器 |
| ObservationSummarizer | `observation_summarizer.py` | 观测 payload → 有限长度文本摘要，集成到规划器 |

## Primitives (9)

| 原语 | 真实执行 | 元数据回退 | 说明 |
|------|----------|-----------|------|
| http-request | POST/PUT/DELETE + form/JSON body, cookie jar, redirect | primitive_payloads | 真实 HTTP 客户端 |
| browser-inspect | HTMLParser 解析 + session 共享, 无 localhost 限制 | primitive_payloads | 语义化 HTML 提取 |
| session-materialize | HTTP POST 登录, cookie/token 获取 | primitive_payloads | 会话建立 |
| structured-parse | JSON/HTML/headers 解析 from completed_observations | primitive_payloads | 结构化数据提取 |
| diff-compare | difflib 序列对比 | primitive_payloads | 观测差异检测 |
| artifact-scan | HTTP 下载 + zip/tar 提取 | primitive_payloads | 文件扫描 |
| binary-inspect | ASCII + UTF-8 + UTF-16LE 字串, ELF/PE 头解析 | primitive_payloads | 二进制分析 |
| code-sandbox | 受限 exec(), 允许 hashlib/base64/struct 等安全导入 | metadata 配置 | 代码沙盒 |
| extract-candidate | 多 pattern 正则 + completed_observations 搜索 | primitive_payloads | flag 提取 |

**激活条件：** 真实执行路径在 `instance.metadata` 包含对应 config key 时激活（如 `http_request`, `session_materialize`）；`structured-parse` 和 `diff-compare` 也可通过 `step.parameters` 激活。无 config key 时走 `_consume_metadata` 回退路径。

**session 传递：** `WorkerRuntime.run_task` 为每次执行创建 `HttpSessionManager`，所有步骤共享 cookie jar。`completed_observations` 在步骤间逐步积累，供后续原语引用。

**参数优先级：** `step.parameters` > metadata defaults > hardcoded defaults。5 个原先忽略 `step.parameters` 的原语（browser-inspect, structured-parse, diff-compare, artifact-scan, extract-candidate）现已通过 `_step_param_overrides()` 接受参数覆盖。

## CodeSandbox Allowed

- **Imports:** hashlib, base64, struct, binascii, itertools, collections, math, re, json
- **Syntax:** FunctionDef, Try (except), Assign
- **Builtins:** len, str, int, float, bool, dict, list, set, tuple, sorted, sum, min, max, range, enumerate, zip, any, all, abs, isinstance, ValueError, TypeError, KeyError, IndexError, AttributeError, RuntimeError, Exception, \_\_import\_\_
- **Blocked:** With, ClassDef, Lambda, Raise, Global, Delete, dunder access, unsafe imports (os, sys, subprocess, etc.)

## Configuration

`config/settings.json` → `AttackAgentConfig.from_file()` 加载。子配置：PlatformConfig, DualPathConfig, PatternDiscoveryConfig, SemanticRetrievalConfig, SecurityConfig, MemoryConfig, LoggingConfig, ModelConfig。

**SecurityConstraints 与 SecurityConfig 对齐：** `SecurityConstraints.from_config(SecurityConfig)` 是单一真实源，Dispatcher 和 Platform 均从 `AttackAgentConfig.security` 读取约束值。默认值已统一（`max_http_requests=30`, `max_program_steps=15`, `max_estimated_cost=50.0`）。

**ObservationSummarizer 配置：** `ModelConfig.observation_summary_budget_chars`（默认 2000）驱动 `ObservationSummarizerConfig.max_total_chars`，控制观测摘要总长度。

## Optional Dependencies

```toml
[project.optional-dependencies]
openai     = ["openai>=1.0"]
anthropic  = ["anthropic>=0.20"]
http       = ["requests>=2.28"]       # http-request 增强（当前使用 urllib）
browser    = ["playwright>=1.40"]     # 真实浏览器（当前使用 stdlib HTMLParser）
all-models = ["openai>=1.0", "anthropic>=0.20"]
all        = ["openai>=1.0", "anthropic>=0.20", "requests>=2.28", "playwright>=1.40"]
```

惰性导入模式：model_adapter.py 检测 openai/anthropic 是否可导入，不可用则返回 None。

## Dual-Path Planning

- **model=None → APGPlanner(HeuristicReasoner)** — 纯规则，结构化路径
- **model=xxx → EnhancedAPGPlanner** — 双路径自动切换
  - 结构化路径：LLMReasoner 候选选择
  - 自由探索路径：ConstraintAwareReasoner 约束推理
  - PathSelectionStrategy 根据置信度/复杂度/探索预算动态选择
  - ObservationSummarizer 为两条路径共享，将观测内容注入 LLM 提示词

## Known Limitations

1. **PrimitiveAdapter 真实执行需要靶场 metadata 配置** — 无 config key 且 `step.parameters` 未提供时只能走 metadata 回退
2. **browser-inspect 无 JS 执行** — 使用 stdlib HTMLParser，非真实浏览器；可选 Playwright 适配
3. **语义检索仅 TF-IDF** — InMemoryVectorStore，无真正 embedding
4. **模式图硬编码** — PatternLibrary 6 族关键词匹配，动态发现的模式未回注
5. ~~**LLM 无执行反馈闭环**~~ ✅ 已完成 — ObservationSummarizer + `_extract_current_state()` 现输出实际观测内容，LLM 可迭代调整策略
6. ~~**原语未参数化**~~ ✅ 已完成 — `_resolve_*_specs()` 接受 `step.parameters` 覆盖，`PRIMITIVE_DESCRIPTIONS` 扩展，`_PRIMITIVE_PARAM_KEYS` 白名单已添加

## Development Conventions

- 架构文档 (`docs/ARCHITECTURE.md`) 是唯一真实源，接口变更须先更新文档
- 类型注解 + dataclass(slots=True) + PEP 8
- 测试覆盖率 > 80%，182 个测试全通过
- 元数据回退路径必须保留（backward compat）
- 安全壳验证在 runtime 执行前，critical 级违规阻止执行

## Test Structure

```
tests/
├── test_platform_flow.py      — 平台集成流程 + HTTP 真实执行
├── test_apg_engine.py         — APG 规划器 + CodeSandbox
├── test_state_graph.py        — 状态图服务
├── test_world_state.py        — 世界状态
├── test_provider.py           — Provider 协议
├── test_constraints.py        — 安全壳 + SecurityConstraints 默认值对齐测试
├── test_enhanced_apg.py       — 增强规划器
├── test_constraint_aware_reasoner.py
├── test_dynamic_pattern_composer.py
├── test_semantic_retrieval.py
├── test_path_selection.py
├── test_model_adapter.py
├── test_real_primitives.py    — 真实原语执行（38 个新测试）
├── test_cli.py                — CLI 入口 + HTTP 集成测试
```

## Next Steps (Priority)

- **P0:** ~~SecurityConstraints 与 AttackAgentConfig.security 对齐~~ ✅ 已完成
- **P1:** ~~CLI 入口 (`python -m attack_agent --config ...`), 真实靶场集成测试~~ ✅ 已完成
- **P2:** 启发式自由探索模板(无 LLM 时), 模式回注机制, 接入 embedding 模型
- **P3:** ~~LLM 反馈闭环 + 原语参数化~~ ✅ 已完成