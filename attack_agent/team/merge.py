"""Phase G — MergeHub: deduplicate, conflict-detect, and arbitrate multi-Solver results."""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import (
    IdeaEntry,
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
    _gen_id,
    _utc_now,
)
from attack_agent.platform_models import EventType


@dataclass
class MergeDecision:
    decision: str = "keep"          # keep / discard / conflict / merge
    kept_entry_id: str = ""
    discarded_ids: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class MergeResult:
    merged_count: int = 0
    conflict_count: int = 0
    decisions: list[MergeDecision] = field(default_factory=list)


@dataclass
class ArbitrationResult:
    selected_flag: str = ""
    selected_idea_id: str = ""
    confidence: float = 0.0
    solver_count: int = 0
    consensus: bool = False
    alternatives: list[dict] = field(default_factory=list)


class MergeHub:
    """Deduplicate and arbitrate facts, ideas, failure boundaries, and candidate flags."""

    def __init__(self, blackboard: BlackboardService) -> None:
        self._bb = blackboard

    # ── facts ──────────────────────────────────────────────────────────

    def merge_facts(self, project_id: str) -> MergeResult:
        state = self._bb.rebuild_state(project_id)
        facts = [f for f in state.facts if f.kind == MemoryKind.FACT]
        if not facts:
            return MergeResult()

        # group by kind:content
        groups: dict[str, list[MemoryEntry]] = {}
        for f in facts:
            key = f"{f.kind.value}:{f.content}"
            groups.setdefault(key, []).append(f)

        decisions: list[MergeDecision] = []
        merged_count = 0
        conflict_count = 0

        for key, entries in groups.items():
            if len(entries) == 1:
                continue
            # sort by confidence descending
            entries.sort(key=lambda e: e.confidence, reverse=True)
            best = entries[0]
            rest = entries[1:]

            # conflict: same content but different confidence sources
            has_conflict = best.confidence > 0 and any(
                e.confidence > 0 and e.confidence != best.confidence for e in rest
            )
            if has_conflict:
                decision_type = "conflict"
                conflict_count += 1
            else:
                decision_type = "discard"
                merged_count += len(rest)

            decisions.append(MergeDecision(
                decision=decision_type,
                kept_entry_id=best.entry_id,
                discarded_ids=[e.entry_id for e in rest],
                reason=f"duplicate {key}: keep highest confidence {best.confidence}"
                + (", conflicting sources" if has_conflict else ""),
            ))

            # write deduped OBSERVATION event
            self._bb.append_event(
                project_id=project_id,
                event_type=EventType.OBSERVATION.value,
                payload={
                    "summary": best.content,
                    "text": best.content,
                    "entry_id": best.entry_id,
                    "kind": best.kind.value,
                    "confidence": best.confidence,
                    "merged_from_ids": [e.entry_id for e in rest],
                    "dedup_count": len(rest),
                },
                source="merge_hub",
            )

        return MergeResult(merged_count=merged_count, conflict_count=conflict_count, decisions=decisions)

    # ── ideas ──────────────────────────────────────────────────────────

    def merge_ideas(self, project_id: str) -> MergeResult:
        ideas = self._bb.list_ideas(project_id)
        if not ideas:
            return MergeResult()

        # group by description
        groups: dict[str, list[IdeaEntry]] = {}
        for i in ideas:
            groups.setdefault(i.description, []).append(i)

        decisions: list[MergeDecision] = []
        merged_count = 0
        conflict_count = 0

        for desc, entries in groups.items():
            if len(entries) == 1:
                continue
            entries.sort(key=lambda e: e.priority, reverse=True)
            best = entries[0]
            rest = entries[1:]
            merged_count += len(rest)

            decisions.append(MergeDecision(
                decision="merge",
                kept_entry_id=best.idea_id,
                discarded_ids=[e.idea_id for e in rest],
                reason=f"duplicate idea '{desc}': keep highest priority {best.priority}",
            ))

            # write merged IDEA_PROPOSED event
            self._bb.append_event(
                project_id=project_id,
                event_type=EventType.IDEA_PROPOSED.value,
                payload={
                    "flag": best.description,
                    "idea_id": best.idea_id,
                    "priority": best.priority,
                    "status": IdeaStatus.PENDING.value,
                    "confidence": 0.5,
                    "merged_from_ids": [e.idea_id for e in rest],
                },
                source="merge_hub",
            )

        return MergeResult(merged_count=merged_count, conflict_count=conflict_count, decisions=decisions)

    # ── failure boundaries ─────────────────────────────────────────────

    def merge_failure_boundaries(self, project_id: str) -> MergeResult:
        from attack_agent.team.memory import MemoryService
        mem = MemoryService(self._bb)
        boundaries = mem.get_failure_boundaries(project_id)
        if not boundaries:
            return MergeResult()

        # group by description
        groups: dict[str, list[FailureBoundary]] = {}
        for b in boundaries:
            groups.setdefault(b.description, []).append(b)

        from attack_agent.team.protocol import FailureBoundary
        decisions: list[MergeDecision] = []
        merged_count = 0
        conflict_count = 0

        for desc, entries in groups.items():
            if len(entries) == 1:
                continue
            # keep the one with most evidence_refs
            entries.sort(key=lambda e: len(e.evidence_refs), reverse=True)
            best = entries[0]
            rest = entries[1:]
            merged_count += len(rest)

            decisions.append(MergeDecision(
                decision="discard",
                kept_entry_id=best.boundary_id,
                discarded_ids=[e.boundary_id for e in rest],
                reason=f"duplicate failure boundary '{desc}': keep most evidence",
            ))

            # write merged ACTION_OUTCOME event
            self._bb.append_event(
                project_id=project_id,
                event_type=EventType.ACTION_OUTCOME.value,
                payload={
                    "status": "error",
                    "error": best.description,
                    "summary": best.description,
                    "entry_id": best.boundary_id,
                    "kind": MemoryKind.FAILURE_BOUNDARY.value,
                    "merged_from_ids": [e.boundary_id for e in rest],
                    "evidence_refs": best.evidence_refs,
                },
                source="merge_hub",
            )

        return MergeResult(merged_count=merged_count, conflict_count=conflict_count, decisions=decisions)

    # ── flag arbitration ───────────────────────────────────────────────

    def arbitrate_flags(self, project_id: str) -> ArbitrationResult:
        ideas = self._bb.list_ideas(project_id)
        # candidate flags = PENDING ideas (typically from different solvers)
        candidates = [i for i in ideas if i.status == IdeaStatus.PENDING]

        if not candidates:
            return ArbitrationResult()

        # group by flag value (description)
        flag_groups: dict[str, list[IdeaEntry]] = {}
        for c in candidates:
            flag_groups.setdefault(c.description, []).append(c)

        # consensus boost: same flag from multiple solvers
        best_flag = ""
        best_idea_id = ""
        best_confidence = 0.0
        best_solver_count = 0
        is_consensus = False
        alternatives: list[dict] = []

        for flag_val, group in flag_groups.items():
            solver_count = len(group)
            # base confidence from individual ideas, boosted by consensus
            avg_confidence = sum(0.5 for _ in group) / len(group)  # default 0.5 per idea
            boosted = avg_confidence + 0.1 * (solver_count - 1)  # +0.1 per additional solver
            boosted = min(boosted, 1.0)

            if boosted > best_confidence or (boosted == best_confidence and solver_count > best_solver_count):
                # push previous best to alternatives
                if best_flag:
                    alternatives.append({
                        "flag": best_flag,
                        "idea_id": best_idea_id,
                        "confidence": best_confidence,
                        "solver_count": best_solver_count,
                    })
                best_flag = flag_val
                best_idea_id = group[0].idea_id
                best_confidence = boosted
                best_solver_count = solver_count
                is_consensus = solver_count > 1
            else:
                alternatives.append({
                    "flag": flag_val,
                    "idea_id": group[0].idea_id,
                    "confidence": boosted,
                    "solver_count": solver_count,
                })

        # write arbitration result as IDEA_PROPOSED event
        if best_flag:
            self._bb.append_event(
                project_id=project_id,
                event_type=EventType.IDEA_PROPOSED.value,
                payload={
                    "flag": best_flag,
                    "idea_id": best_idea_id,
                    "status": IdeaStatus.PENDING.value,
                    "confidence": best_confidence,
                    "solver_count": best_solver_count,
                    "consensus": is_consensus,
                    "solver_id": "merged",
                    "arbitration": True,
                },
                source="merge_hub",
            )

        return ArbitrationResult(
            selected_flag=best_flag,
            selected_idea_id=best_idea_id,
            confidence=best_confidence,
            solver_count=best_solver_count,
            consensus=is_consensus,
            alternatives=alternatives,
        )