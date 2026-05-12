"""Replay Engine — Phase I.

Deterministic replay from Blackboard event journal with intermediate
state snapshots and run comparison.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from attack_agent.team.apply_event import apply_event_to_state
from attack_agent.team.protocol import (
    IdeaEntry,
    MemoryEntry,
    SolverSession,
    TeamProject,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ReplayStep:
    step_index: int
    event: Any  # BlackboardEvent from blackboard.py
    state_snapshot: Any  # MaterializedState from blackboard.py
    timestamp: str


@dataclass
class RunDiffResult:
    added_events: list = field(default_factory=list)  # list[BlackboardEvent]
    removed_events: list = field(default_factory=list)
    diverged_at_step: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collapse_indexes(state: Any,
                       idea_index: dict[str, IdeaEntry],
                       session_index: dict[str, SolverSession]) -> Any:
    """Collapse idea/session indexes into the state lists (latest-wins per id)."""
    state.ideas = list(idea_index.values())
    state.sessions = list(session_index.values())
    return state


def _event_match_key(ev: Any) -> tuple[str, str, str]:
    """Composite key for diff_runs event matching.

    (event_type, kind_or_type, content_or_description) — stable across
    runs that differ only in timestamps/IDs.
    """
    p = ev.payload
    kind = p.get("kind", ev.event_type)
    content = p.get("content") or p.get("summary") or p.get("text") or p.get("description") or p.get("flag") or ""
    return (ev.event_type, kind, content)


# ---------------------------------------------------------------------------
# ReplayEngine
# ---------------------------------------------------------------------------

class ReplayEngine:

    def replay_project(self, project_id: str, blackboard: Any) -> list[ReplayStep]:
        """Replay all events for a project, producing intermediate state snapshots."""
        events = blackboard.load_events(project_id)
        steps: list[ReplayStep] = []
        project: TeamProject | None = None
        facts: list[MemoryEntry] = []
        idea_index: dict[str, IdeaEntry] = {}
        session_index: dict[str, SolverSession] = {}

        for i, ev in enumerate(events):
            project = apply_event_to_state(
                project_id=ev.project_id,
                event_type=ev.event_type,
                payload=ev.payload,
                timestamp=ev.timestamp,
                event_id=ev.event_id,
                state_project=project,
                state_facts=facts,
                idea_index=idea_index,
                session_index=session_index,
            )
            # Build snapshot via blackboard's MaterializedState
            state = blackboard._new_materialized_state()
            state.project = copy.deepcopy(project) if project else None
            state.facts = copy.deepcopy(facts)
            _collapse_indexes(state, idea_index, session_index)
            steps.append(ReplayStep(
                step_index=i,
                event=ev,
                state_snapshot=copy.deepcopy(state),
                timestamp=ev.timestamp,
            ))

        return steps

    def replay_to_step(self, project_id: str, step_index: int,
                       blackboard: Any) -> Any:
        """Replay up to a specific step and return the intermediate MaterializedState."""
        events = blackboard.load_events(project_id)
        if step_index >= len(events) or step_index < 0:
            raise ValueError(f"step_index {step_index} out of range [0, {len(events) - 1}]")
        project: TeamProject | None = None
        facts: list[MemoryEntry] = []
        idea_index: dict[str, IdeaEntry] = {}
        session_index: dict[str, SolverSession] = {}

        for i in range(step_index + 1):
            project = apply_event_to_state(
                project_id=events[i].project_id,
                event_type=events[i].event_type,
                payload=events[i].payload,
                timestamp=events[i].timestamp,
                event_id=events[i].event_id,
                state_project=project,
                state_facts=facts,
                idea_index=idea_index,
                session_index=session_index,
            )

        state = blackboard._new_materialized_state()
        state.project = project
        state.facts = facts
        return _collapse_indexes(state, idea_index, session_index)

    def diff_runs(self, project_id_a: str, project_id_b: str,
                  blackboard_a: Any, blackboard_b: Any) -> RunDiffResult:
        """Compare two project event logs and return differences."""
        events_a = blackboard_a.load_events(project_id_a)
        events_b = blackboard_b.load_events(project_id_b)

        keys_a = [_event_match_key(ev) for ev in events_a]
        keys_b = [_event_match_key(ev) for ev in events_b]

        set_a = set(keys_a)
        set_b = set(keys_b)

        added = [ev for ev, k in zip(events_b, keys_b) if k not in set_a]
        removed = [ev for ev, k in zip(events_a, keys_a) if k not in set_b]

        # Find divergence point: first step where the two runs differ
        diverged_at_step: int | None = None
        min_len = min(len(keys_a), len(keys_b))
        for i in range(min_len):
            if keys_a[i] != keys_b[i]:
                diverged_at_step = i
                break

        return RunDiffResult(
            added_events=added,
            removed_events=removed,
            diverged_at_step=diverged_at_step,
        )