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
from attack_agent.team.event_compat import is_genuine_candidate_flag
from attack_agent.team.manager import TeamManager
from attack_agent.platform_models import EventType
from attack_agent.team.observer import ObservationReport
from attack_agent.team.protocol import (
    FailureBoundary,
    IdeaEntry,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    TeamProject,
    to_dict,
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
    active_ideas: list[IdeaEntry] = field(default_factory=list)
    failure_boundaries: list[FailureBoundary] = field(default_factory=list)
    verification_state: dict[str, str] = field(default_factory=dict)
    budget_remaining: float = 0.0
    recent_human_decisions: list[dict] = field(default_factory=list)
    observer_reports: list[ObservationReport] = field(default_factory=list)
    high_value_facts: list[MemoryEntry] = field(default_factory=list)
    high_value_credentials: list[MemoryEntry] = field(default_factory=list)


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
        review_gate=None,
    ) -> None:
        self.memory_service = memory_service
        self.idea_service = idea_service
        self.manager = manager or TeamManager()
        self.review_gate = review_gate

    def compile_manager_context(
        self, project_id: str, blackboard: BlackboardService
    ) -> ManagerContext:
        """Compile Manager global context from Blackboard state + events."""
        state = blackboard.rebuild_state(project_id)
        events = blackboard.load_events(project_id)

        ctx = ManagerContext()
        ctx.project_state = state.project
        ctx.solver_states = state.sessions

        # candidate flags = genuine extracted flags from candidate_flag events
        genuine_flag_entries = []
        for ev in events:
            if ev.event_type == EventType.CANDIDATE_FLAG.value and is_genuine_candidate_flag(ev.event_type, ev.payload, ev.source):
                genuine_flag_entries.append(IdeaEntry(
                    idea_id=ev.event_id,
                    project_id=project_id,
                    description=ev.payload.get("flag", ""),
                    priority=int(ev.payload.get("confidence", 0.5) * 100),
                ))
        ctx.candidate_flags = genuine_flag_entries

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

        # -- L2: pending reviews from HumanReviewGate --
        if self.review_gate is not None:
            pending = self.review_gate.list_pending_reviews(project_id, blackboard)
            ctx.pending_reviews = [to_dict(r) for r in pending]

        # -- L2: active ideas from Blackboard --
        ctx.active_ideas = blackboard.list_ideas(project_id)

        # -- L2: failure boundaries --
        if self.memory_service is not None:
            ctx.failure_boundaries = self.memory_service.get_failure_boundaries(project_id)
        else:
            # fallback: scan state.facts for FAILURE_BOUNDARY kind
            for f in state.facts:
                if f.kind == MemoryKind.FAILURE_BOUNDARY:
                    ctx.failure_boundaries.append(FailureBoundary(
                        boundary_id=f.entry_id,
                        project_id=f.project_id,
                        description=f.content,
                        evidence_refs=f.evidence_refs,
                    ))

        # -- L2: verification state from SECURITY_VALIDATION events --
        for ev in events:
            if ev.event_type == EventType.SECURITY_VALIDATION.value:
                p = ev.payload
                if p.get("check") == "evidence_chain":
                    idea_id = p.get("candidate_flag_id", "")
                    outcome = p.get("outcome", "")
                    if idea_id and outcome in ("pass", "fail", "warning"):
                        ctx.verification_state[idea_id] = outcome

        # -- L2: budget remaining --
        ctx.budget_remaining = sum(
            s.budget_remaining for s in state.sessions
        )

        # -- L2: recent human decisions --
        for ev in events:
            if ev.event_type == EventType.SECURITY_VALIDATION.value:
                outcome = ev.payload.get("outcome", "")
                if outcome in ("review_approved", "review_rejected", "review_modified"):
                    ctx.recent_human_decisions.append(ev.payload)

        # -- L2: observer reports from CHECKPOINT events --
        for ev in events:
            if ev.event_type == EventType.CHECKPOINT.value:
                p = ev.payload
                if ev.source == "observer" or p.get("severity"):
                    ctx.observer_reports.append(ObservationReport(
                        report_id=ev.event_id,
                        project_id=project_id,
                        observations=[],
                        severity=p.get("severity", "info"),
                        suggested_actions=p.get("suggested_actions", []),
                    ))

        # -- L2: high-value facts (confidence >= 0.7, kind FACT) --
        for f in state.facts:
            if f.kind == MemoryKind.FACT and f.confidence >= 0.7:
                ctx.high_value_facts.append(f)

        # -- L2: high-value credentials --
        for f in state.facts:
            if f.kind == MemoryKind.CREDENTIAL:
                ctx.high_value_credentials.append(f)

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