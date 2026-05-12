"""Pure event application function — extracted from BlackboardService.

This module has no dependency on blackboard.py, breaking the circular import.
Both BlackboardService._apply_event and ReplayEngine use this function.
"""

from __future__ import annotations

from attack_agent.platform_models import EventType
from attack_agent.team.protocol import (
    IdeaEntry,
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    SolverStatus,
    TeamProject,
)


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
) -> TeamProject | None:
    """Apply a single event to state components.

    Returns the updated project (or None if unchanged).
    Mutates state_facts, idea_index, session_index in-place.
    """
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
        flag_text = p.get("flag", "")
        idea_id = p.get("idea_id", event_id)
        idea_status = IdeaStatus(p.get("status", IdeaStatus.PENDING.value))
        solver_id = p.get("solver_id", "")
        idea = IdeaEntry(
            idea_id=idea_id,
            project_id=project_id,
            description=flag_text,
            status=idea_status,
            priority=p.get("priority", 100),
            solver_id=solver_id,
        )
        idea_index[idea_id] = idea
        state_facts.append(
            MemoryEntry(
                entry_id=event_id + "_flag",
                project_id=project_id,
                kind=MemoryKind.FACT,
                content=f"candidate flag: {flag_text}",
                confidence=p.get("confidence", 0.5),
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
            budget_remaining=p.get("budget_remaining", 0.0),
        )
        existing = session_index.get(solver_id)
        if existing is not None:
            session = SolverSession(
                solver_id=solver_id,
                project_id=project_id,
                profile=p.get("profile", existing.profile),
                status=SolverStatus(status_val),
                active_idea_id=existing.active_idea_id,
                local_memory_ids=existing.local_memory_ids,
                budget_remaining=p.get("budget_remaining", existing.budget_remaining),
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
                    active_idea_id=existing.active_idea_id,
                    local_memory_ids=existing.local_memory_ids,
                    budget_remaining=existing.budget_remaining,
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
                        active_idea_id=existing.active_idea_id,
                        local_memory_ids=existing.local_memory_ids,
                        budget_remaining=existing.budget_remaining,
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

    return state_project