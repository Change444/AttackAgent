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
from attack_agent.team.observer import ObservationNote, ObservationReport
from attack_agent.platform_models import EventType
from attack_agent.team.protocol import (
    ActionType,
    FailureBoundary,
    IdeaEntry,
    InterventionLevel,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    TeamProject,
    to_dict,
)


# ---------------------------------------------------------------------------
# Context pack limits (L4 bounding)
# ---------------------------------------------------------------------------

SOLVER_CONTEXT_LIMITS = {
    "max_local_memory": 5,
    "max_global_facts": 10,
    "max_credentials": 5,
    "max_endpoints": 5,
    "max_failure_boundaries": 10,
    "max_recent_tool_outcomes": 3,
    "max_recent_event_ids": 20,
    "max_scratchpad_summary_chars": 500,
    "max_inbox_items": 10,
}


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
    """Local context for a Solver session.

    L4: expanded to include credentials, endpoints, recent tool outcomes,
    budget constraints, scratchpad summary, and recent event IDs.
    All lists are bounded by SOLVER_CONTEXT_LIMITS.
    """

    profile: str = ""
    active_idea: IdeaEntry | None = None
    local_memory: list[MemoryEntry] = field(default_factory=list)
    global_facts: list[MemoryEntry] = field(default_factory=list)
    inbox: list[dict] = field(default_factory=list)
    failure_boundaries: list[FailureBoundary] = field(default_factory=list)
    solver_id: str = ""
    project_id: str = ""
    credentials: list[MemoryEntry] = field(default_factory=list)
    endpoints: list[MemoryEntry] = field(default_factory=list)
    recent_tool_outcomes: list[dict] = field(default_factory=list)
    budget_constraints: dict = field(default_factory=dict)
    scratchpad_summary: str = ""
    recent_event_ids: list[str] = field(default_factory=list)

    def is_boundary_repetition(self, proposed_action: str) -> bool:
        """Check if a proposed action matches a known failure boundary.

        Uses word overlap: if significant words from the proposed action
        appear in a failure boundary description (or vice versa),
        it is considered a repetition.
        """
        action_words = set(w for w in proposed_action.lower().split() if len(w) > 2)
        for fb in self.failure_boundaries:
            boundary_words = set(w for w in fb.description.lower().split() if len(w) > 2)
            overlap = action_words & boundary_words
            # Repetition if at least half of the meaningful words overlap
            if overlap and len(overlap) >= max(1, len(action_words) // 2):
                return True
        return False


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
                    # L11: read candidate_flag_id first, fallback to idea_id
                    idea_id = p.get("candidate_flag_id", "") or p.get("idea_id", "")
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

        # -- L7: observer reports from OBSERVER_REPORT events --
        for ev in events:
            if ev.event_type == EventType.OBSERVER_REPORT.value:
                p = ev.payload
                notes = []
                for obs_data in p.get("observations", []):
                    notes.append(ObservationNote(
                        kind=obs_data.get("kind", ""),
                        description=obs_data.get("description", ""),
                        solver_id=obs_data.get("solver_id", ""),
                        evidence_refs=obs_data.get("evidence_refs", []),
                    ))
                level_str = p.get("intervention_level", "observe")
                try:
                    level = InterventionLevel(level_str)
                except ValueError:
                    level = InterventionLevel.OBSERVE
                action_str = p.get("recommended_action", "")
                try:
                    rec_action = ActionType(action_str) if action_str else None
                except ValueError:
                    rec_action = None
                ctx.observer_reports.append(ObservationReport(
                    report_id=p.get("report_id", ev.event_id),
                    project_id=project_id,
                    observations=notes,
                    severity=p.get("severity", "info"),
                    suggested_actions=p.get("suggested_actions", []),
                    intervention_level=level,
                    recommended_action=rec_action,
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
        """Compile Solver local context from Blackboard + services.

        L4: populates credentials, endpoints, recent_tool_outcomes,
        budget_constraints, scratchpad_summary, recent_event_ids.
        All lists bounded by SOLVER_CONTEXT_LIMITS.
        """
        ctx = SolverContextPack(
            solver_id=solver_id,
            project_id=project_id,
        )
        limits = SOLVER_CONTEXT_LIMITS

        # find the solver's profile and session data
        sessions = blackboard.list_sessions(project_id)
        solver_session = None
        for s in sessions:
            if s.solver_id == solver_id:
                ctx.profile = s.profile
                solver_session = s
                break

        # local memory: recent facts
        if self.memory_service is not None:
            ctx.local_memory = self.memory_service.query_by_kind(
                project_id, MemoryKind.FACT, limit=limits["max_local_memory"],
            )
            ctx.failure_boundaries = self.memory_service.get_failure_boundaries(
                project_id
            )
            ctx.global_facts = self.memory_service.query_by_confidence(
                project_id, 0.7, limit=limits["max_global_facts"],
            )

            # -- L4: credentials (deduped) --
            ctx.credentials = self.memory_service.get_deduped_entries(
                project_id, MemoryKind.CREDENTIAL, limit=limits["max_credentials"],
            )

            # -- L4: endpoints (deduped) --
            ctx.endpoints = self.memory_service.get_deduped_entries(
                project_id, MemoryKind.ENDPOINT, limit=limits["max_endpoints"],
            )

        # Bound failure_boundaries
        ctx.failure_boundaries = ctx.failure_boundaries[:limits["max_failure_boundaries"]]
        ctx.global_facts = ctx.global_facts[:limits["max_global_facts"]]

        # active idea: best unclaimed
        if self.idea_service is not None:
            ctx.active_idea = self.idea_service.get_best_unclaimed(
                project_id
            )

        # -- L4: recent tool outcomes (last N ACTION_OUTCOME events) --
        events = blackboard.load_events(project_id)
        tool_outcomes = []
        for ev in reversed(events):
            if ev.event_type == EventType.ACTION_OUTCOME.value:
                tool_outcomes.append({
                    "status": ev.payload.get("status", ""),
                    "primitive": ev.payload.get("primitive_name", ""),
                    "cost": ev.payload.get("cost", 0.0),
                    "novelty": ev.payload.get("novelty", 0.0),
                    "failure_reason": ev.payload.get("failure_reason", ""),
                })
                if len(tool_outcomes) >= limits["max_recent_tool_outcomes"]:
                    break
        ctx.recent_tool_outcomes = tool_outcomes

        # -- L4: budget constraints and session fields from SolverSession --
        if solver_session is not None:
            ctx.budget_constraints = {
                "budget_remaining": solver_session.budget_remaining,
            }
            ctx.scratchpad_summary = solver_session.scratchpad_summary
            ctx.recent_event_ids = solver_session.recent_event_ids[-limits["max_recent_event_ids"]:]

        # -- L6: inbox from routed/targeted KnowledgePackets --
        inbox_items: list[dict] = []
        for ev in reversed(events):
            if ev.event_type == EventType.KNOWLEDGE_PACKET_MERGED.value:
                pkt = ev.payload
                recipients = pkt.get("suggested_recipients", [])
                if ("all" in recipients) or (solver_id in recipients):
                    inbox_items.append(pkt)
                    if len(inbox_items) >= limits["max_inbox_items"]:
                        break
        ctx.inbox = inbox_items

        return ctx