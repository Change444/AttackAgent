# AttackAgent

AttackAgent is an agent runtime for authorized CTF, training ranges, and security research labs. The project explores a team-style solving architecture, but the current implementation is still in a transition stage.

The guiding idea is **constraint-aware reasoning, not candidate selection**: the framework constrains scope, budget, tools, and evidence, while leaving the model room to explore.

## Current Status

The current runtime is a hybrid:

- `TeamRuntime` is the public entry point.
- `Dispatcher` and `WorkerRuntime` still execute the real solve loop.
- `StateGraphService` is still the execution-side runtime state.
- `BlackboardService` is a SQLite event journal and cross-solver state foundation, but not yet the only source of truth.
- Team modules such as `PolicyHarness`, `HumanReviewGate`, `Observer`, `MergeHub`, `ContextCompiler`, and `SolverSessionManager` exist, but several are not yet mandatory in every scheduling cycle.

This distinction matters. The repository contains many vNext components, but the final multi-Solver team runtime has not been fully realized.

## Quick Start

```bash
# Run tests
python -m unittest discover tests/

# Rule-based mode
python -m attack_agent --config config/settings.json

# Local HTTP provider
python -m attack_agent --provider-url http://127.0.0.1:8080

# LLM mode
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

## Documentation Map

Read these in order:

1. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - current architecture, current gaps, and target boundaries.
2. [docs/TEAM_EVOLUTION_ROADMAP.md](docs/TEAM_EVOLUTION_ROADMAP.md) - executable plan for turning the current hybrid runtime into the intended team runtime.
3. [docs/CONVENTIONS.md](docs/CONVENTIONS.md) - engineering and documentation rules.
4. [docs/TEAM_PLATFORM_GUIDE.md](docs/TEAM_PLATFORM_GUIDE.md) - current CLI/API usage notes and known caveats.
5. [docs/DOCUMENTATION_AUDIT.md](docs/DOCUMENTATION_AUDIT.md) - why the documentation was reorganized and which old assumptions were removed.

Historical material:

- [docs/CHANGELOG.md](docs/CHANGELOG.md) records version history. Do not treat it as the current architecture specification.
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) may contain older user-facing examples; verify against `docs/ARCHITECTURE.md` and source before using it for implementation work.

## Safety Boundary

AttackAgent is for authorized labs and CTF-style targets only. It is not intended for unsanctioned public-target testing, arbitrary command generation, or autonomous attack activity without scope controls.
