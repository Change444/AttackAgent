"""TeamRuntime — Phase H main entry point.

Wires all Phase A~G components into a single orchestrator.
CLI and API consume this class exclusively.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.team.blackboard import BlackboardService, MaterializedState
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.context import ContextCompiler
from attack_agent.team.ideas import IdeaService
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.memory import MemoryService
from attack_agent.team.merge import MergeHub
from attack_agent.team.observer import ObservationReport, Observer
from attack_agent.team.policy import PolicyHarness
from attack_agent.team.protocol import (
    ActionType,
    HumanDecision,
    HumanDecisionChoice,
    IdeaEntry,
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
    PolicyDecision,
    PolicyOutcome,
    ReviewRequest,
    SolverSession,
    StrategyAction,
    TeamProject,
    to_dict,
)
from attack_agent.team.review import HumanReviewGate
from attack_agent.team.scheduler import SchedulerConfig, SyncScheduler
from attack_agent.team.solver import SolverSessionConfig, SolverSessionManager
from attack_agent.team.submission import SubmissionConfig, SubmissionVerifier, VerificationResult


@dataclass
class TeamRuntimeConfig:
    blackboard_db_path: str = "data/blackboard.db"
    max_project_solvers: int = 1
    session_timeout_seconds: int = 300
    budget_per_session: float = 20.0
    max_submissions: int = 3
    flag_pattern: str = r"flag\{[^}]+\}"
    max_cycles: int = 12
    stagnation_threshold: int = 3
    confidence_threshold: float = 0.6


@dataclass
class ProjectStatusReport:
    project_id: str = ""
    challenge_id: str = ""
    status: str = ""
    solver_count: int = 0
    idea_count: int = 0
    fact_count: int = 0
    pending_review_count: int = 0
    candidate_flags: list[str] = field(default_factory=list)
    last_observation_severity: str = ""


@dataclass
class SubmissionResult:
    status: str = ""  # submitted / needs_review / rejected / failed
    verification_result: VerificationResult | None = None
    policy_decision: PolicyOutcome | None = None
    review_created: bool = False
    flag_value: str = ""


class TeamRuntime:
    """Unified entry point wiring all Phase A~G components."""

    def __init__(self, config: TeamRuntimeConfig | None = None) -> None:
        self.config = config or TeamRuntimeConfig()

        bb_config = BlackboardConfig(db_path=self.config.blackboard_db_path)
        self.blackboard = BlackboardService(bb_config)

        manager_config = ManagerConfig(
            stagnation_threshold=self.config.stagnation_threshold,
            confidence_threshold=self.config.confidence_threshold,
            max_cycles=self.config.max_cycles,
        )
        self.manager = TeamManager(manager_config)

        scheduler_config = SchedulerConfig(
            max_cycles=self.config.max_cycles,
            max_project_solvers=self.config.max_project_solvers,
        )
        self.scheduler = SyncScheduler(scheduler_config)

        solver_config = SolverSessionConfig(
            max_project_solvers=self.config.max_project_solvers,
            session_timeout_seconds=self.config.session_timeout_seconds,
            budget_per_session=self.config.budget_per_session,
        )
        self.solver_manager = SolverSessionManager(solver_config)

        self.memory = MemoryService(self.blackboard)
        self.ideas = IdeaService(self.blackboard)
        self.context = ContextCompiler(self.memory, self.ideas, self.manager)
        self.policy = PolicyHarness()
        self.review_gate = HumanReviewGate()
        self.merge = MergeHub(self.blackboard)
        self.verifier = SubmissionVerifier(self.blackboard)
        self.observer = Observer(self.blackboard)

    # -- project lifecycle --

    def run_project(self, challenge_id: str) -> TeamProject:
        """Admit a project and run it until done/abandoned."""
        project = TeamProject(challenge_id=challenge_id, status="new")
        self.manager.admit_project(project)
        self.blackboard.append_event(
            project_id=project.project_id,
            event_type="project_upserted",
            payload=to_dict(project),
            source="team_runtime",
        )
        return self.scheduler.run_project(
            project.project_id, self.manager, self.blackboard
        )

    def run_all(self, challenge_ids: list[str]) -> dict[str, TeamProject]:
        """Run multiple projects sequentially."""
        projects = {}
        for cid in challenge_ids:
            proj = self.run_project(cid)
            projects[cid] = proj
        return projects

    # -- introspection --

    def get_status(self, project_id: str) -> ProjectStatusReport | None:
        """Build a status report from Blackboard materialized state.

        Returns None if the project has no events in Blackboard.
        """
        state: MaterializedState = self.blackboard.rebuild_state(project_id)
        if state.project is None:
            return None

        project = state.project

        facts = state.facts
        ideas = state.ideas
        sessions = state.sessions

        pending_reviews = self.review_gate.list_pending_reviews(
            project_id, self.blackboard
        )
        candidate_flags = [
            i.description
            for i in ideas
            if i.status == IdeaStatus.PENDING and "flag" in i.description.lower()
        ]

        # get last observation severity from checkpoint events
        events = self.blackboard.load_events(project_id)
        last_severity = ""
        for ev in reversed(events):
            if ev.event_type == "checkpoint":
                last_severity = ev.payload.get("severity", "")
                break

        return ProjectStatusReport(
            project_id=project.project_id,
            challenge_id=project.challenge_id,
            status=project.status,
            solver_count=len(sessions),
            idea_count=len(ideas),
            fact_count=len(facts),
            pending_review_count=len(pending_reviews),
            candidate_flags=candidate_flags,
            last_observation_severity=last_severity,
        )

    def list_projects(self) -> list[ProjectStatusReport]:
        """List all known projects from Blackboard."""
        db = self.blackboard._db
        if db is None:
            return []
        cursor = db.cursor()
        cursor.execute(
            "SELECT DISTINCT project_id FROM events ORDER BY project_id"
        )
        rows = cursor.fetchall()
        reports = [self.get_status(row[0]) for row in rows]
        return [r for r in reports if r is not None]

    # -- submission --

    def submit_flag(
        self, project_id: str, flag_value: str, idea_id: str = ""
    ) -> SubmissionResult:
        """Verify → policy → review → submit pipeline."""
        submit_config = SubmissionConfig(
            max_submissions=self.config.max_submissions,
            flag_pattern=self.config.flag_pattern,
        )
        verification = self.verifier.run_all_passes(
            project_id, flag_value, idea_id, submit_config
        )

        if verification.status == "failed":
            return SubmissionResult(
                status="failed",
                verification_result=verification,
                flag_value=flag_value,
            )

        action = StrategyAction(
            action_type=ActionType.SUBMIT_FLAG,
            project_id=project_id,
            target_idea_id=idea_id,
            risk_level="medium",
            reason=f"submit flag: {flag_value}",
        )
        policy_decision: PolicyDecision = self.policy.validate_action(
            action, project_id, self.blackboard
        )

        review_created = False
        if policy_decision.decision == PolicyOutcome.NEEDS_REVIEW:
            request = ReviewRequest(
                project_id=project_id,
                action_type="submit_flag",
                risk_level="medium",
                title=f"Submit flag for {project_id}",
                description=f"Flag value: {flag_value}",
                proposed_action=f"submit {flag_value}",
            )
            self.review_gate.create_review(request, self.blackboard)
            review_created = True
            return SubmissionResult(
                status="needs_review",
                verification_result=verification,
                policy_decision=policy_decision.decision,
                review_created=review_created,
                flag_value=flag_value,
            )

        if policy_decision.decision == PolicyOutcome.DENY:
            return SubmissionResult(
                status="rejected",
                verification_result=verification,
                policy_decision=policy_decision.decision,
                flag_value=flag_value,
            )

        # allowed — record submission
        self.blackboard.append_event(
            project_id=project_id,
            event_type="submission",
            payload={"flag": flag_value, "idea_id": idea_id, "outcome": "submitted"},
            source="team_runtime",
        )
        return SubmissionResult(
            status="submitted",
            verification_result=verification,
            policy_decision=policy_decision.decision,
            review_created=review_created,
            flag_value=flag_value,
        )

    # -- review --

    def get_pending_reviews(self, project_id: str = "") -> list[ReviewRequest]:
        """List pending reviews, optionally filtered by project."""
        return self.review_gate.list_pending_reviews(
            project_id, self.blackboard
        )

    def resolve_review(
        self,
        request_id: str,
        decision: HumanDecisionChoice,
        reason: str = "",
        decided_by: str = "cli_user",
        project_id: str = "",
    ) -> ReviewRequest | None:
        """Resolve a review request with a human decision."""
        human_decision = HumanDecision(
            request_id=request_id,
            decision=decision,
            decided_by=decided_by,
            reason=reason,
        )
        return self.review_gate.resolve_review(
            request_id, human_decision, self.blackboard, project_id
        )

    # -- observation --

    def observe(self, project_id: str) -> ObservationReport:
        """Run all observation detectors and generate a report."""
        return self.observer.generate_report(project_id)

    # -- replay --

    def replay(self, project_id: str) -> list[dict]:
        """Export the full event log for a project."""
        return self.blackboard.export_run_log(project_id)

    # -- cleanup --

    def close(self) -> None:
        """Close the Blackboard database connection."""
        self.blackboard.close()