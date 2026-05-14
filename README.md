# AttackAgent

AttackAgent is an agent runtime for authorized CTF, training ranges, and security research labs. The project explores a team-style solving architecture while preserving the current safe execution shell and legacy solving baseline.

The guiding idea is **constraint-aware reasoning, not candidate selection**: the framework constrains scope, budget, tools, and evidence, while leaving the model room to explore.

## Current Status

The repository now contains the L1-L10 team-platform components:

- clean team event types,
- Manager context compilation,
- Policy and Human Review gates,
- SolverSession, memory, idea, and failure-boundary models,
- KnowledgePacket and MergeHub collaboration primitives,
- Observer reports,
- ToolBroker API path,
- REST API, SSE stream, and React/Tailwind Web UI.

However, the architecture is still in **L11 real-path stabilization**. Several components exist but are not yet fully proven on the actual solving path:

- `LAUNCH_SOLVER` must stop writing worker lifecycle events directly.
- Approved high-risk submissions must execute once without creating a second review.
- Pause/resume must block the real scheduling loop.
- Verification ids must align between `SubmissionVerifier` and `ContextCompiler`.
- ToolBroker must become the real solve execution path, not only the manual API path.
- Observer reports need trigger/throttle logic.
- Replay/audit should use run isolation instead of clearing project events.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/TEAM_EVOLUTION_ROADMAP.md](docs/TEAM_EVOLUTION_ROADMAP.md) for the authoritative status.

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

# Team platform with Web UI
pip install -e ".[team]"
npm.cmd --prefix web install
npm.cmd --prefix web run build
python -m attack_agent team serve --port 8000
# Browser: http://localhost:8000
```

PowerShell note: use `npm.cmd` if script execution policy blocks `npm.ps1`.

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

1. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - current architecture, L11 stabilization findings, and target boundaries.
2. [docs/TEAM_EVOLUTION_ROADMAP.md](docs/TEAM_EVOLUTION_ROADMAP.md) - executable plan, including L11 acceptance tests.
3. [docs/TEAM_PLATFORM_GUIDE.md](docs/TEAM_PLATFORM_GUIDE.md) - CLI, Python API, REST API, SSE stream, ToolBroker, and Web UI guide.
4. [docs/USER_GUIDE.md](docs/USER_GUIDE.md) - user-facing operation manual.
5. [docs/CONVENTIONS.md](docs/CONVENTIONS.md) - engineering and documentation rules.
6. [docs/DOCUMENTATION_AUDIT.md](docs/DOCUMENTATION_AUDIT.md) - documentation roles and known stale assumptions.

Historical material:

- [docs/CHANGELOG.md](docs/CHANGELOG.md) records version history. Do not treat it as the current architecture specification.

## Safety Boundary

AttackAgent is for authorized labs and CTF-style targets only. It is not intended for unsanctioned public-target testing, arbitrary command generation, or autonomous attack activity without scope controls.
