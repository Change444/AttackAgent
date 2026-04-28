# AttackAgent 架构文档

**版本：** 4.0
**最后更新：** 2026-04-28
**维护规则：** 本文档记录架构决策和概念关系，**不含代码定义**（dataclass 字段、enum 值、常量、方法签名、伪代码）。字段变更不需更新本文。需引用代码细节时链接源文件，不复制其内容。仅当架构决策本身变更时才需更新。

---

## 1. 项目愿景与设计原则

### 1.1 愿景

构建解题能力极强的渗透测试 Agent，通过框架引导模型做出正确决策，同时不限制模型创造力。系统采用"约束推理"而非"候选选择"的设计理念。

### 1.2 核心价值

- **安全第一**：外部安全壳确保所有操作在授权范围内
- **框架引导**：提供约束条件而非固定选项，引导模型推理
- **渐进增强**：双路径架构确保稳定性，逐步探索创新
- **自适应性**：从实践中学习，动态发现和优化模式
- **可观测性**：完整的决策追踪和事件记录

### 1.3 设计原则

1. **渐进式改进**：保留现有功能，并行添加新能力
2. **约束推理**：通过约束条件引导模型，而非限制选择
3. **动态模式**：从固定模式转向动态发现和学习
4. **语义增强**：从词汇匹配转向语义理解

---

## 2. 五层架构

```
┌─────────────────────────────────────────────────────────┐
│  控制层 (Control Plane)                                  │
│  CompetitionPlatform (platform.py)                      │
│  - solve_all() / run_cycle()                            │
│  - 挑战生命周期管理，model=None/xxx 分支构建规划器       │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  调度层 (Dispatch Layer)                                 │
│  Dispatcher (dispatcher.py)                             │
│  - 状态机：BOOTSTRAP → REASON → EXPLORE → CONVERGE     │
│  - 集成 SecurityShell 验证                              │
│                                                          │
│  LightweightSecurityShell (constraints.py)              │
│  - validate() 执行前约束验证                            │
│  - critical 违规阻止执行                                 │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  规划层 (Planning Layer)                                 │
│  EnhancedAPGPlanner (enhanced_apg.py)                   │
│  - 双路径规划接口                                       │
│                                                          │
│  结构化路径           │  自由探索路径                    │
│  APGPlanner (apg.py) │  model=xxx: ConstraintAware-    │
│  HeuristicReasoner   │    Reasoner                      │
│  LLMReasoner         │  model=None: HeuristicFree-     │
│  PatternLibrary      │    ExplorationPlanner            │
│  EpisodeMemory       │  DynamicPatternComposer          │
│                      │  SemanticRetrievalEngine          │
│                      │  PatternInjector                  │
│                      │  ObservationSummarizer            │
│                      │  PathSelectionStrategy            │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  执行层 (Execution Layer)                                │
│  WorkerRuntime (runtime.py)                             │
│  - 9 个 PrimitiveAdapter 执行                           │
│  - HttpSessionManager 会话持久化                        │
│  - completed_observations 跨步骤数据共享               │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  状态层 (State Layer)                                    │
│  StateGraphService (state_graph.py)                     │
│  - 项目单一真实源                                      │
│  - 事件日志和状态查询                                   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 双路径规划概念

```
规划请求 → EnhancedAPGPlanner
              ↓
     PathSelectionStrategy.select_path()
     评估：置信度、复杂度、探索预算、历史成功率
              ↓
     ┌──────────┴──────────┐
     ↓                      ↓
  结构化路径            自由探索路径
  APGPlanner.plan()    ConstraintAware/HeuristicFree
     ↓                      ↓
  ActionProgram        ActionProgram
     ↓                      ↓
     └──────────┬──────────┘
                ↓
         SecurityShell 验证
                ↓
         WorkerRuntime 执行
```

**路径选择规则**：
- 置信度低（<0.5）+ 复杂度高（>0.7） → 自由探索
- 置信度高（≥0.7） → 结构化
- 其余 → 70% 结构化 / 30% 自由探索

**model 参数决定自由探索路径实现**：
- model=None → HeuristicFreeExplorationPlanner（FAMILY_KEYWORDS 评分 + FAMILY_PROGRAMS 组装）
- model=xxx → ConstraintAwareReasoner（LLM 约束推理 + 参数白名单过滤）

---

## 4. 层职责与交互

| 层 | 关键模块（文件） | 概念职责 | 关键交互 |
|----|-----------------|----------|----------|
| 控制层 | CompetitionPlatform (`platform.py`), CLI (`__main__.py`), Controller (`controller.py`) | 挑战获取、项目生命周期、flag 提交、hint 管理 | 调用 Dispatcher.schedule()，Controller 调用 Provider |
| 调度层 | Dispatcher (`dispatcher.py`), SecurityShell (`constraints.py`) | 状态机驱动执行，安全壳验证 | schedule() → strategy.next_program() → SecurityShell.validate() → runtime.run_task() |
| 规划层 | EnhancedAPG (`enhanced_apg.py`), APGPlanner (`apg.py`), ConstraintAware (`constraint_aware_reasoner.py`), HeuristicFree (`heuristic_free_exploration.py`), PathSelection (`path_selection.py`), DynamicPattern (`dynamic_pattern_composer.py`), SemanticRetrieval (`semantic_retrieval.py`), PatternInjector (`pattern_injector.py`), ObservationSummarizer (`observation_summarizer.py`) | 双路径规划、模式发现、历史检索、观测摘要 | plan() → PathSelection → 结构化/自由探索 → ActionProgram |
| 执行层 | WorkerRuntime (`runtime.py`), PrimitiveAdapter (`runtime.py`), HttpSessionManager (`runtime.py`), CodeSandbox (`apg.py`) | 9 原语真实执行、会话持久化、跨步骤数据共享 | execute() → 适配器分发 → completed_observations 增量填充 |
| 状态层 | StateGraphService (`state_graph.py`) | 项目记录单一源、事件日志、EpisodeMemory | record_program() → build_episode_entry → EpisodeMemory |

---

## 5. 原语参考

| 原语 | 能力概述 | 激活条件 |
|------|----------|----------|
| http-request | HTTP GET/POST/PUT/DELETE，cookie 持久化，重定向跟随，form/JSON body | instance.metadata 含 `http_request` 或 step.parameters 有 url |
| browser-inspect | HTTP GET + HTMLParser 解析（标题/表单/链接/注释），**无 JS 渲染** | instance.metadata 含 `browser_inspect` 或 step.parameters 有 url |
| session-materialize | HTTP POST 登录，cookie/token 获取，仅 form-encoded body | instance.metadata 含 `session_materialize` 或 step.parameters 有 login_url |
| structured-parse | JSON/HTML/headers 解析，从 completed_observations 读取 | step.parameters 有 parse_source/format/extract_fields |
| diff-compare | difflib 序列对比，变更统计 | step.parameters 有 baseline/variant observation IDs |
| artifact-scan | HTTP 下载 + zip/tar 文件名列表（不提取内容） | instance.metadata 含 `artifact_scan` 或 step.parameters 有 location |
| binary-inspect | ASCII/UTF-8/UTF-16LE 字串 + ELF/PE 头解析 | instance.metadata 含 `binary_inspect` 或 step.parameters 有 location |
| code-sandbox | AST 验证后 exec()，允许 hashlib/base64/struct 等安全导入 | step.instruction 含 Python 代码 |
| extract-candidate | 多 pattern 正则匹配 + completed_observations 搜索 | 默认激活 |

**参数优先级**：`step.parameters` > metadata defaults > hardcoded defaults
**参数白名单**：各原语允许的参数键见 `attack_agent/constraint_aware_reasoner.py` `_PRIMITIVE_PARAM_KEYS`
**无配置时回退**：所有原语走 `_consume_metadata` 路径，消费预定义元数据

---

## 6. 安全模型

LightweightSecurityShell (`attack_agent/constraints.py`) 在 runtime 执行前验证 TaskBundle：

- **验证内容**：目标 URL scope、HTTP 请求计数、sandbox 执行计数、步骤数、成本估算、禁止原语组合、参数 URL scope
- **违规等级**：critical → 阻止执行；warning → 仅记录
- **约束值来源**：SecurityConstraints.from_config(SecurityConfig) — 单一源，默认值对齐
- **参数 scope 验证**：`_check_parameter_scope()` 检查 step.parameters 中 URL 类参数是否匹配 allowed_hostpatterns

---

## 7. 配置架构

AttackAgentConfig (`attack_agent/config.py`) 从 `config/settings.json` 加载。

子配置：
- PlatformConfig (`config.py`)
- DualPathConfig (`platform_models.py`)
- PatternDiscoveryConfig (`config.py`)
- SemanticRetrievalConfig (`config.py`)
- SecurityConfig (`config.py`)
- MemoryConfig (`config.py`)
- ModelConfig (`config.py`)
- LoggingConfig (`config.py`)

SecurityConfig 是 SecurityConstraints 的单一源（`from_config()` 工厂方法）。
ModelConfig.observation_summary_budget_chars 驱动 ObservationSummarizerConfig。

字段定义见源文件和 `config/settings.json`，本文不复制。

---

## 8. 设计决策记录

| 决策 | 日期 | 理由 | 状态 |
|------|------|------|------|
| 双路径架构 | 2026-04-25 | 约束推理 > 候选选择；保留模型创造力；结构化路径提供稳定回退 | Active |
| SecurityConstraints 从 SecurityConfig 构建 | 2026-04-27 | 单一源消除硬编码默认值；配置文件驱动约束值 | Active |
| ObservationSummarizer budget | 2026-04-27 | LLM 必须看实际观测内容而非计数；budget 防 prompt 溢出 | Active |
| 元数据回退路径保留 | 2026-04-26 | 向后兼容测试和 fixture；真实执行通过 instance.metadata opt-in | Active |
| model=None 时 HeuristicFreeExploration | 2026-04-28 | 无 LLM 时仍可双路径规划；FAMILY_PROGRAMS 组装替代 LLM | Active |
| PatternInjector 回注动态族 | 2026-04-28 | 模式发现结果回流到结构化路径；动态族命名 dynamic: 前缀 | Active |
| EmbeddingModel Protocol + 惰性适配 | 2026-04-28 | 无包时 FallbackEmbeddingModel 回退；有包时 OpenAI/SentenceTransformer | Active |
| step.parameters 参数白名单过滤 | 2026-04-27 | LLM 幻觉参数剥离而非拒绝；`_PRIMITIVE_PARAM_KEYS` 白名单 | Active |

---

## 9. 源文件地图

```
attack_agent/
├── __init__.py
├── __main__.py              — CLI 入口
├── platform.py              — 平台入口，model=None/xxx 分支
├── controller.py            — flag 提交 + hint 管理
├── dispatcher.py            — 状态机调度 + 安全壳集成
├── state_graph.py           — 状态图服务
├── runtime.py               — 9 原语执行 + HttpSessionManager
├── strategy.py              — 策略层（should_abandon, stage_after_program）
├── apg.py                   — APG 规划器 + PatternLibrary + CodeSandbox + EpisodeMemory
├── reasoning.py             — HeuristicReasoner + LLMReasoner
├── constraints.py           — LightweightSecurityShell + SecurityConstraints
├── models.py                — 世界状态模型（Asset, Service, Endpoint...）
├── platform_models.py       — 核心数据模型 + DualPathConfig + FreeExplorationPlanner Protocol + EmbeddingModel Protocol
├── world_state.py           — WorldState 管理
├── compilers.py             — TaskBundle 编译
├── console.py               — WebConsoleView 输出
├── platform_demo.py         — 平台演示
├── config.py                — AttackAgentConfig + 所有子配置
├── model_adapter.py         — OpenAI/Anthropic 适配器
├── observation_summarizer.py — 观测摘要器
├── enhanced_apg.py          — 增强规划器（双路径）
├── constraint_aware_reasoner.py — LLM 约束推理
├── heuristic_free_exploration.py — 启发式自由探索
├── pattern_injector.py      — 模式回注器
├── dynamic_pattern_composer.py — 动态模式组合器
├── semantic_retrieval.py    — 语义检索引擎（TF-IDF + embedding + CJK）
├── embedding_adapter.py     — Embedding 模型适配器
└── path_selection.py        — 路径选择策略

config/
└── settings.json            — 主配置文件

tests/                       — 测试目录（`ls tests/` 查看完整列表）
```

---

## 10. 已识别架构问题与解决路线

本节记录当前架构的结构性问题和已规划的解决方向。完整问题清单和四阶段解决计划详见 [CHANGELOG.md](CHANGELOG.md) "Current Limitations & Roadmap" 章节。

### 10.1 原语双路径膨胀（问题 A1）

**现状**：runtime.py 1629 行，每个原语有真实执行 + `_consume_metadata` 假数据两条路径。假数据回退让系统"假装在工作"，掩盖真实能力不足。

**解决方向**：删除 `_consume_metadata` 路径。原语要么真执行，要么干净地返回 `status="failed"` 带明确原因。代码量预计减半，行为诚实。

### 10.2 模式图过于静态（问题 A2）

**现状**：PatternLibrary.build() 从关键词一次性构建模式图，运行中只标记节点 resolved/failed，不重组或增族。DynamicPatternComposer 需要 3+ 成功案例才能发现模式，但系统 3 水失败就放弃（catch-22：需要成功数据发现模式 → 在发现模式前就放弃）。

**解决方向**：
- 放弃阈值从 3 放到 8（Phase 1 配置调优）
- 扩展族数量从 6 到 14+（Phase 3 R9）
- 长期：模式图应支持运行中动态增族

### 10.3 Dispatcher/Strategy 过度间接（问题 A3）

**现状**：Dispatcher → StrategyLayer → EnhancedAPGPlanner → PathSelectionStrategy → APGPlanner/ConstraintAwareReasoner → HeuristicReasoner/LLMReasoner，6 层间接调用，但最终效果只是"选一个族模板执行它"。

**解决方向**：短期不重构（功能还不完整）。Phase 4 合并 Dispatcher + StrategyLayer，减少间接层。

### 10.4 核心能力缺口

| 缺口类别 | 关键问题 | 影响 |
|----------|---------|------|
| Provider | 无 CTFd 适配器 + 无认证 | 连不上真实靶场 |
| browser-inspect | 不执行 JS、丢弃 script 内容 | 40% CTF 题（web JS 类）不能解 |
| http-request | 无 multipart/Basic Auth/SSL 自签名 | 文件上传 + 认证题不能解 |
| session-materialize | 无 CSRF/JSON body/多步认证 | 现代 web 应用登录不能解 |
| 规划策略 | 6 族过浅 + 步骤空模板 + 3 水放弃 | 多数类别无匹配计划 |
| code-sandbox | 禁止 class/lambda/with + 无 crypto | 密码题和复杂算法不能解 |