"""Phase G — MergeHub: deduplicate, conflict-detect, and arbitrate multi-Solver results.

L6: extended with KnowledgePacket validation, dedup, arbitration, and routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import (
    IdeaEntry,
    IdeaStatus,
    KnowledgePacket,
    KnowledgePacketType,
    MemoryEntry,
    MemoryKind,
    SolverStatus,
    _gen_id,
    _utc_now,
    to_dict,
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


@dataclass
class PacketRouteResult:
    global_packets: list[KnowledgePacket] = field(default_factory=list)
    targeted_packets: dict[str, list[KnowledgePacket]] = field(default_factory=dict)
    decisions: list[MergeDecision] = field(default_factory=list)


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

    # ── KnowledgePacket pipeline (L6) ────────────────────────────────────

    def validate_packet(self, packet: KnowledgePacket) -> bool:
        """Check packet has required fields and valid type."""
        return bool(packet.packet_id and packet.packet_type and packet.content)

    def dedup_packets(self, project_id: str, incoming: list[KnowledgePacket]) -> list[MergeDecision]:
        """Deduplicate incoming packets against existing accepted packets."""
        state = self._bb.rebuild_state(project_id)
        existing_packets = [p for p in state.packets if p.merge_status == "accepted"]
        decisions: list[MergeDecision] = []
        for pkt in incoming:
            for ex in existing_packets:
                if ex.packet_type == pkt.packet_type and ex.content == pkt.content:
                    if ex.confidence != pkt.confidence and ex.confidence > 0 and pkt.confidence > 0:
                        decisions.append(MergeDecision(
                            decision="conflict",
                            kept_entry_id=ex.packet_id,
                            discarded_ids=[pkt.packet_id],
                            reason=f"conflicting {pkt.packet_type.value}: '{pkt.content[:50]}' — different confidence {ex.confidence} vs {pkt.confidence}",
                        ))
                    else:
                        decisions.append(MergeDecision(
                            decision="discard",
                            kept_entry_id=ex.packet_id,
                            discarded_ids=[pkt.packet_id],
                            reason=f"duplicate {pkt.packet_type.value}: '{pkt.content[:50]}'",
                        ))
                    break
        return decisions

    def arbitrate_packets(self, project_id: str, packets: list[KnowledgePacket]) -> tuple[list[KnowledgePacket], list[MergeDecision]]:
        """Arbitrate conflicting/competing packets — keep highest confidence.

        Returns (accepted_packets, intra_batch_decisions).
        """
        groups: dict[str, list[KnowledgePacket]] = {}
        for p in packets:
            key = f"{p.packet_type.value}:{p.content}"
            groups.setdefault(key, []).append(p)
        result: list[KnowledgePacket] = []
        batch_decisions: list[MergeDecision] = []
        for key, group in groups.items():
            if len(group) == 1:
                group[0].merge_status = "accepted"
                result.append(group[0])
            else:
                group.sort(key=lambda p: p.confidence * (p.routing_priority / 100), reverse=True)
                best = group[0]
                best.merge_status = "accepted"
                best.merged_from_ids = [p.packet_id for p in group[1:]]
                result.append(best)
                for p in group[1:]:
                    p.merge_status = "discarded"
                    # Check if this intra-batch duplicate is a conflict (different confidence)
                    if best.confidence != p.confidence and best.confidence > 0 and p.confidence > 0:
                        batch_decisions.append(MergeDecision(
                            decision="conflict",
                            kept_entry_id=best.packet_id,
                            discarded_ids=[p.packet_id],
                            reason=f"conflicting {p.packet_type.value}: '{p.content[:50]}' — different confidence {best.confidence} vs {p.confidence}",
                        ))
                    else:
                        batch_decisions.append(MergeDecision(
                            decision="discard",
                            kept_entry_id=best.packet_id,
                            discarded_ids=[p.packet_id],
                            reason=f"duplicate {p.packet_type.value}: '{p.content[:50]}'",
                        ))
        return result, batch_decisions

    def route_packets(self, project_id: str, packets: list[KnowledgePacket]) -> PacketRouteResult:
        """Route accepted packets: global -> Blackboard, targeted -> Solver inbox."""
        global_packets: list[KnowledgePacket] = []
        targeted_packets: dict[str, list[KnowledgePacket]] = {}

        # Resolve profile-based recipients to actual solver_ids
        sessions = self._bb.list_sessions(project_id)

        for pkt in packets:
            if pkt.merge_status != "accepted":
                continue
            # Resolve recipients
            resolved: list[str] = []
            for r in pkt.suggested_recipients:
                if r.startswith("profile:"):
                    profile = r.split(":", 1)[1]
                    for s in sessions:
                        if s.profile == profile and s.status in (SolverStatus.RUNNING, SolverStatus.ASSIGNED):
                            resolved.append(s.solver_id)
                else:
                    resolved.append(r)

            if not resolved or "all" in resolved:
                global_packets.append(pkt)
                # Write global accepted packet to Blackboard
                self._bb.append_event(
                    project_id=project_id,
                    event_type=EventType.KNOWLEDGE_PACKET_MERGED.value,
                    payload={
                        "packet_id": pkt.packet_id,
                        "packet_type": pkt.packet_type.value,
                        "content": pkt.content,
                        "confidence": pkt.confidence,
                        "merge_status": "accepted",
                        "merged_from_ids": pkt.merged_from_ids,
                        "routing_priority": pkt.routing_priority,
                        "source_solver_id": pkt.source_solver_id,
                        "evidence_refs": pkt.evidence_refs,
                        "suggested_recipients": pkt.suggested_recipients,
                    },
                    source="merge_hub",
                )
                self._write_packet_to_blackboard(project_id, pkt)
            else:
                for solver_id in resolved:
                    targeted_packets.setdefault(solver_id, []).append(pkt)

        return PacketRouteResult(
            global_packets=global_packets,
            targeted_packets=targeted_packets,
            decisions=[],
        )

    def _write_packet_to_blackboard(self, project_id: str, pkt: KnowledgePacket) -> None:
        """Convert an accepted KnowledgePacket into appropriate Blackboard events."""
        if pkt.packet_type == KnowledgePacketType.FACT:
            self._bb.append_event(project_id, EventType.OBSERVATION.value, {
                "kind": MemoryKind.FACT.value,
                "summary": pkt.content,
                "confidence": pkt.confidence,
                "entry_id": pkt.packet_id,
                "evidence_refs": pkt.evidence_refs,
                "merged_from_ids": pkt.merged_from_ids,
            }, source="merge_hub")
        elif pkt.packet_type == KnowledgePacketType.CREDENTIAL:
            self._bb.append_event(project_id, EventType.OBSERVATION.value, {
                "kind": MemoryKind.CREDENTIAL.value,
                "summary": pkt.content,
                "confidence": pkt.confidence,
                "entry_id": pkt.packet_id,
            }, source="merge_hub")
        elif pkt.packet_type == KnowledgePacketType.ENDPOINT:
            self._bb.append_event(project_id, EventType.OBSERVATION.value, {
                "kind": MemoryKind.ENDPOINT.value,
                "summary": pkt.content,
                "confidence": pkt.confidence,
                "entry_id": pkt.packet_id,
            }, source="merge_hub")
        elif pkt.packet_type == KnowledgePacketType.CANDIDATE_FLAG:
            self._bb.append_event(project_id, EventType.CANDIDATE_FLAG.value, {
                "flag": pkt.content,
                "confidence": pkt.confidence,
                "format_match": True,
                "dedupe_key": pkt.packet_id,
                "source_chain": pkt.evidence_refs,
                "solver_id": pkt.source_solver_id,
                "routing_priority": pkt.routing_priority,
            }, source="merge_hub")
        elif pkt.packet_type == KnowledgePacketType.FAILURE_BOUNDARY:
            self._bb.append_event(project_id, EventType.ACTION_OUTCOME.value, {
                "status": "error",
                "error": pkt.content,
                "summary": pkt.content,
                "entry_id": pkt.packet_id,
                "kind": MemoryKind.FAILURE_BOUNDARY.value,
                "evidence_refs": pkt.evidence_refs,
                "solver_id": pkt.source_solver_id,
            }, source="merge_hub")

    def process_incoming_packets(self, project_id: str, incoming: list[KnowledgePacket]) -> PacketRouteResult:
        """Full pipeline: validate -> dedup -> arbitrate -> route."""
        valid = [p for p in incoming if self.validate_packet(p)]

        dedup_decisions = self.dedup_packets(project_id, valid)
        conflict_ids = {d.discarded_ids[0] for d in dedup_decisions if d.decision == "conflict" and d.discarded_ids}
        discard_ids = {d.discarded_ids[0] for d in dedup_decisions if d.decision == "discard" and d.discarded_ids}

        remaining = [p for p in valid if p.packet_id not in discard_ids]
        for p in remaining:
            if p.packet_id in conflict_ids:
                p.merge_status = "conflicted"

        # Write conflict events for visibility
        for d in dedup_decisions:
            if d.decision == "conflict":
                self._bb.append_event(project_id, EventType.KNOWLEDGE_PACKET_MERGED.value, {
                    "packet_id": d.discarded_ids[0] if d.discarded_ids else "",
                    "merge_status": "conflicted",
                    "kept_entry_id": d.kept_entry_id,
                    "reason": d.reason,
                }, source="merge_hub")

        arbitrated, batch_decisions = self.arbitrate_packets(project_id, remaining)
        result = self.route_packets(project_id, arbitrated)
        result.decisions = dedup_decisions + batch_decisions
        return result