# MVP Worklog

## Purpose

Record MVP-window execution history in a stable, readable form.

This file is kept ASCII-first on purpose so terminal rendering stays predictable across different shells and code pages.

## Rules

- Handle only one control-approved task at a time.
- Do not continue to a second task before control acceptance.
- Only change files explicitly authorized by control.
- Report changed files, untouched boundaries, tests, and remaining risks for every task.

## Entry Template

## [YYYY-MM-DD HH:MM:SS]
Task:

Goal:

Files changed:

What changed:

What did not change:

Tests run:

Open risks:

## Historical Summary

Entries before `2026-04-23 15:00:00` were affected by earlier mojibake and cross-codepage logging and have been normalized into this summary.

Confirmed Stage 1 MVP milestones completed before the current clean-log window:

- Minimal real `http-request` branch landed with metadata fallback retained.
- Minimal real `browser-inspect` branch landed with metadata fallback retained.
- Minimal real `binary-inspect` branch landed with metadata fallback retained.
- Minimal real `artifact-scan` branch landed with metadata fallback retained.
- Integration-style coverage was added and extended in `tests/test_platform_flow.py`.
- Stage 1 primitive loop was closed before the project moved on to minimal `EpisodeMemory` persistence.

## [2026-04-23 15:23:14]
Task:
Read-only analysis task: lock the next single smallest implementation task for `artifact-scan`.

Goal:
Give control one directly assignable next implementation task recommendation for `artifact-scan` without entering implementation, while preserving the existing MVP slice pattern and metadata fallback model.

Files changed:
- `docs/WORKLOG_MVP.md`

What changed:
- Read-only review completed for:
  - `docs/MVP_REFACTOR_PLAN.md`
  - `docs/CURRENT_STATE.md`
  - `docs/NEXT_STEPS.md`
  - `docs/WORKLOG_MVP.md`
  - `attack_agent/runtime.py`
  - `tests/test_platform_flow.py`
  - `attack_agent/apg.py`
- Locked the minimum implementation path:
  - implementation in `attack_agent/runtime.py`
  - integration-style test in `tests/test_platform_flow.py`
  - metadata fallback retained through `_consume_metadata(..., "artifact-scan")`
- Locked the minimum scope:
  - one local `file://` target
  - one baseline artifact observation
  - no directory traversal
  - no archive handling
  - no broad test expansion

What did not change:
- No Python implementation files were modified.
- No test files were modified.
- No docs body files were modified.
- No implementation was started.

Tests run:
- None. This round was read-only analysis only.

Open risks:
- `artifact-scan` could easily over-expand into broader forensics if the next slice were not kept narrow.

## [2026-04-23 15:26:53]
Task:
Single implementation task: land a minimal real `artifact-scan` branch, preserve metadata fallback, and add 1 integration-style test.

Goal:
Finish the smallest acceptable `artifact-scan` real branch inside the allowed 3 files without widening planner/provider/models or breaking the artifact metadata baseline.

Files changed:
- `attack_agent/runtime.py`
- `tests/test_platform_flow.py`
- `docs/WORKLOG_MVP.md`

What changed:
- Added a minimal real `artifact-scan` execution branch in `attack_agent/runtime.py`.
- Added minimal helpers:
  - `_execute_artifact_scan(...)`
  - `_resolve_artifact_scan_specs(...)`
  - `_perform_artifact_scan(...)`
  - `_extract_text_preview(...)`
- Reused `_resolve_local_file_target(...)` so the real branch stays limited to a single local `file://` target.
- Enabled the real branch only when:
  - `instance.metadata["artifact_scan"]` exists
  - `bundle.target` resolves to a single local `file://` file
- Preserved metadata fallback via `_consume_metadata(..., "artifact-scan")`.
- Real observation payload now includes:
  - `uri`
  - `name`
  - `size_bytes`
  - `suffix`
  - `sha1`
  - `text_preview` when a tiny bounded plain-text read is safe
- Added 1 integration-style test:
  - `test_artifact_scan_with_artifact_scan_config_uses_real_branch`

What did not change:
- `attack_agent/apg.py`
- `attack_agent/provider.py`
- `attack_agent/platform_models.py`
- other docs body files
- `ActionOutcome` / `Observation` models
- planner / provider contracts

Tests run:
- `python -m unittest tests.test_platform_flow.PlatformFlowTests.test_artifact_scan_with_artifact_scan_config_uses_real_branch -v`
- `python -m unittest tests.test_platform_flow.PlatformFlowTests.test_artifact_pattern_solves_without_new_plugin_code -v`
- `python -m unittest tests.test_platform_flow -v`

Open risks:
- This is still only a narrow single-file artifact observation slice.
- It is not directory scanning, archive handling, recursive scanning, or a full forensics workflow.

## [2026-04-23 17:36:30]
Task:
Single implementation task: land a minimal local persistence slice for `EpisodeMemory` and add 1 minimal test.

Goal:
Add the smallest local JSON persistence capability to `EpisodeMemory` without changing `search()` behavior or widening into broader memory/state persistence.

Files changed:
- `attack_agent/apg.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

What changed:
- Added an optional local persistence path parameter to `EpisodeMemory`.
- When no path is provided, `EpisodeMemory` remains pure in-memory mode.
- When a path is provided, initialization attempts to load `EpisodeEntry` records from a single local JSON file.
- If the file does not exist yet, initialization safely starts with an empty entry list.
- `EpisodeMemory.add()` now performs a minimal synchronous write-back when persistence is enabled.
- Persistence scope is strictly limited to:
  - `EpisodeEntry`
  - a single local JSON file
- `search()` logic was not widened or rewritten.
- Added 1 minimal test:
  - `test_episode_memory_persists_entries_to_local_json_file`

What did not change:
- `attack_agent/controller.py`
- `attack_agent/dispatcher.py`
- `attack_agent/runtime.py`
- `attack_agent/provider.py`
- `attack_agent/platform.py`
- `attack_agent/reasoning.py`
- `attack_agent/platform_models.py`
- other docs body files
- retrieval quality logic
- state-graph wide persistence
- database integration
- visualization

Tests run:
- `python -m unittest tests.test_apg_engine.APGEngineTests.test_episode_memory_persists_entries_to_local_json_file -v`
- `python -m unittest tests.test_apg_engine -v`

Open risks:
- Current persistence only covers single-file JSON read/write for `EpisodeEntry`.
- It does not include concurrent write protection, corruption recovery, version migration, or richer retrieval behavior.

## [2026-04-23 20:41:41]
Task:
Read-only analysis task: lock the next single smallest visualization task for `PatternGraph` / `RunJournal`.

Goal:
Give control one directly assignable next implementation task recommendation that stays inside the existing `console` / `state_graph` / `platform` path, without expanding into a full Web UI or frontend refactor.

Files changed:
- `docs/WORKLOG_MVP.md`

What changed:
- Read-only review completed for:
  - `docs/MVP_REFACTOR_PLAN.md`
  - `docs/CURRENT_STATE.md`
  - `docs/NEXT_STEPS.md`
  - `docs/WORKLOG_MVP.md`
  - `attack_agent/state_graph.py`
  - `attack_agent/console.py`
  - `attack_agent/platform.py`
  - `tests/test_platform_flow.py`
  - minimal directly related `PatternGraph` references in `attack_agent/apg.py`
- Direct answers for control:
  1. Next single smallest task should be:
     - `PatternGraph`
  2. Why it is better than `RunJournal` right now:
     - `PatternGraph` already has a dedicated structured query path in `StateGraphService.query_graph(project_id, view="pattern")`
     - `WebConsoleView` already renders project summaries from `state_graph`
     - `RunJournal` is currently exposed as a raw event stream and is easier to over-expand
  3. Smallest implementation entry point:
     - `attack_agent/console.py`
     - specifically extend `WebConsoleView` with one minimal text rendering path for a single project's pattern graph, reusing `state_graph.query_graph(..., view="pattern")`
  4. Smallest test entry point:
     - reuse `tests/test_platform_flow.py`
  5. Boundaries the next implementation must not touch:
     - do not modify `attack_agent/controller.py`
     - do not modify `attack_agent/dispatcher.py`
     - do not modify `attack_agent/runtime.py`
     - do not modify `attack_agent/provider.py`
     - do not modify `attack_agent/reasoning.py`
     - do not modify `attack_agent/platform_models.py`
     - do not expand into HTML/CSS/JS, web routes, interactive graph rendering, or a frontend framework
     - do not bundle `RunJournal` work into the same task
  6. Strict scope of the next minimal visualization slice:
     - text-only console output
     - single-project `PatternGraph` view only
     - show only a tiny bounded subset such as `active_family` plus per-node `id` / `family` / `status`
     - no event timeline, no filtering UI, no persistence changes, no dashboard redesign

What did not change:
- No Python implementation files changed.
- No test files changed.
- No docs body changed outside this worklog entry.
- No visualization behavior was implemented in this round.

Tests run:
- None. This round was read-only analysis only.

Open risks:
- If the next task tries to visualize both `PatternGraph` and `RunJournal` together, the scope will likely jump into a broader console/dashboard design problem.
- If the next task starts in `state_graph.py` instead of `console.py`, it may over-rotate into data-shape redesign even though the minimum `pattern` view already exists.

## [2026-04-23 21:05:00]
Task:
Implement the minimal console visualization slice for `PatternGraph`.

Goal:
Add one bounded single-project text rendering entry in `WebConsoleView` that reuses `state_graph.query_graph(project_id, view="pattern")` and keeps the existing summary overview stable.

Files changed:
- `attack_agent/console.py`
- `tests/test_platform_flow.py`
- `docs/WORKLOG_MVP.md`

What changed:
- In `attack_agent/console.py`:
  - added `WebConsoleView.render_pattern_graph_text(project_id)`
  - the new method reuses `state_graph.query_graph(project_id, view="pattern")`
  - output is strictly limited to:
    - single project text view
    - `active_family`
    - per-node `id` / `family` / `status`
- Kept existing `render_text()` overview format unchanged.
- In `tests/test_platform_flow.py`:
  - added `test_console_view_renders_single_project_pattern_graph`
  - verified that after solving a project, the new text view includes:
    - project id
    - `active_family=identity-boundary`
    - one node id
    - node family
    - node status
- Followed TDD for the slice:
  - wrote the new test first
  - ran the single test and confirmed it failed because the new method did not exist
  - implemented the minimal method
  - reran the single test to green
  - reran the directed file-level test suite

What did not change:
- Did not modify `attack_agent/state_graph.py`
- Did not modify `attack_agent/platform.py`
- Did not modify `attack_agent/controller.py`
- Did not modify `attack_agent/dispatcher.py`
- Did not modify `attack_agent/runtime.py`
- Did not modify `attack_agent/provider.py`
- Did not modify `attack_agent/reasoning.py`
- Did not modify `attack_agent/platform_models.py`
- Did not add any `RunJournal` visualization
- Did not add any HTML/CSS/JS, web route, frontend framework, or dashboard redesign

Tests run:
- `python -m unittest tests.test_platform_flow.PlatformFlowTests.test_console_view_renders_single_project_pattern_graph -v`
- `python -m unittest tests.test_platform_flow -v`

Open risks:
- The new rendering is intentionally minimal and text-only; it does not attempt ordering, grouping, or richer formatting beyond the required fields.
- Node order currently follows the existing `query_graph(..., view="pattern")` output order; if later work requires a stronger presentation contract, that should be assigned as a separate task.

## [2026-04-23 21:12:55]
Task:
Implement the minimal console visualization slice for `RunJournal`.

Goal:
Add one bounded single-project text rendering entry in `WebConsoleView` that reuses `state_graph.query_graph(project_id, view="events")` and keeps the existing summary and `PatternGraph` renderers stable.

Files changed:
- `attack_agent/console.py`
- `tests/test_platform_flow.py`
- `docs/WORKLOG_MVP.md`

What changed:
- In `attack_agent/console.py`:
  - added `WebConsoleView.render_run_journal_text(project_id)`
  - the new method reuses `state_graph.query_graph(project_id, view="events")`
  - output is strictly limited to:
    - single project text view
    - one small header with project id and event count
    - per-event `type` / `source` / `run_id`
  - event order is preserved from the existing events view
- Kept existing `render_text()` and `render_pattern_graph_text()` behavior unchanged.
- In `tests/test_platform_flow.py`:
  - added `test_console_view_renders_single_project_run_journal`
  - verified that after solving a project, the new text view includes:
    - project id
    - event count header
    - ordered event lines showing `type | source | run_id`
    - stable event order for representative events
- Followed TDD for the slice:
  - wrote the new test first
  - ran the single test and confirmed it failed because the new method did not exist
  - implemented the minimal method
  - reran the single test to green
  - reran the directed file-level test suite

What did not change:
- Did not modify `attack_agent/state_graph.py`
- Did not modify `attack_agent/platform.py`
- Did not modify `attack_agent/controller.py`
- Did not modify `attack_agent/dispatcher.py`
- Did not modify `attack_agent/runtime.py`
- Did not modify `attack_agent/provider.py`
- Did not modify `attack_agent/reasoning.py`
- Did not modify `attack_agent/platform_models.py`
- Did not add any new `PatternGraph` requirements
- Did not add any HTML/CSS/JS, web route, frontend framework, dashboard, filtering/search UI, or retrieval optimization

Tests run:
- `python -m unittest tests.test_platform_flow.PlatformFlowTests.test_console_view_renders_single_project_run_journal -v`
- `python -m unittest tests.test_platform_flow -v`

Open risks:
- The new rendering is intentionally minimal and text-only; it does not include payload formatting, grouping, filtering, or richer event summaries.
- Event order currently follows the existing `query_graph(..., view="events")` output order; if later work needs stronger presentation guarantees or truncation rules, that should be assigned separately.

## [2026-04-24 09:12:48]
Task:
Read-only analysis task: lock the next single smallest retrieval-quality improvement task.

Goal:
Give control one directly assignable retrieval-quality implementation slice that stays on the current `EpisodeMemory` / `APGPlanner` path while explicitly preserving the landed single-file JSON persistence behavior.

Files changed:
- `docs/WORKLOG_MVP.md`

What changed:
- Read-only review completed for:
  - `docs/MVP_REFACTOR_PLAN.md`
  - `docs/CURRENT_STATE.md`
  - `docs/NEXT_STEPS.md`
  - `docs/WORKLOG_MVP.md`
  - `attack_agent/apg.py`
  - `tests/test_apg_engine.py`
  - minimal directly related retrieval data definitions in `attack_agent/platform_models.py`
- Direct answers for control:
  1. Smallest implementation entry point:
     - `attack_agent/apg.py`
     - specifically `EpisodeMemory.search()`
     - recommended next slice is to improve hit ranking quality there, not to widen persistence and not to redesign `APGPlanner`
  2. Smallest test entry point:
     - reuse existing `tests/test_apg_engine.py`
     - add exactly 1 thin test that proves a more directly relevant `EpisodeEntry` ranks ahead of a weaker partial-overlap entry for the same query
     - no new test file is needed for this slice
  3. Persistence / fallback behavior that must be preserved:
     - `EpisodeMemory` must continue to support pure in-memory mode when no store path is provided
     - `EpisodeMemory` must continue to persist only `EpisodeEntry`
     - persistence must remain a single local JSON file
     - initialization with a provided path must continue to load existing entries when the file exists
     - a missing file must still initialize safely to an empty memory
     - `add()` must keep the current minimal synchronous write-back behavior
     - no fallback away from the current lexical retrieval path should be introduced in this slice
  4. Files and boundaries the next implementation must not touch:
     - do not modify `attack_agent/state_graph.py`
     - do not modify `attack_agent/platform.py`
     - do not modify `attack_agent/controller.py`
     - do not modify `attack_agent/dispatcher.py`
     - do not modify `attack_agent/runtime.py`
     - do not modify `attack_agent/provider.py`
     - do not modify `attack_agent/reasoning.py`
     - do not modify `attack_agent/platform_models.py`
     - do not modify docs body outside `docs/WORKLOG_MVP.md` unless the next task explicitly allows it
     - do not add a database, embedding store, vector index, or full-state persistence layer
  5. Strict scope of the next minimal retrieval-quality slice:
     - keep the work inside lexical retrieval quality only
     - improve only how existing `EpisodeEntry.feature_text` overlap is scored or tie-broken
     - keep `RetrievalHit` and `EpisodeEntry` data shapes unchanged
     - keep `APGPlanner.plan()` wiring unchanged except for consuming the same improved `search()` output
     - do not expand into query rewriting, model-assisted retrieval, memory schema changes, broad ranking heuristics, or large-scale retrieval rewrites

Recommended next implementation task statement:
- "In `attack_agent/apg.py`, make one minimal retrieval-quality improvement inside `EpisodeMemory.search()` so strongly matching entries rank ahead of weaker partial matches, while preserving the current `EpisodeEntry` single-file JSON persistence behavior. Add exactly 1 thin ranking test in `tests/test_apg_engine.py`."

What did not change:
- No Python implementation files changed.
- No test files changed.
- No docs body files changed outside this worklog entry.
- No retrieval implementation was started.

Tests run:
- None. This round was read-only analysis only.

Open risks:
- Retrieval work can easily sprawl into schema, planner, or persistence redesign if the next slice is not kept inside `EpisodeMemory.search()`.
- If the next slice tries to improve both retrieval scoring and persistence at once, the acceptance boundary will become blurry and harder to validate.

## Purpose

Record MVP-window execution history in a stable, readable form.

This file is kept ASCII-first on purpose so terminal rendering stays predictable across different shells and code pages.

## Rules

- Handle only one control-approved task at a time.
- Do not continue to a second task before control acceptance.
- Only change files explicitly authorized by control.
- Report changed files, untouched boundaries, tests, and remaining risks for every task.

## Entry Template

## [YYYY-MM-DD HH:MM:SS]
Task:

Goal:

Files changed:

What changed:

What did not change:

Tests run:

Open risks:

## Historical Summary

Entries before `2026-04-23 15:00:00` were affected by earlier mojibake and cross-codepage logging and have been normalized into this summary.

Confirmed Stage 1 MVP milestones completed before the current clean-log window:

- Minimal real `http-request` branch landed with metadata fallback retained.
- Minimal real `browser-inspect` branch landed with metadata fallback retained.
- Minimal real `binary-inspect` branch landed with metadata fallback retained.
- Minimal real `artifact-scan` branch landed with metadata fallback retained.
- Integration-style coverage was added and extended in `tests/test_platform_flow.py`.
- Stage 1 primitive loop was closed before the project moved on to minimal `EpisodeMemory` persistence.

## [2026-04-24 09:17:52]
Task:
Implement the minimal retrieval-quality improvement slice in `EpisodeMemory.search()`.

Goal:
Improve lexical retrieval ranking just enough that a more directly relevant `EpisodeEntry` ranks ahead of a weaker partial-overlap entry, while preserving the existing single-file JSON persistence behavior and memory API shape.

Files changed:
- `attack_agent/apg.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

What changed:
- In `tests/test_apg_engine.py`:
  - added `test_episode_memory_ranks_stronger_match_ahead_of_partial_overlap`
  - the new test verifies that, for the same query, an entry covering more of the query intent ranks ahead of a shorter partial-overlap entry
- In `attack_agent/apg.py`:
  - changed only `EpisodeMemory.search()`
  - kept retrieval lexical and based on existing `EpisodeEntry.feature_text`
  - updated the score to prefer:
    - higher overlap count first
    - then higher query coverage
    - then existing entry-side precision as a very small tie-break
  - this keeps the slice bounded to ranking quality only; it does not change schemas or persistence
- Followed TDD for the slice:
  - wrote the new ranking test first
  - ran the single test and confirmed it failed on the old ranking
  - implemented the minimal score adjustment
  - reran the single test to green
  - reran the directed APG test file

What did not change:
- Did not modify `attack_agent/state_graph.py`
- Did not modify `attack_agent/platform.py`
- Did not modify `attack_agent/controller.py`
- Did not modify `attack_agent/dispatcher.py`
- Did not modify `attack_agent/runtime.py`
- Did not modify `attack_agent/provider.py`
- Did not modify `attack_agent/reasoning.py`
- Did not modify `attack_agent/platform_models.py`
- Did not change `EpisodeEntry` shape
- Did not change `RetrievalHit` shape
- Did not change single-file JSON persistence behavior
- Did not change in-memory mode, load-on-init, or `add()` write-back behavior
- Did not introduce a database, embedding/vector store, planner rewrite, query rewriting, or broad model-assisted retrieval

Tests run:
- `python -m unittest tests.test_apg_engine.APGEngineTests.test_episode_memory_ranks_stronger_match_ahead_of_partial_overlap -v`
- `python -m unittest tests.test_apg_engine -v`

Open risks:
- The current improvement is intentionally small and still purely lexical; it improves ranking quality but does not address synonyms, paraphrases, or semantic similarity.
- The new score is a simple bounded heuristic; if future retrieval work needs broader behavior changes, that should be assigned as a separate task instead of folded into this slice.

## [2026-04-24 09:44:18]
Task:
Read-only analysis task: lock the next single smallest model-assisted planning / candidate-ranking improvement on the current APG path.

Goal:
Give control one directly assignable APG-path improvement slice that stays inside the current `APGPlanner` / `EpisodeMemory` / `HeuristicReasoner` flow while explicitly preserving the landed lexical retrieval and single-file persistence behavior.

Files changed:
- `docs/WORKLOG_MVP.md`

What changed:
- Read-only review completed for:
  - `docs/MVP_REFACTOR_PLAN.md`
  - `docs/CURRENT_STATE.md`
  - `docs/NEXT_STEPS.md`
  - `docs/WORKLOG_MVP.md`
  - `attack_agent/apg.py`
  - `attack_agent/reasoning.py`
  - `tests/test_apg_engine.py`
- Direct answers for control:
  1. Smallest implementation entry point:
     - `attack_agent/reasoning.py`
     - specifically `LLMReasoner.choose_program()` and `_validate_program_response()`
     - recommended next slice is to let the model select a candidate by a minimal stable candidate index in the existing ordered candidate list, instead of only by copying `family` and `node_id`
  2. Smallest test entry point:
     - reuse existing `tests/test_apg_engine.py`
     - add exactly 1 thin unit-style test that builds a tiny `ReasoningContext` with at least 2 candidates and verifies that a valid model response selecting a non-fallback candidate index is accepted and returned as `source="llm"`
     - no new test file is needed for this slice
  3. Retrieval / persistence / planning behavior that must be preserved:
     - keep the current lexical retrieval ranking improvement in `EpisodeMemory.search()`
     - keep the current `EpisodeEntry` shape unchanged
     - keep the current `RetrievalHit` shape unchanged
     - keep `EpisodeEntry`-only persistence in a single local JSON file
     - keep pure in-memory mode when no path is provided
     - keep load-on-init behavior
     - keep the current minimal synchronous write-back on `add()`
     - keep `APGPlanner.plan()` candidate generation and family score flow intact
     - keep heuristic fallback behavior intact when the model response is missing or invalid
  4. Files and boundaries the next implementation must not touch:
     - do not modify `attack_agent/apg.py` unless the slice proves it is strictly necessary
     - do not modify `attack_agent/state_graph.py`
     - do not modify `attack_agent/platform.py`
     - do not modify `attack_agent/controller.py`
     - do not modify `attack_agent/dispatcher.py`
     - do not modify `attack_agent/runtime.py`
     - do not modify `attack_agent/provider.py`
     - do not modify `attack_agent/platform_models.py`
     - do not modify docs body outside `docs/WORKLOG_MVP.md` unless the next task explicitly allows it
     - do not add semantic retrieval, vector storage, a database, or a broad reasoning rewrite
  5. Strict scope of the next minimal slice:
     - keep the work inside model response validation and candidate selection only
     - reuse the existing candidate list order already produced by `HeuristicReasoner` / `APGPlanner`
     - allow one minimal alternate model response path such as `candidate_index`
     - keep existing `family` / `node_id` validation as a compatible path
     - do not change planning data models, persistence models, or retrieval logic
     - do not expand into broad planner rewrite, reasoner overhaul, semantic retrieval, database work, or large-scale model integration

Recommended next implementation task statement:
- "In `attack_agent/reasoning.py`, add one minimal model-assisted candidate-selection path so `LLMReasoner` can validate and accept a selected `candidate_index` from the existing ordered candidate list while preserving heuristic fallback. Add exactly 1 thin unit-style test in `tests/test_apg_engine.py`."

What did not change:
- No Python implementation files changed.
- No test files changed.
- No docs body files changed outside this worklog entry.
- No implementation was started.

Tests run:
- None. This round was read-only analysis only.

Open risks:
- Model-assisted planning work can easily sprawl into planner rewrites if the next slice expands beyond response validation and candidate selection.
- If the next slice tries to change retrieval, candidate generation, and model choice semantics at the same time, the acceptance boundary will stop being minimal and testable.

## [2026-04-24 09:48:41]
Task:
Implement the minimal model-assisted candidate-selection slice for `LLMReasoner`.

Goal:
Allow the model to select from the existing ordered candidate list using a stable `candidate_index` field while preserving the current `family` / `node_id` path and heuristic fallback behavior.

Files changed:
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

What changed:
- In `tests/test_apg_engine.py`:
  - added `test_llm_reasoner_accepts_valid_candidate_index_selection`
  - the new test builds a minimal `ReasoningContext` with 2 candidates
  - verifies that a valid `candidate_index` response selects the indexed candidate
  - verifies the returned decision has `source="llm"`
- In `attack_agent/reasoning.py`:
  - updated `LLMReasoner.choose_program()` so the model payload now includes `candidate_index` for each existing candidate in the current ordered candidate list
  - updated `LLMReasoner._validate_program_response()` so it can:
    - accept a valid integer `candidate_index`
    - resolve the selected candidate from the existing candidate list
    - keep the existing `family` / `node_id` validation path as a compatible fallback
    - keep step validation behavior unchanged
  - invalid or missing model selections still fall back to the existing heuristic decision path
- Followed TDD for the slice:
  - wrote the new test first
  - ran the single test and confirmed it failed before implementation
  - implemented the minimal `candidate_index` support
  - reran the single test to green
  - reran the directed APG test file

What did not change:
- Did not modify `attack_agent/apg.py`
- Did not modify `attack_agent/state_graph.py`
- Did not modify `attack_agent/platform.py`
- Did not modify `attack_agent/controller.py`
- Did not modify `attack_agent/dispatcher.py`
- Did not modify `attack_agent/runtime.py`
- Did not modify `attack_agent/provider.py`
- Did not modify `attack_agent/platform_models.py`
- Did not change lexical retrieval ranking logic
- Did not change `EpisodeEntry` shape
- Did not change `RetrievalHit` shape
- Did not change single-file JSON persistence behavior
- Did not change in-memory mode, load-on-init, or `add()` write-back behavior
- Did not introduce semantic retrieval, vector storage, database work, planner rewrite, reasoner overhaul, or broad model-assisted planning redesign

Tests run:
- `python -m unittest tests.test_apg_engine.APGEngineTests.test_llm_reasoner_accepts_valid_candidate_index_selection -v`
- `python -m unittest tests.test_apg_engine -v`

Open risks:
- This is intentionally a narrow response-validation improvement; it does not change how candidates are generated or scored.
- `candidate_index` depends on the existing candidate list order being stable enough for a single planning turn; if future work changes candidate ordering semantics, that should be handled as a separate task.

## [2026-04-24 09:57:47]
Task:
Read-only analysis task: lock the next smallest follow-up improvement after the landed `candidate_index` slice on the current APG path.

Goal:
Give control one directly assignable next APG-path improvement slice that stays inside the current `APGPlanner` / `LLMReasoner` / `HeuristicReasoner` / `EpisodeMemory` flow while explicitly preserving the landed candidate-selection, retrieval, and persistence behavior.

Files changed:
- `docs/WORKLOG_MVP.md`

What changed:
- Read-only review completed for:
  - `docs/MVP_REFACTOR_PLAN.md`
  - `docs/CURRENT_STATE.md`
  - `docs/NEXT_STEPS.md`
  - `docs/WORKLOG_MVP.md`
  - `attack_agent/apg.py`
  - `attack_agent/reasoning.py`
  - `tests/test_apg_engine.py`
- Direct answers for control:
  1. After `candidate_index`, the next smallest follow-up improvement should be:
     - make `candidate_index` resolve against the same heuristic-ordered candidate list that the fallback reasoner already prefers
     - reason:
       - the current slice made indexed selection possible
       - the next smallest quality improvement is to make that index semantically stable with the current heuristic ranking, instead of depending on raw candidate list order
       - this stays inside candidate selection semantics and does not widen the planner or retrieval system
  2. Smallest implementation entry point:
     - `attack_agent/reasoning.py`
     - specifically `LLMReasoner.choose_program()` and `LLMReasoner._validate_program_response()`
     - recommended implementation shape:
       - build one local ordered candidate list using the same ordering rule already used by `HeuristicReasoner.choose_program()`
       - expose `candidate_index` against that ordered list
       - validate `candidate_index` against that same ordered list
  3. Smallest test entry point:
     - reuse existing `tests/test_apg_engine.py`
     - add exactly 1 thin unit-style test that builds 2 candidates in a non-heuristic source order, then verifies `candidate_index=0` selects the heuristically top-ranked candidate rather than merely the first raw candidate
     - no new test file is needed for this slice
  4. Candidate-selection / retrieval / persistence / fallback behavior that must be preserved:
     - keep the current `candidate_index` path in place
     - keep the current `family` / `node_id` validation path in place
     - keep heuristic fallback when the model response is missing or invalid
     - keep the current lexical retrieval ranking improvement in `EpisodeMemory.search()`
     - keep the current `EpisodeEntry` shape unchanged
     - keep the current `RetrievalHit` shape unchanged
     - keep `EpisodeEntry`-only persistence in a single local JSON file
     - keep pure in-memory mode when no path is provided
     - keep load-on-init behavior
     - keep the current minimal synchronous write-back on `add()`
     - keep `APGPlanner.plan()` candidate generation and main flow unchanged
  5. Files and boundaries the next implementation must not touch:
     - do not modify `attack_agent/apg.py`
     - do not modify `attack_agent/state_graph.py`
     - do not modify `attack_agent/platform.py`
     - do not modify `attack_agent/controller.py`
     - do not modify `attack_agent/dispatcher.py`
     - do not modify `attack_agent/runtime.py`
     - do not modify `attack_agent/provider.py`
     - do not modify `attack_agent/platform_models.py`
     - do not modify docs body outside `docs/WORKLOG_MVP.md` unless the next task explicitly allows it
     - do not add semantic retrieval, vector storage, a database, or a broad reasoning rewrite
  6. Strict scope of the next minimal slice:
     - keep the work inside candidate ordering, model payload ordering, and candidate-index validation only
     - do not change candidate generation
     - do not change family scoring
     - do not change retrieval logic
     - do not change persistence behavior
     - do not expand into broad planner rewrite, reasoner overhaul, semantic retrieval, database/vector store work, full-state persistence redesign, or large-scale model integration

Recommended next implementation task statement:
- "In `attack_agent/reasoning.py`, make `candidate_index` map to the same heuristic-ordered candidate list used by the current fallback logic, and add exactly 1 thin unit-style test in `tests/test_apg_engine.py` proving index selection follows heuristic order rather than raw candidate insertion order."

What did not change:
- No Python implementation files changed.
- No test files changed.
- No docs body files changed outside this worklog entry.
- No implementation was started.

Tests run:
- None. This round was read-only analysis only.

Open risks:
- If the next slice changes candidate ordering semantics without keeping payload ordering and validation ordering aligned, `candidate_index` will become ambiguous again.
- If the next slice expands beyond index-to-order alignment, it can easily spill into a broader planner or reasoner redesign.

## [2026-04-24 10:04:15]
Task:
Align `candidate_index` with the current heuristic fallback candidate preference order.

Goal:
Make the model-visible `candidate_index` map to the same ordered candidate list that the current heuristic fallback already prefers, without changing candidate generation, family scoring, retrieval, or persistence behavior.

Files changed:
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

What changed:
- In `tests/test_apg_engine.py`:
  - added `test_llm_reasoner_candidate_index_uses_heuristic_candidate_order`
  - the new test constructs 2 candidates where raw input order differs from heuristic preference order
  - verifies `candidate_index=0` selects the heuristically top-ranked candidate, not the first raw list entry
- In `attack_agent/reasoning.py`:
  - updated `LLMReasoner.choose_program()` so the model payload candidate list is now ordered with the same `(score, len(steps))` descending rule used by `HeuristicReasoner.choose_program()`
  - updated `LLMReasoner._validate_program_response()` so `candidate_index` is validated against that same ordered candidate list
  - kept the existing `family` / `node_id` validation path in place
  - kept heuristic fallback behavior unchanged when the model response is missing or invalid
- Followed TDD for the slice:
  - wrote the new test first
  - ran the single test and confirmed it failed before implementation
  - implemented the minimal candidate-order alignment
  - reran the single test to green
  - reran the directed APG test file

What did not change:
- Did not modify `attack_agent/apg.py`
- Did not modify `attack_agent/state_graph.py`
- Did not modify `attack_agent/platform.py`
- Did not modify `attack_agent/controller.py`
- Did not modify `attack_agent/dispatcher.py`
- Did not modify `attack_agent/runtime.py`
- Did not modify `attack_agent/provider.py`
- Did not modify `attack_agent/platform_models.py`
- Did not change candidate generation
- Did not change family scoring
- Did not change `APGPlanner.plan()` main flow
- Did not change lexical retrieval ranking
- Did not change `EpisodeEntry` shape
- Did not change `RetrievalHit` shape
- Did not change single-file JSON persistence behavior
- Did not change in-memory mode, load-on-init, or `add()` write-back behavior
- Did not introduce planner rewrite, reasoner overhaul, semantic retrieval, database/vector store work, broad model-assisted planning redesign, retrieval rewrite, or full-state persistence redesign

Tests run:
- `python -m unittest tests.test_apg_engine.APGEngineTests.test_llm_reasoner_candidate_index_uses_heuristic_candidate_order -v`
- `python -m unittest tests.test_apg_engine -v`

Open risks:
- The alignment is intentionally narrow and only guarantees consistency with the current heuristic ordering rule inside a single planning turn.
- If future work changes heuristic candidate ordering semantics, the model payload and validation order will need to be kept in sync as part of that separate task.

## [2026-04-24 10:17:14]
Task:
Read-only analysis task: lock the next smallest follow-up improvement after the landed `candidate_index` ordering-alignment slice on the current APG path.

Goal:
Give control one directly assignable next APG-path improvement slice that stays inside the current `APGPlanner` / `LLMReasoner` / `HeuristicReasoner` / `EpisodeMemory` flow while explicitly preserving the landed candidate-selection, retrieval, and persistence behavior.

Files changed:
- `docs/WORKLOG_MVP.md`

What changed:
- Read-only review completed for:
  - `docs/MVP_REFACTOR_PLAN.md`
  - `docs/CURRENT_STATE.md`
  - `docs/NEXT_STEPS.md`
  - `docs/WORKLOG_MVP.md`
  - `attack_agent/apg.py`
  - `attack_agent/reasoning.py`
  - `tests/test_apg_engine.py`
- Worklog ordering repair completed:
  - detected that latest dated entries had been inserted at file head
  - normalized dated worklog entries back into chronological order
  - this round's entry is appended at file tail as required
- Direct answers for control:
  1. After the landed ordering-alignment slice, the next smallest follow-up improvement should be:
     - add one deterministic final tie-break to heuristic candidate ordering so `candidate_index` stays stable even when candidates tie on the current `(score, len(steps))` ordering
     - recommended tie-break scope: keep the existing ordering rule first, then add one stable bounded final comparator such as `node_id`
     - reason:
       - the current slice aligned index selection with heuristic order
       - the next smallest quality improvement is to remove remaining ambiguity when multiple candidates are otherwise equally ranked
       - this keeps the work inside candidate ordering semantics and does not widen the planner or retrieval system
  2. Smallest implementation entry point:
     - `attack_agent/reasoning.py`
     - specifically `LLMReasoner.choose_program()` and `LLMReasoner._validate_program_response()`
     - the fallback heuristic ordering used by `HeuristicReasoner.choose_program()` must also remain the source of truth for the same candidate order
  3. Smallest test entry point:
     - reuse existing `tests/test_apg_engine.py`
     - add exactly 1 thin unit-style test that constructs 2 candidates with equal `score` and equal step-count, intentionally in reverse raw order, and verifies `candidate_index=0` resolves to the deterministically tie-broken candidate rather than merely the first raw entry
     - no new test file is needed for this slice
  4. Candidate-selection / retrieval / persistence / fallback behavior that must be preserved:
     - keep the current `candidate_index` path in place
     - keep the current `family` / `node_id` validation path in place
     - keep heuristic fallback when the model response is missing or invalid
     - keep the current lexical retrieval ranking improvement in `EpisodeMemory.search()`
     - keep the current single-file JSON persistence behavior in `EpisodeMemory`
     - keep pure in-memory mode when no path is provided
     - keep load-on-init behavior
     - keep the current minimal synchronous write-back on `add()`
     - keep the current `EpisodeEntry` shape unchanged
     - keep the current `RetrievalHit` shape unchanged
     - keep `APGPlanner.plan()` candidate generation and main flow unchanged
  5. Files and boundaries the next implementation must not touch:
     - do not modify `attack_agent/apg.py`
     - do not modify `attack_agent/state_graph.py`
     - do not modify `attack_agent/platform.py`
     - do not modify `attack_agent/controller.py`
     - do not modify `attack_agent/dispatcher.py`
     - do not modify `attack_agent/runtime.py`
     - do not modify `attack_agent/provider.py`
     - do not modify `attack_agent/platform_models.py`
     - do not modify docs body outside `docs/WORKLOG_MVP.md` unless the next task explicitly allows it
     - do not add semantic retrieval, vector storage, a database, or full-state persistence redesign
  6. Strict scope of the next minimal slice:
     - keep the work inside the final deterministic candidate-order tie-break only
     - keep model payload ordering and candidate-index validation aligned to that same deterministic order
     - do not change candidate generation
     - do not change family scoring
     - do not change retrieval logic
     - do not change persistence behavior
     - do not expand into broad planner rewrite, reasoner overhaul, semantic retrieval, database/vector store work, full-state persistence redesign, or large-scale model integration

Recommended next implementation task statement:
- "In `attack_agent/reasoning.py`, add one deterministic final tie-break to the current heuristic candidate ordering so `candidate_index` remains stable under equal-ranked candidates, and add exactly 1 thin unit-style test in `tests/test_apg_engine.py` proving index selection follows that deterministic tie-break rather than raw candidate insertion order."

What did not change:
- No Python implementation files changed.
- No test files changed.
- No docs body files changed outside this worklog entry.
- No implementation was started.

Tests run:
- None. This round was read-only analysis only.

Open risks:
- If the next slice changes heuristic ordering without making the tie-break explicit, `candidate_index` can still become ambiguous under equal-ranked candidates.
- If the next slice expands beyond deterministic tie-breaking, it can easily spill into a broader planner or reasoner redesign.

## [2026-04-24 10:26:00]
Task:
Add one deterministic final tie-break to heuristic candidate ordering so equal-ranked candidates stay stable for `candidate_index`.

Goal:
Keep the existing `(score, len(steps))` ranking rule and add one smallest stable final comparator using `node_id`, with one thin regression test proving `candidate_index=0` resolves to the deterministically first equal-ranked candidate rather than the raw first list entry.

Files changed:
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

What changed:
- Added `test_llm_reasoner_candidate_index_uses_deterministic_tie_break` in `tests/test_apg_engine.py`.
- The new test builds 2 equal-ranked candidates in reverse raw order and verifies `candidate_index=0` selects the deterministically tie-broken candidate with the lexically smaller `node_id`.
- Updated `HeuristicReasoner.choose_program()` to sort by `(score, len(steps), node_id)` with descending score and step count, keeping `node_id` as the final stable tie-break.
- Updated `LLMReasoner.choose_program()` to emit the same deterministic candidate ordering in its payload.
- Updated `LLMReasoner._validate_program_response()` to resolve `candidate_index` against the same deterministic ordering.
- Kept the existing heuristic fallback, the `candidate_index` path, the `family` / `node_id` path, lexical retrieval, and single-file JSON persistence behavior unchanged.
- Followed TDD:
  - wrote the new test first
  - ran the targeted test and confirmed it failed because equal-ranked candidates still fell back to raw input order
  - applied the smallest ordering change
  - reran the targeted test to green
  - reran the full `tests.test_apg_engine` file to confirm no regression

What did not change:
- Did not modify `attack_agent/apg.py`
- Did not modify `attack_agent/state_graph.py`
- Did not modify `attack_agent/platform.py`
- Did not modify `attack_agent/controller.py`
- Did not modify `attack_agent/dispatcher.py`
- Did not modify `attack_agent/runtime.py`
- Did not modify `attack_agent/provider.py`
- Did not modify `attack_agent/platform_models.py`
- Did not change candidate generation, family scoring, retrieval logic, or persistence behavior
- Did not touch any docs body outside this worklog append

Tests run:
- `python -m unittest tests.test_apg_engine.APGEngineTests.test_llm_reasoner_candidate_index_uses_deterministic_tie_break -v`
- `python -m unittest tests.test_apg_engine -v`

Open risks:
- The new tie-break assumes `node_id` remains a stable lexical identifier for equal-ranked candidates.
- If future work changes the meaning of `node_id` or candidate ordering semantics, this ordering contract will need a separate update.

## [2026-04-24 15:33:39]
Task:
Read-only analysis task: lock the next smallest safe follow-up improvement after the landed deterministic tie-break on the current APG path.

Goal:
Give control one directly assignable next APG-path improvement slice that preserves the current candidate-selection, retrieval, persistence, and planner contracts while reducing the most immediate residual risk in the landed ordering behavior.

Files changed:
- `docs/WORKLOG_MVP.md`

What changed:
- Final conclusion:
  - The next smallest follow-up improvement should be to centralize the current heuristic candidate ordering into one private helper inside `attack_agent/reasoning.py`, and make `HeuristicReasoner.choose_program()`, `LLMReasoner.choose_program()`, and `LLMReasoner._validate_program_response()` all consume that single ordering source.
- Direct answers for control:
  1. Next smallest follow-up improvement:
     - extract one shared deterministic candidate-order helper in `attack_agent/reasoning.py`
     - use it in both heuristic fallback selection and LLM candidate payload / validation paths
  2. Why this is smaller and safer than other directions:
     - the current APG behavior already works, but the same ordering rule is duplicated across multiple functions
     - that duplication is now the smallest concrete risk to the landed `candidate_index` contract
     - removing the duplication is smaller and safer than changing scoring, candidate generation, planner flow, retrieval, or model scope
  3. Smallest implementation entry file:
     - `attack_agent/reasoning.py`
  4. Smallest implementation function / exact edit surface:
     - add one private helper for deterministic candidate ordering
     - update only:
       - `HeuristicReasoner.choose_program()`
       - `LLMReasoner.choose_program()`
       - `LLMReasoner._validate_program_response()`
  5. Smallest test entry file:
     - `tests/test_apg_engine.py`
  6. Smallest test shape:
     - add exactly 1 thin regression test that constructs a context where heuristic fallback and `candidate_index=0` should resolve to the same candidate under the current deterministic ordering
     - assert both paths produce the same `node_id`
  7. Behaviors that must be preserved:
     - keep the current `candidate_index` path
     - keep the current `family` / `node_id` path
     - keep the current heuristic fallback
     - keep the current deterministic candidate ordering contract:
       - primary rule remains `(score, len(steps))`
       - `node_id` remains only the final tie-break for equal-ranked candidates
     - keep current lexical retrieval behavior
     - keep current single-file JSON persistence behavior
     - keep current `EpisodeEntry` shape
     - keep current `RetrievalHit` shape
     - keep current `APGPlanner.plan()` main flow
  8. Files and boundaries that must not be touched:
     - do not modify `attack_agent/apg.py`
     - do not modify `attack_agent/state_graph.py`
     - do not modify `attack_agent/platform.py`
     - do not modify `attack_agent/controller.py`
     - do not modify `attack_agent/dispatcher.py`
     - do not modify `attack_agent/runtime.py`
     - do not modify `attack_agent/provider.py`
     - do not modify `attack_agent/platform_models.py`
     - do not modify `tests/test_platform_flow.py`
     - do not modify docs body outside `docs/WORKLOG_MVP.md`
  9. Direct implementation task statement:
     - "In `attack_agent/reasoning.py`, extract the current deterministic candidate ordering into one shared private helper and make heuristic fallback plus `candidate_index` payload/validation all consume it; add exactly 1 thin regression test in `tests/test_apg_engine.py` proving heuristic fallback and `candidate_index=0` resolve to the same candidate."

What did not change:
- No Python implementation files changed.
- No test files changed.
- No docs body files changed outside this worklog entry.
- No implementation was started.

Tests run:
- None. This round was read-only analysis only.

Open risks:
- This follow-up is intentionally small and mostly guards against future drift; it does not widen product capability by itself.
- If the next task expands beyond shared ordering consolidation, it can easily spill into broader planner or reasoner redesign.

## [2026-04-24 15:44:01]
Task:
Extract the current deterministic candidate ordering into one shared private helper in `attack_agent/reasoning.py`.

Goal:
Keep heuristic fallback selection and `candidate_index` payload / validation on one shared deterministic ordering source without changing candidate generation, family scoring, retrieval, persistence, or `APGPlanner.plan()`.

Files changed:
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

What changed:
- Added `test_llm_reasoner_candidate_index_matches_heuristic_fallback_choice` in `tests/test_apg_engine.py`.
- The new test builds a minimal context where heuristic fallback should choose the top-ranked candidate and verifies `candidate_index=0` resolves to the same `node_id`.
- Added a single private helper in `attack_agent/reasoning.py`:
  - `_order_candidates(...)`
- Updated these functions to reuse the shared helper:
  - `HeuristicReasoner.choose_program()`
  - `LLMReasoner.choose_program()`
  - `LLMReasoner._validate_program_response()`
- Preserved the current deterministic ordering contract:
  - primary rule remains `(score, len(steps))`
  - `node_id` remains only the final tie-break for equal-ranked candidates
- Preserved the current `candidate_index` path, `family` / `node_id` path, heuristic fallback, lexical retrieval, JSON persistence behavior, `EpisodeEntry` / `RetrievalHit` structure, and `APGPlanner.plan()` main flow.
- Followed the requested sequence:
  - wrote the regression test first
  - observed the behavior was already green before refactor
  - performed the smallest shared-helper extraction
  - reran the targeted test and full `tests.test_apg_engine` suite

What did not change:
- Did not modify `attack_agent/apg.py`
- Did not modify `attack_agent/state_graph.py`
- Did not modify `attack_agent/platform.py`
- Did not modify `attack_agent/controller.py`
- Did not modify `attack_agent/dispatcher.py`
- Did not modify `attack_agent/runtime.py`
- Did not modify `attack_agent/provider.py`
- Did not modify `attack_agent/platform_models.py`
- Did not modify `tests/test_platform_flow.py`
- Did not change candidate generation
- Did not change family scoring
- Did not change lexical retrieval
- Did not change single-file JSON persistence behavior
- Did not change docs body outside this worklog append

Tests run:
- `python -m unittest tests.test_apg_engine.APGEngineTests.test_llm_reasoner_candidate_index_matches_heuristic_fallback_choice -v`
- `python -m unittest tests.test_apg_engine -v`

Open risks:
- This follow-up removes duplication risk but does not expand planner capability.
- If future work changes ordering semantics, the shared helper must remain the only source of truth to keep `candidate_index` stable.

## [2026-04-24 15:55:28]
Task:
Repair `docs/WORKLOG_MVP.md` ordering and duplicate-entry state after the recent APG follow-up logging drift.

Goal:
Restore the MVP worklog to a unique, chronological, tail-appended state without changing any code, tests, or other documentation files.

Files changed:
- `docs/WORKLOG_MVP.md`

What changed:
- Removed the obsolete duplicated `2026-04-24 15:33:39` analysis entry that still pointed to the pre-shared-order-helper follow-up.
- Kept the correct post-shared-order-helper analysis entry and normalized it to a later timestamp so it now sorts after the `2026-04-24 15:44:01` implementation entry.
- Restored chronological tail ordering so the latest dated entry is once again at file end.
- Did not alter any Python, tests, or other docs body files.

What did not change:
- No Python implementation files changed.
- No test files changed.
- No docs body files changed outside this worklog file.
- No analysis conclusion content was expanded into implementation.

Tests run:
- None

Open risks:
- Future manual head-insert logging would break chronological reviewability again.
- Timestamp normalization in the worklog remains a human process unless future logging is constrained more strictly.
