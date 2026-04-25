# Current State

## Project Goal

Build `AttackAgent` into a legally authorized CTF competition platform with a stable control plane and a generalized APG solving core.

## Current Architecture

The current platform shape is:

- `CompetitionProvider`
- `Controller`
- `Dispatcher`
- `StateGraphService`
- `APGPlanner`
- `Primitive Runtime`
- `Web Console`

The solving core is no longer organized around per-challenge plugins. It uses:

- primitive actions
- pattern graphs
- retrieval memory
- a restricted code sandbox

## Completed Modules

The repository already contains these working modules:

- `provider`
- `controller`
- `dispatcher`
- `state_graph`
- `apg`
- `runtime`
- `strategy`
- `platform`
- `console`
- `platform_demo`
- `tests`

## Verified Baseline

Validation commands:

```powershell
python -m unittest discover -s tests -v
python -m attack_agent.platform_demo
```

Current expected baseline:

- tests: `32/32 OK`
- demo output:

```text
project:web-1 | done | solved | family=identity-boundary | flags=1
```

## Current Limitations

- The runtime now has narrow real `http-request`, `browser-inspect`, `binary-inspect`, and `artifact-scan` branches, but the broader primitive surface is still incomplete.
- The current real `browser-inspect` path is only a minimal rendered-page slice, not full browser automation.
- The current real `binary-inspect` path is only a minimal printable-strings/baseline observation slice, not full binary analysis.
- The current real `artifact-scan` path is only a minimal single-file artifact observation slice, not directory scanning or a full forensics workflow.
- `EpisodeMemory` now has a minimal local persistence slice, but it is not yet a full memory system.
- `EpisodeMemory.search()` now has a minimal retrieval-quality ranking improvement, but it is not a full retrieval system.
- `LLMReasoner` now has a minimal model-assisted candidate-selection slice, but it is not a full model-assisted planner.
- `PatternGraph` and `RunJournal` now each have a minimal single-project text console view, but there is still no web visualization for either one.
- The platform is a generalized solving skeleton, not a finished real-environment executor.

## Minimal Real Primitive Status

The first-stage minimal real primitive loop is now closed in the current repository:

- `http-request`
- `browser-inspect`
- `binary-inspect`
- `artifact-scan`

These are still narrow slices, not broad live-environment coverage.

## Legacy Decommission Status

The old single-agent path is no longer the product path.

- The canonical entry point is `attack_agent.platform`.
- Legacy single-agent public entry points, demo wiring, and legacy-only tests have been removed from the active repository surface.
- Some shared internal modules with legacy origins still remain because they are reused by the platform state/handoff layer and must be migrated carefully rather than deleted blindly.

## MVP HTTP Slice Status

The current MVP HTTP slice is partially real rather than metadata-only:

- `http-request` is no longer only metadata-driven.
- For local HTTP targets, the runtime can use a real request branch when `instance.metadata["http_request"]` is present.
- When `http_request` configuration is absent, the existing metadata fallback path remains in place.
- The real HTTP observation path currently records baseline structured fields including `endpoints`, `cookies`, `forms`, and `auth_clues`.
- Platform-flow tests cover both the real HTTP branch and the metadata fallback branch.

## MVP Browser Slice Status

The current browser slice is also partially real, but still intentionally minimal:

- `browser-inspect` now has a minimal real branch in addition to the metadata-driven path.
- The real branch is only enabled for local loopback `http(s)` rendered web targets when `instance.metadata["browser_inspect"]` is present.
- When `browser_inspect` configuration is absent, the existing metadata fallback path remains in place.
- The current real `browser-inspect` slice is limited to basic rendered-page capture fields such as page title, rendered text, HTML comments, and rendered node identifiers.
- Platform-flow tests cover both the real `browser-inspect` branch and the existing browser metadata path baseline.
- This should not be read as full browser automation: there is no claim here of JavaScript execution, multi-step interaction, or multi-page workflow support.

## MVP Binary Slice Status

The current binary slice is also partially real, but still intentionally minimal:

- `binary-inspect` now has a minimal real branch in addition to the metadata-driven path.
- The real branch is only enabled for a single local file-backed target when `instance.metadata["binary_inspect"]` is present.
- When `binary_inspect` configuration is absent, the existing metadata fallback path remains in place.
- The current real `binary-inspect` slice is limited to deterministic printable-strings extraction and baseline binary observation fields.
- Platform-flow tests cover both the real `binary-inspect` branch and the existing binary metadata path baseline.
- This should not be read as full binary analysis: there is no claim here of ELF/PE parsing, disassembly, symbol recovery, or multi-stage sample analysis.

## MVP Artifact Slice Status

The current artifact slice is also partially real, but still intentionally minimal:

- `artifact-scan` now has a minimal real branch in addition to the metadata-driven path.
- The real branch is only enabled for a single local `file://` target when `instance.metadata["artifact_scan"]` is present.
- When `artifact_scan` configuration is absent, the existing metadata fallback path remains in place.
- The current real `artifact-scan` slice is limited to baseline artifact observation fields: URI, name, size, suffix, hash, and a strictly bounded small text preview.
- Platform-flow tests cover both the real `artifact-scan` branch and the existing artifact metadata path baseline.
- This should not be read as directory scanning, archive handling, recursive scanning, or a full forensics workflow.

## EpisodeMemory Persistence Status

`EpisodeMemory` is no longer limited to pure in-memory mode:

- The current persistence slice only stores `EpisodeEntry` records.
- Persistence uses a single local JSON file.
- When no store path is provided, `EpisodeMemory` remains purely in-memory.
- When a store path is provided, initialization can load existing persisted entries.
- If the file does not exist yet, initialization safely starts with an empty entry set.
- `add()` performs a minimal synchronous write-back when persistence is enabled.
- `tests/test_apg_engine.py` covers both persistence write-out and a rebuilt instance successfully finding a persisted entry via `search()`.
- This should not be read as a full memory system: there is no claim here of database storage, complex retrieval infrastructure, or full-state persistence.

## EpisodeMemory Retrieval Quality Status

`EpisodeMemory.search()` now has a minimal retrieval-quality improvement, but it is still intentionally narrow:

- The current slice only improves ranking inside the existing lexical retrieval path.
- The immediate goal is to rank a stronger match ahead of a weaker partially overlapping entry.
- The `EpisodeEntry` shape has not changed.
- The `RetrievalHit` shape has not changed.
- The current single-file JSON persistence behavior has not changed.
- The current in-memory-without-path mode, load-on-init behavior, and `add()` write-back behavior have not changed.
- `tests/test_apg_engine.py` covers this minimal ranking improvement.
- This should not be read as semantic retrieval, vector retrieval, database-backed memory, or a full retrieval system.

## LLMReasoner Candidate Selection Status

`LLMReasoner` now has a minimal model-assisted candidate-selection slice, but it is still intentionally narrow:

- The current slice only adds a `candidate_index` selection path inside the existing model-response validation flow.
- `candidate_index` now aligns to the same candidate preference order used by the heuristic fallback.
- The shared heuristic candidate order now keeps the existing `(score, len(steps))` rule and uses `node_id` only as a final deterministic tie-break for equal-ranked candidates.
- The current reasoner paths now share one private candidate-order helper, so heuristic fallback selection and `candidate_index` payload / validation consume the same ordering source.
- The candidate list sent in the model payload and the candidate list used during validation now share the same ordered candidate set.
- The existing `family` / `node_id` selection path remains in place.
- If the model response is missing or invalid, the current heuristic fallback still remains in place.
- The current slice does not change candidate generation.
- The current slice does not change family scoring.
- The current slice does not change the main `APGPlanner.plan()` flow.
- The current slice does not change lexical retrieval ranking.
- The current slice does not change the single-file JSON persistence behavior.
- `tests/test_apg_engine.py` covers the minimal `candidate_index` improvement, the ordering-alignment refinement, the deterministic tie-break refinement, and the shared-order-helper refinement.
- This should not be read as a full model-assisted planner, a broad planner rewrite, a reasoner overhaul, semantic retrieval, or database/vector-backed memory.

## PatternGraph Console View Status

`PatternGraph` now has a minimal visualization slice, but it is still intentionally narrow:

- The current slice is single-project only.
- It is text-only console output.
- It reuses `state_graph.query_graph(project_id, view="pattern")`.
- The current view only shows `active_family` and the minimum node fields `id`, `family`, and `status`.
- `tests/test_platform_flow.py` covers this minimal text view.
- This should not be read as `RunJournal` visualization, a Web UI, a dashboard, or an interactive graphical interface.

## RunJournal Console View Status

`RunJournal` now also has a minimal visualization slice, but it is still intentionally narrow:

- The current slice is single-project only.
- It is text-only console output.
- It reuses `state_graph.query_graph(project_id, view="events")`.
- The current view only shows a small header plus each event's `type`, `source`, and `run_id`.
- Event order is preserved.
- `tests/test_platform_flow.py` covers this minimal text view.
- This should not be read as a new `PatternGraph` capability, a Web UI, a dashboard, a filtering/search UI, or an interactive graphical interface.
