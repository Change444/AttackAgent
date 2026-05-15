# AttackAgent Team Platform Guide

Last updated: 2026-05-15

This guide describes the current Team Runtime platform: CLI, Python API, REST API, SSE event stream, ToolBroker, and Web UI Console. L1-L11 stabilization is complete.

## 1. Current Capability

The repository contains the L1-L11 platform components. The real solve path has been stabilized with all 8 L11 bugs fixed.

| Phase | Capability | Current status |
|-------|------------|----------------|
| L1 | Clean event semantics | Complete |
| L2 | Manager consumes compiled ManagerContext | Complete |
| L3 | Policy/review execution gates | Complete |
| L4 | Memory-driven solver continuity | Complete |
| L5 | SolverSession lifecycle | Complete |
| L6 | KnowledgePacket + MergeHub routing | Complete |
| L7 | Observer scheduling loop with trigger/throttle | Complete |
| L8 | ToolBroker execution path | Complete (API/manual + retroactive real-path journaling) |
| L9 | REST API + SSE event stream | Complete |
| L10 | Web UI Console | Complete |
| L11 | Real-path stabilization | Complete |

Known limitations:

- Solver freeze/stop/launch profile API endpoints are pending or disabled in UI.
- Mark idea valid/invalid API endpoints are pending.
- ToolBroker real solve path is retroactive journaling; full mediation still requires Dispatcher/WorkerRuntime.
- Multi-Solver collaboration requires end-to-end proof beyond single-Solver baseline.

## 2. CLI

```bash
# Run project
python -m attack_agent team run --config config/team_settings.json

# Status
python -m attack_agent team status
python -m attack_agent team status <project_id>

# Replay
python -m attack_agent team replay <project_id>
python -m attack_agent team replay-steps <project_id>

# Reviews
python -m attack_agent team reviews
python -m attack_agent team reviews <project_id>

# Review actions
python -m attack_agent team review approve <request_id> --project-id <pid> --reason "approved"
python -m attack_agent team review reject <request_id> --project-id <pid> --reason "rejected"
python -m attack_agent team review modify <request_id> --project-id <pid> --reason "modified"

# Observation
python -m attack_agent team observe <project_id>

# Evaluation & tools
python -m attack_agent team evaluate <project_id>
python -m attack_agent team tools

# Start API server with Web UI static mount when web/dist exists
python -m attack_agent team serve --port 8000
```

## 3. Python API

```python
from attack_agent.factory import build_team_runtime
from attack_agent.provider import InMemoryCompetitionProvider

provider = InMemoryCompetitionProvider([...])
runtime = build_team_runtime(provider)
runtime.solve_all()
```

Direct TeamRuntime construction:

```python
from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig

runtime = TeamRuntime(TeamRuntimeConfig())
project = runtime.run_project("demo-1")
report = runtime.get_status(project.project_id)
runtime.close()
```

## 4. REST API

The API should be treated as the UI/product boundary. UI code should not reach into internal services directly.

### Project endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects` | List all projects with status reports |
| GET | `/api/projects/{id}` | Single project status report |
| POST | `/api/projects/start-project` | Start a new project |
| POST | `/api/projects/{id}/pause` | Pause a running project |
| POST | `/api/projects/{id}/resume` | Resume a paused project |
| POST | `/api/projects/{id}/hint` | Inject a hint into a project |
| GET | `/api/projects/{id}/ideas` | List idea entries |
| GET | `/api/projects/{id}/memory` | Deduped fact memory entries |
| GET | `/api/projects/{id}/solvers` | Solver session list |
| GET | `/api/projects/{id}/reviews` | Pending review requests |
| GET | `/api/projects/{id}/events` | Full event replay log |
| GET | `/api/projects/{id}/observe` | Current observation report |
| GET | `/api/projects/{id}/graph` | Materialized state |
| GET | `/api/projects/{id}/observer-reports` | Observer report events |
| GET | `/api/projects/{id}/candidate-flags` | Genuine candidate flag events |
| GET | `/api/projects/{id}/artifacts` | Artifact events |
| GET | `/api/projects/{id}/replay-timeline` | Replay with human-readable explanations |
| GET | `/api/projects/{id}/replay-steps` | Replay steps with state snapshots |
| GET | `/api/projects/{id}/metrics` | RunMetrics for a project |
| GET | `/api/projects/{id}/verify-consistency` | Verify API data matches Blackboard replay |

### Review endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/reviews/{id}/approve` | Approve a review request |
| POST | `/api/reviews/{id}/reject` | Reject a review request |
| POST | `/api/reviews/{id}/modify` | Modify a review request |
| GET | `/api/reviews` | Global review queue |

### Tool and evaluation endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tools` | List available primitives |
| GET | `/api/tools/{name}` | Single primitive spec |
| POST | `/api/projects/{id}/request-tool` | Request a tool for a solver through ToolBroker |
| POST | `/api/regression` | Run regression comparison |

### SSE event stream

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events/stream` | SSE real-time event stream |

Query params: `project_id` optional filter, `last_event_id` resume point.

SSE event type mapping:

| EventType | SSE channel |
|-----------|-------------|
| `project_upserted` | `project_updated` |
| `worker_assigned`, `worker_heartbeat`, `worker_timeout` | `solver_updated` |
| `idea_proposed`, `idea_claimed`, `idea_verified`, `idea_failed` | `idea_updated` |
| `observation`, `memory_stored` | `memory_added` |
| `observer_report` | `observer_reported` |
| `security_validation` pending | `review_created` |
| `security_validation` decided | `review_decided` |
| `candidate_flag` | `candidate_flag_found` |
| `action_outcome`, `tool_request` | `tool_event` |
| `hint` | `hint_added` |
| `knowledge_packet_published` | `knowledge_published` |
| `knowledge_packet_merged` | `knowledge_merged` |

## 5. ToolBroker

ToolBroker provides the brokered API/manual tool path with PolicyHarness validation and event journaling, plus retroactive real-path journaling via `journal_real_execution()`. IO-dependent primitives use `WorkerRuntimeIOContextProvider` to access session/browser/http context.

| Primitive | Capability | IO-dependent | Current broker path |
|-----------|------------|--------------|---------------------|
| `http-request` | network/http | Yes | ToolBroker -> IOContextProvider -> WorkerRuntime backend |
| `browser-inspect` | browser/dom | Yes | ToolBroker -> IOContextProvider -> WorkerRuntime backend |
| `session-materialize` | session/state | Yes | ToolBroker -> IOContextProvider -> WorkerRuntime backend |
| `artifact-scan` | artifact/fs | Yes | ToolBroker -> IOContextProvider -> WorkerRuntime backend |
| `binary-inspect` | binary/strings | Yes | ToolBroker -> IOContextProvider -> WorkerRuntime backend |
| `structured-parse` | text/parse | No | ToolBroker direct |
| `diff-compare` | compare/diff | No | ToolBroker direct |
| `code-sandbox` | sandbox/transform | No | ToolBroker direct |
| `extract-candidate` | extract/flag | No | ToolBroker direct |

## 6. Web UI Console

### Startup

Production mode, single port:

```bash
npm.cmd --prefix web install
npm.cmd --prefix web run build
python -m attack_agent team serve --port 8000
```

Browser: `http://localhost:8000`

Development mode:

```bash
# Terminal 1: backend
python -m attack_agent team serve --port 8000

# Terminal 2: frontend
npm.cmd --prefix web install
npm.cmd --prefix web run dev
```

Browser: `http://localhost:5173`

PowerShell note: use `npm.cmd` if script execution policy blocks `npm.ps1`.

### Core views

| View | Route | Description |
|------|-------|-------------|
| Dashboard | `/dashboard` | Project list with global stats |
| Project Workspace | `/projects/{id}` | Single project detail with lifecycle controls and tabs |
| Graph View | `/projects/{id}/graph` | Materialized state graph |
| Team Board | `/projects/{id}/team` | Solver pool with status and budget |
| Idea Board | `/projects/{id}/ideas` | Idea lifecycle columns |
| Memory Board | `/projects/{id}/memory` | Memory entries by kind |
| Observer Panel | `/projects/{id}/observer` | Observer reports with severity/intervention |
| Review Queue | `/reviews` | Global review queue |
| Candidate Flag Panel | `/projects/{id}/flags` | Candidate flags with evidence |
| Artifact Viewer | `/projects/{id}/artifacts` | Artifact list |
| Replay Timeline | `/projects/{id}/replay` | Step-by-step replay |

### Human operations

| Operation | Where | API endpoint |
|-----------|-------|--------------|
| Start project | Dashboard | POST `/api/projects/start-project` |
| Pause project | Project Workspace header | POST `/api/projects/{id}/pause` |
| Resume project | Project Workspace header | POST `/api/projects/{id}/resume` |
| Add hint | Project Workspace header | POST `/api/projects/{id}/hint` |
| Approve review | Review Queue / Project Workspace | POST `/api/reviews/{id}/approve` |
| Reject review | Review Queue / Project Workspace | POST `/api/reviews/{id}/reject` |
| Modify review | Review Queue | POST `/api/reviews/{id}/modify` |

Disabled or semantically pending operations:

- Freeze Solver.
- Stop Solver.
- Launch Solver with a selected profile.
- Mark idea valid/invalid.
- Direct flag approval outside the review flow.

## 7. How To Test

### Environment checks

```bash
python --version
npm.cmd --prefix web --version
```

If `python` is not on PATH, fix the local Python launcher before running backend tests.

### Backend tests

```bash
python -m unittest discover tests/
```

Focused L11 tests cover:

- launch/session event separation,
- approved submit executes once,
- modified review executes modified payload,
- pause blocks real scheduling,
- verification state field alignment,
- ToolBroker events appear on the real solve path,
- Observer trigger/throttle,
- run replay is not destroyed by a second run.

### Frontend build

```bash
npm.cmd --prefix web run build
```

### API and Web UI smoke test

```bash
python -m attack_agent team serve --port 8000
```

Then check:

- `GET http://localhost:8000/api/projects`
- `GET http://localhost:8000/api/events/stream`
- `http://localhost:8000` renders the Web UI from `web/dist`.

### Manual runtime smoke test

1. Start a project through API or Web UI.
2. Confirm a Manager action is recorded as `STRATEGY_ACTION`.
3. Confirm SolverSession lifecycle events are written only by `SolverSessionManager`.
4. Create or trigger a high-risk review.
5. Approve it and confirm exactly one execution and one `review_consumed` event.
6. Pause a project and confirm no scheduling cycle runs until resume.
7. Open Replay Timeline and confirm the decision chain is understandable.
