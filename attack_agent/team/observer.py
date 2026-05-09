"""Phase G — Observer: read-only analyzer that detects anomalies and suggests corrections."""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import MemoryKind, _gen_id, _utc_now
from attack_agent.platform_models import EventType


@dataclass
class ObservationNote:
    kind: str = ""          # repeated_action / low_novelty / ignored_boundary / stagnation / tool_misuse
    description: str = ""
    solver_id: str = ""
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class ObservationReport:
    report_id: str = field(default_factory=_gen_id)
    project_id: str = ""
    observations: list[ObservationNote] = field(default_factory=list)
    severity: str = "info"  # info / warning / critical
    suggested_actions: list[str] = field(default_factory=list)


class Observer:
    """Read-only analyzer: detect anomalies and write advisory CHECKPOINT events."""

    def __init__(self, blackboard: BlackboardService) -> None:
        self._bb = blackboard

    def detect_repeated_action(self, project_id: str, threshold: int = 3) -> list[ObservationNote]:
        events = self._bb.load_events(project_id)
        outcomes = [
            e for e in events if e.event_type == EventType.ACTION_OUTCOME.value
        ]
        # group by (solver_id, primitive, target)
        groups: dict[str, list] = {}
        for e in outcomes:
            p = e.payload
            key = f"{p.get('solver_id', '')}:{p.get('primitive', '')}:{p.get('target', '')}"
            groups.setdefault(key, []).append(e)

        notes: list[ObservationNote] = []
        for key, group in groups.items():
            if len(group) >= threshold:
                parts = key.split(":")
                notes.append(ObservationNote(
                    kind="repeated_action",
                    description=f"solver {parts[0]} repeated {parts[1]} on {parts[2]} {len(group)} times",
                    solver_id=parts[0],
                    evidence_refs=[e.event_id for e in group],
                ))
        return notes

    def detect_low_novelty(self, project_id: str, min_novelty: float = 0.1) -> list[ObservationNote]:
        state = self._bb.rebuild_state(project_id)
        recent = state.facts[-10:] if len(state.facts) >= 10 else state.facts
        if not recent:
            return []

        # check if ALL recent facts have confidence below threshold
        low_entries = [f for f in recent if f.confidence < min_novelty]
        if len(low_entries) == len(recent) and len(recent) > 0:
            return [ObservationNote(
                kind="low_novelty",
                description=f"all {len(recent)} recent facts below confidence {min_novelty}",
                solver_id="",
                evidence_refs=[f.entry_id for f in recent],
            )]
        return []

    def detect_ignored_failure_boundary(self, project_id: str) -> list[ObservationNote]:
        from attack_agent.team.memory import MemoryService
        mem = MemoryService(self._bb)
        boundaries = mem.get_failure_boundaries(project_id)
        if not boundaries:
            return []

        # group boundaries by description (multiple events may create
        # separate FailureBoundary entries with the same description)
        desc_groups: dict[str, list] = {}
        for b in boundaries:
            desc_groups.setdefault(b.description, []).append(b)

        events = self._bb.load_events(project_id)
        outcomes = [
            e for e in events if e.event_type == EventType.ACTION_OUTCOME.value
            and e.payload.get("status", "") != "ok"
        ]

        notes: list[ObservationNote] = []
        for desc, group in desc_groups.items():
            # count unique solver_ids across all outcomes matching this description
            solver_ids = set()
            for o in outcomes:
                err_text = o.payload.get("error", o.payload.get("summary", ""))
                if err_text == desc:
                    solver_ids.add(o.payload.get("solver_id", ""))
            if len(solver_ids) >= 2:
                notes.append(ObservationNote(
                    kind="ignored_boundary",
                    description=f"failure boundary '{desc}' attempted by {len(solver_ids)} solvers",
                    solver_id="",
                    evidence_refs=[b.boundary_id for b in group],
                ))
        return notes

    def detect_stagnation(self, project_id: str, cycle_threshold: int = 5) -> list[ObservationNote]:
        events = self._bb.load_events(project_id)
        if len(events) < cycle_threshold:
            return []

        recent = events[-cycle_threshold:]
        # check if none of the recent events produced new facts or ideas
        has_new_fact = any(
            e.event_type == EventType.OBSERVATION.value for e in recent
        )
        has_new_idea = any(
            e.event_type == EventType.CANDIDATE_FLAG.value for e in recent
        )

        if not has_new_fact and not has_new_idea:
            return [ObservationNote(
                kind="stagnation",
                description=f"no new facts/ideas in last {cycle_threshold} events",
                solver_id="",
                evidence_refs=[e.event_id for e in recent],
            )]
        return []

    def detect_tool_misuse(self, project_id: str) -> list[ObservationNote]:
        events = self._bb.load_events(project_id)
        outcomes = [
            e for e in events if e.event_type == EventType.ACTION_OUTCOME.value
        ]
        # group by (solver_id, primitive) where outcome is failure
        groups: dict[str, list] = {}
        for e in outcomes:
            p = e.payload
            if p.get("status", "") != "ok":
                key = f"{p.get('solver_id', '')}:{p.get('primitive', '')}"
                groups.setdefault(key, []).append(e)

        notes: list[ObservationNote] = []
        for key, group in groups.items():
            # at least 3 consecutive failures with same primitive
            if len(group) >= 3:
                parts = key.split(":")
                notes.append(ObservationNote(
                    kind="tool_misuse",
                    description=f"solver {parts[0]} failed with {parts[1]} {len(group)} times consecutively",
                    solver_id=parts[0],
                    evidence_refs=[e.event_id for e in group],
                ))
        return notes

    def generate_report(self, project_id: str) -> ObservationReport:
        all_notes: list[ObservationNote] = []

        all_notes.extend(self.detect_repeated_action(project_id))
        all_notes.extend(self.detect_low_novelty(project_id))
        all_notes.extend(self.detect_ignored_failure_boundary(project_id))
        all_notes.extend(self.detect_stagnation(project_id))
        all_notes.extend(self.detect_tool_misuse(project_id))

        # determine severity
        critical_kinds = {"ignored_boundary", "tool_misuse"}
        warning_kinds = {"repeated_action", "stagnation"}

        if any(n.kind in critical_kinds for n in all_notes):
            severity = "critical"
        elif any(n.kind in warning_kinds for n in all_notes):
            severity = "warning"
        else:
            severity = "info"

        # suggest actions
        suggested: list[str] = []
        for n in all_notes:
            if n.kind == "repeated_action":
                suggested.append(f"steer solver {n.solver_id} away from repeated action")
            elif n.kind == "low_novelty":
                suggested.append("inject new observations or switch exploration strategy")
            elif n.kind == "ignored_boundary":
                suggested.append("mark boundary as hard constraint and skip related approaches")
            elif n.kind == "stagnation":
                suggested.append("switch path or abandon project")
            elif n.kind == "tool_misuse":
                suggested.append(f"revoke tool {n.solver_id} or change approach")

        report = ObservationReport(
            project_id=project_id,
            observations=all_notes,
            severity=severity,
            suggested_actions=suggested,
        )

        # write advisory CHECKPOINT event (does not alter decisions)
        self._bb.append_event(
            project_id=project_id,
            event_type=EventType.CHECKPOINT.value,
            payload={
                "report_id": report.report_id,
                "severity": severity,
                "observation_count": len(all_notes),
                "observations": [
                    {"kind": n.kind, "description": n.description, "solver_id": n.solver_id}
                    for n in all_notes
                ],
                "suggested_actions": suggested,
            },
            source="observer",
        )

        return report