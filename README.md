# AttackAgent

`AttackAgent` is a safe-by-default scaffold for building an authorized CTF competition platform around:

- a provider/controller/dispatcher control plane
- a generalized APG solving core
- a structured state graph as the source of truth
- a primitive runtime with narrow real adapters plus metadata fallback
- an optional reasoning layer that stays inside platform guardrails

This repository intentionally does **not** ship exploit payloads, internet scanning logic, or arbitrary command generation. The included runtime is meant for authorized local targets and controlled fixtures.

## Quick start

```powershell
python -m unittest discover -s tests -v
python -m attack_agent.platform_demo
```

## Resume Work

When context is running out, resume from these files instead of relying on old chat history:

- [Current State](docs/CURRENT_STATE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Next Steps](docs/NEXT_STEPS.md)
- [Handoff Template](docs/HANDOFF_TEMPLATE.md)

## Canonical path

The canonical product path is the platform flow rooted at `attack_agent.platform`.

Read and extend the system in this order:

- `attack_agent.platform`: canonical platform entry point
- `attack_agent.controller`: challenge lifecycle and submit policy
- `attack_agent.dispatcher`: worker scheduling and stage flow
- `attack_agent.state_graph`: project state, journal, handoff, and memory source of truth
- `attack_agent.apg`: action-program generation and pattern-graph planning
- `attack_agent.runtime`: primitive runtime and adapter execution
- `attack_agent.strategy`: worker profile and family-selection policy

This is the path that matches the current architecture documents and active MVP refactor direction.

## Current stage

The first-stage minimal real primitive loop is now closed:

- `http-request`
- `browser-inspect`
- `binary-inspect`
- `artifact-scan`

Each of these keeps a metadata fallback path for tests and controlled fixtures, but they are still intentionally narrow slices rather than full environment coverage.

## Legacy status

The older single-agent path is no longer part of the product surface.

This repository is actively decommissioning the old single-agent entry points and their tests. Some shared internal modules still remain while platform-facing state and memory internals are migrated more cleanly, but they should not be treated as public or canonical APIs.

## Supporting modules

- `attack_agent.world_state`: structured blackboard used by the state-graph handoff and evidence pipeline
- `attack_agent.compilers`: progress and retry handoff compilation
- `attack_agent.apg`: pattern graphs, retrieval memory, APG planner, and code sandbox
- `attack_agent.reasoning`: heuristic and model-driven reasoning adapters for platform decisions
- `attack_agent.provider`: local and in-memory competition provider adapters
- `attack_agent.state_graph`: persistent project graph, entity graph, run journal, and memory views
- `attack_agent.controller`: competition lifecycle and submit/hint policy
- `attack_agent.dispatcher`: worker scheduling, heartbeat, timeout, requeue, and stop-loss
- `attack_agent.runtime`: worker runtime, primitive adapters, and workspace checkpoints
- `attack_agent.platform`: end-to-end competition platform orchestrator
- `attack_agent.console`: read-only console snapshot layer
- `attack_agent.platform_models`: canonical platform-path data structures

## Design choices

- Execution stays constrained to allowed local targets and controlled runtime paths.
- Primitive adapters are the main extension mechanism, not one plugin per challenge type.
- The runtime keeps metadata fallback so tests and narrow fixtures stay stable while real branches are added.
- The state graph service remains the single source of truth for project, journal, evidence, handoff, and pattern status.
- Reasoning may choose among bounded candidates, but it does not bypass provider, runtime, or state-graph boundaries.
