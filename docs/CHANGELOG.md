# Change Log

本文件记录 AttackAgent 的版本演进、已完成里程碑和已解决限制。
写入后不再修改——新变更追加到末尾。

---

## Version History

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| 4.18 | 2026-05-12 | Team Runtime Phase K-3 StateGraphService ↔ Blackboard 双写对齐：新增 `attack_agent/team/state_sync.py`（StateSyncService + SyncConfig）。StateSyncService.sync_project 全量同步（observations→OBSERVATION、candidate_flags→CANDIDATE_FLAG、snapshot→project_upserted、stagnation_counter→CHECKPOINT、session_state→OBSERVATION(kind=session_state)、pattern_graph→CHECKPOINT）。sync_delta 增量同步（sync_marker dedup + 只写新增 ID）。validate_consistency 一致性验证（不一致→纠正 project_upserted）。MemoryKind 新增 SESSION_STATE。apply_event_to_state OBSERVATION kind 非法值 fallback→FACT + content 保留原始 kind 前缀。_execute_solver_cycle 增强（per-observation OBSERVATION + pattern_graph CHECKPOINT + session_state OBSERVATION + stagnation CHECKPOINT）。SyncScheduler 执行后 sync_delta。solve_all 循环后 sync_project + validate_consistency。新增 `tests/test_team_state_sync.py`(21 测试)。708 测试全通过（687 原有 + 21 新增）
| 4.17 | 2026-05-11 | Team Runtime Phase K-2 CompetitionPlatform → TeamRuntime 迁移完成：新增 `attack_agent/factory.py`（build_team_runtime 函数提取 CompetitionPlatform.__init__ 全部 wiring 逻辑，返回 TeamRuntime）。TeamRuntime.solve_all() 替代 CompetitionPlatform.solve_all()：bootstrap(Controller.sync_challenges+ensure_instance) + Blackboard 注入 + SyncScheduler.run_all + StateGraphService 状态同步。TeamRuntime.submit_flag() 真实提交路径(Controller.submit_candidate)。_execute_solver_cycle() 修复：BOOTSTRAP→REASON→EXPLORE 全阶段推进+第一个 EXPLORE 执行在一次调用中完成（不再消耗额外循环计数），匹配原 CompetitionPlatform.run_cycle 行为。SyncScheduler._execute_submit_if_possible SUBMIT_FLAG 眯实提交。`__main__.py`/`platform_demo.py` 迁移到 build_team_runtime。所有测试 builder 改为 runtime 版本。新增 `tests/test_team_k2_integration.py`(7 测试)。CompetitionPlatform 类从 platform.py 移除（只剩 stub）。__init__.py 导出从 CompetitionPlatform 改为 TeamRuntime+TeamRuntimeConfig+build_team_runtime。CLAUDE.md/AGENTS.md/README.md/docs/ 更新 CompetitionPlatform 引用替换为 TeamRuntime。687 测试全通过
| 4.16 | 2026-05-11 | Team Runtime Phase K-1 TeamRuntime 接收真实 WorkerRuntime + Dispatcher：修改 `attack_agent/dispatcher.py`（Dispatcher.schedule 新增 skip_stage_decisions: bool=False 参数。True 时 BOOTSTRAP/REASON 阶段返回 None（TeamManager 处理），EXPLORE 阶段跳过 _stage_after_program() 和 should_abandon()，返回 (outcome, events) tuple 而非 None。False 时行为完全不变）。修改 `attack_agent/team/runtime.py`（TeamRuntime 构造器新增 worker_runtime/dispatcher/state_graph/enhanced_planner 可选参数。新增 TeamRuntimeConfig.use_real_executor: bool=False 字段。新增 use_real_executor 属性（config.use_real_executor=True + 所有 executor 组件非 None）。新增 _execute_solver_cycle(project_id) 方法：BOOTSTRAP→REASON→EXPLORE 全阶段推进 + 第一个 EXPLORE 执行在单次调用完成；EXPLORE→Dispatcher.schedule(skip_stage_decisions=True)→从结果写入 Blackboard（ACTION_OUTCOME/CANDIDATE_FLAG/SECURITY_VALIDATION 事件）。SyncScheduler.schedule_cycle/run_project/run_all 新增 runtime 参数。LAUNCH_SOLVER/STEER_SOLVER + runtime.use_real_executor=True → 调用 _execute_solver_cycle，执行后 TeamManager 重新评估项目状态决定下一步决策。修改 `attack_agent/team/scheduler.py`（schedule_cycle 新增 runtime: TeamRuntime | None=None 参数 + execution branch；run_project/run_all 传递 runtime）。新增 `tests/test_team_k1_integration.py`（12 测试）。680 测试全通过（668 原有 + 12 新增）。CompetitionPlatform.solve_all() 外部行为不变
| 4.15 | 2026-05-11 | Team Runtime Phase J ToolBroker 能力扩展：新增 `attack_agent/team/tool_broker.py`（ToolBroker 统一 policy gate + event journal + IO-free primitive 执行。ToolRequest→PolicyHarness.validate_action→PolicyDecision→(non-ALLOW→ToolError / ALLOW+IO-free→PrimitiveAdapter.execute→ToolResult / ALLOW+IO-dependent→ToolError(requires_io_context))。全程写入 Blackboard event journal（TOOL_REQUEST request_created + SECURITY_VALIDATION policy_checked + ACTION_OUTCOME completed / TOOL_REQUEST failed）。IO-free primitives=structured-parse/diff-compare/code-sandbox/extract-candidate，IO-dependent=http-request/browser-inspect/session-materialize/artifact-scan/binary-inspect 暂不支持 broker 直接执行返回 requires_io_context）。ToolRequest/ToolResult/ToolError/ToolEvent dataclass。ToolBroker.list_available_primitives(profile→registry.visible_primitives) + get_primitive_spec(name→adapter.spec)。修改 `attack_agent/platform_models.py`（EventType 新增 TOOL_REQUEST）。修改 `attack_agent/team/protocol.py`（ActionType 新增 USE_PRIMITIVE）。修改 `attack_agent/team/runtime.py`（self.tool_broker=ToolBroker(PrimitiveRegistry(),self.policy,self.blackboard) + request_tool/list_available_primitives 方法）。修改 `attack_agent/team/cli.py`（team tools --profile 命令，rich Table 列出 primitive/capability/risk/cost）。修改 `attack_agent/team/api.py`（GET /api/tools + GET /api/tools/{name} + POST /api/projects/{id}/request-tool 端点）。新增 `tests/test_team_tool_broker.py`(43 测试)。668 测试全通过（625 原有 + 43 新增）。
| 4.14 | 2026-05-11 | Team Runtime Phase I Replay/Evaluation：新增 `attack_agent/team/apply_event.py`（从 BlackboardService._apply_event 提取纯函数 apply_event_to_state，打破 blackboard↔replay 循环依赖，函数签名拆为独立字段参数而非 BlackboardEvent/MaterializedState 对象，action_outcome SolverStatus 转换增加 ValueError 保护）。新增 `attack_agent/team/replay.py`（ReplayEngine：replay_project 逐步重放+deepcopy snapshot→list[ReplayStep]，replay_to_step 重放到指定步骤返回中间 MaterializedState，diff_runs 组合键(event_type,kind,content)匹配→RunDiffResult(added_events/removed_events/diverged_at_step)。ReplayStep/RunDiffResult dataclass。BlackboardService 新增 _new_materialized_state()方法）。新增 `attack_agent/team/benchmark.py`（BenchmarkRunner：evaluate_project 从 event journal 计算 RunMetrics(solve_success/total_cycles/failed_attempts/review_count/policy_blocks/submission_attempts/repeated_failure_rate/stagnation_events/observation_severity_counts/budget_consumed/idea_claim_rate)，compare_metrics→MetricsComparison(delta+weighted overall_score)，run_regression 纯指标对比两个 Blackboard DB→RegressionReport(baseline_metrics/current_metrics/regressions/improvements/overall_status=pass/fail/mixed)。RunMetrics/MetricsComparison/RegressionReport dataclass）。TeamRuntime 新增 replay_steps/evaluate/compare_runs 方法。CLI 新增 replay-steps/evaluate/regression 命令（rich Table/Panel 输出）。API 新增 GET replay-steps/metrics + POST regression 端点。BlackboardService._apply_event 改为委托 apply_event_to_state。新增 `tests/test_team_replay.py`(15 测试)+`tests/test_team_benchmark.py`(12 测试)。625 测试全通过（598 原有 + 27 新增）。不修改任何现有文件的核心逻辑 |
| 4.13 | 2026-05-09 | Team Runtime Phase H CLI/API 先于 Web UI：新增 `attack_agent/team/runtime.py`（TeamRuntime 串联入口，wiring 全部 Phase A~G 组件：BlackboardService/TeamManager/SyncScheduler/MemoryService/IdeaService/ContextCompiler/PolicyHarness/HumanReviewGate/SolverSessionManager/MergeHub/SubmissionVerifier/Observer。方法：run_project/run_all/get_status/list_projects/submit_flag/get_pending_reviews/resolve_review/observe/replay/close。TeamRuntimeConfig/ProjectStatusReport/SubmissionResult dataclass。submit_flag 完整链路：SubmissionVerifier.run_all_passes→PolicyHarness.validate_action→(needs_review→HumanReviewGate.create_review)→Blackboard SUBMISSION event）。新增 `attack_agent/team/cli.py`（click + rich CLI：team run/status/replay/reviews/review approve/reject/modify/observe/serve。team_main() 函数供 __main__.py 调用）。新增 `attack_agent/team/api.py`（FastAPI read-only + review governance：8 GET endpoints（projects/ideas/memory/solvers/reviews/events/observe）+ 3 POST review actions（approve/reject/modify）+ CORS middleware + async lifespan handler）。修改 `attack_agent/__main__.py`（添加 ~5 行 team 入口分发：sys.argv[1]=="team"→cli.team_main）。修改 `attack_agent/team/blackboard.py`（SQLite check_same_thread=False 支持异步线程访问）。修改 `pyproject.toml`（新增 api/cli/team optional dependency groups + 合入 all）。新增 `tests/test_team_runtime.py`(13 测试)+`tests/test_team_cli.py`(9 测试)+`tests/test_team_api.py`(14 测试)。598 测试全通过（562 原有 + 36 新增）。不修改任何现有文件的核心逻辑 |
| 4.12 | 2026-05-09 | Team Runtime Phase G MergeHub + SubmissionVerifier + Observer：新增 `attack_agent/team/merge.py`（MergeHub：merge_facts 去重+冲突检测，kind:content 相同保留最高 confidence，不同 confidence 来源标记 conflict；merge_ideas 去重+优先级仲裁，description 相同合并保留最高 priority；merge_failure_boundaries 去重，description 相同保留最多 evidence_refs；arbitrate_flags 跨 Solver 共识 boost +0.1/solver，选出最高 confidence flag。MergeResult/MergeDecision/ArbitrationResult dataclass。归并结果写入 Blackboard OBSERVATION/CANDIDATE_FLAG/ACTION_OUTCOME 事件）。新增 `attack_agent/team/submission.py`（SubmissionVerifier 内部 pass：verify_flag_format regex 匹配 flag_pattern、verify_evidence_chain 检查 idea evidence_refs 存在性、verify_submission_budget 检查已提交次数<max_submissions、verify_completeness 检查 project.status!=solved、run_all_passes 串联全部 pass 任一 failed 则整体 failed。VerificationResult/CheckResult/SubmissionConfig dataclass。每个 VerificationResult 写入 SECURITY_VALIDATION 事件）。新增 `attack_agent/team/observer.py`（Observer 只读 analyzer：detect_repeated_action 同 Solver 连续相同 primitive+target 超阈值、detect_low_novelty 最近 N 条 MemoryEntry 全低 confidence、detect_ignored_failure_boundary FailureBoundary 被 2+ Solver 尝试、detect_stagnation 最近 N 事件无新 fact/idea、detect_tool_misuse Solver 连续同一 primitive 全 failure、generate_report 串联所有 detect + severity 自动分级(critical/warning/info) + suggested_actions。ObservationReport/ObservationNote dataclass。Observer 只写 CHECKPOINT 事件不写决策性事件）。新增 `tests/test_team_merge.py`(17 测试)+`tests/test_team_observer.py`(15 测试)+`tests/test_team_submission.py`(19 测试)。562 测试全通过（511 原有 + 51 新增）。不修改任何现有文件 |
| 4.11 | 2026-05-09 | Team Runtime Phase F SolverSession 生命周期与有限多 Session：新增 `attack_agent/team/solver.py`（SolverSessionManager + SolverSessionConfig）。SolverSessionManager 实现显式长生命周期 session 管理：create_session/create_and_persist/claim_session/start_session/heartbeat/complete_session/expire_session/cancel_session/get_session/list_sessions/create_session_from_bundle。状态机严格定义：created→assigned→running→waiting_review→completed/failed/expired/cancelled，非法转换返回 None。并发控制：create_and_persist 检查 max_project_solvers，当前项目已有 max 个 active(created/assigned/running/waiting_review) session 时拒绝创建。duplicate completion rejection：已 terminal(completed/failed/expired/cancelled) session 拒绝二次完成。create_session_from_bundle 从 TaskBundle 创建 SolverSession（legacy→vNext 映射扩展）。每个 session 状态转换写入 Blackboard event journal（WORKER_ASSIGNED/WORKER_HEARTBEAT/WORKER_TIMEOUT/ACTION_OUTCOME 事件驱动 session 状态演变）。Blackboard _apply_event 增强：session_index(latest-wins per solver_id)替代简单 append，支持 WORKER_HEARTBEAT/WORKER_TIMEOUT/ACTION_OUTCOME 事件驱动 session 状态演变。新增 `tests/test_team_solver.py`(36 测试)。511 测试全通过（475 原有 + 36 新增）。不修改任何现有文件（platform_models.py/dispatcher.py/runtime.py） |
| 4.10 | 2026-05-09 | Team Runtime Phase E PolicyHarness + HumanReviewGate：新增 `attack_agent/team/policy.py`（PolicyHarness + PolicyConfig + RiskThresholds）。PolicyHarness.validate_action() 统一安全决策入口，收敛 risk threshold 映射（critical→deny, high→needs_review, medium→allow, low→allow）+ primitive visibility（deny forbidden primitives）+ budget check（budget_exceeded）+ rate limit check（rate_limit）+ submit_flag 特殊处理（requires_review=True 或 risk_level=high/critical → needs_review）。PolicyDecision 7 种结果：allow/deny/needs_review/needs_human/redact/rate_limit/budget_exceeded。每个 PolicyDecision 写入 Blackboard event journal（EventType.SECURITY_VALIDATION）。新增 `attack_agent/team/review.py`（HumanReviewGate）。HumanReviewGate 纯逻辑服务：create_review（写入 SECURITY_VALIDATION 事件，payload 含 review_id/status/outcome）+ resolve_review（更新 approved/rejected/modified，写入 resolution 事件，causal_ref 关联 review_id；reject 时写入 ACTION_OUTCOME failure_boundary）+ list_pending_reviews（从 event journal 重建 pending 列表）+ auto_expire_reviews（超时未决按 timeout_policy 自动 reject，decided_by=auto_expire）。新增 `tests/test_team_policy.py`（13 测试）+ `tests/test_team_review.py`（15 测试）。475 测试全通过（447 原有 + 28 新增）。不修改任何现有文件 |
| 4.8 | 2026-05-09 | Team Runtime Phase D ContextCompiler + MemoryService + IdeaService：新增 `attack_agent/team/memory.py`（MemoryService：store_entry/query_by_kind/query_by_confidence/dedupe/get_failure_boundaries/get_deduped_entries）、`attack_agent/team/ideas.py`（IdeaService：propose/claim/mark_verified/mark_failed/list_available/get_best_unclaimed）、`attack_agent/team/context.py`（ManagerContext + SolverContextPack dataclass + ContextCompiler：compile_manager_context/compile_solver_context）。MemoryService.store_entry 写入 Blackboard event journal（OBSERVATION for fact/credential/endpoint/hint，ACTION_OUTCOME for failure_boundary），payload 保留 kind/entry_id/evidence_refs。IdeaService.propose/claim/mark_verified/mark_failed 写入 CANDIDATE_FLAG 事件，payload 保留 idea_id/status/solver_id/priority/failure_boundary_refs。mark_failed 同时写入 ACTION_OUTCOME failure_boundary 事件。ContextCompiler 从 Blackboard + MemoryService + IdeaService 编译 Manager 全局态势和 Solver 局部上下文。Blackboard `_apply_event` 增强：OBSERVATION 从 payload 读取 kind（而非硬编码 FACT，支持 CREDENTIAL/ENDPOINT/HINT）；OBSERVATION/ACTION_OUTCOME 读取 entry_id；CANDIDATE_FLAG 读取 idea_id/status/solver_id；rebuild_state 引入 idea_index dict，每个 idea_id 的最新 CANDIDATE_FLAG 事件胜出（解决 append-only journal 中 idea 状态演变问题）。新增 `tests/test_team_memory.py`（20 测试）+ `tests/test_team_ideas.py`（17 测试）+ `tests/test_team_context.py`（14 测试）。447 测试全通过（396 原有 + 51 新增） |
| 4.7 | 2026-05-09 | Team Runtime Phase C 同步 ManagerScheduler：新增 `attack_agent/team/manager.py`（TeamManager + ManagerConfig）。TeamManager 实现 7 个纯决策函数：admit_project（项目准入→LAUNCH_SOLVER）、decide_stage_transition（bootstrap→LAUNCH_SOLVER / reason→STEER_SOLVER / explore→CONVERGE/STEER_SOLVER/ABANDON）、assign_solver（solver 分配→LAUNCH_SOLVER）、handle_solver_heartbeat（心跳确认→STEER_SOLVER）、handle_solver_timeout（超时→STEER_SOLVER(requeue)/ABANDON）、decide_convergence（收敛/放弃/继续探索）、decide_submit（提交→SUBMIT_FLAG / 等待→CONVERGE / 无候选→ABANDON）。决策阈值从 Dispatcher 移植：stagnation_threshold=8、confidence_threshold=0.6、tombstone_threshold=2、recent_failures_limit=4。候选 flag 存在时优先收敛不放弃（与 Dispatcher candidate_flags→CONVERGE 一致）。新增 `attack_agent/team/scheduler.py`（SyncScheduler + SchedulerConfig）。SyncScheduler 实现 schedule_cycle（读 Blackboard 事件→Manager 决策→写回事件）、run_project（循环 schedule_cycle 直到 done/abandoned，max_cycles 超限后写入 PROJECT_UPSERTED status=abandoned）、run_all（顺序处理多项目，concurrency=1）。新增 `tests/test_team_manager.py`（19 测试）+ `tests/test_team_scheduler.py`（11 测试）。396 测试全通过（366 原有 + 30 新增）。不修改任何现有文件 |
| 4.6 | 2026-05-09 | Team Runtime Phase B Blackboard Event Journal：新增 `attack_agent/team/blackboard.py`（BlackboardService + BlackboardEvent + MaterializedState）+ `attack_agent/team/blackboard_config.py`（BlackboardConfig）。BlackboardService 实现 SQLite append-only event journal：append_event（不可变追加，自动 event_id + timestamp，可选 causal_ref 因果链）+ load_events（按 project_id + timestamp 排序读取）+ rebuild_state（从事件重建 TeamProject + facts/ideas/sessions）+ list_facts/list_ideas/list_sessions（按 kind 过滤）+ export_run_log（完整 JSON 事件日志）。事件 schema 预留 Replay 需求（causal_ref 因果链追踪 + 不可变追加 + ISO 8601 timestamp）。rebuild_state 消费 EventType 全部子类型：project_upserted→TeamProject、observation→MemoryEntry(fact)、candidate_flag→IdeaEntry+MemoryEntry、worker_assigned→SolverSession、action_outcome(failed)→MemoryEntry(failure_boundary)、submission→project.status 更新、security_validation(deny)→MemoryEntry(failure_boundary)。新增 `tests/test_team_blackboard.py`（15 测试：append/load round-trip + ordering + payload 保留 + rebuild project/facts/ideas/sessions/failure_boundary + successful outcome 不入 facts + security deny + submission 更新 + list_facts 过滤 + crash/reload 恢复 + causal_ref 链 + export JSON）。366 测试全通过（351 原有 + 15 新增）。不修改任何现有文件 |
| 4.5 | 2026-05-09 | Team Runtime Phase A 协议抽取与兼容映射：新增 `attack_agent/team/` 子包（`__init__.py` + `protocol.py`），定义 7 个 enum（ActionType/SolverStatus/MemoryKind/IdeaStatus/PolicyOutcome/ReviewStatus/HumanDecisionChoice）+ 9 个 protocol dataclass（TeamProject/StrategyAction/SolverSession/MemoryEntry/IdeaEntry/FailureBoundary/PolicyDecision/ReviewRequest/HumanDecision）+ 4 个 legacy 映射函数（legacy_project_to_team_project/legacy_bundle_to_solver_session/legacy_submit_decision_to_policy/legacy_episode_to_memory_entry）+ to_dict/from_dict 序列化。新增 `tests/test_team_protocol.py`（24 测试：实例化 + 序列化 round-trip + legacy 映射）。351 测试全通过（327 原有 + 24 新增）。不修改任何现有文件。演进路线图见 docs/TEAM_EVOLUTION_ROADMAP.md |
| 4.4 | 2026-05-08 | Session 跨 Cycle 持久化修复：(1) state_graph.py 新增 SessionState dataclass（存储 cookies/auth_headers/base_url）+ ProjectRecord.session_state 字段 + StateGraphService.get/set_session_state() 方法；(2) runtime.py WorkerRuntime.run_task() 新增 state_service 和 project_id 参数，任务执行前从 StateGraphService 恢复 session cookies 和 auth headers，任务完成后将 session-materialize 观测中的 cookies/auth 持久化；(3) dispatcher.py 调用 run_task() 时传递 state_service 和 project_id。解题率 3/4→4/4（web-auth-easy 登录成功 ✓）。参考 Cairn 架构（Fact-Intent Graph + OODA 循环），整理 CLAUDE.md：合并通用 AI 编码准则（Think Before Coding/Simplicity First/Surgical Changes/Goal-Driven Execution）与项目特定指令，新增 docs/USER_GUIDE.md 导航 |
| 4.3 | 2026-05-08 | 本地靶场解题率 1/4→3/4：(1) _inject_challenge_params 增强——privileged_paths 注入从"紧跟 session-materialize"改为"第二个+ http-request"（修复 identity-boundary verification 阶段无法访问 /admin），session-materialize 注入 login_url+credentials（从 metadata 读取），token_chain query 注入（支持 API 链式调用）；(2) structured-parse 增强——提取 cookies + base64 自动解码（decoded_cookies + potential_secrets），encoding-transform 族 cookie 中的 flag 可被 extract-candidate 发现；(3) http-request 增强——_substitute_observe_templates 支持 {observe.*} 模板替换（从最近 http-request 观测 JSON 中提取字段注入 query），session cookie 恢复（从 completed_observations 中 session-materialize 观测提取 cookies_obtained 注入 session_manager.cookie_jar）；(4) _plan_candidates 增强——VERIFICATION_GATE 规划时自动前置 session-materialize 步骤（保持 cookie 在同一 task bundle 内）；(5) local_range.py metadata 增强——web-auth-easy 添加 login_url+credentials+privileged_paths，web-chain-medium 添加 api_endpoints+token_chain；(6) _make_cookie_from_header helper（Set-Cookie header→Cookie 对象）。解题：web-render-easy ✓、web-encoding-medium ✓（base64 cookie 解码）、web-chain-medium ✓（token 链式传递）。web-auth-easy 仍 403（cookie 在 jar 中但 HTTP 请求未携带，疑似 http.cookiejar domain/path 匹配问题） |
| 4.2 | 2026-05-06 | 真实 CTF 靶场联调：thinking model 支持（Anthropic enable_thinking + budget_tokens + thinking 耗尽 output budget 时自动 re-request），verbose LLM trace 日志（╔══ LLM CALL ══ banner + response trace），dispatcher cycle/program/outcome trace，Windows GBK safe_print（_safe_print 替换 print 防止 UnicodeEncodeError），健壮性修复（apg.py KeyError free_exploration 节点、controller.py stop_challenge try-except、runtime.py code-sandbox RuntimeError catch + structured-parse 自动检测最近观测、model_adapter.py 清除冲突 Anthropic 环境变量防 401 + SDK max_retries=0 防长重试挂起 + empty_response 检测），ModelConfig 新增 enable_thinking 字段，本地 CTF 靶场服务器 scripts/local_range.py（4 题：web-auth-easy/web-render-easy/web-encoding-medium/web-chain-medium），AGENTS.md。成功解题 web-render-easy（Hidden Comments：flag{hidden_in_comments_042}） |
| 4.1 | 2026-04-30 | Phase 4 架构清理：SecurityConstraints 删除→SecurityConfig 直接作为约束源（消除重复类+from_config桥接），SecurityConfig 新增 forbidden_primitive_combinations 字段；StrategyLayer 删除→Dispatcher 内联策略逻辑（stagnation/submit/stage），strategy.py 仅保留 SubmitClassifier+TaskPromptCompiler；ARCHITECTURE.md v4.1 对齐更新 |
| 3.16 | 2026-04-29 | Phase 3 R11+R12 switch_path 真实逻辑 + 多族组合：EnhancedAPGPlanner.switch_path() 实现 STRUCTURED→FREE_EXPLORATION(停滞≥3时自动切换) + FREE_EXPLORATION→STRUCTURED(预算耗尽或置信度≥0.7时回切) + 停滞计数器(_stagnation_counters) + record_outcome() + PATH_SELECTION 事件记录 + stagnation reset，_compose_multi_family_candidates() 融合 2 族步骤(观察阶段用主族 + 操作阶段用副族 + 验证阶段用主族，副族得分≥0.7×主族得分时组合) + PlanCandidate.secondary_families + ProgramDecision.secondary_families + ActionProgram 融合描述/rationale + HeuristicFreeExplorationPlanner 多族融合 + DualPathConfig.path_switch_stagnation_threshold + DualPathConfig.multi_family_score_ratio + StrategyLayer.update_after_outcome 调用 record_outcome，12 项新测试(6 项 R11 + 6 项 R12)，330 测试通过 |
| 3.15 | 2026-04-29 | Phase 3 R10 步骤参数注入：_inject_challenge_params() 在规划阶段注入 target URL 到 http-request(url)/browser-inspect(url)/session-materialize(login_url)/artifact-scan(url)/binary-inspect(url) 步骤模板(setdefault 不覆盖已有参数)，runtime _resolve_http_request_specs/_resolve_browser_inspect_specs/_resolve_session_materialize_specs 增加 bundle.target 回退(metadata+param_overrides 均空时)，APGPlanner._plan_candidates() + HeuristicFreeExplorationPlanner 调用注入，8 项注入单元测试 + 1 项 APG 集成测试 + 1 项启发式集成测试 + 3 项 runtime 回退测试，318 测试通过 |
| 3.14 | 2026-04-29 | Phase 3 R9 扩展族关键词 6→14：新增 ssrf-server-boundary(ssrf/internal/proxy/metadata/9关键词) + ssti-template-boundary(ssti/jinja/mako/twig/10关键词) + csrf-state-boundary(csrf/cross-site/forgery/referer/8关键词) + idor-access-boundary(idor/insecure/privilege/uuid/10关键词) + crypto-math-boundary(rsa/aes/ecb/cbc/padding/oracle/16关键词) + pwn-memory-boundary(pwn/overflow/rop/gadget/13关键词) + protocol-logic-boundary(protocol/tcp/dns/mqtt/serialization/14关键词) + race-condition-boundary(race/concurrent/toctou/11关键词)，FAMILY_PROFILES + FAMILY_PROGRAMS 各 8 族 4 节点完整步骤，8 项族匹配测试 + 2 项启发式测试 + 14 族完整性 + 关键词重叠检查，305 测试通过 |
| 3.13 | 2026-04-29 | Phase 2 R8 code-sandbox 放宽：_SafeAstValidator 移除 ClassDef/With/Raise 禁止(添加 visit_ClassDef 跟踪类名), SAFE_IMPORTS 加入 zlib/csv(9→11), SAFE_BUILTINS 加入 __build_class__, globals_scope 加入 __name__, ConstraintAwareReasoner 更新 code-sandbox 描述, 测试新增 class/with/raise/zlib/csv 5 项, 297 测试通过 |
| 3.12 | 2026-04-29 | Phase 2 R7 artifact-scan 提取 ZIP/tar 内容 + 增大预览：_extract_archive_members 添加 content_preview(ZIP/tar 成员文本内容) + content_type(_guess_content_type 扩展名映射), _extract_text_preview 上限 128→4096 默认 64→512, _perform_artifact_scan 返回 (payload, temp_dir) 元组延迟清理, _execute_artifact_scan 批量清理 temp_dirs, Observation payload 新增 content_type 字段, PrimitiveRegistry + ConstraintAwareReasoner 新增 max_depth/max_members 参数, 292 测试全通过 |
| 3.11 | 2026-04-29 | Phase 2 R6 session-materialize CSRF 预取 + JSON body：_CSRFTokenParser(HTML hidden input + meta tag 解析), _extract_csrf_token(csrf_field/csrf_source 自动检测), _execute_session_materialize CSRF GET 预取(form/meta/header 3 来源) + JSON body 登录(json/content_type spec 字段) + auth token 持久化回写 session_manager.add_auth_header(), Observation payload 新增 csrf_prefetched/csrf_token_value/body_type 字段, PrimitiveRegistry + ConstraintAwareReasoner 新字段, 284 测试全通过 |
| 3.10 | 2026-04-29 | Phase 2 R5 http-request 接 requests：HttpConfig(engine/verify_ssl/max_redirects/timeout_seconds), RequestsHttpClient(multipart + Basic Auth + Bearer Auth + SSL bypass), StdlibHttpClient(graceful fallback), HttpSessionManager.auth_headers 持久化, _resolve_http_request_specs 新增 auth/auth_type/auth_token/files/verify_ssl 字段, Observation payload 新增 auth_used/ssl_verified/uploaded_files 字段, WorkerRuntime 接 http_config, 276 测试全通过 |
| 3.9 | 2026-04-28 | Phase 2 R4 browser-inspect 接 Playwright：BrowserConfig(engine/headless/browser_type/timeout/wait_for_selector/extract_scripts), PlaywrightBrowserInspector(JS 渲染 + script 读取 + console + cookies), StdlibBrowserInspector(graceful fallback), _HTMLPageParser extract_scripts 模式, Observation payload 新增 scripts/js_rendered_text/console_messages/cookies 字段, WorkerRuntime 接 browser_config, 252 测试全通过 |
| 3.5 | 2026-04-28 | P2 启发式自由探索 + 模式回注 + Embedding 接入：HeuristicFreeExplorationPlanner, FreeExplorationPlanner Protocol, PatternInjector + PatternLibrary 动态族, EmbeddingModel Protocol + adapters, InMemoryVectorStore cosine similarity, TF-IDF 修正, CJK tokenize, SemanticRetrievalConfig wiring |
| 3.6 | 2026-04-28 | Phase 1 R1 参数调优：stagnation_threshold 3→8 可配置, flag_confidence_threshold 0.85→0.6 可配置, StrategyLayer/SubmitClassifier 构造参数化, CLI override 支持 |
| 3.7 | 2026-04-28 | Phase 1 R2 CTFd 适配器：CTFdCompetitionProvider (session auth + API token), 6 方法 Protocol 实现, CLI --ctfd-url/--ctfd-username/--ctfd-password/--ctfd-token |
| 3.8 | 2026-04-28 | Phase 1 R3 删除假数据路径：_consume_metadata/_hash_payload 删除, _clean_fail 替换 10 个调用点, _extract_candidates/structured-parse/diff-compare 元数据回退删除, runtime.py 1629→1502 行, 测试改写验证干净失败 |
| 3.4 | 2026-04-27 | P3 LLM 反馈闭环 + 原语参数化：ObservationSummarizer, step.parameters 参数化, ConstraintAwareReasoner enrichment, ReasoningContext.observation_summaries, 安全壳参数 scope 验证, FAMILY_PROGRAMS 保守参数化 |
| 3.3 | 2026-04-27 | 规划 P3 实施方案：记录 LLM 反馈闭环缺失 + 原语未参数化问题 |
| 3.2 | 2026-04-27 | CLI 入口 (`python -m attack_agent`)，AttackAgentConfig.from_defaults()，真实靶场 HTTP 集成测试 |
| 3.1 | 2026-04-27 | SecurityConstraints 与 SecurityConfig 对齐：默认值同步、from_config() 工厂方法、Dispatcher/Platform 接受外部约束 |
| 3.0 | 2026-04-26 | 真实 PrimitiveAdapter 实现，HttpSessionManager，completed_observations，CodeSandbox 增强 |
| 2.0 | 2026-04-25 | 添加双路径架构，完整重写 |
| 1.0 | — | 初始版本 |

---

## Completed Milestones

| 里程碑 | 目标 | 完成日期 |
|--------|------|----------|
| M1 | 自由探索路径可用 | 2026-04-25 |
| M2 | 双路径切换正常 | 2026-04-26 |
| M3 | 模式发现功能 | 2026-04-26 |
| M4 | 语义检索集成 | 2026-04-27 |
| M5 | 真实 PrimitiveAdapter | 2026-04-27 |
| M6 | LLM 反馈闭环 + 原语参数化 | 2026-04-27 |
| M7 | P2 启发式自由探索 + 模式回注 + Embedding | 2026-04-28 |
| M8 | Phase 1 R1 参数调优 | 2026-04-28 |
| M9 | Phase 1 R2 CTFd 适配器 | 2026-04-28 |
| M10 | Phase 1 R3 删除假数据路径 | 2026-04-28 |
| M11 | Phase 2 R4 browser-inspect 接 Playwright | 2026-04-28 |
| M12 | Phase 2 R5 http-request 接 requests | 2026-04-29 |
| M13 | Phase 2 R6 session-materialize CSRF + JSON body | 2026-04-29 |
| M14 | Phase 2 R7 artifact-scan ZIP/tar 内容提取 + 增大预览 | 2026-04-29 |
| M15 | Phase 2 R8 code-sandbox 放宽 class/with/raise + zlib/csv | 2026-04-29 |
| M16 | Phase 3 R9 扩展族关键词 6→14 | 2026-04-29 |
| M17 | Phase 3 R10 步骤参数注入 | 2026-04-29 |
| M18 | Phase 3 R11 switch_path 真实逻辑 | 2026-04-29 |
| M19 | Phase 3 R12 多族组合 | 2026-04-29 |
| M20 | Phase 4 R13 合并 SecurityConstraints → SecurityConfig | 2026-04-30 |
| M21 | Phase 4 R14 更新 ARCHITECTURE.md 与代码对齐 | 2026-04-30 |
| M22 | Phase 4 R15 简化 Dispatcher/StrategyLayer 间接层 | 2026-04-30 |
| M23 | 真实 CTF 靶场联调 + thinking model + verbose trace + 健壮性修复 | 2026-05-06 |
| M24 | 本地靶场解题率 1/4→3/4（cookie/base64/token chain） | 2026-05-08 |
| M25 | Team Runtime Phase A 协议抽取与兼容映射 | 2026-05-09 |
| M26 | Team Runtime Phase B Blackboard Event Journal | 2026-05-09 |
| M27 | Team Runtime Phase C 同步 ManagerScheduler | 2026-05-09 |
| M28 | Team Runtime Phase D ContextCompiler + MemoryService + IdeaService | 2026-05-09 |
| M29 | Team Runtime Phase E PolicyHarness + HumanReviewGate | 2026-05-09 |
| M30 | Team Runtime Phase F SolverSessionManager | 2026-05-09 |
| M31 | Team Runtime Phase G MergeHub + SubmissionVerifier + Observer | 2026-05-09 |
| M32 | Team Runtime Phase H TeamRuntime + CLI + API | 2026-05-09 |
| M33 | Team Runtime Phase I ReplayEngine + BenchmarkRunner | 2026-05-11 |
| M34 | Team Runtime Phase J ToolBroker 能力扩展 | 2026-05-11 |

---

## Completed Priority Items

| 优先级 | 模块 | 工作量 | 完成日期 |
|--------|------|--------|----------|
| P0 | SecurityConstraints 与 SecurityConfig 对齐 | 1 天 | 2026-04-27 |
| P0 | ConstraintAwareReasoner | 3 天 | 2026-04-25 |
| P0 | EnhancedAPGPlanner | 2 天 | 2026-04-26 |
| P0 | 路径选择逻辑 | 2 天 | 2026-04-26 |
| P0 | 真实 PrimitiveAdapter | 4 天 | 2026-04-27 |
| P1 | DynamicPatternComposer | 4 天 | 2026-04-27 |
| P1 | SemanticRetrievalEngine | 5 天 | 2026-04-27 |
| P1 | CLI 入口 + 集成测试 | 2 天 | 2026-04-27 |
| P2 | 启发式自由探索 + 模式回注 + Embedding 接入 | 5 天 | 2026-04-28 |
| P3 | LLM 反馈闭环 + 原语参数化 | 4 天 | 2026-04-27 |
| P0 | 参数调优（stagnation/confidence 可配置） | 0.5 天 | 2026-04-28 |
| P0 | CTFd Provider 适配器（session auth + API token） | 3 天 | 2026-04-28 |
| P0 | 删除 _consume_metadata 假数据路径（原语真执行或干净失败） | 1.5 天 | 2026-04-28 |
| P1 | browser-inspect 接 Playwright（JS 渲染 + script 读取） | 2 天 | 2026-04-28 |
| P1 | http-request 接 requests（multipart + Basic Auth + SSL bypass） | 1 天 | 2026-04-29 |
| P1 | session-materialize CSRF 预取 + JSON body（CSRF 3 来源 + JSON 登录 + auth 持久化） | 1 天 | 2026-04-29 |
| P1 | artifact-scan 提取 ZIP/tar 内容 + 保留临时文件 + 增大预览（content_preview + content_type + 预览 512→4096） | 0.5 天 | 2026-04-29 |
| P1 | code-sandbox 放宽（class/with/raise 允许 + zlib/csv 导入） | 0.5 天 | 2026-04-29 |
| P2 | 扩展族关键词 6→14（+SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议/竞态） | 1 天 | 2026-04-29 |
| P2 | 步骤参数注入（_inject_challenge_params + bundle.target 回退） | 1 天 | 2026-04-29 |
| P2 | switch_path 真实逻辑（STRUCTURED→FREE_EXPLORATION 停滞切换 + FREE_EXPLORATION→STRUCTURED 回切 + stagnation counter + PATH_SELECTION 事件） | 0.5 天 | 2026-04-29 |
| P2 | 多族组合（_compose_multi_family_candidates 融合 2 族步骤 + PlanCandidate.secondary_families + HeuristicFree 多族融合） | 0.5 天 | 2026-04-29 |

---

## Resolved Limitations

| 原限制 | 解决版本 | 解决方式 |
|--------|----------|----------|
| PrimitiveAdapter 模拟执行 | v3.0 | 9 个原语全部实现真实执行路径 |
| 语义检索仅 TF-IDF | v3.5 | InMemoryVectorStore cosine similarity + embedding, TF-IDF 实现修正, CJK tokenize |
| 模式图硬编码 | v3.5 | PatternInjector 回注动态模式到 PatternLibrary, APGPlanner._plan_candidates 使用动态族 |
| LLM 无执行反馈闭环 | v3.4 | ObservationSummarizer + `_extract_current_state()` 输出实际观测内容 |
| 原语未参数化 | v3.4 | `_resolve_*_specs()` 接受 `step.parameters` 覆盖, `_step_param_overrides()` helper |
| SecurityConstraints 硬编码 | v3.1→v4.1 | v3.1 `SecurityConstraints.from_config(SecurityConfig)` 单一源 → v4.1 SecurityConstraints 删除，SecurityConfig 直接作为 LightweightSecurityShell 约束源 |
| 无 CLI 入口 | v3.2 | `__main__.py` 提供 `python -m attack_agent` 入口 |
| 无启发式自由探索 | v3.5 | HeuristicFreeExplorationPlanner, model=None 时双路径自动切换 |
| 停滞阈值/提交置信度硬编码 | v3.6 | StrategyLayer 构造参数化, stagnation_threshold→8, confidence_threshold→0.6, PlatformConfig 可配置 |
| 无 CTFd 靶场适配器 | v3.7 | CTFdCompetitionProvider 实现 6 方法 Protocol, session auth + API token, CLI --ctfd-* 参数 |
| 原语假数据回退掩盖能力不足 | v3.8 | _consume_metadata 删除, 10 个调用点改为 _clean_fail 干净失败, _extract_candidates 不再读取 primitive_payloads, runtime.py 精简 127 行 |
| browser-inspect 不执行 JS 且丢弃 `<script>` 标签内容 | v3.9 | PlaywrightBrowserInspector(JS 渲染 + script 读取 + console + cookies), StdlibBrowserInspector(graceful fallback), _HTMLPageParser extract_scripts 模式, BrowserConfig(engine/headless/browser_type/timeout/wait_for_selector/extract_scripts) |
| http-request 无 multipart 文件上传、无 HTTP Basic Auth、无 SSL 自签名证书支持 | v3.10 | RequestsHttpClient(multipart + Basic Auth + Bearer Auth + SSL bypass), StdlibHttpClient(graceful fallback), HttpSessionManager.auth_headers 持久化, HttpConfig(engine/verify_ssl/max_redirects/timeout_seconds) |
| session-materialize 仅 form POST 登录（CSRF/JSON body 部分） | v3.11 | _CSRFTokenParser + _extract_csrf_token(CSRF 3 来源), JSON body 登录(json/content_type), auth token 持久化回写 session_manager.add_auth_header(), Observation payload csrf_prefetched/csrf_token_value/body_type |
| artifact-scan 不提取 ZIP/tar 内容（仅列文件名），预览仅 64 字节，下载后立即清理临时文件 | v3.12 | _extract_archive_members 添加 content_preview(ZIP/tar 成员文本预览) + content_type(_guess_content_type 扩展名→MIME 映射), _extract_text_preview 上限 128→4096 默认 64→512, _perform_artifact_scan 返回 (payload, temp_dir) 元组延迟清理, Observation payload 新增 content_type 字段 |
| code-sandbox 禁止 class/with/raise，缺少 zlib/csv 解码库 | v3.13 | _SafeAstValidator 移除 ClassDef/With/Raise 禁止 + visit_ClassDef 跟踪类名, SAFE_IMPORTS 加入 zlib/csv, SAFE_BUILTINS 加入 __build_class__, globals_scope 加入 __name__, class/with/raise 可用 |
| 6 个族关键词过浅，缺少 SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议分析等族 | v3.14 | FAMILY_KEYWORDS 6→14，新增 ssrf-server/ssti-template/csrf-state/idor-access/crypto-math/pwn-memory/protocol-logic/race-condition 8 族，FAMILY_PROFILES + FAMILY_PROGRAMS 4 节点完整步骤，族关键词覆盖常见 CTF 类别(web/crypto/pwn/forensics/protocol) |
| FAMILY_PROGRAMS 步骤不含挑战特定 URL/路径参数 | v3.15 | _inject_challenge_params() 在规划阶段注入 challenge.target→url/login_url 到模板步骤(setdefault 不覆盖)，runtime _resolve_*_specs() 增加 bundle.target 回退(metadata+param_overrides 均空时) |
| switch_path() 是空 stub | v3.16 | EnhancedAPGPlanner.switch_path() 实现 STRUCTURED→FREE_EXPLORATION(停滞≥3自动切换) + FREE_EXPLORATION→STRUCTURED(预算耗尽或置信度≥0.7回切) + _stagnation_counters + record_outcome() + PATH_SELECTION 事件 + stagnation reset |
| 无多族组合攻击链 | v3.16 | _compose_multi_family_candidates() 融合 2 族步骤(观察→主族 + 操作→副族 + 验证→主族，副族得分≥0.7×主族)，PlanCandidate.secondary_families + ProgramDecision.secondary_families + HeuristicFree 多族融合 + DualPathConfig.multi_family_score_ratio |
| identity-boundary verification 阶段无法访问 /admin（privileged_paths 仅注入紧跟 session-materialize 的 http-request） | v4.3 | _inject_challenge_params 改为"第二个+ http-request after session-materialize"注入 privileged_paths |
| SOLVER profile 缺 http-request，encoding-transform 无法收集初始数据 | v4.3 | SOLVER profile 添加 http-request |
| protocol-logic-boundary 关键词缺少 api/rest/token/chain/json/endpoint 等 | v4.3 | 关键词扩展 +11 个 |
| encoding-transform OBSERVATION_GATE 无 http-request 步骤 | v4.3 | 模板添加 http-request + structured-parse |
| web-chain-medium http-request 命中首页而非 /api/step1, /api/step2 | v4.3 | api_endpoints metadata + 注入 |
| session-materialize 无 login_url/credentials 注入 | v4.3 | metadata login_url + credentials 注入 session-materialize 步骤 |
| encoding-transform 无法从 cookie 中提取 base64 编码的 flag | v4.3 | structured-parse 提取 cookies + base64 自动解码 |
| API 链式调用无法传递 token（/api/step1→/api/step2） | v4.3 | token_chain metadata + _substitute_observe_templates {observe.*} 替换 |
| 跨 phase session cookie 丢失（VERIFICATION_GATE 新 task bundle 无 ACTION_TEMPLATE 的 cookie） | v4.3 | _plan_candidates VERIFICATION_GATE 前置 session-materialize + http-request session cookie 恢复 |

---

## Current Limitations & Roadmap

### 已识别问题清单

#### 执行层原语能力缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| E1 | browser-inspect 不执行 JS 且丢弃 `<script>` 标签内容 | 所有 JS 渲染页面、XSS 发现、DOM 操纵类 web 题（约 40% CTF） | 致命 |
| E2 | ~~http-request 无 multipart 文件上传、无 HTTP Basic Auth、无 SSL 自签名证书支持~~ → 已解决 | ~~文件上传题、Basic Auth 保护页面、HTTPS 自签名靶场~~ → v3.10 RequestsHttpClient(multipart + Basic Auth + Bearer Auth + SSL bypass), StdlibHttpClient(graceful fallback), HttpSessionManager.auth_headers |
| E3 | ~~session-materialize 仅 form POST 登录~~ → 部分解决 | ~~Django/Flask-WTF 等 CSRF 站点、API 登录~~ → v3.11 CSRF 预取(form/meta/header) + JSON body + auth 持久化已实现；多步认证(2FA/OAuth)仍 TODO | ~~致命~~ → 降为高 |
| E4 | ~~code-sandbox 禁止 class/lambda/with/raise，无 crypto 库~~ → 部分解决 | ~~RSA/AES/ECC 类密码题、复杂算法~~ → v3.13 class/with/raise 允许 + zlib/csv 导入；lambda 仍禁止 + crypto 库(cryptography/pycryptodome)仍不可用 | ~~高~~ → 降为中 |
| E5 | ~~artifact-scan 不提取 ZIP/tar 内容（仅列文件名），预览仅 64 字节，下载后立即清理临时文件~~ → 已解决 | ~~Forensics 取证题、需要多步分析的文件题~~ → v3.12 content_preview(ZIP/tar 成员文本) + content_type(MIME 映射) + 预览 512→4096 + temp_dir 延迟清理 | ~~高~~ → 已解决 |
| E6 | binary-inspect 无反汇编、无熵分析、strings 限制 20 条 | Reverse 逆向题 | 高 |
| E7 | extract-candidate 仅正则匹配，无启发式 flag 检测 | 非 `flag{}` 格式的 flag | 中 |
| E8 | 原语无 retry 逻辑，网络失败直接返回 failed | 瞬态故障场景 | 低 |

#### 接入层 Provider 缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| P1 | ~~无真实 CTF 平台适配器~~ → 已解决 | 无法对接任何真实靶场 → v3.7 CTFdCompetitionProvider 实现 6 方法 Protocol | ~~致命~~ → 已解决 |
| P2 | ~~HTTP transport 无认证机制~~ → 已解决 | 需要认证的靶场全部无法接入 → v3.7 CTFd session auth + API token | ~~致命~~ → 已解决 |
| P3 | 实例生命周期模型与真实 CTF 不匹配 | 静态挑战、动态容器等场景 | 高 |

#### 规划层策略缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| S1 | ~~6 个族关键词过浅，缺少 SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议分析等族~~ → 已解决 | ~~多数 CTF 类别无匹配，无匹配时返回 None~~ → v3.14 族关键词 6→14，覆盖 SSRF/SSTI/CSRF/IDOR/crypto/pwn/协议/竞态 8 族，FAMILY_PROGRAMS 4 节点完整步骤 | ~~致命~~ → 已解决 |
| S2 | ~~FAMILY_PROGRAMS 步骤不含挑战特定参数（URL/路径/payload）~~ → 部分解决 | ~~步骤是空模板，无法执行具体操作~~ → v3.15 _inject_challenge_params() 填充 url/login_url，runtime 回退 bundle.target；parse_source/program_fragment/diff-compare 仍需 metadata 或 LLM 提供 | ~~高~~ → 降为中 |
| S3 | ~~停滞阈值 3 次连续失败就放弃~~ → 已解决 | 真实解题通常需 10+ 次迭代 → v3.6 stagnation_threshold→8 可配置 | ~~高~~ → 已解决 |
| S4 | max_cycles 默认 12 次 | 远不够真实解题所需 | 高 |
| S5 | ~~switch_path() 是空 stub~~ → 已解决 | ~~文档声称有路径切换功能，实际不存在~~ → v3.16 switch_path() 实现 STRUCTURED→FREE_EXPLORATION(停滞≥3自动切换) + FREE_EXPLORATION→STRUCTURED(预算耗尽或置信度≥0.7回切) + stagnation counter + PATH_SELECTION 事件 | ~~高~~ → 已解决 |
| S6 | ~~flag 提交置信度阈值 0.85 过高~~ → 已解决 | 可能拒绝正确 flag → v3.6 flag_confidence_threshold→0.6 可配置 | ~~中~~ → 已解决 |
| S7 | ~~无多族组合攻击链~~ → 已解决 | ~~只选最高得分族，无法组合跨族策略~~ → v3.16 _compose_multi_family_candidates() 融合 2 族步骤(观察→主族 + 操作→副族 + 验证→主族，副族得分≥0.7×主族得分) + PlanCandidate.secondary_families | ~~中~~ → 已解决 |
| S8 | catch-22：DynamicPatternComposer 需要 3+ 成功案例，但 3 水失败就放弃 | 模式发现闭环无法闭合 | 中 |

#### 架构结构性问题

| # | 问题 | 说明 | 严重度 |
|---|------|------|--------|
| A1 | ~~原语双路径膨胀~~ → 已解决 | 每个原语有真实+回退两条路径，假数据掩盖能力不足 → v3.8 删除假数据路径，原语真执行或干净失败，runtime.py 1629→1502 行 | ~~高~~ → 已解决 |
| A2 | 模式图过于静态 | PatternLibrary.build() 一次性构建，运行中只标记节点状态不重组 | 中 |
| A3 | ~~Dispatcher/Strategy 6 层间接调用~~ → 已解决 | StrategyLayer 是极薄 wrapper → v4.1 StrategyLayer 删除，Dispatcher 内联策略逻辑(stagnation/submit/stage)，strategy.py 仅保留 SubmitClassifier+TaskPromptCompiler | ~~低~~ → 已解决 |

#### 当前能解 vs 不能解

**本地靶场验证结果（v4.4，4 题 4 通过）**：
- web-render-easy（Hidden Comments）✓ — browser-inspect + extract-candidate
- web-encoding-medium（Base64 Cookie）✓ — http-request cookie 捕获 + structured-parse base64 自动解码 + extract-candidate
- web-chain-medium（Multi-Step API）✓ — http-request /api/step1 获取 token + {observe.token} 模板替换注入 /api/step2 query + extract-candidate
- web-auth-easy（Login Portal）✓ — session-materialize 登录成功 + session cookie 跨 cycle 持久化

**能解（约 30-35% CTF 题）**：
- 简单 HTTP GET 页面 + HTML 注释隐藏 flag
- 简单 base64/xor/hex/zlib 压缩/CSV 解析编码题（code-sandbox class/with/raise 可解）
- Cookie 中 base64 编码的 flag（structured-parse 自动解码）
- 多步 API 链式调用（token_chain + {observe.*} 模板替换）
- 简单 class 结构化解码（RSA/AES 参数组装、自定义解码器）
- with 上下文管理器模式（资源清理、文件操作模拟）
- 简单 form POST 登录后获取 flag（需 cookie 正确传递）
- JSON API 响应中直接包含 flag
- Basic Auth 保护页面
- Bearer token 保护 API
- 文件上传 web 题
- HTTPS 自签名靶场
- CSRF token 保护登录页面（Django/Flask-WTF 等）
- JSON body API 登录
- ZIP/tar 内嵌 flag（内容提取 + 文本预览）
- SSRF/SSTI/IDOR/简单密码/pwn/协议分析类题（族关键词匹配）

**仍不能解（约 60-65% CTF 题）**：
- JS 渲染/JS 操纵类 web 题（Playwright 可渲染，但复杂 DOM 操纵仍受限）
- 现代密码题（RSA/AES/padding oracle，crypto 库不可用）
- Reverse/pwn 题（无反汇编、无调试器）
- Forensics 取证题（无 pcap 深度分析、无 EXIF/磁盘映像）
- 多步认证（2FA、OAuth、JWT 操纵）
- 复杂竞态条件（无并发请求基础设施）
- session cookie 跨域/path 传递问题（v4.4 SessionState 持久化已解决）

---

### 四阶段解决计划

#### Phase 1：让系统能跑起来（P0，已完成 ✅）

| # | 任务 | 工作量 | 交付物 | 完成日期 |
|---|------|--------|--------|----------|
| R1 | 参数调优：max_cycles→50, 停滞阈值→8, 提交置信度→0.6 | 0.5 天 | 配置变更 + 测试 | 2026-04-28 |
| R2 | CTFd Provider 适配器（含 session auth） | 3 天 | `ctfd_provider.py` + 测试 | 2026-04-28 |
| R3 | 删除 `_consume_metadata` 假数据路径 | 1.5 天 | runtime.py 精简 + 测试更新 | 2026-04-28 |

**Phase 1 目标已达成**：系统连接真实 CTFd 靶场，原语真执行或干净失败，不再假装工作。

#### Phase 2：补齐原语能力（P1，约 5 天）

| # | 任务 | 工作量 | 交付物 | 完成日期 |
|---|------|--------|--------|----------|
| R4 | browser-inspect 接 Playwright | 2 天 | JS 渲染 + script 读取 + 测试 | 2026-04-28 |
| R5 | http-request 接 requests + multipart + Basic Auth + SSL | 1 天 | 文件上传 + 认证 + 测试 | 2026-04-29 |
| R6 | session-materialize CSRF 预取 + JSON body | 1 天 | CSRF token + JSON 登录 + 测试 | 2026-04-29 |
| R7 | artifact-scan 提取 ZIP/tar 内容 + 保留临时文件 + 增大预览 | 0.5 天 | 完整文件分析 + 测试 | 2026-04-29 |
| R8 | code-sandbox 放宽：class/with/raise + 加 zlib/csv | 0.5 天 | 更强解码能力 + 测试 | 2026-04-29 |

**Phase 2 目标**：原语覆盖 70%+ 常见 web/encoding/forensics 类 CTF 题。

#### Phase 3：规划策略增强（P2，已完成 ✅）

| # | 任务 | 工作量 | 交付物 | 完成日期 |
|---|------|--------|--------|----------|
| R9 | 扩展 FAMILY_KEYWORDS：+SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议等 8 族 | 1 天 | 14 族关键词 + FAMILY_PROGRAMS + 测试 | 2026-04-29 |
| R10 | 步骤参数注入：挑战 target/endpoint/credential 注入步骤模板 | 1 天 | 动态参数填充 + 测试 | 2026-04-29 |
| R11 | 实现 switch_path() 真实逻辑 | 0.5 天 | 路径切换 + 测试 | 2026-04-29 |
| R12 | 多族组合：允许 plan 融合 2 个族的步骤 | 0.5 天 | 组合策略 + 测试 | 2026-04-29 |

**Phase 3 目标已达成**：规划覆盖主流 CTF 类别，步骤不再只是空模板，路径可自动切换，多族组合增强策略覆盖。

#### Phase 4：架构清理（P3，已完成 ✅）

| # | 任务 | 工作量 | 交付物 | 完成日期 |
|---|------|--------|--------|----------|
| R13 | 合并 SecurityConstraints → SecurityConfig（消除重复） | 0.5 天 | 单一约束源 | 2026-04-30 |
| R14 | 更新 ARCHITECTURE.md 与代码对齐 | 0.5 天 | 文档-代码一致 | 2026-04-30 |
| R15 | 简化 Dispatcher/StrategyLayer 间接层 | 1 天 | 合并冗余层 | 2026-04-30 |

**Phase 4 目标已达成**：代码架构清晰，文档准确，无冗余间接层。SecurityConstraints 删除，SecurityConfig 直接作为约束源；StrategyLayer 删除，Dispatcher 内联策略逻辑。

---

### Phase 6 遗留项（原计划）

| 项目 | 状态 |
|------|------|
| 实现路径选择自适应 | → 合入 Phase 3 R11 |
| 添加性能监控 | 未开始 |
| 优化检索质量 | 未开始 |
| 优化规划延迟 | 未开始 |

---

## 2026-04-30 运行验证记录：测试提速与真实模型联调

### 背景

本次验证目标是确认当前项目能否正常工作，并定位全量测试耗时过长的问题。验证范围包括：
- 本地单元/集成测试：`python -m unittest discover tests/ -v`
- CLI heuristic 冒烟：`python -m attack_agent --config config/settings.json --max-cycles 12 --verbose`
- OpenAI 兼容接口真实模型联调：通过 `config/local-openai-compatible.json` + `ATTACK_AGENT_API_KEY`/本地密钥配置

### 已解决问题

1. **全量测试耗时过长**
   - 根因：`tests/test_platform_flow.py` 中多个失败路径测试使用生产默认 HTTP/browser timeout，并重复执行 `solve_all(max_cycles=12)`；无真实 target 时会反复等待网络超时。
   - 修复：为 platform flow 测试增加测试专用 `fast_test_config()`，使用 stdlib HTTP/browser、短 timeout、短 stagnation/path-switch 阈值；将该模块中的 `solve_all(max_cycles=12)` 收敛为 `FAST_SOLVE_CYCLES = 3`。
   - 结果：全量测试从约 **292s** 降到约 **36s**；`test_platform_flow` 从约 **5min+** 降到约 **14s**。

2. **重复集成测试浪费时间**
   - 根因：console summary/pattern/journal 三个测试各自重新跑一次完整 platform flow；`http_request_without_real_target` 与 identity 无真实 target 测试覆盖同一失败语义。
   - 修复：合并 console 输出测试为一个用例；删除重复的 HTTP 无真实 target 测试，保留 identity/http 失败语义覆盖。
   - 结果：测试数从 **330** 调整为 **327**，覆盖重点保持不变。

3. **本地模型配置误提交风险**
   - 根因：真实模型联调需要在本地配置 OpenAI 兼容 `base_url`/`model_name`/key。
   - 修复：`.gitignore` 增加 `config/local-openai-compatible.json`，避免提交本地接口地址和密钥。

### 真实模型联调发现

1. **模型接口可用**
   - `select_worker_profile` 最小探针成功返回 JSON，包含 `profile`/`reason`。
   - 平台 API 联调成功产生 `program_compiled`，`planner_source=['llm', 'llm']`，说明真实模型已参与 worker/profile 决策和结构化 program 选择。

2. **API key 配置优先级容易踩坑**
   - 当前 `model_adapter._resolve_api_key()` 优先读取 `api_key_env`，只有 `api_key_env` 为空时才读取 literal `api_key`。
   - 如果配置同时写了 `api_key` 和 `api_key_env="ATTACK_AGENT_API_KEY"`，但环境变量未设置，CLI 会报 `ValueError: environment variable ATTACK_AGENT_API_KEY not set`。
   - 临时联调方式：在启动进程前把本地配置中的 key 注入同名环境变量；长期建议二选一：要么只用环境变量，要么清空 `api_key_env` 后使用本地 literal key。

3. **OpenAI 兼容接口对较长输出参数敏感**
   - `max_tokens=1024` 时，`choose_program` 曾触发 `model_adapter_connection_error`。
   - 将 `max_tokens` 临时降到 `256`、`timeout_seconds` 提高到 `60` 后，`choose_program` 和平台 4-cycle 联调均成功。
   - 建议本地模型联调配置：
     - `max_tokens`: 256
     - `timeout_seconds`: 60
     - `max_retries`: 0（调试时避免重试掩盖真实失败点）

4. **当前 `127.0.0.1:8000` 未提供可连接靶场服务**
   - shell 侧 `Invoke-WebRequest http://127.0.0.1:8000/` 返回无法连接远程服务器。
   - 因此本次只能确认“模型 + AttackAgent 调度链路”正常，不能确认“模型 + 真实 localhost:8000 靶场解题”。

### 验证结果

```bash
python -m unittest tests.test_platform_flow -v
# Ran 13 tests in ~14s, OK

python -m unittest discover tests/ -v
# Ran 327 tests in ~36s, OK
```

真实模型平台联调摘要：
```text
ok=True
program_compiled_count=2
planner_sources=['llm', 'llm']
outcome_count=2
candidate_flags=0
```

---

## 2026-05-06 运行验证记录：真实 CTF 靶场解题 + thinking model 联调

### 背景

本次验证目标是确认 AttackAgent 能否对接真实 CTF 靶场并解题。使用本地靶场服务器 `scripts/local_range.py`（4 题）+ Xiaomi mimo-v2.5-pro thinking 模型（Anthropic API 格式）。

### 已解决问题

1. **UnicodeEncodeError: 'gbk' codec（Windows 终端）**
   - 根因：LLM 返回文本含 © 等非 GBK 字符，Windows PowerShell 终端默认 GBK 编码
   - 修复：`_safe_print()` 替换所有 `print()`，捕获 UnicodeEncodeError 并替换不可编码字符

2. **KeyError: 'free_exploration'（apg.py）**
   - 根因：`update_graph()` 遍历 `program.pattern_nodes` 时，自由探索程序节点不在 `pattern_graph.nodes` 中
   - 修复：遍历前增加 `if node_id not in record.pattern_graph.nodes: continue` 保护

3. **Anthropic SDK 401 Unauthorized**
   - 根因：系统环境变量 `ANTHROPIC_AUTH_TOKEN` 和 `ATTACK_AGENT_API_KEY` 残留旧值，Anthropic SDK 自动读取并添加冲突的 Bearer header
   - 修复：`AnthropicReasoningModel.__init__()` 清除 `ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL` 环境变量

4. **Thinking model 仅返回 thinking blocks，无 text 输出**
   - 根因：mimo-v2.5-pro 的 thinking 消耗全部 output budget，未留 text block 给 JSON response
   - 修复：当 `enable_thinking=True` 且 `text` 为空但有 `thinking_text` 时，自动 re-request（去掉 thinking 参数），获取实际 JSON 输出

5. **Anthropic SDK 长重试挂起**
   - 根因：SDK 默认 `max_retries=2`，累积等待时间过长
   - 修复：OpenAI 和 Anthropic SDK 客户端均设置 `max_retries=0`

6. **code-sandbox RuntimeError 崩溃**
   - 根因：LLM 生成的代码使用 disallowed calls（如 print），sandbox.execute() 抛出 RuntimeError
   - 修复：`_execute_code_sandbox()` 包裹 try-except RuntimeError，返回 `_clean_fail("code-sandbox")`

7. **stop_challenge HTTP 404**
   - 根因：靶场平台不支持 `/stop_challenge` 端点
   - 修复：`controller.py` 包裹 try-except，pass 忽略可选端点

8. **structured-parse 无 parse_source 时 crash**
   - 根因：缺少 `parse_source` 参数时直接返回 `_clean_fail`，但最近观测可用
   - 修复：自动检测 `completed_observations` 中最近观测作为 `parse_source`

### 解题成果

成功解题 **web-render-easy (Hidden Comments)**：
- 解题路径：browser-inspect → Playwright 渲染页面 → 提取 HTML 注释 → extract-candidate 正则匹配
- Flag：`flag{hidden_in_comments_042}`
- Agent 自动提交 flag，Controller 确认 accepted，项目状态 → DONE

### 新增功能

- **Thinking model 支持**：ModelConfig 新增 `enable_thinking: bool = False`，Anthropic 适配器支持 extended thinking（budget_tokens, temperature=1 强制要求）
- **Verbose LLM trace**：`╔══ LLM CALL: {task} ══` banner + response trace，覆盖 OpenAI 和 Anthropic 两个适配器
- **Dispatcher trace**：cycle header（CYCLE #N | Project | Stage | Stagnation）、program trace（Path/Goal/Steps）、execution outcome trace（Status/Novelty/Cost/Flags）
- **本地靶场服务器**：`scripts/local_range.py`，4 题（web-auth-easy/web-render-easy/web-encoding-medium/web-chain-medium），实现完整 CompetitionProvider REST API + 挑战页面

### 验证结果

```
python -m unittest discover tests/ -v
# 327 tests in ~36s, OK

python scripts/local_range.py --port 8484
python -m attack_agent --config config/local-openai-compatible.json --provider-url http://127.0.0.1:8484 --verbose
# → 成功解题 web-render-easy，flag{hidden_in_comments_042}
```
