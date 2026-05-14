# AttackAgent - Agent Instructions

## Project

AttackAgent is a Python 3.10+ agent runtime for authorized CTF, training range, and security research environments.

The product direction is a **multi-Solver team runtime** with Manager, Solver, Observer, Human Review, Blackboard, MergeHub, PolicyHarness, ToolBroker, API, and Web UI. The current implementation is still hybrid: `TeamRuntime` is the entry point, while `Dispatcher`, `WorkerRuntime`, and `StateGraphService` still carry much of the real solving behavior.

## Architecture Warning

Team Runtime Phase A-K and L1-L10 created the platform components. L11 real-path stabilization is now complete: all Manager decisions are recorded as `STRATEGY_ACTION`, approved submissions execute once, pause/resume blocks scheduling, verification-state fields align, ToolBroker journals real-path events, Observer is trigger-throttled, and replay uses run_id isolation.

Do not assume a component is complete because a class, endpoint, or UI view exists. The remaining gaps are: memory must be proven as mandatory Solver input in the real path, multi-Solver collaboration must be proven end-to-end, and ToolBroker must become the sole execution path (not only retroactive journaling).

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
npm.cmd --prefix web run build
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
| Execution | `Dispatcher` -> `WorkerRuntime` | Route real solve primitive execution through ToolBroker |
| Runtime state | `StateGraphService` plus Blackboard sync | Blackboard as decision source, StateGraph as per-solver scratchpad |
| Scheduling | `SyncScheduler` calls `TeamManager`, then legacy execution; Manager decisions recorded as STRATEGY_ACTION, worker lifecycle events only from SolverSessionManager | Manager consumes compiled context, reviews, observer reports, budgets, and solver states |
| Memory | `MemoryService`, `IdeaService`, `ContextCompiler`, `MemoryReducer`, and `SolverContextPack` exist | Memory is proven as mandatory Solver input in the real solve path |
| Collaboration | `KnowledgePacket` and `MergeHub` exist | Solver output flows through KnowledgePacket -> MergeHub -> Blackboard/inbox with multi-Solver proof |
| Review | `HumanReviewGate` exists; approved submit executes once, modified review executes modified payload with delta | Review decisions pause/resume/modify real actions exactly once |
| Observer | Observer runs in scheduling loop with trigger/throttle via should_observe() | Observer produces actionable steering without event spam |
| Tools | ToolBroker handles API/manual requests and retroactive real-path journaling via journal_real_execution(); real solve path still goes through Dispatcher/WorkerRuntime directly | ToolBroker mediates real solve tool execution |
| UI | REST API, SSE, and React/Tailwind Web UI exist | Web UI remains product boundary while runtime semantics stabilize |

## Non-Negotiable Rules

- Only authorized targets and local/range fixtures are allowed.
- Do not make Solver code write global protocol state directly; route through Manager/MergeHub/Blackboard services.
- Do not treat complete chat history as memory. Use structured events, facts, ideas, failure boundaries, evidence references, and summaries.
- Do not mix `IdeaEntry`, `CandidateFlag`, and `StrategyAction` in the same event semantics.
- Manager decisions must be `STRATEGY_ACTION`; worker lifecycle events must describe real worker/session transitions only.
- Keep compatibility with the current test baseline unless a roadmap item explicitly changes the behavior.
- Prefer small vertical migrations over broad rewrites.
- Do L11 stabilization before increasing multi-Solver concurrency.
- No test method may take over 2 seconds. Full suite must run under 60 seconds. Use `fast_test_config()` with `stdlib` engine and `timeout_seconds <= 0.5`. Do not use `config/settings.json` in tests.

## Tests

Run focused tests for the touched area, then the full suite when feasible:

```bash
python -m unittest discover tests/
npm.cmd --prefix web run build
```

PowerShell note: use `npm.cmd` if execution policy blocks `npm.ps1`.
