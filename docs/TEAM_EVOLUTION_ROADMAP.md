# AttackAgent Team Runtime Execution Plan

Last updated: 2026-05-12

This is the executable plan for moving the current hybrid runtime toward the intended multi-Solver team platform. It replaces the older phase-completion roadmap as the planning authority.

## 1. Planning Baseline

Current state:

- `TeamRuntime` is the entry point.
- `Dispatcher` and `WorkerRuntime` still execute the real solving loop.
- `StateGraphService` remains the execution-side state structure.
- `BlackboardService` receives events directly and through state sync.
- Team services exist, but some are not yet active in the real scheduling path.

Main risk:

> The repository looks like it already contains the final team architecture, but much of it is still scaffolding. The next work must move decision authority, memory authority, and collaboration authority into the team runtime.

## 2. Roadmap Principles

1. **Control before concurrency**: make Manager + Context + Policy + Review correct before increasing Solver count.
2. **Memory before model cleverness**: solving continuity comes from structured state, not long chat history.
3. **Event semantics before UI**: Web UI must read clean state, not infer meaning from overloaded events.
4. **Policy before tools**: all action execution routes must be policy-visible before ToolBroker expands.
5. **Observer as input, not decoration**: observer reports must affect scheduling decisions.
6. **Compatibility by adapters**: keep the current test baseline while gradually moving source-of-truth responsibilities.

## 3. Phase L0 - Documentation and Protocol Reset

Status: complete

Goal: stop future implementation drift by defining the current truth and the next migration boundary.

Work items:

- Replace outdated architecture prose with a current-reality architecture document.
- Mark `CHANGELOG.md` as historical, not prescriptive.
- Clarify that Blackboard is not yet the only source of truth.
- Clarify that multi-Solver is not complete.
- Document event overloading as a known architectural bug.
- Add a documentation audit file.

Acceptance:

- README points to `ARCHITECTURE.md` and this plan as the authoritative pair.
- `AGENTS.md` tells future agents not to treat Phase A-K as final architecture.
- `CONVENTIONS.md` contains flexible but explicit team-runtime rules.

## 4. Phase L1 - Event Semantics Cleanup

Status: complete

Problem:

Current code reuses `candidate_flag` for multiple meanings:

- actual candidate flags,
- idea lifecycle,
- convergence action,
- MergeHub arbitration output.

This contaminates scheduling, status, and submission logic.

Implementation plan:

1. Extend team protocol with explicit event names or event payload wrappers.
2. Add compatibility readers that still understand old `candidate_flag` events.
3. Change `IdeaService` to emit idea-specific events.
4. Change `SyncScheduler._record_action()` so `CONVERGE` is recorded as a strategy action, not a candidate flag.
5. Change `apply_event_to_state()` to materialize ideas only from idea events and candidate flags only from candidate events.
6. Add a `CandidateFlagEntry` protocol model if needed.
7. Update status and submit code to read candidate flags from the candidate stream, not from pending ideas.

Acceptance tests:

- Proposing an idea does not increase candidate flag count.
- Recording `CONVERGE` does not create an `IdeaEntry`.
- A real extracted flag appears as candidate flag with evidence refs.
- `TeamManager.decide_submit()` ignores non-flag ideas.
- Legacy event logs can still be replayed.

## 5. Phase L2 - Manager Context Becomes Mandatory

Status: complete

Goal: make Manager decisions depend on compiled team context rather than raw stage inference only.

Implementation plan:

1. Expand `ManagerContext`:
   - project status and stage,
   - solver states,
   - active ideas and claims,
   - candidate flags with verification state,
   - pending reviews,
   - recent human decisions,
   - observer reports,
   - resource and budget status,
   - failure boundaries,
   - high-value facts and credentials.
2. Make `SyncScheduler.schedule_cycle()` call `ContextCompiler.compile_manager_context()` before any Manager decision.
3. Change `TeamManager.decide_stage_transition()` to accept `ManagerContext`.
4. Keep a compatibility method for tests that still pass raw events.
5. Make Manager output richer `StrategyAction` payloads:
   - target solver,
   - target idea,
   - risk level,
   - budget request,
   - policy tags,
   - review requirement,
   - reason and evidence refs.

Acceptance tests:

- Pending review blocks execution of the corresponding action.
- Active failure boundary changes a `STEER_SOLVER` decision.
- A high-confidence candidate flag produces submit intent only when verification data exists.
- Resource exhaustion changes launch/steer behavior.

## 6. Phase L3 - Policy and Review Become Execution Gates

Status: complete

Goal: no Manager action executes without policy validation and review handling.

Implementation plan:

1. Add a scheduler-level `execute_strategy_action()` function.
2. Every action passes:
   - `PolicyHarness.validate_action()`,
   - `HumanReviewGate` when policy says review is required,
   - action executor only if allowed or approved.
3. `ReviewRequest` must persist the exact proposed action payload.
4. Approval resumes the exact action once.
5. Rejection writes a `FailureBoundary` or policy memory entry.
6. Modified approval creates a new action payload and records the delta.
7. Fix submit risk handling so Manager's high-risk submit action is not downgraded inside `TeamRuntime.submit_flag()`.
8. Add fail-closed timeout behavior for safety/cost/submission reviews.

Acceptance tests:

- A high-risk action creates a pending review and does not execute.
- Approving review executes the exact action once.
- Rejecting review prevents execution and records a failure boundary.
- Submit flag always goes through verifier, policy, and review rules.
- A review decision appears in replay with causal linkage to the original action.

## 7. Phase L4 - Memory Drives Solver Continuity

Status: complete

Goal: each Solver receives a compact, structured, continuous context instead of relying on isolated task calls.

Implementation plan:

1. Expand `SolverContextPack`:
   - active claimed idea,
   - solver local memory,
   - global facts,
   - credentials/endpoints,
   - failure boundaries,
   - inbox knowledge packets,
   - artifacts,
   - recent tool outcomes,
   - budget and risk constraints.
2. Bind `SolverSession` to the context pack used for each execution.
3. Add `scratchpad_summary` and `recent_event_ids` to session state.
4. After every tool outcome, run memory reducers:
   - fact extractor,
   - idea updater,
   - failure boundary extractor,
   - candidate flag extractor,
   - knowledge packet builder.
5. Feed the next Solver turn from `SolverContextPack`, not raw full logs.
6. Ensure failure boundaries are injected into planning and can suppress repeated attempts.

Acceptance tests:

- A Solver's second turn sees facts produced by its first turn.
- A failed approach becomes a failure boundary and prevents immediate repetition.
- A credential discovered by one turn is available as structured context later.
- Context pack length remains bounded while preserving key evidence.

## 8. Phase L5 - Real SolverSession Ownership

Status: complete

Goal: make SolverSession a real long-lived role in the execution path.

Implementation plan:

1. Create sessions through `SolverSessionManager` for every active Solver.
2. Assign and claim an idea before execution.
3. Bind execution outcome to `solver_id` and `active_idea_id`.
4. Track session budget and status transitions inside real solve cycles.
5. Keep `Dispatcher` as a legacy runner adapter, but pass in solver identity and compiled context.
6. Allow multiple active sessions only after idea claims and memory routing are reliable.

Acceptance tests:

- A launched Solver has a persisted session before execution.
- Solver status transitions from created -> assigned -> running -> completed/failed.
- Outcome events include `solver_id`.
- Two Solvers cannot claim the same idea lease.
- `max_project_solvers=1` remains compatible with current baseline.

## 9. Phase L6 - KnowledgePacket and MergeHub Routing

Status: complete

Goal: make Solver collaboration structured and low-noise.

Implementation plan:

1. Add `KnowledgePacket` protocol:
   - type: fact, idea, failure_boundary, credential, endpoint, artifact_summary, candidate_flag, help_request,
   - source solver,
   - confidence,
   - evidence refs,
   - routing priority,
   - suggested recipients.
2. Solver publishes packets after each turn.
3. MergeHub validates, dedupes, arbitrates, and routes packets.
4. Global accepted packets update Blackboard.
5. Targeted packets enter Solver inbox.
6. Raw logs remain evidence refs, not broadcast content.

Acceptance tests:

- Duplicate facts merge into one accepted memory entry.
- Conflicting facts create a merge decision rather than overwriting silently.
- High-priority candidate flag reaches Verifier/Manager.
- A help request routes to a different Solver profile.
- Solver inbox changes the next context pack.

## 10. Phase L7 - Observer in the Scheduling Loop

Status: complete

Goal: Observer detects drift and Manager acts on it.

Implementation plan:

1. Run Observer after N events, repeated failures, low novelty, or solver timeout.
2. Store `ObserverReport` as a first-class protocol event.
3. Add intervention levels:
   - L0 observe,
   - L1 reminder,
   - L2 steer,
   - L3 throttle,
   - L4 stop/reassign,
   - L5 safety block.
4. Manager consumes reports and chooses steer/throttle/stop/reassign/review.
5. Stop/reassign/safety recommendations pass PolicyHarness and HumanReviewGate when required.

Acceptance tests:

- Repeated action report causes a steering action.
- Ignored failure boundary can stop or reassign a Solver.
- Observer never directly mutates facts or stops a Solver.
- Critical observer reports create review or policy-block events.

## 11. Phase L8 - ToolBroker Becomes the Tool Execution Path

Status: complete

Goal: all primitive/tool execution is brokered and policy-visible.

Implementation plan:

1. Move IO-dependent primitives behind ToolBroker:
   - HTTP,
   - browser,
   - session materialization,
   - artifact scan,
   - binary inspect.
2. Pass real session/browser/http context into broker adapters.
3. Record request, policy decision, execution start, result, and failure events.
4. Keep WorkerRuntime as the actual primitive executor during migration.
5. Make direct WorkerRuntime execution a compatibility path only.

Acceptance tests:

- HTTP primitive request passes through ToolBroker and PolicyHarness.
- Denied tool request never reaches WorkerRuntime.
- Tool result creates memory extraction events.
- Tool event stream is replayable.

## 12. Phase L9 - API Event Stream and Web UI Foundation

Status: complete

Goal: prepare for GUI/Web UI without coupling UI to internals.

Implementation plan:

1. Add missing REST endpoints:
   - start/pause/resume project,
   - add hint,
   - graph view,
   - observer reports,
   - candidate flags,
   - artifacts,
   - replay timeline.
2. Add SSE or WebSocket events:
   - project_updated,
   - solver_updated,
   - idea_updated,
   - memory_added,
   - observer_reported,
   - review_created,
   - review_decided,
   - candidate_flag_found,
   - tool_event.
3. Fix `team serve` CLI path and tests.
4. Build Web UI only after API contract is stable.

Acceptance tests:

- API can start and pause a project.
- Review queue updates through API.
- Event stream emits solver and memory updates.
- Replay endpoint explains the key decisions.

## 13. Phase L10 - Web UI / GUI Console

Status: in progress

Goal: expose the team runtime as an operable product.

Core views:

- Dashboard
- Project Workspace
- Graph View
- Team Board
- Idea Board
- Memory Board
- Observer Panel
- Review Queue
- Artifact Viewer
- Candidate Flag Panel
- Replay Timeline

Required actions:

- start/pause/resume project,
- approve/reject/modify review,
- add hint,
- freeze or stop Solver,
- launch Solver profile,
- mark idea valid/invalid,
- approve flag submit,
- inspect evidence chain,
- replay full solve.

Acceptance:

- Operator can understand what the system is doing.
- Operator can intervene at key nodes.
- Candidate flags show evidence and verifier status.
- Replay explains why Manager made key decisions.

## 14. Priority Order

Do this order unless a bug blocks the baseline:

1. L0 documentation reset.
2. L1 event semantics cleanup.
3. L2 Manager context mandatory.
4. L3 policy/review execution gate.
5. L4 memory-driven continuity.
6. L5 real SolverSession ownership.
7. L6 KnowledgePacket/MergeHub routing.
8. L7 Observer scheduling loop.
9. L8 ToolBroker real execution path.
10. L9 API event stream.
11. L10 Web UI.

## 15. Definition of Done for the Team Architecture

The architecture is not "done" until these are true in the real solve path:

- Manager consumes compiled context.
- Policy validates every strategy action.
- Review can pause and resume real actions.
- SolverSession owns long-lived state.
- Memory and failure boundaries affect planning.
- Solver sharing happens through KnowledgePacket and MergeHub.
- Observer reports affect scheduling.
- Tool execution goes through ToolBroker.
- Candidate flag submission is governed and auditable.
- Replay explains the decision chain.
- Web UI can operate and audit the process.
