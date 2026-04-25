# Next Steps

## Recommended Build Order

1. Implement the next smallest APG-path improvement already locked by the latest read-only analysis.
2. Rebaseline `docs/NEXT_STEPS.md` and `docs/CURRENT_STATE.md` after that implementation slice is accepted.
3. Only then perform another read-only analysis for the next APG-path follow-up.
4. Only then deepen model-assisted planning and candidate ranking beyond the current narrow landed slices.
5. After retrieval behavior is better understood, expand browser, artifact, and binary capabilities beyond their current narrow slices.
6. Only then expand to more advanced multi-worker coordination.

## Best Next Single Goal

The most recommended next task is:

`Implement one minimal consistency check in attack_agent/reasoning.py so conflicting mixed selector responses in LLMReasoner._validate_program_response() are rejected and heuristic fallback remains the safety net, without changing the current candidate-selection, retrieval, persistence, ordering, or planner contracts.`

Why this is the best next step:

- the first-stage minimal real primitive loop is already closed
- the minimal `EpisodeMemory` persistence slice is already landed
- the minimal retrieval-quality ranking improvement is already landed
- the minimal model-assisted candidate-selection slice is already landed
- the minimal `candidate_index` ordering-alignment refinement is already landed
- the minimal deterministic final tie-break for equal-ranked candidate ordering is already landed
- the shared deterministic candidate-order helper is already landed
- the next smallest remaining APG-path ambiguity is mixed selector interpretation when a model response includes both `candidate_index` and `family` / `node_id`
- resolving that validation ambiguity is smaller and safer than changing scoring, candidate generation, planner flow, retrieval, persistence, or model scope

## Expected Acceptance Criteria For That Task

- implement only in `attack_agent/reasoning.py`
- keep the exact write set limited to:
  - `attack_agent/reasoning.py`
  - `tests/test_apg_engine.py`
  - `docs/WORKLOG_MVP.md`
- keep the implementation primarily inside `LLMReasoner._validate_program_response()`
- allow at most a minimal compatible touch in `LLMReasoner.choose_program()` only if needed for test clarity
- do not change `HeuristicReasoner.choose_program()`
- add exactly 1 thin regression test in `tests/test_apg_engine.py`
- the new test must construct a context where:
  - at least 2 candidates are present
  - `candidate_index` points to one candidate
  - `family` / `node_id` point to a different candidate
  - the conflicting response is rejected
  - the final returned decision falls back to the heuristic choice
- explicitly preserve:
  - the current `candidate_index` model-selection path
  - the current `family` / `node_id` response-validation path
  - heuristic fallback for missing or invalid model responses
  - the current deterministic candidate ordering contract:
    - preserve `(score, len(steps))` as the main ordering rule
    - preserve `node_id` as the final deterministic tie-break for equal-ranked candidates
  - the current shared-order-helper as the single ordering source
  - the current lexical retrieval ranking improvement
  - the current `EpisodeEntry` shape
  - the current `RetrievalHit` shape
  - `EpisodeEntry`-only storage in a single local JSON file
  - in-memory mode when no path is provided
  - load-on-init and minimal synchronous write-back on `add()`
  - the current `APGPlanner.plan()` main flow
- explicitly forbid:
  - broad planner rewrite
  - reasoner overhaul
  - candidate generation rewrite
  - family scoring rewrite
  - semantic retrieval rewrite
  - database or vector store introduction
  - full-state persistence redesign
  - broader model integration
