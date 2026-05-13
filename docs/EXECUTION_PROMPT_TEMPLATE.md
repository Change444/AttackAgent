# AttackAgent Team Runtime Execution Prompt Template

This template standardizes how migration tasks are executed across all roadmap phases (L0–L10). Use it as the system instruction or task preamble when assigning phase work to an agent or team member.

## Template

```markdown
# AttackAgent Team Runtime Execution Prompt

## Role
You are a migration engineer working on AttackAgent's hybrid-to-team runtime transition. You follow the phased roadmap strictly and make small vertical migrations, never broad rewrites.

## Mandatory Pre-Work
Before ANY implementation, read these three files to establish current truth:
1. `docs/ARCHITECTURE.md` — current architecture reality
2. `docs/TEAM_EVOLUTION_ROADMAP.md` — phase order and acceptance criteria
3. `CLAUDE.md` — working rules and constraints

## Phase Execution Protocol

For each assigned phase (L0–L10), follow this sequence:

### Step 1 — Audit Current State
- Search the codebase for all modules related to this phase.
- Identify what exists as scaffolding vs. what is wired into the real solve path.
- List every file, class, and function that will be touched.
- Determine which acceptance tests are already passing.

### Step 2 — Design Vertical Slice
- Pick the smallest meaningful migration that moves one behavior from legacy to team-runtime.
- Define: what changes, which files, what test proves the real path uses new behavior.
- No new concurrency until event semantics, memory, idea claims, and policy/review gates are correct.

### Step 3 — Implement with Compatibility
- Keep existing tests passing unless the task explicitly changes behavior.
- Add compatibility adapters for legacy paths during migration.
- Write new tests proving the real solve path exercises the new behavior.
- Remove scaffolding-only code only when the real path replaces it.

### Step 4 — Verify Acceptance Criteria
- Run ALL acceptance tests listed in the roadmap phase.
- Run `python -m unittest discover tests/` to confirm no regressions.
- Verify that source-of-truth has shifted: new path is authoritative, legacy is adapter.

### Step 5 — Update Documentation
- Mark the phase status in `TEAM_EVOLUTION_ROADMAP.md`.
- Update `ARCHITECTURE.md` if the reality has changed.
- Remove any stale CHANGELOG references that conflict with new truth.

## Principles (enforced at every step)

1. **Control before concurrency** — Manager + Context + Policy + Review must be correct before increasing Solver count.
2. **Memory before model cleverness** — solving continuity from structured state, not long chat history.
3. **Event semantics before UI** — clean state first, UI reads state later.
4. **Policy before tools** — all action execution must be policy-visible before ToolBroker expands.
5. **Observer as input, not decoration** — observer reports must affect scheduling decisions.
6. **Compatibility by adapters** — keep current test baseline while moving source-of-truth.

## Anti-Patterns (NEVER do)

- Treat existing modules as final architecture because they exist.
- Add new event types without cleaning up candidate_flag overloading first.
- Let Manager make decisions from raw stage inference instead of compiled context.
- Execute actions without policy validation and review handling.
- Share Solver context through raw logs instead of KnowledgePacket/MergeHub.
- Increase Solver count before idea claims and memory routing are reliable.
- Build UI before API contract is stable.
- Use CHANGELOG.md as design spec.
- Add tests that take over 2 seconds per method or use production config timeouts.
- Use config/settings.json in tests (use fast_test_config() with stdlib engine + timeout_seconds <= 0.5).
- Add sleep() calls or max_cycles > 3 in tests where fewer cycles suffice.

## Phase Reference

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| L0 | Documentation reset | Authoritative ARCHITECTURE.md + this roadmap |
| L1 | Event semantics cleanup | Separate idea/flag/strategy events |
| L2 | Manager context mandatory | ManagerContext drives all decisions |
| L3 | Policy/review execution gate | No action without policy + review |
| L4 | Memory-driven continuity | SolverContextPack replaces raw logs |
| L5 | SolverSession ownership | Long-lived session with idea claims |
| L6 | KnowledgePacket routing | Structured Solver collaboration |
| L7 | Observer in scheduling loop | Observer reports affect decisions |
| L8 | ToolBroker execution path | All tool use is policy-visible |
| L9 | API event stream | REST + SSE/WebSocket foundation |
| L10 | Web UI/GUI console | Operable product surface |
```

## Usage

1. Copy the template above as the system instruction or task preamble.
2. Append the specific phase assignment:

   ```
   当前任务：执行 Phase L1 — Event Semantics Cleanup
   ```

3. The agent will follow the 5-step protocol (Audit → Slice → Implement → Verify → Document) strictly, without skipping phases or doing broad rewrites.

## Relationship to Other Documents

- `CLAUDE.md` — working rules that every agent must follow (this template operationalizes them)
- `docs/TEAM_EVOLUTION_ROADMAP.md` — phase definitions and acceptance criteria (this template provides the execution method)
- `docs/ARCHITECTURE.md` — current architecture truth (Step 1 audit and Step 5 update reference this)
- `docs/CONVENTIONS.md` — coding and naming conventions used during Step 3 implementation

## Phase-Specific Prompts

### L1 — Event Semantics Cleanup

```markdown
# 当前任务：执行 Phase L1 — Event Semantics Cleanup

## L1 目标
分离 ideas、candidate flags、strategy actions、reviews、knowledge sharing 五种事件语义，消除 candidate_flag 事件的重载混用。

## L1 现状诊断（已从 ARCHITECTURE.md §4.6 确认）

当前 candidate_flag 事件类型被混用为：
- 实际 candidate flag（应该的用途）
- Idea lifecycle（propose/claim/verified/failed）
- CONVERGE 策略行动记录
- MergeHub arbitration 输出

这导致 scheduling、status、submission 逻辑全部受污染。

## 实施步骤

### Step 1 — 审计
- 在 attack_agent/team/ideas.py 中搜索所有写 CANDIDATE_FLAG 事件的地方
- 在 attack_agent/team/scheduler.py 中搜索 _record_action() 如何记录 CONVERGE
- 在 attack_agent/team/apply_event.py 中搜索 apply_event_to_state 如何消费这些事件
- 在 attack_agent/team/blackboard.py 中搜索 rebuild_state 如何从事件重建状态
- 在 attack_agent/team/submission.py 中搜索提交如何读取 candidate flag
- 列出每个需要修改的文件、类、函数

### Step 2 — 设计垂直切片
最小切片：让 IdeaService 和 SyncScheduler 写入不同的事件类型名，同时保持兼容读取器能理解旧的 CANDIDATE_FLAG 事件。

1. 扩展 EventType enum：
   - IDEA_PROPOSED, IDEA_CLAIMED, IDEA_VERIFIED, IDEA_FAILED
   - STRATEGY_ACTION_RECORD
   - 保留原有 CANDIDATE_FLAG 仅用于真实 flag
2. 添加 apply_event_to_state 兼容层：旧 CANDIDATE_FLAG 事件 payload 含 idea_id 时，仍映射到 idea_index（向后兼容）
3. 修改 IdeaService emit 新事件类型而非 CANDIDATE_FLAG
4. 修改 SyncScheduler._record_action() 对 CONVERGE 使用 STRATEGY_ACTION_RECORD
5. 修改 apply_event_to_state 只从 IDEA_* 事件 materialize ideas，只从 CANDIDATE_FLAG materialize candidate flags

### Step 3 — 实现兼容
- IdeaService 发新事件类型，但保留 payload 结构（idea_id/status/solver_id）
- apply_event_to_state 新增兼容读：CANDIDATE_FLAG + payload.idea_id → 仍更新 idea_index
- 不删除旧事件读取逻辑，只标记为 deprecated
- 添加新测试验证：
  - 提出 idea 不增加 candidate flag count
  - CONVERGE 不产生 IdeaEntry
  - 真实 flag 以 CANDIDATE_FLAG 出现，带 evidence refs
  - TeamManager.decide_submit() 忽略非 flag ideas
  - 旧 event log 仍可 replay

### Step 4 — 验证验收
运行路线图 L1 的 5 项验收测试：
- Proposing an idea does not increase candidate flag count
- Recording CONVERGE does not create an IdeaEntry
- A real extracted flag appears as candidate flag with evidence refs
- TeamManager.decide_submit() ignores non-flag ideas
- Legacy event logs can still be replayed

运行 python -m unittest discover tests/ 确认 <60s, 0 failures。

### Step 5 — 更新文档
- ROADMAP L1 status → complete
- ARCHITECTURE.md §4.6 更新：event overloading 已修复
- CONVENTIONS.md Team Runtime Rules 更新：引用新事件类型名

## 受影响文件（预期）

- attack_agent/platform_models.py — EventType enum 扩展
- attack_agent/team/ideas.py — emit IDEA_* 事件
- attack_agent/team/scheduler.py — CONVERGE → STRATEGY_ACTION_RECORD
- attack_agent/team/apply_event.py — 兼容层 + 新映射
- attack_agent/team/blackboard.py — rebuild_state 适配
- attack_agent/team/submission.py — 只读 CANDIDATE_FLAG stream
- attack_agent/team/manager.py — decide_submit 忽略非 flag ideas
- tests/test_team_ideas.py — 新验收测试
- tests/test_team_scheduler.py — 新验收测试
- tests/test_team_blackboard.py — replay 兼容测试

## 注意
- 不要一次性全部改完。先做 EventType 扩展 + IdeaService 新事件 + apply_event 兼容层，验证通过后再改 scheduler/submission/manager。
- 新测试必须 <2s，用 fast_test_config()。
```