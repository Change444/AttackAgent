"""ContextCompiler + ContextPack — Phase D.

Compiles ManagerContext (global态势) and SolverContextPack (局部上下文)
from Blackboard materialized state + MemoryService + IdeaService.

First version translates from existing data structures:
- ManagerContext.project_state ← Blackboard.rebuild_state().project
- ManagerContext.solver_states ← Blackboard.list_sessions()
- ManagerContext.candidate_flags ← Blackboard.list_ideas() (PENDING)
- ManagerContext.stagnation_points ← _compute_stagnation()
- SolverContextPack.local_memory ← MemoryService query recent facts
- SolverContextPack.failure_boundaries ← MemoryService.get_failure_boundaries
- SolverContextPack.active_idea ← IdeaService.get_best_unclaimed
- SolverContextPack.global_facts ← MemoryService query high-confidence facts
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.team.blackboard import BlackboardEvent, BlackboardService
from attack_agent.team.manager import TeamManager
from attack_agent.team.protocol import (
    FailureBoundary,
    IdeaEntry,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    TeamProject,
)


# ---------------------------------------------------------------------------
# ContextPack dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ManagerContext:
    """Global situation awareness for the Manager."""

    project_state: TeamProject | None = None
    solver_states: list[SolverSession] = field(default_factory=list)
    pending_reviews: list[dict] = field(default_factory=list)
    candidate_flags: list[IdeaEntry] = field(default_factory=list)
    stagnation_points: list[str] = field(default_factory=list)
    resource_status: dict = field(default_factory=dict)


@dataclass
class SolverContextPack:
    """Local context for a Solver session."""

    profile: str = ""
    active_idea: IdeaEntry | None = None
    local_memory: list[MemoryEntry] = field(default_factory=list)
    global_facts: list[MemoryEntry] = field(default_factory=list)
    inbox: list[dict] = field(default_factory=list)
    failure_boundaries: list[FailureBoundary] = field(default_factory=list)
    solver_id: str = ""
    project_id: str = ""


# ---------------------------------------------------------------------------
# ContextCompiler
# ---------------------------------------------------------------------------

class ContextCompiler:
    """Compiles context packs from Blackboard + services."""

    def __init__(
        self,
        memory_service=None,
        idea_service=None,
        manager: TeamManager | None = None,
    ) -> None:
        self.memory_service = memory_service
        self.idea_service = idea_service
        self.manager = manager or TeamManager()

    def compile_manager_context(
        self, project_id: str, blackboard: BlackboardService
    ) -> ManagerContext:
        """Compile Manager global context from Blackboard state + events."""
        state = blackboard.rebuild_state(project_id)
        events = blackboard.load_events(project_id)

        ctx = ManagerContext()
        ctx.project_state = state.project

        ctx.solver_states = state.sessions

        # candidate flags = pending ideas
        ctx.candidate_flags = [
            i for i in state.ideas
            if i.status.value == "pending"
        ]

        # stagnation points from manager stagnation computation
        stagnation = self.manager._compute_stagnation(project_id, events)
        if stagnation.stagnation_counter > 0:
            ctx.stagnation_points.append(
                f"stagnation_counter={stagnation.stagnation_counter}"
            )
        if stagnation.dead_end_count > 0:
            ctx.stagnation_points.append(
                f"dead_ends={stagnation.dead_end_count}"
            )
        if stagnation.low_novelty:
            ctx.stagnation_points.append("low_novelty")

        ctx.resource_status = {
            "idea_count": len(state.ideas),
            "fact_count": len(state.facts),
            "session_count": len(state.sessions),
        }

        return ctx

    def compile_solver_context(
        self,
        project_id: str,
        solver_id: str,
        blackboard: BlackboardService,
    ) -> SolverContextPack:
        """Compile Solver local context from Blackboard + services."""
        ctx = SolverContextPack(
            solver_id=solver_id,
            project_id=project_id,
        )

        # find the solver's profile
        sessions = blackboard.list_sessions(project_id)
        for s in sessions:
            if s.solver_id == solver_id:
                ctx.profile = s.profile
                break

        # local memory: recent facts
        if self.memory_service is not None:
            ctx.local_memory = self.memory_service.query_by_kind(
                project_id, MemoryKind.FACT, limit=5,
            )
            ctx.failure_boundaries = self.memory_service.get_failure_boundaries(
                project_id
            )
            ctx.global_facts = self.memory_service.query_by_confidence(
                project_id, 0.7, limit=10,
            )

        # active idea: best unclaimed
        if self.idea_service is not None:
            ctx.active_idea = self.idea_service.get_best_unclaimed(
                project_id
            )

        return ctx