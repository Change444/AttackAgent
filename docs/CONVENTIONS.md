# AttackAgent Conventions

This file defines working rules for future implementation agents. These are guidelines, not a cage. When a rule conflicts with a safer or clearly simpler implementation, document the reason in the PR or implementation note.

## Engineering Rules

- Keep changes scoped to the requested behavior.
- Preserve the current passing baseline unless the task explicitly changes it.
- Prefer existing project patterns over new abstractions.
- Use typed public functions and dataclasses for protocol objects.
- Add tests proportional to risk. Architecture migrations need integration tests, not only dataclass tests.
- Do not fake successful tool execution. Missing configuration or unsupported capabilities must fail cleanly.

## Test Performance Rules

- Every individual test method must complete in under 2 seconds.
- The full test suite must complete in under 60 seconds.
- No real network timeouts above 1 second in tests. Use `stdlib` engine with `timeout_seconds <= 0.5` via `fast_test_config()`.
- No `sleep()` calls in tests. Use event-driven waits or reduce cycle counts instead.
- Tests that run `solve_all()` must use the minimum cycle count needed to verify the assertion. "Fails cleanly" tests typically need only 1 cycle; "solves successfully" tests need 2-3.
- Do not use `config/settings.json` (production config with 30s/10s timeouts) in tests. Use a fast test config dict written to a temp file instead.
- Playwright browser tests are exempt from the 2s-per-method rule due to browser startup cost, but must share a browser instance across the test class via `setUpClass`/`tearDownClass`.

## Team Runtime Rules

- `TeamRuntime` is the public entry point.
- `ManagerScheduler`/`TeamManager` must become the only control plane for team decisions.
- Solver code must not directly claim global protocol ownership or write authoritative global facts.
- Blackboard events should be structured and semantically specific. Avoid reusing one event type for unrelated concepts.
- `IdeaEntry`, `CandidateFlag`, `StrategyAction`, `ReviewRequest`, and `KnowledgePacket` should remain separate protocol concepts.
- `ContextCompiler` output must be treated as operational input, not merely an introspection artifact.
- `PolicyHarness` should gate Manager actions, Solver plans, tool calls, submissions, and human-approved actions.
- `Observer` is advisory by design, but its reports must be consumed by Manager if generated inside the scheduling loop.

## Memory Rules

- LLM chat history is not the memory system.
- Durable memory is composed of EventLog, MemoryEntry, IdeaEntry, FailureBoundary, evidence references, artifacts, and compact summaries.
- A failure that has evidence should become a `FailureBoundary`.
- A hypothesis without evidence is an idea, not a fact.
- Facts require evidence references or a clear source event.

## KnowledgePacket Rules

- Solver sharing uses `KnowledgePacket`, not raw logs or full chat history.
- All packets pass through MergeHub (validate → dedup → arbitrate → route) before entering Blackboard or Solver inbox.
- Global accepted packets update Blackboard as OBSERVATION, CANDIDATE_FLAG, or ACTION_OUTCOME events.
- Targeted packets enter Solver inbox via `KNOWLEDGE_PACKET_MERGED` events.
- Conflicting packets produce `MergeDecision` entries visible in Blackboard, not silent overwrites.
- Help requests use `suggested_recipients` with `"profile:X"` notation for profile-based routing.
- Inbox is bounded by `SOLVER_CONTEXT_LIMITS["max_inbox_items"]`.

## Security Rules

- AttackAgent is limited to authorized labs, CTFs, and controlled fixtures.
- Scope, budget, tool risk, host allowlists, and submission limits must be policy-visible.
- High-risk actions, candidate flag submission, scope expansion, environment/container actions, and conflict arbitration must support human review.
- Safety-related review timeouts should fail closed.

## Documentation Rules

- `docs/ARCHITECTURE.md` is the current architecture authority.
- `docs/TEAM_EVOLUTION_ROADMAP.md` is the executable implementation plan.
- `docs/CHANGELOG.md` is historical only.
- `docs/USER_GUIDE.md` and `docs/TEAM_PLATFORM_GUIDE.md` should describe current usage, not future aspirations.
- When architecture and implementation differ, document both: "current reality" and "target direction".
- Avoid huge phase-completion claims unless the code path actually uses the component in the real solve loop.
