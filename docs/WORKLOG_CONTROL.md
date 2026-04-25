# Control Worklog

## Purpose

Single source of truth for control-window decisions:

- stage summaries
- task dispatch
- acceptance
- risks
- next actions

This recovered version was rebuilt after `docs/WORKLOG_CONTROL.md` was found zero-filled on 2026-04-24 15:36:48. Historical detail before the recovered entries below may be incomplete.

## Rules

- `docs/MVP_REFACTOR_PLAN.md` is the sole planning source.
- Dispatch only one clear task to one window at a time.
- Do not assign a second task to the same window before acceptance.
- Do not let two windows modify the same file at the same time.
- Record every dispatch, acceptance, and major control decision.

## Entry Template

## [YYYY-MM-DD HH:MM:SS]
Stage:

Window:

Task:

Decision:

Files reviewed:

Acceptance result:

Tests checked:

Risks:

Next action for user:

## [2026-04-24 10:17:35]
Stage:
Control workflow adjustment

Window:
Control

Task:
Refine task ownership after repeated lightweight doc-sync and MVP worklog-order issues.

Decision:
- `docs/CURRENT_STATE.md` and `docs/NEXT_STEPS.md` are maintained directly by Control.
- Structure-window work should prioritize actual structural adjustments instead of routine status docs.
- Future MVP packets must append `docs/WORKLOG_MVP.md` at file end in chronological order and repair any accidental head insertion within the same task.

Files reviewed:
- `docs/WORKLOG_CONTROL.md`
- `docs/WORKLOG_MVP.md`
- `docs/CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`

Acceptance result:
Process updated.

Tests checked:
- None. Process decision only.

Risks:
- Control now owns more live-doc maintenance, so dispatches must stay short and precise.

Next action for user:
- Continue with MVP-only APG-path analysis and implementation packets.

## [2026-04-24 10:22:20]
Stage:
Next APG follow-up analysis accepted

Window:
MVP

Task:
Accept the read-only analysis that locked the next smallest follow-up improvement after the landed ordering-alignment slice.

Decision:
- Accepted the next smallest follow-up improvement as:
  - add one deterministic final tie-break to heuristic candidate ordering so `candidate_index` remains stable under equal-ranked candidates
- Accepted `attack_agent/reasoning.py` as the minimum implementation entry point.
- Accepted `tests/test_apg_engine.py` as the minimum test entry point.

Files reviewed:
- `docs/WORKLOG_MVP.md`
- `attack_agent/reasoning.py`
- `attack_agent/apg.py`
- `tests/test_apg_engine.py`

Acceptance result:
Accepted.

Tests checked:
- None. This was a read-only analysis task.

Risks:
- If the next slice expands beyond an explicit deterministic tie-break, it can spill into a broader planner or reasoner redesign.

Next action for user:
- Dispatch the minimal deterministic tie-break implementation packet.

## [2026-04-24 10:22:45]
Stage:
Deterministic tie-break implementation dispatched

Window:
MVP

Task:
Dispatch the minimal deterministic candidate-order tie-break implementation packet on the current APG path.

Decision:
- Keep the task as a single-goal MVP packet for deterministic tie-break alignment only.
- Lock the write set to:
  - `attack_agent/reasoning.py`
  - `tests/test_apg_engine.py`
  - `docs/WORKLOG_MVP.md`
- Keep the scope inside:
  - `HeuristicReasoner.choose_program()`
  - `LLMReasoner.choose_program()`
  - `LLMReasoner._validate_program_response()`

Files reviewed:
- `docs/WORKLOG_CONTROL.md`
- `docs/WORKLOG_MVP.md`
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`

Acceptance result:
- Pending dispatch execution.

Tests checked:
- None. Dispatch only.

Risks:
- The packet could still sprawl if it changes candidate generation or family scoring instead of staying inside one deterministic final tie-break.

Next action for user:
- Send the implementation packet to the MVP window and return for acceptance.

## [2026-04-24 10:36:06]
Stage:
Deterministic tie-break implementation accepted

Window:
MVP

Task:
Accept the minimal deterministic candidate-order tie-break implementation packet on the current APG path.

Decision:
- Accepted the narrow change in `attack_agent/reasoning.py`.
- Confirmed `HeuristicReasoner.choose_program()` preserves the current `(score, len(steps))` preference rule and uses `node_id` only as the final deterministic tie-break.
- Confirmed `LLMReasoner.choose_program()` emits that same deterministic candidate order in the model payload.
- Confirmed `LLMReasoner._validate_program_response()` resolves `candidate_index` against that same deterministic ordered list.
- Confirmed the existing `candidate_index` path, `family` / `node_id` path, heuristic fallback, lexical retrieval behavior, and single-file JSON persistence behavior remain intact.

Files reviewed:
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

Acceptance result:
Accepted.

Tests checked:
- `python -m unittest tests.test_apg_engine -v`
- `python -m unittest discover -s tests -v`
- Fresh full regression baseline: `31/31 OK`

Risks:
- The deterministic tie-break depends on `node_id` remaining a stable lexical identifier for equal-ranked candidates.

Next action for user:
- Let Control sync `docs/CURRENT_STATE.md` and `docs/NEXT_STEPS.md`, then dispatch the next read-only APG-path analysis packet.

## [2026-04-24 10:36:06]
Stage:
Post-tie-break control doc sync

Window:
Control

Task:
Resync current-state and next-steps docs after acceptance of the deterministic candidate-order tie-break slice.

Decision:
- Updated `docs/CURRENT_STATE.md` to reflect the landed deterministic final tie-break.
- Updated `docs/NEXT_STEPS.md` to point at the next read-only APG-path analysis packet.

Files reviewed:
- `docs/CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG_CONTROL.md`

Acceptance result:
Completed.

Tests checked:
- Reused the fresh verification from this control pass:
  - `python -m unittest tests.test_apg_engine -v`
  - `python -m unittest discover -s tests -v`

Risks:
- `docs/NEXT_STEPS.md` intentionally left the next APG improvement generic until a new read-only analysis locked the smallest safe target.

Next action for user:
- Ask Control for the next MVP analysis dispatch packet when ready.

## [2026-04-24 15:33:39]
Stage:
Next APG follow-up analysis accepted

Window:
MVP

Task:
Accept the read-only analysis that locks the next smallest safe follow-up improvement after the landed deterministic tie-break on the current APG path.

Decision:
- Accepted the next smallest follow-up improvement as:
  - extract one shared deterministic candidate-order helper in `attack_agent/reasoning.py`
  - make heuristic fallback plus `candidate_index` payload and validation consume that single ordering source
- Accepted `attack_agent/reasoning.py` as the smallest implementation entry file.
- Accepted the exact narrow change surface:
  - add one private helper for deterministic candidate ordering
  - update only:
    - `HeuristicReasoner.choose_program()`
    - `LLMReasoner.choose_program()`
    - `LLMReasoner._validate_program_response()`
- Accepted `tests/test_apg_engine.py` as the smallest test entry file.
- Accepted the minimum test shape:
  - add exactly 1 thin regression test proving heuristic fallback and `candidate_index=0` resolve to the same candidate under the current deterministic ordering
- Confirmed the required preserved behavior:
  - current `candidate_index` path
  - current `family` / `node_id` path
  - current heuristic fallback
  - current deterministic candidate ordering contract:
    - `(score, len(steps))` remains the primary rule
    - `node_id` remains only the final tie-break for equal-ranked candidates
  - current lexical retrieval
  - current single-file JSON persistence
  - current `EpisodeEntry` / `RetrievalHit` shapes
  - current `APGPlanner.plan()` main flow
- Confirmed the analysis stayed read-only and appended to `docs/WORKLOG_MVP.md` at file end.

Files reviewed:
- `docs/WORKLOG_MVP.md`
- `attack_agent/apg.py`
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`
- `docs/MVP_REFACTOR_PLAN.md`
- `docs/CURRENT_STATE.md`

Acceptance result:
Accepted.

Tests checked:
- None. This was a read-only analysis task.

Risks:
- This follow-up mainly reduces duplication drift and does not widen product capability by itself.
- If the next packet expands beyond shared ordering consolidation, it can spill into broader planner or reasoner redesign.

Next action for user:
- Dispatch the minimal shared-order-helper implementation packet.

## [2026-04-24 15:36:48]
Stage:
Control doc recovery

Window:
Control

Task:
Recover zero-filled control and next-steps docs, then record the current accepted MVP analysis result.

Decision:
- Rebuilt `docs/WORKLOG_CONTROL.md` after detecting it had been overwritten with zero bytes.
- Rebuilt `docs/NEXT_STEPS.md` to reflect the current accepted next single goal.
- Preserved the current accepted APG direction and latest verified baseline while noting that older historical detail may be incomplete in the recovered control log.

Files reviewed:
- `docs/WORKLOG_CONTROL.md`
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG_MVP.md`
- `docs/CURRENT_STATE.md`

Acceptance result:
Completed.

Tests checked:
- No code tests run. This was a control-doc recovery and logging pass.

Risks:
- Earlier detailed control history before the recovered entries is no longer fully reconstructable from the zero-filled file itself.

Next action for user:
- Send the next MVP implementation packet to the MVP window and return for acceptance.

## [2026-04-24 15:46:30]
Stage:
Shared-order-helper implementation review

Window:
MVP

Task:
Review the minimal shared deterministic candidate-order helper implementation packet on the current APG path.

Decision:
- Code scope is acceptable:
  - `attack_agent/reasoning.py` adds one private helper and only updates the three allowed reasoner functions.
  - `tests/test_apg_engine.py` adds one thin regression test matching the approved test shape.
- Fresh verification is green:
  - `python -m unittest tests.test_apg_engine -v`
  - `python -m unittest discover -s tests -v`
  - current fresh full regression baseline is `32/32 OK`
- However, the packet is not accepted yet because `docs/WORKLOG_MVP.md` does not satisfy the logging-order requirement:
  - the new `2026-04-24 15:44:01` implementation entry appears before the older `2026-04-24 15:33:39` analysis entry
  - this violates the rule that the latest MVP entry must be appended at file end in chronological order

Files reviewed:
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

Acceptance result:
Rejected pending MVP worklog order repair.

Tests checked:
- `python -m unittest tests.test_apg_engine -v`
- `python -m unittest discover -s tests -v`

Risks:
- If we accept code while relaxing the worklog-order rule, future MVP packets will keep drifting out of chronological order and weaken control traceability.

Next action for user:
- Send a minimal MVP repair packet that only normalizes `docs/WORKLOG_MVP.md` chronology for the latest entries, then return for re-review.

## [2026-04-24 15:58:30]
Stage:
MVP worklog repair accepted

Window:
MVP

Task:
Accept the minimal MVP repair packet that only normalizes `docs/WORKLOG_MVP.md` chronology and duplicate-entry state.

Decision:
- Accepted the worklog-only repair in `docs/WORKLOG_MVP.md`.
- Confirmed the obsolete duplicate analysis entry was removed.
- Confirmed the retained entries are now in chronological order and the latest repair entry is appended at file end.
- Confirmed the repair packet did not change Python files, test files, or other docs body files.

Files reviewed:
- `docs/WORKLOG_MVP.md`

Acceptance result:
Accepted.

Tests checked:
- None. This was a worklog-only repair task.

Risks:
- MVP worklog ordering remains vulnerable to future manual head-insert logging if packets do not keep self-repairing within the same task.

Next action for user:
- Re-run acceptance for the previously blocked shared-order-helper implementation packet.

## [2026-04-24 15:58:30]
Stage:
Shared-order-helper implementation accepted

Window:
MVP

Task:
Accept the minimal shared deterministic candidate-order helper implementation packet on the current APG path after worklog repair cleared the previous process blocker.

Decision:
- Accepted the narrow change in `attack_agent/reasoning.py`.
- Confirmed one private helper now centralizes deterministic candidate ordering:
  - `_order_candidates(...)`
- Confirmed only the approved reasoner methods were updated to consume that shared ordering source:
  - `HeuristicReasoner.choose_program()`
  - `LLMReasoner.choose_program()`
  - `LLMReasoner._validate_program_response()`
- Confirmed the current deterministic ordering contract remains intact:
  - primary rule `(score, len(steps))`
  - `node_id` only as the final tie-break for equal-ranked candidates
- Confirmed the current `candidate_index` path, `family` / `node_id` path, heuristic fallback, lexical retrieval behavior, single-file JSON persistence behavior, and `APGPlanner.plan()` main flow remain intact.
- Confirmed the new thin regression test proves heuristic fallback and `candidate_index=0` resolve to the same candidate.

Files reviewed:
- `attack_agent/reasoning.py`
- `tests/test_apg_engine.py`
- `docs/WORKLOG_MVP.md`

Acceptance result:
Accepted.

Tests checked:
- `python -m unittest tests.test_apg_engine -v`
- `python -m unittest discover -s tests -v`
- Fresh full regression baseline is now `32/32 OK`.

Risks:
- This slice reduces duplication drift but does not widen planner capability by itself.
- If future work changes ordering semantics, `_order_candidates(...)` must remain the single source of truth.

Next action for user:
- Let Control sync `docs/CURRENT_STATE.md` and `docs/NEXT_STEPS.md`, then continue from the latest accepted APG follow-up analysis.

## [2026-04-24 15:58:30]
Stage:
Post-shared-helper control doc sync

Window:
Control

Task:
Resync current-state and next-steps docs after acceptance of the shared deterministic candidate-order helper slice.

Decision:
- Updated `docs/CURRENT_STATE.md` to reflect the shared-order-helper landing and the fresh `32/32 OK` baseline.
- Updated `docs/NEXT_STEPS.md` so it now points at the next already-locked APG-path improvement after the shared-order-helper slice.
- Kept the wording narrow and did not over-claim a broader model-assisted planner, retrieval redesign, or persistence redesign.

Files reviewed:
- `docs/CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/WORKLOG_CONTROL.md`

Acceptance result:
Completed.

Tests checked:
- Reused the fresh verification from this control pass:
  - `python -m unittest tests.test_apg_engine -v`
  - `python -m unittest discover -s tests -v`

Risks:
- The next APG slice still needs a narrow implementation packet to avoid widening beyond mixed selector consistency validation.

Next action for user:
- Ask Control for the next MVP implementation packet when ready.
