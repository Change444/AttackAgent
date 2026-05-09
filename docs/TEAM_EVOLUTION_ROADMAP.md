# AttackAgent Team Runtime 演进路线图

**版本：** 1.1
**创建日期：** 2026-05-09
**依据：** `docs/TEAM_RUNTIME_DESIGN.md`（目标蓝图）+ 当前代码库评估
**状态：** Phase A+B+C+D+E+F+G+H 已完成 ✅，Phase I 规划中

---

## 一、当前项目现状

### 1.1 已有的 Team Runtime 雏形

| 目标设计组件 | 当前近似实现 | 主要差距 |
|---|---|---|
| **Blackboard** | `StateGraphService` + `ProjectRecord` + `WorldState` | 非 durable，事件模型不够结构化 |
| **ManagerScheduler** | `Dispatcher.schedule()` + `CompetitionPlatform.run_cycle()` | 无独立 Manager 抽象，无 durable lease |
| **SolverSession** | `TaskBundle` + `WorkerRuntime.run_task()` + `WorkerLease` / `WorkerPool` | 缺少显式长生命周期会话实体 |
| **Memory / IdeaBoard** | `EpisodeMemory` + `HandoffMemory` | 粒度轻，缺少 `ContextPack` / `FailureBoundary` / `IdeaEntry` |
| **PolicyHarness** | `SubmitClassifier` + primitive gating + `LightweightSecurityShell` + `CodeSandbox` | 安全策略分散，无统一 decision object |
| **ToolBroker** | `PrimitiveRegistry` + `PrimitiveAdapter` + `WorkerRuntime` | 无 broker 协议、无 policy preflight、无异步执行 |
| **Console / Web UI** | `WebConsoleView` 文本渲染 | 实际是文本视图，不是 Web UI |
| **Observer / Verifier** | 部分 reasoning / strategy 检查逻辑 | 没有独立角色服务 |
| **Human Review** | 仅有 `SubmitClassifier` 自动分类 | 无人工审批流 |
| **MergeHub** | 仅有 handoff 编译 + state upsert | 无正式归并子系统 |
| **Replay / Evaluation** | 测试 + run journal 雏形 | 无完整重放引擎 |
| **CLI team 命令** | 无 | 只有 `python -m attack_agent.platform_demo` |

### 1.2 核心判断

**设计书方向正确，但它是 vNext 目标架构蓝图，不适合作为直接施工顺序。**

原因：

1. 当前项目是紧凑的同步单进程平台，4/4 本地 CTF baseline 已通过 327 测试验证。
2. 设计书描述的是"多 Solver 协作平台"，当前最大瓶颈是状态连贯性和调度边界，而不是并发数量。
3. 设计书原 9 阶段顺序中，Phase 1 就要 SQLite Blackboard + API，Phase 7 才有 Web UI——但 Phase D（ContextCompiler / Memory / FailureBoundary）本应是 Phase 4 的核心，却被放在了靠后位置。
4. PolicyHarness 在设计书中太晚出现（隐含在 Phase 2），但工具能力扩展（Phase 8）却排在 Replay（Phase 9）之前——这会导致扩工具后安全策略继续分散。

### 1.3 当前测试保护策略

演进过程中必须保持：

```bash
# 本地单元测试
python -m unittest discover tests/

# 纯规则模式
python -m attack_agent.platform_demo

# 本地靶场（如有）
python scripts/local_range.py
```

默认保持单进程、同步、`concurrency=1`，确保不破坏现有 baseline。

---

## 二、演进总原则

1. **不重写当前 compact loop**——在现有架构上做渐进抽取，不做颠覆性重构。
2. **协议抽取先于协议冻结**——先建立 legacy → vNext 兼容映射，再逐阶段收拢。
3. **同步 ManagerScheduler 先行**——不急于 async queue / 分布式 worker / Web UI。
4. **ContextCompiler 和 FailureBoundary 提前**——多 Solver 的核心是上下文一致性和失败路径复用，不是并发数量。
5. **PolicyHarness 早于 ToolBroker 扩展**——避免工具面扩大后安全策略继续分散。
6. **CLI/API 先于 Web UI**——runtime 稳定后再暴露操作面。

---

## 三、调整后的阶段路线

### Phase A — 协议抽取与兼容映射 ✅ 已完成

**目标：** 从现有代码抽取最小 vNext 协议，建立 legacy → vNext 映射，不破坏当前测试。

**主要工作：**

- 新增 `attack_agent/team/protocol.py`。
- 定义最小协议子集：
  - `TeamProject`（项目真相源）
  - `StrategyAction`（Manager 调度动作）
  - `SolverSession`（Solver 长生命周期状态）
  - `MemoryEntry`（结构化事实、凭据、endpoint、失败边界）
  - `IdeaEntry`（可 claim 的攻击路线或假设）
  - `FailureBoundary`（已验证失败路径）
  - `PolicyDecision`（统一安全决策）
  - `ReviewRequest`（人工审批请求）
  - `HumanDecision`（人工审批结果）
- 建立 legacy 映射：
  - `ProjectRecord` / `WorldState` → Blackboard project / facts
  - `TaskBundle` → `SolverSession` + executable action context
  - `WorkerLease` → session lease
  - `EpisodeMemory` / `HandoffMemory` → memory entries
  - `SubmitClassifier` output → policy / review decision

**关键文件：**

- `attack_agent/platform_models.py`（核心协议对象）
- `attack_agent/state_graph.py`（ProjectRecord / WorldState）
- `attack_agent/strategy.py`（SubmitClassifier）
- 新增 `attack_agent/team/__init__.py`
- 新增 `attack_agent/team/protocol.py`

**验证：**

- 当前测试全部继续通过。
- 新增 protocol dataclass / serialization 测试。
- 新增 legacy object → vNext protocol mapping 测试。

---

### Phase B — Blackboard Event Journal 先行 ✅ 已完成

**目标：** 先做 append-only event journal + materialized state，不急于完整 API / Web 数据库。

**主要工作：**

- 新增 `attack_agent/team/blackboard_config.py`（BlackboardConfig: db_path）。
- 新增 `attack_agent/team/blackboard.py`。
- BlackboardService SQLite 第一版：
  - `append_event(project_id, event_type, payload, source, causal_ref)` — 不可变追加，自动生成 event_id + timestamp（ISO 8601），可选 causal_ref 因果链追踪
  - `load_events(project_id)` — 按 project_id + timestamp 排序读取全部事件
  - `rebuild_state(project_id)` — 从事件重建 materialized project state（返回 TeamProject + facts / ideas / sessions 列表）
  - `list_facts(project_id)` / `list_ideas(project_id)` / `list_sessions(project_id)` — 按 kind 过滤
  - `export_run_log(project_id)` — 导出完整事件日志为 JSON
- 事件 schema 预留 Replay 需求：causal_ref 因果链、不可变追加、ISO 8601 timestamp
- rebuild_state 消费 EventType 全部子类型：project_upserted → TeamProject，observation → MemoryEntry(fact)，candidate_flag → IdeaEntry + MemoryEntry，worker_assigned → SolverSession，action_outcome(failed) → MemoryEntry(failure_boundary)，submission → project.status 更新，security_validation(deny) → MemoryEntry(failure_boundary)
- SQLite 数据库路径默认 data/blackboard.db（BlackboardConfig 可配置），首次启动自动建表
- 保持 StateGraphService 作为兼容 facade，不修改任何现有文件

**关键文件：**

- 新增 `attack_agent/team/blackboard.py`
- 新增 `attack_agent/team/blackboard_config.py`
- 新增 `tests/test_team_blackboard.py`

**验证：**

- 366 测试全通过（351 原有 + 15 新增）。
- SQLite append / load round-trip ✅
- event ordering（timestamp 递增）✅
- rebuild_state 从事件重建出正确的 TeamProject + facts / ideas / sessions ✅
- crash / reload 后数据可恢复 ✅
- causal_ref 链式追踪 ✅
- export_run_log 输出完整 JSON ✅

---

### Phase C — 同步 ManagerScheduler ✅ 已完成

**目标：** 把控制面抽出来，仍保持同步执行。

**主要工作：**

- 新增 `attack_agent/team/manager.py`。
- 新增 `attack_agent/team/scheduler.py`。
- 将 `CompetitionPlatform.run_cycle()` 与 `Dispatcher.schedule()` 中的团队级决策抽象为 `StrategyAction`。
- Manager 统一负责：
  - project admission
  - stage transition（BOOTSTRAP → REASON → EXPLORE → CONVERGE）
  - worker / session claim / heartbeat / release
  - timeout / requeue / converge / abandon
  - submit 前判断
- 保留当前 `Dispatcher` 作为 legacy solver runner / scheduler backend。
- Worker / Runtime 只返回 outcome / events，不直接拥有协议状态。

**关键文件：**

- `attack_agent/platform.py`（CompetitionPlatform 主入口）
- `attack_agent/dispatcher.py`（Dispatcher 调度逻辑）
- `attack_agent/runtime.py`（WorkerRuntime / WorkerPool）
- 新增 `attack_agent/team/manager.py`
- 新增 `attack_agent/team/scheduler.py`

**验证：**

- 396 测试全通过（366 原有 + 30 新增）。
- TeamManager.admit_project 返回 LAUNCH_SOLVER ✅
- TeamManager.decide_stage_transition 各阶段转换正确（bootstrap→reason→explore→converge/abandon） ✅
- TeamManager.handle_solver_timeout 返回 STEER_SOLVER(requeue) / ABANDON ✅
- TeamManager.decide_submit 返回 SUBMIT_FLAG / CONVERGE / ABANDON ✅
- TeamManager.decide_convergence 返回 CONVERGE / ABANDON / STEER_SOLVER ✅
- SyncScheduler.schedule_cycle 产生 StrategyAction 列表并写入 Blackboard ✅
- SyncScheduler.run_project 循环直到 done / abandoned ✅
- SyncScheduler.run_all 处理多个项目 ✅
- 所有 StrategyAction 写入 Blackboard event journal 可查询 ✅

---

### Phase D — ContextCompiler + Memory/Idea/FailureBoundary ✅ 已完成

**目标：** 多 Solver 前先解决"每轮拿什么上下文"和"失败路径如何阻止重复劳动"。

**主要工作：**

- 新增 `attack_agent/team/context.py`。
- 新增 `attack_agent/team/memory.py`。
- 新增 `attack_agent/team/ideas.py`。
- 定义 ContextPack 最小版本：
  - `ManagerContext`：全局态势（project state、solver 状态列表、待审批列表、候选 flag 列表、停滞点列表、资源状态）
  - `SolverContextPack`：profile、active idea、局部记忆（最近 N 条 MemoryEntry）、相关全局事实（跨 solver 共享的 fact/credential/endpoint）、inbox（未处理的 ReviewRequest）、failure boundaries（已验证失败路径列表）
- MemoryService 实现：
  - `store_entry(project_id, entry: MemoryEntry)` — 存入 MemoryEntry，FAILURE_BOUNDARY 写入 ACTION_OUTCOME 事件，其他 kind 写入 OBSERVATION 事件（payload 保留 kind/entry_id/evidence_refs）
  - `query_by_kind(project_id, kind, limit=20)` — 从 materialized state 按 kind 过滤
  - `query_by_confidence(project_id, min_confidence, limit=10)` — 高置信度事实优先
  - `dedupe(project_id)` — 返回重复条目数量（基于 kind:content 相同）
  - `get_failure_boundaries(project_id)` — 从 MemoryEntry 转换为 FailureBoundary 对象
  - `get_deduped_entries(project_id, kind, limit)` — 去重后保留最高置信度条目
- IdeaService 实现：
  - `propose(project_id, description, priority=100)` — 创建 IdeaEntry，写入 CANDIDATE_FLAG 事件（payload 保留 idea_id/status/priority）
  - `claim(project_id, idea_id, solver_id)` — 标记 idea 为 claimed，写入 CANDIDATE_FLAG 事件（status=claimed）
  - `mark_verified(project_id, idea_id)` — 标记 idea 为 verified
  - `mark_failed(project_id, idea_id, failure_boundary_ids)` — 标记 idea 为 failed，写入 CANDIDATE_FLAG + ACTION_OUTCOME 事件
  - `list_available(project_id, solver_id)` — 列出未 claimed 或被指定 solver claimed 的 ideas
  - `get_best_unclaimed(project_id)` — 最高优先级未 claimed idea
- ContextCompiler 实现：
  - `compile_manager_context(project_id, blackboard)` — 从 Blackboard materialized state + events 编译 Manager 全局上下文
  - `compile_solver_context(project_id, solver_id, blackboard)` — 从 Blackboard + MemoryService + IdeaService 编译 Solver 局部上下文
  - 编译逻辑第一版从现有数据翻译：
    - ManagerContext.project_state ← Blackboard.rebuild_state().project
    - ManagerContext.solver_states ← Blackboard.list_sessions()
    - ManagerContext.candidate_flags ← Blackboard.list_ideas()（IdeaStatus.PENDING）
    - ManagerContext.stagnation_points ← TeamManager._compute_stagnation()
    - SolverContextPack.local_memory ← MemoryService.query_by_kind(project_id, FACT, limit=5)
    - SolverContextPack.failure_boundaries ← MemoryService.get_failure_boundaries(project_id)
    - SolverContextPack.active_idea ← IdeaService.get_best_unclaimed(project_id)
    - SolverContextPack.global_facts ← MemoryService.query_by_confidence(project_id, 0.7, limit=10)
- Blackboard `_apply_event` 增强：
  - OBSERVATION 事件从 payload 读取 `kind` 字段（而非硬编码 FACT），支持 CREDENTIAL/ENDPOINT/HINT 等 kind 保留
  - OBSERVATION/ACTION_OUTCOME 事件从 payload 读取 `entry_id` 字段，保留 MemoryService 写入的 ID
  - CANDIDATE_FLAG 事件从 payload 读取 `idea_id`/`status`/`solver_id` 字段，支持 idea 状态演变
  - `rebuild_state` 引入 `idea_index: dict[str, IdeaEntry]`，每个 idea_id 的最新 CANDIDATE_FLAG 事件胜出（解决 append-only journal 中 idea 状态演变问题）

**关键文件：**

- 新增 `attack_agent/team/context.py`
- 新增 `attack_agent/team/memory.py`
- 新增 `attack_agent/team/ideas.py`
- 修改 `attack_agent/team/blackboard.py`（_apply_event 增强）
- 新增 `tests/test_team_context.py`
- 新增 `tests/test_team_memory.py`
- 新增 `tests/test_team_ideas.py`

**验证：**

- 447 测试全通过（396 原有 + 51 新增）。
- MemoryService store/query/dedupe/get_failure_boundaries ✅
- IdeaService propose/claim/mark_verified/mark_failed/list_available/get_best_unclaimed ✅
- ContextCompiler 从 Blackboard 事件编译出正确 ManagerContext/SolverContextPack ✅
- failure boundary 注入后不重复同类失败路径 ✅
- memory dedupe 测试 ✅
- Blackboard rebuild_state 正确保留 MemoryKind/entry_id/idea 状态演变 ✅

---

### Phase E — PolicyHarness + HumanReviewGate ✅ 已完成

**目标：** 把安全、预算、提交治理和人工审批统一起来。

**主要工作：**

- 新增 `attack_agent/team/policy.py`。
- PolicyHarness 统一安全决策入口 `validate_action()`：
  - risk threshold 映射（critical→deny, high→needs_review, medium→allow, low→allow）
  - primitive visibility 检查 → deny forbidden primitives
  - budget check → budget_exceeded
  - rate limit check → rate_limit
  - submit_flag 特殊处理：requires_review=True 或 risk_level=high/critical → needs_review
- PolicyConfig / RiskThresholds 可配置
- PolicyDecision 7 种结果：allow / deny / needs_review / needs_human / redact / rate_limit / budget_exceeded
- 每个 PolicyDecision 写入 Blackboard event journal（EventType.SECURITY_VALIDATION）
- 新增 `attack_agent/team/review.py`。
- HumanReviewGate 纯逻辑服务：
  - create_review → 写入 SECURITY_VALIDATION 事件（payload 含 review 详情）
  - resolve_review → 更新状态（approved/rejected/modified），写入 resolution 事件（causal_ref 关联 review_id）
  - list_pending_reviews → 从 event journal 重建 pending 请求列表
  - auto_expire_reviews → 超时未决定的 review 按 timeout_policy 自动 reject，记录 failure boundary
- reject 后记录 ACTION_OUTCOME failure boundary 到 Blackboard
- 不修改任何现有文件（constraints.py、strategy.py、dispatcher.py、platform.py）

**关键文件：**

- 新增 `attack_agent/team/policy.py`
- 新增 `attack_agent/team/review.py`
- 新增 `tests/test_team_policy.py`
- 新增 `tests/test_team_review.py`

**验证：**

- 475 测试全通过（447 原有 + 28 新增）。
- PolicyHarness.validate_action 返回 allow/deny/needs_review/budget_exceeded/rate_limit ✅
- critical risk → deny ✅
- high risk → needs_review ✅
- medium risk → allow ✅
- low risk → allow ✅
- submit_flag + high risk → needs_review ✅
- submit_flag + requires_review → needs_review ✅
- budget exceeded → budget_exceeded ✅
- rate limit exceeded → rate_limit ✅
- PolicyDecision 写入 Blackboard event journal 可查询 ✅
- HumanReviewGate.create_review 写入 Blackboard ✅
- HumanReviewGate.resolve_review 更新状态（approved/rejected） ✅
- HumanReviewGate.list_pending_reviews ✅
- auto_expire_reviews 按 timeout_policy 自动 reject ✅
- approve 后 PolicyReviewIntegration 验证链路 ✅
- reject 后记录 failure boundary 到 Blackboard ✅
- 自定义 RiskThresholds 配置生效 ✅

---

### Phase F — SolverSession 生命周期与有限多 Session ✅ 已完成

**目标：** 实现显式长生命周期 SolverSession，然后再有限并发。

**主要工作：**

- 新增 `attack_agent/team/solver.py`。
- SolverSessionManager + SolverSessionConfig（max_project_solvers=1, session_timeout_seconds=300, budget_per_session=20.0）。
- 状态机严格定义：`created` → `assigned` → `running` → `waiting_review` → `completed` / `failed` / `expired` / `cancelled`。
- 非法状态转换返回 None（不写入事件）。
- 方法：create_session / create_and_persist / claim_session / start_session / heartbeat / complete_session / expire_session / cancel_session / get_session / list_sessions / create_session_from_bundle。
- 并发控制：create_and_persist 检查 max_project_solvers——当前项目已有 max_project_solvers 个 active（created/assigned/running/waiting_review）session 时拒绝创建。
- duplicate completion rejection：已 completed/failed/expired/cancelled 的 session 拒绝二次完成。
- create_session_from_bundle 从 TaskBundle 创建 SolverSession（legacy → vNext 映射扩展）。
- Blackboard _apply_event 增强：session_index（latest-wins per solver_id）替代简单 append，支持 WORKER_HEARTBEAT / WORKER_TIMEOUT / ACTION_OUTCOME 事件驱动 session 状态演变。
- 不修改任何现有文件（platform_models.py、dispatcher.py、runtime.py）。

**关键文件：**

- 新增 `attack_agent/team/solver.py`
- 修改 `attack_agent/team/blackboard.py`（_apply_event session_index 增强）
- 新增 `tests/test_team_solver.py`

**验证：**

- 511 测试全通过（475 原有 + 36 新增）。
- SolverSessionManager.create_session 写入 Blackboard ✅
- SolverSession 状态机转换正确（created→assigned→running→completed / failed） ✅
- 非法状态转换返回 None ✅
- duplicate completion rejection（已 completed session 拒绝二次 complete） ✅
- expire_session 超时标记 ✅
- cancel_session ✅
- heartbeat 写入事件 ✅
- concurrency limit（max_project_solvers=1 拒绝第二个 session） ✅
- create_session_from_bundle 从 TaskBundle 创建 ✅
- get_session / list_sessions ✅
- default single-session baseline 不变 ✅
- budget_remaining preserved across transitions ✅

---

### Phase G — MergeHub + 内部 Verifier/Observer Passes ✅ 已完成

**目标：** 多 Solver 结果可归并、验证、去重、纠偏。

**主要工作：**

- 新增 `attack_agent/team/merge.py`。
- MergeHub 第一版处理：
  - duplicate facts（kind:content 相同保留最高 confidence，不同 confidence 来源标记 conflict）
  - conflicting facts（同 content 不同 confidence → MergeDecision.CONFLICT）
  - duplicate ideas（description 相同合并，保留最高 priority）
  - candidate flag arbitration（跨 Solver 共识 boost：+0.1/solver，最高 confidence 优先选出）
  - failure boundary merge（description 相同保留最多 evidence_refs）
- 新增 `attack_agent/team/submission.py`。
- SubmissionVerifier（内部 pass，非独立 agent）：
  - verify_flag_format：regex 匹配 flag_pattern（默认 `flag\{[^}]+\}`）
  - verify_evidence_chain：检查 idea 的 evidence_refs 在 Blackboard 中有对应 MemoryEntry
  - verify_submission_budget：检查已提交次数 < max_submissions（默认 3）
  - verify_completeness：检查 project.status != "solved"
  - run_all_passes：串联所有 pass，任一 failed 则整体 failed
  - 每个 VerificationResult 写入 Blackboard SECURITY_VALIDATION 事件
- 新增 `attack_agent/team/observer.py`。
- Observer（只读 analyzer，不夺取执行权）：
  - detect_repeated_action：同一 Solver 连续相同 ACTION_OUTCOME（primitive + target）超过 threshold → stagnation
  - detect_low_novelty：最近 N 条 MemoryEntry 全部 confidence < min_novelty → low_novelty
  - detect_ignored_failure_boundary：FailureBoundary 被 2+ Solver 尝试但都失败 → ignored_boundary
  - detect_stagnation：最近 cycle_threshold 个事件无新 fact/idea → stagnation
  - detect_tool_misuse：Solver 连续使用同一 primitive 但每次 outcome=failure → tool_misuse
  - generate_report：串联所有 detect 方法，生成汇总报告，写入 CHECKPOINT 事件
  - severity 自动分级：critical（ignored_boundary/tool_misuse）→ warning（repeated_action/stagnation）→ info
  - suggested_actions：按 observation kind 自动建议纠正动作
- MergeResult / MergeDecision / ArbitrationResult / VerificationResult / CheckResult / SubmissionConfig / ObservationReport / ObservationNote dataclass
- Observer 只写 CHECKPOINT 事件（建议性），不写 ACTION_OUTCOME / CANDIDATE_FLAG 等决策性事件
- 不修改任何现有文件（strategy.py、state_graph.py、platform_models.py 等）

**关键文件：**

- 新增 `attack_agent/team/merge.py`
- 新增 `attack_agent/team/observer.py`
- 新增 `attack_agent/team/submission.py`
- 新增 `tests/test_team_merge.py`
- 新增 `tests/test_team_observer.py`
- 新增 `tests/test_team_submission.py`

**验证：**

- 562 测试全通过（511 原有 + 51 新增）。
- MergeHub.merge_facts 去重 + 冲突检测 ✅
- MergeHub.merge_ideas 去重 + 优先级仲裁 ✅
- MergeHub.merge_failure_boundaries 去重 ✅
- MergeHub.arbitrate_flags 跨 Solver 共识 boost + 选出最高 confidence ✅
- SubmissionVerifier.verify_flag_format pass/fail ✅
- SubmissionVerifier.verify_evidence_chain complete/incomplete ✅
- SubmissionVerifier.verify_submission_budget within/over limit ✅
- SubmissionVerifier.verify_completeness already_solved/not_solved ✅
- SubmissionVerifier.run_all_passes all_passed / any_failed ✅
- Observer.detect_repeated_action ✅
- Observer.detect_low_novelty ✅
- Observer.detect_ignored_failure_boundary ✅
- Observer.detect_stagnation ✅
- Observer.detect_tool_misuse ✅
- Observer.generate_report 写入 CHECKPOINT 事件 ✅
- 所有 MergeDecision 可从 Blackboard 事件审计 ✅

---

### Phase H — CLI / API 先于 Web UI ✅ 已完成

**目标：** runtime 稳定后再外露操作面；先 CLI / API introspection，后 Web UI。

**主要工作：**

- 扩展 CLI（通过 `attack_agent/__main__.py` 或新增 `attack_agent/team/cli.py`）：
  - `attack-agent team run --config ...`
  - `attack-agent team status`
  - `attack-agent team replay <project_id>`
  - `attack-agent team reviews`
- API 第一版先只读：
  - `GET /api/projects`
  - `GET /api/projects/{id}/graph`
  - `GET /api/projects/{id}/ideas`
  - `GET /api/projects/{id}/memory`
  - `GET /api/projects/{id}/solvers`
  - `GET /api/projects/{id}/reviews`
- 审批 endpoints 后接：`POST /api/reviews/{id}/approve` / `reject` / `modify`
- Web UI 最后消费稳定 API，不直接读内部对象。

**关键文件：**

- `attack_agent/__main__.py`
- 新增 `attack_agent/team/api.py`
- 新增 `attack_agent/team/runtime.py`（TeamRuntime 主入口）

**验证：**

- 598 测试全通过（562 原有 + 36 新增）。
- TeamRuntime 构造 + 组件初始化 ✅
- TeamRuntime.run_project 循环直到 done/abandoned ✅
- TeamRuntime.get_status 返回完整 ProjectStatusReport ✅
- TeamRuntime.submit_flag 验证链路（verifier → policy → submission） ✅
- TeamRuntime.submit_flag needs_review → review created ✅
- TeamRuntime.resolve_review approve/reject/modify ✅
- TeamRuntime.observe 返回 ObservationReport ✅
- TeamRuntime.replay 返回 event log ✅
- CLI team status/replay/reviews/observe/review 输出 ✅
- API GET /api/projects 项目列表 ✅
- API GET /api/projects/{id} 项目详情 ✅
- API GET endpoints 返回正确 JSON ✅
- API POST review approve/reject/modify ✅
- API GET endpoints 不修改 Blackboard 状态 ✅（observe 写 CHECKPOINT 是预期行为）
- BlackboardService check_same_thread=False 支持异步线程 ✅

---

### Phase I — Replay / Evaluation

**目标：** 让团队 runtime 可回放、可评估、可回归。

**主要工作：**

- 新增 `attack_agent/team/replay.py`。
- 基于 event journal rebuild materialized state。
- 支持 deterministic replay fixture。
- 支持 run comparison metrics：
  - solve success
  - cycles
  - failed attempts
  - review count
  - policy blocks
  - submission attempts
  - repeated failure rate

**关键文件：**

- 新增 `attack_agent/team/replay.py`
- 新增 `attack_agent/team/benchmark.py`
- `attack_agent/team/blackboard.py`

**验证：**

- event log replay 后状态一致。
- deterministic fixture 稳定。
- failed run 可解释。
- local CTF baseline 可纳入 regression。

---

### Phase J — ToolBroker 能力扩展

**目标：** 在 PolicyHarness、Blackboard、Replay 稳定后再扩大工具能力。

**主要工作：**

- 新增 `attack_agent/team/tool_broker.py`。
- 从 `PrimitiveRegistry` / `PrimitiveAdapter` / `WorkerRuntime` 抽出 broker 协议：
  - `ToolRequest`
  - `ToolResult`
  - `ToolError`
  - `ToolEvent`
- 每个 tool request 必须经过 PolicyHarness。
- 才考虑接入 web / browser / crypto / forensics / reverse / pwn / protocol / race capability packs。

**关键文件：**

- `attack_agent/runtime.py`（PrimitiveRegistry / PrimitiveAdapter / WorkerRuntime）
- `attack_agent/team/policy.py`
- 新增 `attack_agent/team/tool_broker.py`

**验证：**

- policy preflight。
- tool result journal。
- budget accounting。
- existing primitive behavior compatibility。

---

## 四、关键文件索引

### 新增文件（按阶段）

```
attack_agent/team/
├── __init__.py
├── protocol.py          # Phase A
├── blackboard.py        # Phase B
├── manager.py            # Phase C
├── scheduler.py          # Phase C
├── context.py            # Phase D
├── memory.py             # Phase D
├── ideas.py              # Phase D
├── policy.py             # Phase E
├── review.py             # Phase E
├── solver.py             # Phase F
├── merge.py              # Phase G
├── observer.py           # Phase G
├── submission.py         # Phase G
├── runtime.py            # Phase H（TeamRuntime 主入口）
├── cli.py                # Phase H（click + rich CLI）
├── api.py                # Phase H（FastAPI API server）
├── api.py                # Phase H
├── runtime.py            # Phase H（TeamRuntime 主入口）
├── replay.py             # Phase I
├── benchmark.py          # Phase I
└── tool_broker.py        # Phase J
```

### 修改文件（按阶段）

| 文件 | 涉及阶段 |
|------|----------|
| `attack_agent/platform.py` | C, F, H |
| `attack_agent/dispatcher.py` | C, F |
| `attack_agent/state_graph.py` | B, D |
| `attack_agent/team/blackboard.py` | B, D, F, H |
| `attack_agent/runtime.py` | C, F, J |
| `attack_agent/strategy.py` | A |
| `attack_agent/platform_models.py` | A, F |
| `attack_agent/constraints.py` | J |
| `attack_agent/observation_summarizer.py` | D |
| `attack_agent/semantic_retrieval.py` | D |
| `attack_agent/__main__.py` | H |

---

## 五、对设计书的修订建议

`docs/TEAM_RUNTIME_DESIGN.md` 建议增加以下章节或修正：

1. **Current Architecture Mapping**：明确 `CompetitionPlatform` / `Dispatcher` / `StateGraphService` / `WorldState` / `WorkerRuntime` / `EnhancedAPGPlanner` 分别迁移到哪里。

2. **Compatibility Strategy**：说明哪些旧类保留、哪些作为 facade、哪些逐步废弃。

3. **Minimal Protocol Subset**：第一阶段不冻结全部协议模型，只冻结最小闭环（`Project`、`StrategyAction`、`SolverSession`、`MemoryEntry`、`FailureBoundary`、`PolicyDecision`、`ReviewRequest`、`HumanDecision`）。

4. **Event Journal First**：明确 SQLite Blackboard 第一版是 append-only event journal + materialized view，而不是完整平台数据库。

5. **Synchronous First ManagerScheduler**：明确第一版不要求分布式、不要求 async queue。

6. **Policy Before Tool Expansion**：将 ToolBroker 扩展放在 PolicyHarness 之后。

7. **CLI/API Before Web UI**：Web UI 后置，先做 inspect / debug / review CLI 或 API。

8. **Replay as Schema Constraint**：虽然完整 replay 可后置，但 event schema 从 Phase B 起就要满足 replay 需求。

---

## 六、验证策略

每阶段都必须保护当前 baseline：

```bash
# 单元测试
python -m unittest discover tests/

# 纯规则模式 smoke
python -m attack_agent.platform_demo

# 本地靶场（若有）
python scripts/local_range.py
```

关键验证项：

- 当前测试全部继续通过（Phase A 开始，每阶段都要验证）。
- LLM off / heuristic mode 持续可运行。
- model enabled 路径在有配置时持续可运行。
- 高风险 / 外部副作用 / flag submit 进入 review / policy 路径。
- 新增模块有独立单元测试。

---

## 七、启动提示词

以下提示词用于从 Phase A 开始第一个工作项：

> **Phase A: Protocol Extraction and Compatibility Mapping**
>
> 目标：从现有 `attack_agent/` 代码中抽取 Team Runtime vNext 协议的最小子集，建立 legacy → vNext 映射，**不改变任何现有行为**。
>
> 具体任务：
>
> 1. 在 `attack_agent/team/` 目录下创建 `__init__.py` 和 `protocol.py`。
> 2. 在 `protocol.py` 中定义以下 dataclass（参考 `attack_agent/platform_models.py` 的现有类型命名）：
>    - `TeamProject`：`project_id`、`challenge_id`、`status`、`created_at`、`updated_at`
>    - `StrategyAction`：`action_type`（launch_solver / stop_solver / steer_solver / submit_flag / converge / abandon 等）、`project_id`、`target_solver_id`、`target_idea_id`、`priority`、`risk_level`、`budget_request`、`reason`、`evidence_refs`、`requires_review`
>    - `SolverSession`：`solver_id`、`project_id`、`profile`、`status`（created / assigned / running / waiting_review / completed / failed / expired / cancelled）、`active_idea_id`、`local_memory_ids`、`budget_remaining`
>    - `MemoryEntry`：`entry_id`、`project_id`、`kind`（fact / credential / endpoint / failure_boundary / hint）、`content`、`evidence_refs`、`confidence`、`created_at`
>    - `IdeaEntry`：`idea_id`、`project_id`、`description`、`status`（pending / claimed / testing / verified / failed / shelved）、`solver_id`、`priority`、`failure_boundary_refs`
>    - `FailureBoundary`：`boundary_id`、`project_id`、`description`、`evidence_refs`、`created_at`
>    - `PolicyDecision`：`decision`（allow / deny / needs_review / needs_human / redact / rate_limit / budget_exceeded）、`action_type`、`risk_level`、`reason`、`constraints`
>    - `ReviewRequest`：`request_id`、`project_id`、`requested_by`、`action_type`、`risk_level`、`title`、`description`、`evidence_refs`、`proposed_action`、`alternatives`、`timeout_policy`、`status`（pending / approved / rejected / modified / expired）、`decision`、`decided_by`、`decided_at`
>    - `HumanDecision`：`request_id`、`decision`（approved / rejected / modified）、`modified_params`、`decided_by`、`decided_at`、`reason`
>
> 3. 在 `protocol.py` 中增加 legacy 映射函数（返回上述 vNext 对象）：
>    - `legacy_project_to_team_project(record: ProjectRecord) -> TeamProject`
>    - `legacy_bundle_to_solver_session(bundle: TaskBundle, session_id: str) -> SolverSession`
>    - `legacy_submit_decision_to_policy(decision: SubmitDecision) -> PolicyDecision`
>    - `legacy_episode_to_memory_entry(entry: EpisodeEntry) -> MemoryEntry`
>
> 4. 所有新增 dataclass 必须能序列化（dataclass + field(default_factory)），供后续 Phase B SQLite 使用。
>
> 5. **不修改任何现有文件**，只新增 `attack_agent/team/` 目录和文件。
>
> 6. 新增 `tests/test_team_protocol.py`，测试：
>    - 所有 dataclass 可以正常实例化
>    - legacy 映射函数输出非 None
>    - 序列化 round-trip（to_dict / from_dict）
>
> 验证：`python -m unittest discover tests/ -v` 全部通过。

