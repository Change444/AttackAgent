# Documentation Audit

Last updated: 2026-05-12

This audit explains why the documentation system was reorganized.

## 1. Problems Found

### 1.1 Current reality and target architecture were mixed

Several documents described Team Runtime Phase A-K as completed, but the code still shows a hybrid runtime:

- `TeamRuntime` is the entry point.
- `Dispatcher` and `WorkerRuntime` still execute real solve cycles.
- `StateGraphService` remains execution-side state.
- `Blackboard` is durable but still synchronized from legacy state.
- `ContextCompiler`, `Observer`, `Review`, `MergeHub`, and `SolverSessionManager` exist but are not all mandatory in the real scheduling loop.

This made it easy for future implementation agents to assume the final architecture already existed.

### 1.2 Roadmap acted like a completion log

The previous `TEAM_EVOLUTION_ROADMAP.md` mixed:

- original target design,
- completed phase logs,
- implementation notes,
- acceptance claims,
- future plans.

That made it too hard to answer: "What should we do next?"

### 1.3 Event semantics were not called out strongly enough

The biggest architecture bug is semantic overloading:

- `candidate_flag` is used for candidate flags,
- idea lifecycle,
- convergence actions,
- MergeHub arbitration output.

This distorts scheduling and submission governance. The new roadmap makes event cleanup Phase L1.

### 1.4 Documentation rules were too rigid

The old convention "do not update docs for dataclass/enum changes" was too strict for an architecture migration. Protocol and event semantics are part of the architecture. Future docs should not copy every field, but they must describe meaning, ownership, and migration impact.

### 1.5 Historical docs were used as live design docs

`CHANGELOG.md` is useful history, but it should not drive implementation. It can say a phase was completed, while the real architecture may still need integration work.

## 2. New Documentation Roles

| Document | Role |
|---|---|
| `README.md` | Short project entry and doc map |
| `AGENTS.md` | Instructions for future coding agents |
| `docs/ARCHITECTURE.md` | Current architecture authority |
| `docs/TEAM_EVOLUTION_ROADMAP.md` | Executable migration plan |
| `docs/CONVENTIONS.md` | Engineering, memory, security, and documentation rules |
| `docs/TEAM_PLATFORM_GUIDE.md` | Current CLI/API usage and caveats |
| `docs/USER_GUIDE.md` | User examples; verify against architecture before using for implementation |
| `docs/CHANGELOG.md` | Historical record only |
| `docs/DOCUMENTATION_AUDIT.md` | Rationale for documentation restructuring |

## 3. Current Authoritative Reading Order

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

## 4. Documents Rewritten

- `README.md`
- `AGENTS.md`
- `docs/CONVENTIONS.md`
- `docs/ARCHITECTURE.md`
- `docs/TEAM_EVOLUTION_ROADMAP.md`
- `docs/TEAM_PLATFORM_GUIDE.md`
- `CLAUDE.md`

## 5. Known Remaining Risk

`docs/CHANGELOG.md` and `docs/USER_GUIDE.md` may still contain older statements. They are intentionally retained as historical or user-facing references, but they should not override `ARCHITECTURE.md`.

Future work should gradually update `USER_GUIDE.md` after the runtime API stabilizes.
