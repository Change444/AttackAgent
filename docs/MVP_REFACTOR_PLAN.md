# AttackAgent Refactor And MVP Plan

## Purpose

This document defines a refactor direction that keeps the current architecture idea intact while making the codebase easier to understand, extend, and turn into a real agent MVP.

The goal is not to redesign the system from scratch.

The goal is to:

- preserve the current platform architecture
- remove structural ambiguity
- define a clear MVP boundary
- create a development sequence we can execute incrementally

## Progress Snapshot

The architectural direction in this document still stands, but the repository has moved forward since the plan was first written.

Current repository facts:

- the platform path is the canonical product path
- the legacy single-agent path is being decommissioned
- the first-stage minimal real primitive loop is already closed:
  - `http-request`
  - `browser-inspect`
  - `binary-inspect`
  - `artifact-scan`
- each of those primitives now has:
  - a minimal real branch
  - metadata fallback retained
  - integration-style coverage in `tests/test_platform_flow.py`

That means the project has already completed the earliest primitive-delivery phase envisioned in this plan and is moving into the next stage: persistence, observability, and later model leverage.

## Brainstorm Summary

### What is working already

The current repository already has the right architectural backbone:

- provider-driven challenge lifecycle
- controller and dispatcher control plane
- APG-style planning over primitive actions
- state graph as the source of truth
- runtime with restricted execution semantics
- tests and demos that validate the orchestration loop

This is strong enough to keep.

### What is confusing today

The main problem is not that the architecture is wrong.

The main problem is that the codebase currently mixes two mental models:

1. an older single-agent flow
2. a newer platform/APG flow

That creates four kinds of confusion:

- duplicated concepts: `agent.py` and `platform.py` both look like "the entry point"
- mixed terminology: `models.py` vs `platform_models.py`, old planner vs APG planner
- unclear product boundary: is this a pentest agent, a competition platform, or both
- runtime ambiguity: some parts look agentic, but execution is still mostly metadata-driven

### Recommended design stance

Keep the current platform architecture as the only primary path.

That means the future system should be read as:

`Provider -> Controller -> Dispatcher -> Strategy/APGPlanner -> Runtime -> StateGraph -> Console/API`

The old single-agent path should be treated as one of these:

- legacy compatibility code
- a future thin adapter built on top of the platform

It should no longer be treated as the main product path.

## Product Definition For The MVP

## MVP statement

AttackAgent MVP is:

`a safe, authorized CTF/lab-solving agent platform that can plan, execute a small set of real primitives against local targets, accumulate structured state, and submit a validated flag`

## MVP must do

- ingest challenge definitions from a provider
- start a challenge instance
- choose a worker profile and a pattern family
- execute at least one real primitive against a local target
- convert raw outputs into structured observations/artifacts/hypotheses
- generate and validate candidate flags
- submit a flag through the provider
- preserve a full run journal in the state graph

## MVP explicitly does not need yet

- multi-worker distributed execution
- rich web UI
- persistent long-term memory across many runs
- broad live-environment coverage
- autonomous browser exploitation chains
- support for many challenge families at once

## Architecture To Preserve

We keep these planes:

- Control plane: `provider`, `controller`, `dispatcher`
- Solving plane: `strategy`, `apg`, `reasoning`
- Execution plane: `runtime`, primitive adapters, sandbox
- State plane: `state_graph`, `world_state`, handoff/memory
- Interface plane: demos, console, later API/UI

## Refactor Principles

1. One primary execution path

The platform path is the product path.
Everything else is either legacy, compatibility, or internal utility.

2. Stable domain vocabulary

Each concept should exist in one obvious place:

- challenge/project lifecycle
- planning/program generation
- primitive execution
- state ingestion
- reasoning

3. Preserve behavior before widening capability

Refactor first for clarity.
Then add the first real primitive.
Then add more capabilities.

4. Keep structure aligned with runtime boundaries

Directory layout should reflect how the system actually flows at runtime.

5. Keep AI reasoning constrained

Models may choose among allowed options and propose structured outputs.
They should not bypass policy, provider, runtime, or state-graph boundaries.

## Recommended Package Structure

This is the recommended target structure for the refactor.

```text
attack_agent/
  app/
    platform.py
    bootstrap.py
  domain/
    challenge.py
    events.py
    planning.py
    runtime.py
    state.py
  control/
    controller.py
    dispatcher.py
    provider.py
  solving/
    strategy.py
    apg.py
    reasoning.py
    memory.py
  execution/
    runtime.py
    primitives/
      base.py
      metadata.py
      http_request.py
      browser_inspect.py
      artifact_scan.py
      binary_inspect.py
      extract_candidate.py
      sandbox.py
  state/
    state_graph.py
    world_state.py
    compilers.py
  interfaces/
    console.py
    demos/
      platform_demo.py
      legacy_demo.py
  legacy/
    agent.py
    planner.py
    policy.py
    tools.py
    task_dag.py
    models.py
```

## Why this structure

- `control` owns lifecycle and queueing
- `solving` owns reasoning and action selection
- `execution` owns primitive adapters
- `state` owns durable interpretation and memory
- `interfaces` owns human-facing entry points
- `legacy` isolates the older agent path without deleting it immediately

This preserves the architecture while making the codebase legible.

## Recommended Refactor Decisions

These are the decisions I recommend we adopt unless we explicitly change them.

### Decision 1

The platform path becomes canonical.

Canonical entry point:

- `CompetitionPlatform`

Secondary or legacy:

- `CompetitionPentestAgent`

### Decision 2

The current `reasoning.py` belongs to the platform path, not the legacy path.

It should evolve into the standard AI decision surface for:

- worker profile selection
- family selection
- program step ordering
- later structured analysis and candidate ranking

### Decision 3

Primitive adapters become the main extension mechanism.

New capabilities should come from:

- real adapters
- improved structured parsers
- better memory/reasoning

Not from adding one plugin per challenge type.

### Decision 4

The first MVP environment should be intentionally narrow.

Recommend:

- web challenge only
- local HTTP target only
- one real primitive: `http-request`
- metadata fallback retained for tests and demos

This gives us a real agent loop with controlled scope.

## MVP Scope Recommendation

## MVP target

The first MVP should solve a single local web auth-style challenge using:

- real `http-request`
- metadata or simple rule-based `extract-candidate`
- existing `StateGraphService`
- existing `Controller` and `Dispatcher`
- current APG family selection with optional reasoning assist

## MVP success criteria

1. The platform can run against a local or stubbed HTTP target.
2. `http-request` produces real observations from HTTP responses.
3. Those observations are converted into structured state.
4. The planner reaches `CONVERGE`.
5. The system emits at least one candidate flag.
6. The provider accepts a correct flag.
7. Existing tests stay green.

## What we build in the MVP

### Slice A: Clarify structure

- isolate legacy path
- add clear package boundaries or package-like folders
- update imports and docs
- define one canonical read order

### Slice B: Real primitive path

- implement a real `http-request` adapter
- keep metadata adapter path for fixtures
- let runtime select between real and metadata adapters

### Slice C: State ingestion contract

- standardize how HTTP responses become `Observation`
- standardize extracted endpoints, forms, cookies, response text, and clues

### Slice D: Reasoning contract

- keep heuristic reasoner as fallback
- allow model reasoner to choose among bounded candidates
- log rationale in state graph

### Slice E: MVP test harness

- add an integration-style local HTTP test
- keep unit tests for planner/runtime/state behavior

## Proposed Execution Flow After Refactor

1. Provider returns a challenge definition and starts an instance.
2. Controller creates a project in `StateGraphService`.
3. Dispatcher advances project stage.
4. Strategy selects a worker profile.
5. APG planner builds candidate action programs.
6. Reasoner chooses among bounded candidates.
7. Runtime executes primitives through concrete adapters.
8. Adapter outputs become `ActionOutcome`.
9. State graph ingests events and updates project state.
10. Controller submits a validated candidate.

This is the same architecture as today, just made explicit and cleaner.

## Refactor Sequence

## Phase 1: Make the structure understandable

- mark legacy modules clearly
- document the canonical platform path
- normalize naming around platform concepts

Deliverable:

- cleaner layout and developer docs

## Phase 2: Make one primitive real

- real `http-request`
- metadata fallback retained
- integration-style test added

Deliverable:

- first real environment path

## Phase 3: Make reasoning truly useful

- improve reasoning context
- add real model provider integration behind interface
- keep bounded output schema and fallback path

Deliverable:

- real model-assisted planning that stays safe

## Phase 4: Expand carefully

- browser primitive
- artifact primitive
- binary primitive
- memory persistence

Deliverable:

- broader but still structured solving capability

## Development Tasks For The MVP

### Workstream 1: Architecture cleanup

- create clear module grouping
- move legacy modules behind a `legacy` namespace or mark them clearly
- update imports and demos
- update README and architecture docs

### Workstream 2: HTTP primitive

- define adapter interface
- add real HTTP implementation
- support GET and simple POST
- capture response body, headers, status code, cookies, discovered links
- map output to `Observation`

### Workstream 3: Runtime selection

- choose adapter path by challenge/instance metadata
- retain metadata-driven fixture path for tests
- keep runtime return type stable as `ActionOutcome`

### Workstream 4: Structured parsing

- extract endpoints
- extract auth clues
- extract candidate-looking strings
- keep parser deterministic for MVP

### Workstream 5: Testing

- local HTTP fixture server
- runtime adapter tests
- end-to-end platform flow test with real HTTP calls
- no regression in existing suite

## Risks And Guardrails

### Risk 1

Refactor may blur the boundary between legacy and platform code.

Guardrail:

Do not delete legacy immediately.
Isolate it and stop routing new work through it.

### Risk 2

Real primitive integration may break the clean test baseline.

Guardrail:

Keep metadata fallback and add integration-style tests separately.

### Risk 3

Model reasoning may become too unconstrained.

Guardrail:

Only allow model selection among bounded candidates and allowed primitives.

### Risk 4

Scope may expand too early.

Guardrail:

The first MVP solves one web flow only.

## Acceptance Criteria For This Refactor Plan

- there is one clearly documented canonical architecture path
- legacy code is visibly separated from canonical platform flow
- a development plan exists for a first real primitive
- the MVP scope is narrow and testable
- reasoning integration is preserved but constrained

## Recommended Immediate Next Step

Implement Phase 1 and Phase 2 together in a narrow slice:

- clarify package/module boundaries
- add the real `http-request` adapter
- add one integration-style web challenge test

That is the smallest slice that turns the project from "architecture prototype" into "real agent MVP path".

## Open Decisions For Collaborative Review

These are the decisions I want us to confirm before coding:

1. Should the old single-agent path be moved under `legacy/` now, or only marked deprecated first.
2. Should the MVP target only `http-request`, or include `extract-candidate` improvements in the same slice.
3. Should reasoning integration in the MVP stay heuristic-first, or should we also wire in a real model provider in the same milestone.

## My Recommendation

Recommended answer set:

1. mark legacy first, move second
2. build `http-request` first, keep `extract-candidate` simple
3. keep heuristic-first for MVP, add real model provider in the next milestone

This is the fastest path to a usable and stable MVP.

## Confirmed Control Decisions

These decisions are now confirmed for the current MVP refactor and should be treated as active guidance unless explicitly changed later.

### Decision A

Do not move or rename legacy files in the current slice.

For now we:

- mark the platform path as canonical in developer-facing docs
- mark the old single-agent path as legacy/deprecated
- defer any file migration until after the first real `http-request` MVP slice is accepted

This keeps the current baseline stable while removing ambiguity at the documentation and task-routing level.

### Decision B

`attack_agent.platform_models` is the canonical data-model surface for the platform path.

`attack_agent.models` remains part of the legacy path unless a later refactor explicitly promotes or splits specific types.

That means:

- new platform/MVP work should prefer `platform_models.py`
- no merge or rename happens in the current structure-cleanup slice
- any future consolidation must be proposed as a separate, explicit refactor task

### Decision C

Phase ordering remains strict:

1. documentation and structure clarity
2. real `http-request` primitive slice
3. reasoning improvements
4. broader primitive expansion

The current next implementation milestone is still:

- add the real `http-request` adapter path
- keep metadata fallback
- add one integration-style local HTTP test
