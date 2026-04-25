# Stage 1 Report

## Summary

Stage 1 is complete.

`AttackAgent` now has a stable canonical platform path and a closed first-stage minimal real primitive loop.

## What Was Completed

The platform path stayed canonical:

- `platform`
- `controller`
- `dispatcher`
- `state_graph`
- `apg`
- `runtime`
- `strategy`

The following minimal real primitives were closed:

- `http-request`
- `browser-inspect`
- `binary-inspect`
- `artifact-scan`

Each primitive now has:

- a minimal real runtime branch
- metadata fallback retained
- integration-style coverage in platform-flow tests

## What This Means

The repository is no longer only a metadata-driven architecture skeleton.

It is now a runnable platform skeleton with:

- real primitive execution against narrow local targets
- structured state ingestion
- candidate flag generation and submission flow
- state-graph and journal capture across the platform path

This means the project has reached the `can run` milestone.

## What Is Still Missing

The platform has not yet reached `can operate` or `can scale`:

- `EpisodeMemory` is still in-memory only
- `PatternGraph` and `RunJournal` are not yet visualized in a real web UI
- browser, binary, and artifact support are still minimal slices
- model assistance is present, but not yet backed by persistent memory and stronger observability

## Legacy Decommission Outcome

The old single-agent path is no longer treated as the product path.

This cleanup phase removes legacy public entry points, demos, and legacy-only tests while keeping shared internals that are still reused by platform state and handoff code.

New repository baseline after cleanup:

- `python -m unittest discover -s tests -v` -> `24/24 OK`
- `python -m attack_agent.platform_demo` -> solved demo output preserved

## Recommended Next Stage

The next stage should move from `can run` to `can accumulate` and then `can observe`:

1. minimal `EpisodeMemory` persistence
2. retrieval quality improvements
3. minimal `PatternGraph` / `RunJournal` visualization
4. only then deeper model-assisted planning
5. only then broader primitive expansion
