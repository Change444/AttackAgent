# Documentation Audit

Last updated: 2026-05-14

This audit explains why the documentation system was reorganized and tracks the current state of each document.

2026-05-14 update: the documentation now distinguishes **platform components exist** from **the real solve path is complete**. Phase L11 stabilized the real solve path: all Manager decisions are STRATEGY_ACTION, approved submit executes once, pause/resume blocks scheduling, verification fields align, ToolBroker retroactive events, Observer trigger/throttle, and run_id isolation.

## 1. Problems Found

### 1.1 Current reality and target architecture were mixed

Early documents described Team Runtime Phase A-K as completed, but the code still showed a hybrid runtime. L0 reset established the distinction. L1-L10 added the platform components, but the 2026-05-14 review found that some components are still not fully active in the real solve path.

### 1.2 Roadmap acted like a completion log

The original roadmap mixed design, completion logs, and future plans. It now acts as an executable migration plan with explicit acceptance criteria per phase. L11 is the active stabilization phase.

### 1.3 Event semantics were overloaded

`candidate_flag` was reused for idea lifecycle, convergence actions, and merge output. L1 resolved most of this with distinct event types. L11 completed the remaining correction: all Manager decisions (LAUNCH_SOLVER, STEER_SOLVER, etc.) are now recorded as `STRATEGY_ACTION`, not worker lifecycle events.

### 1.4 Documentation rules were too rigid

The old convention "do not update docs for dataclass/enum changes" was too strict for an architecture migration. Updated docs now allow protocol/event semantics documentation when it affects runtime behavior.

### 1.5 Historical docs were used as live design docs

`CHANGELOG.md` is historical only. It must not override `ARCHITECTURE.md` or `TEAM_EVOLUTION_ROADMAP.md`.

## 2. Current Document Roles

| Document | Current Role |
|---|---|
| `README.md` | Short project entry, corrected current status, quick start, doc map |
| `CLAUDE.md` | Working rules for coding agents |
| `AGENTS.md` | Local agent guidance when present in workspace context |
| `docs/ARCHITECTURE.md` | Architecture authority: current reality, L11 stabilization complete, target boundaries, module responsibility, gaps |
| `docs/TEAM_EVOLUTION_ROADMAP.md` | Executable migration plan with acceptance criteria per phase; L11 complete |
| `docs/CONVENTIONS.md` | Engineering, memory, security, and documentation rules |
| `docs/TEAM_PLATFORM_GUIDE.md` | Platform guide: CLI, Python API, REST API, SSE stream, ToolBroker, Web UI Console, and testing playbook |
| `docs/USER_GUIDE.md` | User-facing manual; may lag architecture details, so defer to `ARCHITECTURE.md` for runtime truth |
| `docs/CHANGELOG.md` | Historical record only; do not use as design spec |
| `docs/DOCUMENTATION_AUDIT.md` | Rationale for documentation restructuring and current doc roles |
| `docs/EXECUTION_PROMPT_TEMPLATE.md` | Standardized template for assigning roadmap phase work to agents |

## 3. Authoritative Reading Order

For architecture or team-runtime implementation:

1. `docs/ARCHITECTURE.md`
2. `docs/TEAM_EVOLUTION_ROADMAP.md`
3. `docs/CONVENTIONS.md`
4. Source files touched by the task
5. Relevant tests

For usage:

1. `README.md`
2. `docs/TEAM_PLATFORM_GUIDE.md`
3. `docs/USER_GUIDE.md`

For history:

1. `docs/CHANGELOG.md`

## 4. Documents Rewritten During L0-L11

- `README.md` (L0 + L10 + L11 status correction)
- `CLAUDE.md` (L0, supersedes older tool-specific assumptions)
- `docs/CONVENTIONS.md` (L0)
- `docs/ARCHITECTURE.md` (L0 + each phase + L11 findings)
- `docs/TEAM_EVOLUTION_ROADMAP.md` (L0 + each phase status update + L11 plan)
- `docs/TEAM_PLATFORM_GUIDE.md` (L9 + L10 full rewrite + L11 testing guide)
- `docs/USER_GUIDE.md` (user-facing guide; needs future cleanup for stale claims)
- `docs/DOCUMENTATION_AUDIT.md` (L0 + L10 + L11 update)

## 5. Remaining Documentation Risks

- `docs/CHANGELOG.md` contains Phase A-K and version 4.x entries that reference pre-L0 architecture. These are historical and should not override `ARCHITECTURE.md`.
- `docs/USER_GUIDE.md` still contains older prose and should be cleaned later, but it is no longer the architecture authority.
- Solver freeze/stop/launch and mark idea valid/invalid are documented as pending API/UI operations and will need doc updates when implemented.
- Multi-Solver concurrency above one Solver per project is documented as a remaining limitation until collaboration tests pass end-to-end.
- The remaining gaps after L11 are: memory must be proven as mandatory Solver input in the real path, multi-Solver collaboration must be proven end-to-end, and ToolBroker must become the sole execution path (not only retroactive journaling).
