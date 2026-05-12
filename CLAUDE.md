# AttackAgent - Claude/Coding Agent Notes

These notes are for agents working in this repository.

## First Principle

Do not assume the team architecture is complete because the modules exist. The current codebase is a hybrid runtime. Read `docs/ARCHITECTURE.md` and `docs/TEAM_EVOLUTION_ROADMAP.md` before changing team-runtime behavior.

## Project Summary

AttackAgent is a Python 3.10+ runtime for authorized CTF, training range, and security research environments. The target product is a multi-Solver team platform with Manager, Solver, Observer, Human Review, Blackboard, MergeHub, PolicyHarness, ToolBroker, CLI/API, and eventually Web UI.

## Current Implementation Summary

- Public construction: `attack_agent.factory.build_team_runtime`.
- Main runtime: `attack_agent.team.runtime.TeamRuntime`.
- Real solve execution still depends on `Dispatcher` and `WorkerRuntime`.
- `StateGraphService` still owns much execution-side state.
- `BlackboardService` is durable and important, but it is not yet the only source of truth.
- Several team services are componentized but not mandatory in every real scheduling cycle.

## Working Rules

- Prefer small vertical migrations over broad rewrites.
- Keep existing tests passing unless the requested task explicitly changes behavior.
- Do not treat `CHANGELOG.md` as the current design spec.
- Do not add new concurrency before event semantics, memory, idea claims, and policy/review gates are correct.
- Route architecture decisions through the concepts in `docs/ARCHITECTURE.md`.
- Use `docs/TEAM_EVOLUTION_ROADMAP.md` for implementation order.

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

## Architecture Work Checklist

Before implementing a team-runtime change, identify which migration phase it belongs to:

- L1 event semantics cleanup
- L2 Manager context mandatory
- L3 policy/review execution gate
- L4 memory-driven continuity
- L5 real SolverSession ownership
- L6 KnowledgePacket/MergeHub routing
- L7 Observer scheduling loop
- L8 ToolBroker real execution path
- L9 API event stream
- L10 Web UI

Architecture changes should include tests proving the real path uses the new behavior, not only component-level tests.
