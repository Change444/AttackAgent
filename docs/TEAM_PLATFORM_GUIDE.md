# AttackAgent Team Platform Guide

Last updated: 2026-05-12

This guide describes the current CLI/API surface. It does not claim that the final Web UI or full multi-Solver runtime is complete.

## 1. Current Capability

Available today:

- `TeamRuntime` Python entry point.
- CLI commands under `python -m attack_agent team ...`.
- FastAPI app factory in `attack_agent.team.api`.
- Blackboard event replay and metrics helpers.
- Review lifecycle endpoints.
- ToolBroker for IO-free primitives.

Known caveats:

- Real solving still goes through `Dispatcher` and `WorkerRuntime`.
- IO-dependent primitives are not fully brokered through `ToolBroker`.
- `Observer` is manual/advisory unless explicitly called.
- Human review can be created and resolved, but scheduler-level pause/resume is not complete.
- There is no production Web UI yet.

## 2. CLI

```bash
python -m attack_agent team run --config config/team_settings.json
python -m attack_agent team status
python -m attack_agent team status <project_id>
python -m attack_agent team replay <project_id>
python -m attack_agent team reviews
python -m attack_agent team reviews <project_id>
python -m attack_agent team observe <project_id>
python -m attack_agent team replay-steps <project_id>
python -m attack_agent team evaluate <project_id>
python -m attack_agent team tools
```

Review commands:

```bash
python -m attack_agent team review approve <request_id> --project-id <pid> --reason "approved"
python -m attack_agent team review reject <request_id> --project-id <pid> --reason "rejected"
python -m attack_agent team review modify <request_id> --project-id <pid> --reason "modified"
```

API serving is intended to be:

```bash
python -m attack_agent team serve --port 8000
```

However, verify `attack_agent/team/cli.py` before relying on this command. The current source should be checked and fixed as part of the API/UI phase because older docs claimed this path before it was fully hardened.

## 3. Python API

```python
from attack_agent.factory import build_team_runtime
from attack_agent.provider import InMemoryCompetitionProvider

provider = InMemoryCompetitionProvider([...])
runtime = build_team_runtime(provider)
runtime.solve_all()
```

Direct TeamRuntime construction is useful for component tests and event-journal experiments:

```python
from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig

runtime = TeamRuntime(TeamRuntimeConfig())
project = runtime.run_project("demo-1")
report = runtime.get_status(project.project_id)
runtime.close()
```

## 4. API

The current FastAPI router exposes read/introspection and review endpoints:

```text
GET  /api/projects
GET  /api/projects/{project_id}
GET  /api/projects/{project_id}/ideas
GET  /api/projects/{project_id}/memory
GET  /api/projects/{project_id}/solvers
GET  /api/projects/{project_id}/reviews
GET  /api/projects/{project_id}/events
GET  /api/projects/{project_id}/observe
POST /api/reviews/{request_id}/approve
POST /api/reviews/{request_id}/reject
POST /api/reviews/{request_id}/modify
GET  /api/tools
GET  /api/tools/{name}
POST /api/projects/{project_id}/request-tool
GET  /api/projects/{project_id}/replay-steps
GET  /api/projects/{project_id}/metrics
POST /api/regression
```

Missing for final product:

- project start/pause/resume,
- hint injection,
- graph endpoint with stable protocol,
- observer report list,
- candidate flag endpoint,
- artifact endpoint,
- SSE/WebSocket event stream,
- Web UI.

## 5. ToolBroker

Current ToolBroker supports IO-free primitive execution:

- `structured-parse`
- `diff-compare`
- `code-sandbox`
- `extract-candidate`

IO-dependent primitives currently need more integration:

- `http-request`
- `browser-inspect`
- `session-materialize`
- `artifact-scan`
- `binary-inspect`

These should move behind ToolBroker in the roadmap phase dedicated to real tool execution.
