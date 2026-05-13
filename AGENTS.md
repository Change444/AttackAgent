# AttackAgent - Agent Instructions

## Project

AttackAgent is a Python 3.10+ agent runtime for authorized CTF, training range, and security research environments.

The product direction is a **multi-Solver team runtime** with Manager, Solver, Observer, Human Review, Blackboard, MergeHub, PolicyHarness, and ToolBroker. The current implementation is not fully there yet. It is a hybrid runtime where `TeamRuntime` is the entry point, while `Dispatcher`, `WorkerRuntime`, and `StateGraphService` still carry much of the real solving behavior.

## Phase A-K Warning

Team Runtime Phase A through K (protocol, blackboard, manager, scheduler, context, memory, ideas, policy, review, solver, merge, observer, submission, runtime, CLI, API) created the component scaffolding. These phases are **not** the final architecture. Many components exist but are not yet mandatory in every real scheduling cycle. Read `docs/ARCHITECTURE.md` and `docs/TEAM_EVOLUTION_ROADMAP.md` for the current reality and migration boundary before assuming a component is complete.

## Read First

Before implementing architecture or team-runtime changes, read:

1. `docs/ARCHITECTURE.md`
2. `docs/TEAM_EVOLUTION_ROADMAP.md`
3. `docs/CONVENTIONS.md`
4. Source files touched by the change

Use `docs/CHANGELOG.md` only as history, not as the current design authority.

## Quick Start

```bash
python -m unittest discover tests/
python -m attack_agent --config config/settings.json
python -m attack_agent --provider-url http://127.0.0.1:8080
python -m attack_agent --config config/settings.json --model openai --verbose
```

Python API:

```python
from attack_agent.factory import build_team_runtime
from attack_agent.provider import InMemoryCompetitionProvider

provider = InMemoryCompetitionProvider([...])
runtime = build_team_runtime(provider)
runtime.solve_all()
```

## Current Architecture Map

| Area | Current Reality | Target Direction |
|---|---|---|
| Entry | `build_team_runtime()` + `TeamRuntime.solve_all()` | Keep as public entry |
| Execution | `Dispatcher` -> `WorkerRuntime` | Gradually route through SolverSession + ToolBroker |
| Runtime state | `StateGraphService` plus Blackboard sync | Blackboard as decision source, StateGraph as per-solver scratchpad |
| Scheduling | `SyncScheduler` calls `TeamManager`, then legacy execution; L3 hard policy/review gate; L4 SolverContextPack compiled after execution | Manager consumes compiled context, reviews, observer reports, budgets, and solver states |
| Memory | `MemoryService`, `IdeaService`, `ContextCompiler`, `MemoryReducer` — L4 complete: SolverContextPack carries facts, credentials, endpoints, failure boundaries, tool outcomes, budget, scratchpad; compiled in production scheduling path; all lists bounded | Memory continues as mandatory Solver input; L5 gives SolverSession real ownership; L6 adds KnowledgePacket inbox |
| Collaboration | `MergeHub` exists, no formal KnowledgePacket protocol | Solver output flows through KnowledgePacket -> MergeHub -> Blackboard/inbox |
| Review | `HumanReviewGate` exists; L3 complete: review pauses/resumes real actions, causal linkage, re-execution from proposed_action_payload | Review decisions pause/resume real actions |
| Observer | Manual/advisory observer | Observer runs in scheduling loop and produces actionable steering |
| UI | CLI/API only; old `WebConsoleView` is text output | Web UI/GUI console after API semantics stabilize |

## Non-Negotiable Rules

- Only authorized targets and local/range fixtures are allowed.
- Do not make Solver code write global protocol state directly; route through Manager/MergeHub/Blackboard services.
- Do not treat complete chat history as memory. Use structured events, facts, ideas, failure boundaries, evidence references, and summaries.
- Do not mix `IdeaEntry`, `CandidateFlag`, and `StrategyAction` in the same event semantics.
- Keep compatibility with the current test baseline unless a roadmap item explicitly changes the behavior.
- Prefer small vertical migrations over broad rewrites.
- No test method may take over 2 seconds. Full suite must run under 60 seconds. Use `fast_test_config()` with `stdlib` engine and `timeout_seconds <= 0.5`. Do not use `config/settings.json` in tests.

## Tests

Run focused tests for the touched area, then the full suite when feasible:

```bash
python -m unittest discover tests/
```
