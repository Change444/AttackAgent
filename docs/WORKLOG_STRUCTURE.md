# Structure Worklog

## Purpose

Record structure-window work in a stable, compact format:

- doc synchronization
- naming and entry-point cleanup
- scope-preserving structural edits

This file is kept ASCII-first so terminal rendering stays predictable.

## Rules

- Handle one control-approved task at a time.
- Do not take a second task before control acceptance.
- Prefer docs, naming, and entry-point cleanup over Python implementation unless explicitly authorized.
- Record changed files, untouched boundaries, tests, and risks for every task.

## Entry Template

## [YYYY-MM-DD HH:MM:SS]
Task:

Goal:

Files changed:

What changed:

What did not change:

Tests run:

Open risks:

Recommendation for control:

## [2026-04-23 12:58:01]
Task:
Read-only analysis of the biggest current structure problem and initialize the structure worklog.

Goal:
Identify the largest readability/boundary issue without changing code.

Files changed:
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Created the structure worklog.
- Identified the biggest repository readability issue:
  - platform path and old single-agent path were both visible as if they were primary
  - terminology was split across `models.py` and `platform_models.py`
  - entry-point guidance was inconsistent

What did not change:
- No Python files.
- No runtime behavior.

Tests run:
- None.

Open risks:
- Any direct file move or rename would have been too wide for the task.

Recommendation for control:
- First clarify the canonical path in docs before touching implementation.

## [2026-04-23 13:09:18]
Task:
Clarify README entry points.

Goal:
Make the platform path explicit and mark the old path as legacy/deprecated.

Files changed:
- `README.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Added a canonical-path section pointing to `attack_agent.platform`.
- Added a legacy-path section for the old single-agent route.
- Reduced the chance that readers would treat both paths as equally primary.

What did not change:
- No Python files.
- No runtime behavior.

Tests run:
- None.

Open risks:
- The repository layout still physically contained the legacy files.

Recommendation for control:
- Move next into narrow MVP primitive work, not broad structure cleanup.

## [2026-04-23 13:35:57]
Task:
Sync `CURRENT_STATE` for the real `http-request` slice.

Goal:
Describe the landed minimal real `http-request` branch without over-claiming.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Recorded the real `http-request` branch.
- Recorded preserved metadata fallback.
- Recorded platform-flow coverage for real branch plus fallback.

What did not change:
- No Python files.
- No broader planning docs.

Tests run:
- None.

Open risks:
- Planning docs still pointed at earlier stages.

Recommendation for control:
- Keep syncing only landed facts, not broader future promises.

## [2026-04-23 13:39:11]
Task:
Fix the stale baseline count in `CURRENT_STATE`.

Goal:
Bring the documented test baseline back in line with the repository at that moment.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Corrected the documented baseline count.

What did not change:
- No Python files.
- No architecture or planning edits.

Tests run:
- None.

Open risks:
- Baseline numbers would need another update after later cleanup work.

Recommendation for control:
- Treat baseline counts as sync-only edits when facts change.

## [2026-04-23 13:44:11]
Task:
Sync `NEXT_STEPS` to point at the next then-current MVP task.

Goal:
Stop showing `http-request` as the next goal after it had already landed.

Files changed:
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Switched the recommended next slice to minimal real `browser-inspect`.

What did not change:
- No Python files.

Tests run:
- None.

Open risks:
- `NEXT_STEPS` would need further sync as additional slices landed.

Recommendation for control:
- Continue treating `NEXT_STEPS` as a live but minimal planning surface.

## [2026-04-23 14:51:34]
Task:
Sync `CURRENT_STATE` for the real `browser-inspect` slice.

Goal:
Describe the landed minimal real `browser-inspect` branch without overstating browser capability.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Recorded the real `browser-inspect` branch.
- Recorded preserved metadata fallback.
- Recorded the bounded rendered-page scope.

What did not change:
- No Python files.
- No broader planning docs.

Tests run:
- None.

Open risks:
- Readers could still overread this as full browser automation if future docs were careless.

Recommendation for control:
- Keep browser wording intentionally narrow.

## [2026-04-23 15:15:53]
Task:
Sync `CURRENT_STATE` for the real `binary-inspect` slice.

Goal:
Describe the landed minimal real `binary-inspect` branch without overstating binary-analysis scope.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Recorded the real `binary-inspect` branch.
- Recorded preserved metadata fallback.
- Recorded the bounded printable-strings observation scope.

What did not change:
- No Python files.

Tests run:
- None.

Open risks:
- Readers could still overread this as a broader binary-analysis pipeline if future docs got loose.

Recommendation for control:
- Keep binary wording intentionally narrow.

## [2026-04-23 15:31:01]
Task:
Sync `CURRENT_STATE` for the real `artifact-scan` slice and the Stage 1 primitive loop closure.

Goal:
Show that the first-stage minimal real primitive loop had closed without overstating artifact capability.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Recorded the real `artifact-scan` branch.
- Added the Stage 1 minimal-real-primitive closure summary.
- Recorded the bounded single-file observation scope.

What did not change:
- No Python files.

Tests run:
- None.

Open risks:
- `artifact-scan` could still be overread as a full forensics path if later docs were careless.

Recommendation for control:
- Close Stage 1 and move into persistence/observability planning.

## [2026-04-23 20:33:52]
Task:
Sync `CURRENT_STATE` for minimal `EpisodeMemory` persistence.

Goal:
Describe the landed minimal `EpisodeMemory` JSON persistence slice without overstating it as a full memory system.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Recorded that `EpisodeMemory` is no longer pure in-memory only.
- Recorded the current persistence boundary:
  - `EpisodeEntry` only
  - one local JSON file
  - safe empty initialization when the file does not yet exist
  - minimal synchronous write-back on `add()`
- Recorded the APG-engine test coverage for persistence and reload search hits.

What did not change:
- No Python files.
- No broader planning docs.

Tests run:
- None.

Open risks:
- This is still a narrow persistence slice, not a complete memory/retrieval system.

Recommendation for control:
- Move next into either retrieval-quality analysis or minimal visualization analysis.

## [2026-04-23 21:07:27]
Task:
Sync `CURRENT_STATE` for the minimal `PatternGraph` console-visualization slice.

Goal:
Describe the landed single-project text `PatternGraph` view without overstating it as `RunJournal` visualization, a Web UI, or an interactive dashboard.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Recorded that `PatternGraph` now has a minimal visualization slice.
- Recorded the current view boundary:
  - single-project only
  - text-only console output
  - reuses `state_graph.query_graph(project_id, view="pattern")`
  - shows only `active_family` plus node `id` / `family` / `status`
- Recorded platform-flow coverage for the minimal text view.

What did not change:
- No Python files.
- No broader planning docs.
- No `RunJournal` or Web UI claims.

Tests run:
- None.

Open risks:
- This is still only a narrow console slice; readers could overread it as a broader visualization layer if future wording gets loose.

Recommendation for control:
- Keep future visualization sync clearly split between the minimal `PatternGraph` text view and any later `RunJournal`/Web UI work.

## [2026-04-23 21:20:01]
Task:
Sync `CURRENT_STATE` for the minimal `RunJournal` console-visualization slice.

Goal:
Describe the landed single-project text `RunJournal` view without overstating it as a `PatternGraph` change, a Web UI, a dashboard, a filtering/search UI, or an interactive interface.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Recorded that `RunJournal` now has a minimal visualization slice.
- Recorded the current view boundary:
  - single-project only
  - text-only console output
  - reuses `state_graph.query_graph(project_id, view="events")`
  - shows only a small header plus event `type` / `source` / `run_id`
  - preserves event order
- Recorded platform-flow coverage for the minimal text view.

What did not change:
- No Python files.
- No broader planning docs.
- No `PatternGraph` scope expansion claims.
- No Web UI, dashboard, filtering/search UI, or interactive-interface claims.

Tests run:
- None.

Open risks:
- This is still only a narrow console slice; readers could overread it as a broader run-journal observability layer if future wording gets loose.

Recommendation for control:
- Keep future observability sync clearly split between the minimal `RunJournal` text view and any later Web/dashboard/search work.

## [2026-04-23 21:24:34]
Task:
Resync `NEXT_STEPS` to the current post-primitive, post-persistence, post-minimal-visualization phase.

Goal:
Stop treating minimal persistence or minimal text visualization as the next task, and instead point the repository at a read-only retrieval-quality analysis as the next smallest justified step.

Files changed:
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Updated `Recommended Build Order` so it now starts with read-only retrieval-quality analysis rather than persistence or minimal visualization work.
- Updated `Best Next Single Goal` to a read-only retrieval-quality improvement analysis task.
- Updated `Expected Acceptance Criteria For That Task` so the task now locks:
  - the smallest implementation entry point to identify
  - the smallest test entry point to identify
  - the current persistence behavior that must be preserved
  - the boundaries that must not be touched
- Kept the wording intentionally narrow:
  - no claim that retrieval work has already begun
  - no claim that memory is now a full memory system
  - no claim that console text views are equivalent to web visualization

What did not change:
- No Python files.
- No `docs/CURRENT_STATE.md`.
- No planning-source edits to `docs/MVP_REFACTOR_PLAN.md`.
- No architecture-doc edits.

Tests run:
- None.

Open risks:
- `docs/CURRENT_STATE.md` still shows a stale baseline count and remains a separate sync concern outside this task.
- `docs/MVP_REFACTOR_PLAN.md` still centers the earlier MVP phase and may need a later control-approved sync if planning and current repository phase need to be restated together.

Recommendation for control:
- Treat the next work packet as a strict read-only analysis task for retrieval quality, and require it to lock implementation/test entry points plus non-goals before any code changes begin.

## [2026-04-24 09:26:42]
Task:
Sync the minimal retrieval-quality slice into `CURRENT_STATE` and rewrite `NEXT_STEPS` to the next post-retrieval phase.

Goal:
Reflect that the smallest `EpisodeMemory.search()` ranking improvement is already landed, update the verified baseline, and move the next recommended task to a read-only analysis for the smallest model-assisted planning / candidate-ranking slice on the current APG path.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Updated `docs/CURRENT_STATE.md` to reflect that `EpisodeMemory.search()` now includes a minimal retrieval-quality improvement.
- Recorded the current boundary of that slice:
  - it only improves ranking inside the existing lexical retrieval path
  - it is meant to rank a stronger match above a weaker partially overlapping entry
  - it does not change `EpisodeEntry`
  - it does not change `RetrievalHit`
  - it does not change the single-file JSON persistence behavior
  - it does not change no-path in-memory mode, load-on-init, or `add()` write-back
- Recorded that `tests/test_apg_engine.py` covers the minimal ranking improvement.
- Updated the `Verified Baseline` test count in `docs/CURRENT_STATE.md` to `28/28 OK`.
- Rewrote `docs/NEXT_STEPS.md` so retrieval analysis/implementation is no longer treated as the next task.
- Set the next recommended task to a read-only analysis that locks the smallest model-assisted planning / candidate-ranking improvement slice on the current APG path.
- Rewrote the expected acceptance criteria so the next task stays analysis-only, preserves the current retrieval/persistence contracts, and explicitly excludes database, vector-store, semantic-retrieval, full-state-persistence, or broad model-overhaul work.

What did not change:
- No Python files.
- No implementation logic.
- No `docs/ARCHITECTURE.md`.
- No `docs/MVP_REFACTOR_PLAN.md`.
- No `docs/WORKLOG_CONTROL.md`.

Tests run:
- None; this task only synchronized documentation to already-landed code and tests.

Open risks:
- `docs/MVP_REFACTOR_PLAN.md` remains the source of truth and still describes the broader staged plan; this sync only updates status and next-step docs to match the currently landed repository facts.
- Future wording around model-assisted planning must stay narrow so readers do not infer that semantic retrieval, database-backed memory, or a larger planning rewrite has already started.

Recommendation for control:
- Treat the next work packet as a strict read-only analysis of the smallest model-assisted planning / candidate-ranking slice on the current APG path, and require it to lock entry points, test points, preserved contracts, and non-goals before any implementation begins.

## [2026-04-24 09:53:38]
Task:
Sync the minimal model-assisted candidate-selection slice into `CURRENT_STATE` and rewrite `NEXT_STEPS` to the next post-candidate-selection phase.

Goal:
Reflect that `LLMReasoner` now includes the smallest landed model-assisted candidate-selection improvement, update the verified baseline, and move the next recommended task to a read-only analysis for the next smallest follow-up improvement on the current APG path.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Updated `docs/CURRENT_STATE.md` to reflect that `LLMReasoner` now has a minimal model-assisted candidate-selection slice.
- Recorded the current boundary of that slice:
  - it only adds a `candidate_index` selection path inside the existing model-response validation flow
  - the existing `family` / `node_id` path remains in place
  - heuristic fallback remains in place for missing or invalid model responses
  - it does not change candidate generation
  - it does not change the main `APGPlanner.plan()` flow
  - it does not change lexical retrieval ranking
  - it does not change the single-file JSON persistence behavior
- Recorded that `tests/test_apg_engine.py` covers the minimal `candidate_index` improvement.
- Updated the `Verified Baseline` test count in `docs/CURRENT_STATE.md` to `29/29 OK`.
- Rewrote `docs/NEXT_STEPS.md` so model-assisted planning analysis for the just-landed slice is no longer treated as the next task.
- Set the next recommended task to a read-only analysis that locks the next smallest follow-up improvement on the current APG path.
- Rewrote the expected acceptance criteria so the next task stays analysis-only, preserves the current candidate-selection/retrieval/persistence contracts, and explicitly excludes broad planner rewrite, reasoner overhaul, semantic retrieval, database/vector-store memory, or full-state-persistence redesign work.

What did not change:
- No Python files.
- No implementation logic.
- No `docs/ARCHITECTURE.md`.
- No `docs/MVP_REFACTOR_PLAN.md`.
- No `docs/WORKLOG_CONTROL.md`.

Tests run:
- None; this task only synchronized documentation to already-landed code and tests.

Open risks:
- `docs/MVP_REFACTOR_PLAN.md` remains the source of truth and still describes a broader staged plan; this sync only updates status and next-step docs to match the currently landed repository facts.
- The phrase "next follow-up improvement" is intentionally generic; if control wants a narrower next-step target, that should be assigned as a separate read-only analysis task instead of inferred here.

Recommendation for control:
- Treat the next work packet as a strict read-only analysis of the next smallest follow-up improvement on the current APG path, and require it to lock scope, entry points, preserved contracts, and non-goals before any implementation begins.

## [2026-04-24 10:11:05]
Task:
Sync the minimal `candidate_index` ordering-alignment slice into `CURRENT_STATE` and resync `NEXT_STEPS` to the next post-alignment phase.

Goal:
Reflect that `LLMReasoner` has moved one small step beyond the first candidate-selection slice by aligning `candidate_index` to the same ordered candidate preference used by heuristic fallback, update the verified baseline, and keep the next recommended task at a read-only analysis for the next smallest follow-up improvement on the current APG path.

Files changed:
- `docs/CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG_STRUCTURE.md`

What changed:
- Updated `docs/CURRENT_STATE.md` to reflect the additional ordering-alignment refinement inside the existing minimal `LLMReasoner` candidate-selection slice.
- Recorded the current boundary of that refinement:
  - `candidate_index` now aligns to the same candidate preference order used by heuristic fallback
  - the candidate list sent in the model payload and the candidate list used during validation now share the same ordered candidate set
  - the existing `family` / `node_id` path remains in place
  - heuristic fallback remains in place for missing or invalid model responses
  - it does not change candidate generation
  - it does not change family scoring
  - it does not change the main `APGPlanner.plan()` flow
  - it does not change lexical retrieval ranking
  - it does not change the single-file JSON persistence behavior
- Recorded that `tests/test_apg_engine.py` covers this minimal ordering-alignment improvement.
- Updated the `Verified Baseline` test count in `docs/CURRENT_STATE.md` to `30/30 OK`.
- Reworded `docs/NEXT_STEPS.md` so the just-landed ordering-alignment slice is no longer implied to be pending work.
- Kept the next recommended task as a read-only analysis for the next smallest follow-up improvement on the current APG path, without turning it into implementation.

What did not change:
- No Python files.
- No implementation logic.
- No `docs/ARCHITECTURE.md`.
- No `docs/MVP_REFACTOR_PLAN.md`.
- No `docs/WORKLOG_CONTROL.md`.

Tests run:
- None; this task only synchronized documentation to already-landed code and tests.

Open risks:
- `docs/MVP_REFACTOR_PLAN.md` remains the source of truth and still describes the broader staged plan; this sync only updates status and next-step docs to match the currently landed repository facts.
- The next-step wording is intentionally narrow and generic; if control wants a more specific next target, that should be assigned as a separate read-only analysis task rather than inferred from this sync.

Recommendation for control:
- Treat the next work packet as a strict read-only analysis of the next smallest follow-up improvement on the current APG path, and require it to lock scope, preserved contracts, test entry points, and non-goals before any implementation begins.
