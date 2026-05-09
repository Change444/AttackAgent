# AttackAgent 架构文档

**版本：** 4.13
**最后更新：** 2026-05-09
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
│  - 集成 SecurityShell 验证 + 策略逻辑(stagnation/submit)│
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
| 调度层 | Dispatcher (`dispatcher.py`), SecurityShell (`constraints.py`), SubmitClassifier/TaskPromptCompiler (`strategy.py`) | 状态机驱动执行，安全壳验证，stagnation/submit 策略逻辑，cycle/program/outcome trace | schedule() → planner.plan() → SecurityShell.validate() → runtime.run_task() + should_abandon/stage_after_program |
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
**无配置时行为**：原语返回 `_clean_fail` 干净失败，不再假装工作

---

## 6. 安全模型

LightweightSecurityShell (`attack_agent/constraints.py`) 在 runtime 执行前验证 TaskBundle：

- **验证内容**：目标 URL scope、HTTP 请求计数、sandbox 执行计数、步骤数、成本估算、禁止原语组合、参数 URL scope
- **违规等级**：critical → 阻止执行；warning → 仅记录
- **约束值来源**：SecurityConfig — 单一源，LightweightSecurityShell 直接持有 SecurityConfig
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

SecurityConfig 是 LightweightSecurityShell 的约束单一源（直接持有，无需中间桥接类）。
ModelConfig.observation_summary_budget_chars 驱动 ObservationSummarizerConfig。

字段定义见源文件和 `config/settings.json`，本文不复制。

---

## 8. 设计决策记录

| 决策 | 日期 | 理由 | 状态 |
|------|------|------|------|
| 双路径架构 | 2026-04-25 | 约束推理 > 候选选择；保留模型创造力；结构化路径提供稳定回退 | Active |
| SecurityConstraints 从 SecurityConfig 构建 | 2026-04-27 | 单一源消除硬编码默认值；配置文件驱动约束值 | Superseded → v4.1 SecurityConstraints 删除，SecurityConfig 直接作为约束源 |
| 合并 StrategyLayer → Dispatcher | 2026-04-30 | 消除 6 层间接调用；策略逻辑内联到调度层 | Active |
| ObservationSummarizer budget | 2026-04-27 | LLM 必须看实际观测内容而非计数；budget 防 prompt 溢出 | Active |
| 元数据回退路径保留 | 2026-04-26 | 向后兼容测试和 fixture；真实执行通过 instance.metadata opt-in | Active |
| model=None 时 HeuristicFreeExploration | 2026-04-28 | 无 LLM 时仍可双路径规划；FAMILY_PROGRAMS 组装替代 LLM | Active |
| PatternInjector 回注动态族 | 2026-04-28 | 模式发现结果回流到结构化路径；动态族命名 dynamic: 前缀 | Active |
| EmbeddingModel Protocol + 惰性适配 | 2026-04-28 | 无包时 FallbackEmbeddingModel 回退；有包时 OpenAI/SentenceTransformer | Active |
| step.parameters 参数白名单过滤 | 2026-04-27 | LLM 幻觉参数剥离而非拒绝；`_PRIMITIVE_PARAM_KEYS` 白名单 | Active |
| Thinking model 支持 | 2026-05-06 | Anthropic extended thinking（budget_tokens + temperature=1）+ thinking 耗尽 output budget 时自动 re-request | Active |
| Verbose LLM trace | 2026-05-06 | `╔══ LLM CALL ══` banner + response trace，用于调试真实 CTF 解题过程 | Active |
| SDK max_retries=0 | 2026-05-06 | OpenAI/Anthropic SDK 默认重试累积等待过长；max_retries=0 由 model_adapter 自行实现指数退避 | Active |
| 清除 Anthropic 环境变量 | 2026-05-06 | Anthropic SDK 自动读取 ANTHROPIC_API_KEY/AUTH_TOKEN/BASE_URL，可能冲突导致 401 | Active |
| _safe_print GBK 兼容 | 2026-05-06 | Windows 终端默认 GBK 编码，LLM 响应含非 GBK 字符时 UnicodeEncodeError | Active |
| Team Runtime Phase A 协议抽取 | 2026-05-09 | 协议抽取先于协议冻结；先建 legacy → vNext 映射再逐阶段收拢；不改变任何现有行为 | Active |
| Team Runtime Phase B Blackboard Event Journal | 2026-05-09 | Append-only SQLite event store + materialized state rebuild；causal_ref 因果链；rebuild_state 消费全部 EventType | Active |
| Team Runtime Phase C 同步 ManagerScheduler | 2026-05-09 | 纯决策 TeamManager（7 函数→StrategyAction）+ 同步 SyncScheduler（schedule_cycle/run_project/run_all）；决策阈值从 Dispatcher 移植；候选 flag 优先于 abandon | Active |
| Team Runtime Phase D ContextCompiler + MemoryService + IdeaService | 2026-05-09 | ManagerContext/SolverContextPack 上下文编译；MemoryService（store/query/dedupe/failure_boundaries）；IdeaService（propose/claim/verify/fail）；Blackboard _apply_event 增强（kind/entry_id/idea 状态演变） | Active |
| Team Runtime Phase E PolicyHarness + HumanReviewGate | 2026-05-09 | 统一安全决策入口 validate_action()→PolicyDecision（risk threshold + budget + rate limit + submit governance）；HumanReviewGate（create/resolve/list_pending/auto_expire）；reject→failure boundary；所有决策写入 event journal | Active |
| Team Runtime Phase F SolverSession 生命周期 | 2026-05-09 | 显式长生命周期 SolverSession（状态机 created→assigned→running→waiting_review→completed/failed/expired/cancelled）；SolverSessionManager 并发控制（max_project_solvers）；Blackboard session_index（latest-wins per solver_id）替代简单 append | Active |
| Team Runtime Phase G MergeHub + Verifier + Observer | 2026-05-09 | 多 Solver 结果归并（MergeHub：事实去重+冲突检测、idea 去重+优先级仲裁、flag 共识 boost +0.1/solver、failure boundary 合并）；提交验证内部 pass（SubmissionVerifier：flag 格式/evidence chain/budget/completeness）；只读异常检测（Observer：repeated_action/low_novelty/ignored_boundary/stagnation/tool_misuse → CHECKPOINT 事件） | Active |
| Team Runtime Phase H TeamRuntime + CLI + API | 2026-05-09 | TeamRuntime 串联全部 Phase A~G 组件（run_project/get_status/submit_flag/resolve_review/observe/replay）；click + rich CLI（run/status/replay/reviews/review approve/reject/modify/observe/serve）；FastAPI 只读 + review 治理 API（8 GET + 3 POST）；CLI/API 先于 Web UI；不修改任何现有文件核心逻辑 | Active |

---

## 9. 源文件地图

```
attack_agent/
├── __init__.py
├── __main__.py              — CLI 入口
├── platform.py              — 平台入口，model=None/xxx 分支
├── controller.py            — flag 提交 + hint 管理
├── dispatcher.py            — 状态机调度 + 安全壳集成 + 策略逻辑(stagnation/submit)
├── state_graph.py           — 状态图服务
├── runtime.py               — 9 原语执行 + HttpSessionManager
├── strategy.py              — SubmitClassifier + TaskPromptCompiler
├── apg.py                   — APG 规划器 + PatternLibrary + CodeSandbox + EpisodeMemory
├── reasoning.py             — HeuristicReasoner + LLMReasoner
├── constraints.py           — LightweightSecurityShell（直接持有 SecurityConfig）
├── models.py                — 世界状态模型（Asset, Service, Endpoint...）
├── platform_models.py       — 核心数据模型 + DualPathConfig + FreeExplorationPlanner Protocol + EmbeddingModel Protocol
├── world_state.py           — WorldState 管理
├── compilers.py             — TaskBundle 编译
├── console.py               — WebConsoleView 输出
├── platform_demo.py         — 平台演示
├── config.py                — AttackAgentConfig + 所有子配置
├── model_adapter.py         — OpenAI/Anthropic 适配器（thinking model + verbose trace + GBK safe_print）
├── observation_summarizer.py — 观测摘要器
├── enhanced_apg.py          — 增强规划器（双路径）
├── constraint_aware_reasoner.py — LLM 约束推理
├── heuristic_free_exploration.py — 启发式自由探索
├── pattern_injector.py      — 模式回注器
├── dynamic_pattern_composer.py — 动态模式组合器
├── semantic_retrieval.py    — 语义检索引擎（TF-IDF + embedding + CJK）
├── embedding_adapter.py     — Embedding 模型适配器
├── path_selection.py        — 路径选择策略
└── team/                    — Team Runtime vNext 子包（Phase A~H）
    ├── __init__.py           — 子包入口
    ├── protocol.py           — Phase A 协议 dataclass + enum + legacy 映射 + 序列化
    ├── blackboard_config.py  — Phase B Blackboard 配置（db_path）
    ├── blackboard.py         — Phase B+F BlackboardService（SQLite event journal + materialized state rebuild + idea_index/session_index + check_same_thread=False）
    ├── manager.py            — Phase C TeamManager（7 决策函数→StrategyAction）+ ManagerConfig
    ├── scheduler.py          — Phase C SyncScheduler（schedule_cycle/run_project/run_all）+ SchedulerConfig
    ├── context.py            — Phase D ContextCompiler（compile_manager_context / compile_solver_context）
    ├── memory.py             — Phase D MemoryService（store/query_by_kind/query_by_confidence/dedupe/get_failure_boundaries/get_deduped_entries）
    ├── ideas.py              — Phase D IdeaService（propose/claim/mark_verified/mark_failed/list_available/get_best_unclaimed）
    ├── policy.py             — Phase E PolicyHarness（validate_action→PolicyDecision）+ PolicyConfig + RiskThresholds
    ├── review.py             — Phase E HumanReviewGate（create_review/resolve_review/list_pending_reviews/auto_expire_reviews）
    ├── solver.py             — Phase F SolverSessionManager（状态机 + 并发控制 + 生命周期管理）+ SolverSessionConfig
    ├── merge.py              — Phase G MergeHub（merge_facts/merge_ideas/merge_failure_boundaries/arbitrate_flags）
    ├── observer.py           — Phase G Observer（detect_* + generate_report → CHECKPOINT 事件）
    ├── submission.py         — Phase G SubmissionVerifier（verify_flag_format/evidence_chain/budget/completeness/run_all_passes）
    ├── runtime.py            — Phase H TeamRuntime（串联入口 + submit_flag/resolve_review/observe/replay）+ TeamRuntimeConfig/ProjectStatusReport/SubmissionResult
    ├── cli.py                — Phase H click + rich CLI（run/status/replay/reviews/review approve/reject/modify/observe/serve）
    └── api.py                — Phase H FastAPI（8 GET + 3 POST review actions + CORS + lifespan）

config/
└── settings.json            — 主配置文件

scripts/
└── local_range.py           — 本地 CTF 靶场服务器（4 题，CompetitionProvider REST API + 挑战页面）

tests/                       — 测试目录（`ls tests/` 查看完整列表）
```

---

## 10. 已识别架构问题与解决路线

本节记录当前架构的结构性问题和已规划的解决方向。完整问题清单和四阶段解决计划详见 [CHANGELOG.md](CHANGELOG.md) "Current Limitations & Roadmap" 章节。

### 10.1 原语双路径膨胀（问题 A1 — 已解决 ✅）

**已解决**：runtime.py 1502 行（原 1629 行），`_consume_metadata` 假数据路径已删除（v3.8）。原语要么真执行，要么干净地返回 `status="failed"` 带明确原因（`_clean_fail`）。行为诚实。

### 10.2 模式图过于静态（问题 A2）

**现状**：PatternLibrary.build() 从关键词一次性构建模式图，运行中只标记节点 resolved/failed，不重组或增族。DynamicPatternComposer 需要 3+ 成功案例才能发现模式，但系统 3 水失败就放弃（catch-22：需要成功数据发现模式 → 在发现模式前就放弃）。

**解决方向**：
- 放弃阈值从 3 放到 8（Phase 1 配置调优）
- 扩展族数量从 6 到 14+（Phase 3 R9）
- 长期：模式图应支持运行中动态增族

### 10.3 Dispatcher/Strategy 过度间接（问题 A3 — 已解决 ✅）

**已解决**：StrategyLayer 合并入 Dispatcher（v4.1）。原来 6 层间接调用（Dispatcher → StrategyLayer → EnhancedAPGPlanner → PathSelectionStrategy → APGPlanner/ConstraintAwareReasoner → HeuristicReasoner/LLMReasoner），现在 Dispatcher 直接持有 planner，策略逻辑（stagnation/submit/stage）内联到 Dispatcher。

### 10.4 核心能力缺口

| 缺口类别 | 关键问题 | 影响 |
|----------|---------|------|
| Provider | 无 CTFd 适配器 + 无认证 | 连不上真实靶场 |
| browser-inspect | 不执行 JS、丢弃 script 内容 | 40% CTF 题（web JS 类）不能解 |
| http-request | 无 multipart/Basic Auth/SSL 自签名 | 文件上传 + 认证题不能解 |
| session-materialize | 无 CSRF/JSON body/多步认证 | 现代 web 应用登录不能解 |
| 规划策略 | 6 族过浅 + 步骤空模板 + 3 水放弃 | 多数类别无匹配计划 |
| code-sandbox | 禁止 class/lambda/with + 无 crypto | 密码题和复杂算法不能解 |