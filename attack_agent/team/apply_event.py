"""Pure event application function — extracted from BlackboardService.

This module has no dependency on blackboard.py, breaking the circular import.
Both BlackboardService._apply_event and ReplayEngine use this function.
"""

from __future__ import annotations

from attack_agent.platform_models import EventType
from attack_agent.team.event_compat import classify_candidate_flag_event
from attack_agent.team.protocol import (
    IdeaEntry,
    IdeaStatus,
    KnowledgePacket,
    KnowledgePacketType,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    SolverStatus,
    TeamProject,
)


_STATUS_MAP = {
    "idea_proposed": IdeaStatus.PENDING,
    "idea_claimed": IdeaStatus.CLAIMED,
    "idea_verified": IdeaStatus.VERIFIED,
    "idea_failed": IdeaStatus.FAILED,
}


def _apply_idea_event(
    classified: str,
    payload: dict,
    event_id: str,
    project_id: str,
    timestamp: str,
    idea_index: dict[str, IdeaEntry],
) -> None:
    """Apply an idea lifecycle event to the idea_index."""
    idea_id = payload.get("idea_id", event_id)
    idea_status = _STATUS_MAP.get(classified, IdeaStatus.PENDING)
    idea = IdeaEntry(
        idea_id=idea_id,
        project_id=project_id,
        description=payload.get("flag", ""),
        status=idea_status,
        priority=payload.get("priority", 100),
        solver_id=payload.get("solver_id", ""),
        failure_boundary_refs=payload.get("failure_boundary_refs", []),
    )
    idea_index[idea_id] = idea


def apply_event_to_state(
    project_id: str,
    event_type: str,
    payload: dict,
    timestamp: str,
    event_id: str,
    state_project: TeamProject | None,
    state_facts: list[MemoryEntry],
    idea_index: dict[str, IdeaEntry],
    session_index: dict[str, SolverSession],
    packet_index: dict[str, KnowledgePacket] | None = None,
    source: str = "system",
) -> TeamProject | None:
    """Apply a single event to state components.

    Returns the updated project (or None if unchanged).
    Mutates state_facts, idea_index, session_index, packet_index in-place.
    """
    pidx = packet_index if packet_index is not None else {}
    p = payload
    et = event_type

    if et == EventType.PROJECT_UPSERTED.value:
        state_project = TeamProject(
            project_id=project_id,
            challenge_id=p.get("challenge_id", ""),
            status=p.get("status", "new"),
            created_at=timestamp,
            updated_at=timestamp,
        )
    elif et == EventType.OBSERVATION.value:
        kind_str = p.get("kind", MemoryKind.FACT.value)
        try:
            kind = MemoryKind(kind_str)
        except ValueError:
            # Primitive kind (e.g. "http-request") is not a MemoryKind — store as FACT
            # but preserve the original kind in content for searchability
            kind = MemoryKind.FACT
        raw_content = p.get("summary", p.get("text", ""))
        if kind == MemoryKind.FACT and kind_str not in MemoryKind._value2member_map_:
            content = f"{kind_str}: {raw_content}" if raw_content else kind_str
        else:
            content = raw_content
        entry_id = p.get("entry_id", event_id)
        state_facts.append(
            MemoryEntry(
                entry_id=entry_id,
                project_id=project_id,
                kind=kind,
                content=content,
                confidence=p.get("confidence", 0.0),
                created_at=timestamp,
            )
        )
    elif et == EventType.CANDIDATE_FLAG.value:
        classified = classify_candidate_flag_event(p, source)
        if classified == "candidate_flag":
            # Genuine extracted flag — store as fact only
            state_facts.append(
                MemoryEntry(
                    entry_id=event_id + "_flag",
                    project_id=project_id,
                    kind=MemoryKind.FACT,
                    content=f"candidate flag: {p.get('flag', '')}",
                    confidence=p.get("confidence", 0.5),
                    created_at=timestamp,
                )
            )
        else:
            # Legacy idea lifecycle event — route to idea handler
            _apply_idea_event(classified, p, event_id, project_id, timestamp, idea_index)
    elif et == EventType.IDEA_PROPOSED.value:
        _apply_idea_event("idea_proposed", p, event_id, project_id, timestamp, idea_index)
    elif et == EventType.IDEA_CLAIMED.value:
        _apply_idea_event("idea_claimed", p, event_id, project_id, timestamp, idea_index)
    elif et == EventType.IDEA_VERIFIED.value:
        _apply_idea_event("idea_verified", p, event_id, project_id, timestamp, idea_index)
    elif et == EventType.IDEA_FAILED.value:
        _apply_idea_event("idea_failed", p, event_id, project_id, timestamp, idea_index)
        # Also record failure_boundary memory entry for idea_failed (same as
        # IdeaService.mark_failed does with ACTION_OUTCOME)
        fb_refs = p.get("failure_boundary_refs", [])
        if fb_refs:
            state_facts.append(
                MemoryEntry(
                    entry_id=event_id + "_fb",
                    project_id=project_id,
                    kind=MemoryKind.FAILURE_BOUNDARY,
                    content=p.get("flag", ""),
                    confidence=0.0,
                    created_at=timestamp,
                )
            )
    elif et == EventType.WORKER_ASSIGNED.value:
        solver_id = p.get("solver_id", event_id)
        status_val = p.get("status", SolverStatus.ASSIGNED.value)
        session = SolverSession(
            solver_id=solver_id,
            project_id=project_id,
            profile=p.get("profile", "network"),
            status=SolverStatus(status_val),
            active_idea_id=p.get("active_idea_id", ""),
            local_memory_ids=p.get("local_memory_ids", []),
            budget_remaining=p.get("budget_remaining", 0.0),
            scratchpad_summary=p.get("scratchpad_summary", ""),
            recent_event_ids=p.get("recent_event_ids", []),
        )
        existing = session_index.get(solver_id)
        if existing is not None:
            session = SolverSession(
                solver_id=solver_id,
                project_id=project_id,
                profile=p.get("profile", existing.profile),
                status=SolverStatus(status_val),
                active_idea_id=p.get("active_idea_id", existing.active_idea_id),
                local_memory_ids=p.get("local_memory_ids", existing.local_memory_ids),
                budget_remaining=p.get("budget_remaining", existing.budget_remaining),
                scratchpad_summary=p.get("scratchpad_summary", existing.scratchpad_summary),
                recent_event_ids=p.get("recent_event_ids", existing.recent_event_ids),
            )
        session_index[solver_id] = session
    elif et == EventType.WORKER_HEARTBEAT.value:
        solver_id = p.get("solver_id", "")
        status_val = p.get("status", "")
        if solver_id and status_val:
            existing = session_index.get(solver_id)
            if existing is not None:
                session_index[solver_id] = SolverSession(
                    solver_id=solver_id,
                    project_id=existing.project_id,
                    profile=existing.profile,
                    status=SolverStatus(status_val),
                    active_idea_id=p.get("active_idea_id", existing.active_idea_id),
                    local_memory_ids=p.get("local_memory_ids", existing.local_memory_ids),
                    budget_remaining=p.get("budget_remaining", existing.budget_remaining),
                    scratchpad_summary=p.get("scratchpad_summary", existing.scratchpad_summary),
                    recent_event_ids=p.get("recent_event_ids", existing.recent_event_ids),
                )
    elif et == EventType.WORKER_TIMEOUT.value:
        solver_id = p.get("solver_id", "")
        status_val = p.get("status", SolverStatus.EXPIRED.value)
        if solver_id:
            existing = session_index.get(solver_id)
            if existing is not None:
                session_index[solver_id] = SolverSession(
                    solver_id=solver_id,
                    project_id=existing.project_id,
                    profile=existing.profile,
                    status=SolverStatus(status_val),
                    active_idea_id=existing.active_idea_id,
                    local_memory_ids=existing.local_memory_ids,
                    budget_remaining=existing.budget_remaining,
                    scratchpad_summary=existing.scratchpad_summary,
                    recent_event_ids=existing.recent_event_ids,
                )
    elif et == EventType.ACTION_OUTCOME.value:
        solver_id = p.get("solver_id", "")
        outcome_status = p.get("status", "")
        if solver_id and outcome_status:
            try:
                solver_status = SolverStatus(outcome_status)
            except ValueError:
                solver_status = None
            if solver_status is not None:
                existing = session_index.get(solver_id)
                if existing is not None:
                    session_index[solver_id] = SolverSession(
                        solver_id=solver_id,
                        project_id=existing.project_id,
                        profile=existing.profile,
                        status=solver_status,
                        active_idea_id=p.get("active_idea_id", existing.active_idea_id),
                        local_memory_ids=p.get("local_memory_ids", existing.local_memory_ids),
                        budget_remaining=p.get("budget_remaining", existing.budget_remaining),
                        scratchpad_summary=p.get("scratchpad_summary", existing.scratchpad_summary),
                        recent_event_ids=p.get("recent_event_ids", existing.recent_event_ids),
                    )
        raw_status = p.get("status", "")
        if raw_status != "ok":
            entry_id = p.get("entry_id", event_id)
            state_facts.append(
                MemoryEntry(
                    entry_id=entry_id,
                    project_id=project_id,
                    kind=MemoryKind.FAILURE_BOUNDARY,
                    content=p.get("error", p.get("summary", "action failed")),
                    confidence=0.0,
                    created_at=timestamp,
                )
            )
    elif et == EventType.SUBMISSION.value:
        if state_project is not None:
            state_project.status = p.get("result", "submitted")
            state_project.updated_at = timestamp
    elif et == EventType.SECURITY_VALIDATION.value:
        outcome = p.get("outcome", "unknown")
        if outcome in ("deny", "block", "critical"):
            state_facts.append(
                MemoryEntry(
                    entry_id=event_id,
                    project_id=project_id,
                    kind=MemoryKind.FAILURE_BOUNDARY,
                    content=f"security validation: {outcome} — {p.get('reason', '')}",
                    confidence=0.0,
                    created_at=timestamp,
                )
            )
    elif et == EventType.PROJECT_DONE.value:
        if state_project is not None:
            state_project.status = "done"
            state_project.updated_at = timestamp
    elif et == EventType.KNOWLEDGE_PACKET_PUBLISHED.value:
        pkt_id = p.get("packet_id", event_id)
        packet = KnowledgePacket(
            packet_id=pkt_id,
            project_id=project_id,
            packet_type=KnowledgePacketType(p.get("packet_type", "fact")),
            source_solver_id=p.get("source_solver_id", ""),
            content=p.get("content", ""),
            confidence=p.get("confidence", 0.0),
            evidence_refs=p.get("evidence_refs", []),
            routing_priority=p.get("routing_priority", 100),
            suggested_recipients=p.get("suggested_recipients", []),
            merge_status="pending",
            created_at=timestamp,
        )
        pidx[pkt_id] = packet
    elif et == EventType.KNOWLEDGE_PACKET_MERGED.value:
        pkt_id = p.get("packet_id", "")
        if pkt_id and pkt_id in pidx:
            existing = pidx[pkt_id]
            pidx[pkt_id] = KnowledgePacket(
                packet_id=pkt_id,
                project_id=existing.project_id,
                packet_type=existing.packet_type,
                source_solver_id=existing.source_solver_id,
                content=existing.content,
                confidence=p.get("confidence", existing.confidence),
                evidence_refs=existing.evidence_refs,
                routing_priority=p.get("routing_priority", existing.routing_priority),
                suggested_recipients=existing.suggested_recipients,
                merge_status=p.get("merge_status", "accepted"),
                merged_from_ids=p.get("merged_from_ids", existing.merged_from_ids),
                created_at=existing.created_at,
            )
        elif pkt_id:
            # Packet merged without prior published event — create from payload
            pidx[pkt_id] = KnowledgePacket(
                packet_id=pkt_id,
                project_id=project_id,
                packet_type=KnowledgePacketType(p.get("packet_type", "fact")),
                source_solver_id=p.get("source_solver_id", ""),
                content=p.get("content", ""),
                confidence=p.get("confidence", 0.0),
                evidence_refs=p.get("evidence_refs", []),
                routing_priority=p.get("routing_priority", 100),
                suggested_recipients=p.get("suggested_recipients", []),
                merge_status=p.get("merge_status", "accepted"),
                merged_from_ids=p.get("merged_from_ids", []),
                created_at=timestamp,
            )

    return state_project