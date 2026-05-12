"""IdeaService — Phase D.

Attack route / hypothesis management over Blackboard event journal.
Ideas represent candidate attack strategies that solvers can claim,
test, verify, or fail.
"""

from __future__ import annotations

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import (
    IdeaEntry,
    IdeaStatus,
    to_dict,
)


class IdeaService:
    """Propose, claim, and track attack ideas via Blackboard events."""

    def __init__(self, blackboard: BlackboardService) -> None:
        self.blackboard = blackboard

    def propose(
        self, project_id: str, description: str, priority: int = 100
    ) -> IdeaEntry:
        """Create a new IdeaEntry and write it to Blackboard."""
        idea = IdeaEntry(
            project_id=project_id,
            description=description,
            status=IdeaStatus.PENDING,
            priority=priority,
        )
        self.blackboard.append_event(
            project_id,
            EventType.IDEA_PROPOSED.value,
            {
                "flag": description,
                "idea_id": idea.idea_id,
                "priority": priority,
                "confidence": 0.5,
                "status": IdeaStatus.PENDING.value,
            },
            source="idea_service",
        )
        return idea

    def claim(
        self, project_id: str, idea_id: str, solver_id: str
    ) -> IdeaEntry | None:
        """Mark an idea as claimed by a solver.

        Writes an idea_claimed event to record the claim.
        Returns the updated IdeaEntry, or None if idea not found.
        """
        ideas = self.blackboard.list_ideas(project_id)
        target = None
        for idea in ideas:
            if idea.idea_id == idea_id and idea.status in (
                IdeaStatus.PENDING,
                IdeaStatus.FAILED,
                IdeaStatus.shelved,
            ):
                target = idea
                break
        if target is None:
            return None

        target.status = IdeaStatus.CLAIMED
        target.solver_id = solver_id
        self.blackboard.append_event(
            project_id,
            EventType.IDEA_CLAIMED.value,
            {
                "flag": target.description,
                "idea_id": target.idea_id,
                "priority": target.priority,
                "confidence": 0.5,
                "status": IdeaStatus.CLAIMED.value,
                "solver_id": solver_id,
            },
            source="idea_service",
        )
        return target

    def mark_verified(
        self, project_id: str, idea_id: str
    ) -> IdeaEntry | None:
        """Mark an idea as verified (flag validation succeeded)."""
        ideas = self.blackboard.list_ideas(project_id)
        target = None
        for idea in ideas:
            if idea.idea_id == idea_id:
                target = idea
                break
        if target is None:
            return None

        target.status = IdeaStatus.VERIFIED
        self.blackboard.append_event(
            project_id,
            EventType.IDEA_VERIFIED.value,
            {
                "flag": target.description,
                "idea_id": target.idea_id,
                "priority": target.priority,
                "confidence": 1.0,
                "status": IdeaStatus.VERIFIED.value,
            },
            source="idea_service",
        )
        return target

    def mark_failed(
        self,
        project_id: str,
        idea_id: str,
        failure_boundary_ids: list[str],
    ) -> IdeaEntry | None:
        """Mark an idea as failed and associate FailureBoundary refs."""
        ideas = self.blackboard.list_ideas(project_id)
        target = None
        for idea in ideas:
            if idea.idea_id == idea_id:
                target = idea
                break
        if target is None:
            return None

        target.status = IdeaStatus.FAILED
        target.failure_boundary_refs = failure_boundary_ids
        self.blackboard.append_event(
            project_id,
            EventType.IDEA_FAILED.value,
            {
                "flag": target.description,
                "idea_id": target.idea_id,
                "priority": target.priority,
                "confidence": 0.0,
                "status": IdeaStatus.FAILED.value,
                "failure_boundary_refs": failure_boundary_ids,
            },
            source="idea_service",
        )
        # also record a failure_boundary memory entry
        self.blackboard.append_event(
            project_id,
            EventType.ACTION_OUTCOME.value,
            {
                "status": "error",
                "error": f"idea {idea_id} failed",
                "summary": f"idea {idea_id} failed: {target.description}",
                "boundary_ids": failure_boundary_ids,
            },
            source="idea_service",
        )
        return target

    def list_available(
        self, project_id: str, solver_id: str | None = None
    ) -> list[IdeaEntry]:
        """List unclaimed ideas, or ideas claimed by a specific solver."""
        ideas = self.blackboard.list_ideas(project_id)
        if solver_id is None:
            return [
                i for i in ideas
                if i.status in (IdeaStatus.PENDING, IdeaStatus.shelved)
            ]
        return [
            i for i in ideas
            if i.status == IdeaStatus.PENDING
            or (i.status == IdeaStatus.CLAIMED and i.solver_id == solver_id)
        ]

    def get_best_unclaimed(
        self, project_id: str
    ) -> IdeaEntry | None:
        """Return the highest-priority unclaimed idea."""
        available = self.list_available(project_id)
        if not available:
            return None
        return max(available, key=lambda i: i.priority)