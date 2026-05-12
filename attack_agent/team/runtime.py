"""TeamRuntime — Phase H main entry point.

Wires all Phase A~G components into a single orchestrator.
CLI and API consume this class exclusively.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.platform_models import EventType
from attack_agent.team.benchmark import BenchmarkRunner, RegressionReport, RunMetrics, MetricsComparison
from attack_agent.team.blackboard import BlackboardService, MaterializedState
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.context import ContextCompiler
from attack_agent.team.event_compat import is_genuine_candidate_flag
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
from attack_agent.team.replay import ReplayEngine, ReplayStep, RunDiffResult
from attack_agent.team.review import HumanReviewGate
from attack_agent.team.scheduler import SchedulerConfig, SyncScheduler
from attack_agent.team.solver import SolverSessionConfig, SolverSessionManager
from attack_agent.team.submission import SubmissionConfig, SubmissionVerifier, VerificationResult
from attack_agent.team.tool_broker import ToolBroker, ToolRequest, ToolResult, ToolError
from attack_agent.team.state_sync import StateSyncService, SyncConfig
from attack_agent.runtime import PrimitiveRegistry
from attack_agent.dispatcher import Dispatcher
from attack_agent.enhanced_apg import EnhancedAPGPlanner
from attack_agent.runtime import WorkerRuntime
from attack_agent.state_graph import StateGraphService


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
    use_real_executor: bool = False


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

    def __init__(
        self,
        config: TeamRuntimeConfig | None = None,
        worker_runtime: WorkerRuntime | None = None,
        dispatcher: Dispatcher | None = None,
        state_graph: StateGraphService | None = None,
        enhanced_planner: EnhancedAPGPlanner | None = None,
    ) -> None:
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
        self.tool_broker = ToolBroker(PrimitiveRegistry(), self.policy, self.blackboard)
        self.state_sync = StateSyncService(SyncConfig())

        # Real executor components (Phase K-1)
        self._worker_runtime = worker_runtime
        self._dispatcher = dispatcher
        self._state_graph = state_graph
        self._enhanced_planner = enhanced_planner

        # Bootstrap and submission components (Phase K-2)
        self._controller: Any | None = None
        self._provider: Any | None = None

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
            project.project_id, self.manager, self.blackboard, self
        )

    def run_all(self, challenge_ids: list[str]) -> dict[str, TeamProject]:
        """Run multiple projects sequentially."""
        projects = {}
        for cid in challenge_ids:
            proj = self.run_project(cid)
            projects[cid] = proj
        return projects

    def solve_all(self) -> dict[str, TeamProject]:
        """Bootstrap challenges via Controller and run all projects.

        Replaces CompetitionPlatform.solve_all(). Requires _controller
        and _state_graph to be set (via build_team_runtime factory).
        """
        if self._controller is None or self._state_graph is None:
            raise RuntimeError("solve_all() requires _controller and _state_graph — use build_team_runtime()")

        # 1. Bootstrap: sync challenges + ensure instances
        project_ids = self._controller.sync_challenges()
        for pid in project_ids:
            self._controller.ensure_instance(pid)

        # 1b. Clear stale Blackboard data for each project — prevent
        #     abandoned status from previous runs polluting rebuild_state
        for pid in project_ids:
            self.blackboard.clear_project_events(pid)

        # 2. Inject challenge data into Blackboard
        for pid in project_ids:
            record = self._state_graph.projects[pid]
            self.blackboard.append_event(
                project_id=pid,
                event_type="project_upserted",
                payload={
                    "challenge_id": record.snapshot.challenge.id,
                    "status": "new",
                    "stage": "bootstrap",
                },
                source="team_runtime",
            )
            if record.snapshot.instance is not None:
                self.blackboard.append_event(
                    project_id=pid,
                    event_type="instance_started",
                    payload={
                        "instance_id": record.snapshot.instance.instance_id,
                        "target": record.snapshot.instance.target,
                    },
                    source="team_runtime",
                )

        # 3. Run all projects via SyncScheduler
        results = self.scheduler.run_all(self.manager, self.blackboard, project_ids, self)

        # 4. Sync StateGraphService → Blackboard final state first (Phase K-3)
        for pid in project_ids:
            bb_state = self.blackboard.rebuild_state(pid)
            if bb_state.project is not None:
                record = self._state_graph.projects.get(pid)
                if record is not None:
                    bb_stage = bb_state.project.status
                    if bb_stage in ("done", "abandoned"):
                        from attack_agent.platform_models import ProjectStage
                        record.snapshot.stage = ProjectStage.DONE if bb_stage == "done" else ProjectStage.ABANDONED
                        record.snapshot.status = bb_stage
            # Now sync StateGraphService state into Blackboard (states are consistent)
            self.state_sync.sync_project(pid, self._state_graph, self.blackboard)
            # Validate consistency; if mismatch, corrective event is written
            self.state_sync.validate_consistency(pid, self._state_graph, self.blackboard)

        return results

    # -- real executor (Phase K-1) --

    @property
    def use_real_executor(self) -> bool:
        """Whether TeamRuntime has real execution capability."""
        return (
            self.config.use_real_executor
            and self._dispatcher is not None
            and self._worker_runtime is not None
            and self._state_graph is not None
        )

    def _execute_solver_cycle(self, project_id: str) -> dict | None:
        """Execute one real solver cycle via Dispatcher.

        BOOTSTRAP+REASON+first EXPLORE are all done in a single call,
        matching CompetitionPlatform.run_cycle() behavior where one
        cycle includes full stage advancement + execution.

        Returns a dict with outcome summary, or None if execution failed.
        """
        if not self.use_real_executor:
            return None

        state_graph = self._state_graph
        record = state_graph.projects.get(project_id)
        if record is None:
            return None

        from attack_agent.platform_models import ProjectStage

        # BOOTSTRAP → REASON → EXPLORE: advance all stages in one call
        if record.snapshot.stage == ProjectStage.BOOTSTRAP:
            profile, _reason = self._enhanced_planner.reasoner.choose_profile(record.snapshot)
            record.snapshot.worker_profile = profile
            record.snapshot.stage = ProjectStage.REASON
            self.blackboard.append_event(
                project_id=project_id,
                event_type="project_upserted",
                payload={
                    "challenge_id": record.snapshot.challenge.id,
                    "status": record.snapshot.status,
                    "stage": "reason",
                    "worker_profile": profile.value,
                },
                source="team_runtime_executor",
            )

            # Continue immediately to REASON → EXPLORE
            record.pattern_graph = self._enhanced_planner.create_graph(record.snapshot)
            record.snapshot.stage = ProjectStage.EXPLORE
            self.blackboard.append_event(
                project_id=project_id,
                event_type="project_upserted",
                payload={
                    "challenge_id": record.snapshot.challenge.id,
                    "status": record.snapshot.status,
                    "stage": "explore",
                },
                source="team_runtime_executor",
            )

        elif record.snapshot.stage == ProjectStage.REASON:
            # REASON → EXPLORE: advance and continue to execution
            record.pattern_graph = self._enhanced_planner.create_graph(record.snapshot)
            record.snapshot.stage = ProjectStage.EXPLORE
            self.blackboard.append_event(
                project_id=project_id,
                event_type="project_upserted",
                payload={
                    "challenge_id": record.snapshot.challenge.id,
                    "status": record.snapshot.status,
                    "stage": "explore",
                },
                source="team_runtime_executor",
            )

        # EXPLORE: execute via Dispatcher
        if record.snapshot.stage != ProjectStage.EXPLORE:
            return None

        result = self._dispatcher.schedule(project_id, skip_stage_decisions=True)
        if result is None:
            # Dispatcher returned None — likely "No program produced" → CONVERGE.
            # Sync the stage change to Blackboard to avoid stale state.
            if record.snapshot.stage != ProjectStage.EXPLORE:
                self.blackboard.append_event(
                    project_id=project_id,
                    event_type="project_upserted",
                    payload={
                        "challenge_id": record.snapshot.challenge.id,
                        "status": record.snapshot.status,
                        "stage": record.snapshot.stage.value,
                    },
                    source="team_runtime_executor",
                )
            return None

        outcome, events = result

        # Write per-observation OBSERVATION events with full detail
        for obs in outcome.observations:
            self.blackboard.append_event(
                project_id=project_id,
                event_type="observation",
                payload={
                    "kind": obs.kind,
                    "source": obs.source,
                    "target": obs.target,
                    "payload": obs.payload,
                    "confidence": obs.confidence,
                    "novelty": obs.novelty,
                    "entry_id": obs.id,
                    "summary": obs.payload.get("summary", obs.kind),
                },
                source="team_runtime_executor",
            )

        # Write ACTION_OUTCOME to Blackboard (summary)
        self.blackboard.append_event(
            project_id=project_id,
            event_type="action_outcome",
            payload={
                "status": outcome.status,
                "primitive_name": outcome.observations[0].kind if outcome.observations else "",
                "cost": outcome.cost,
                "novelty": outcome.novelty,
                "observations_count": len(outcome.observations),
                "candidate_flags_count": len(outcome.candidate_flags),
                "failure_reason": outcome.failure_reason or "",
                "broker_execution": True,
                "stagnation_counter": record.stagnation_counter,
            },
            source="team_runtime_executor",
        )

        # Write CANDIDATE_FLAG events for each flag found
        for flag in outcome.candidate_flags:
            self.blackboard.append_event(
                project_id=project_id,
                event_type="candidate_flag",
                payload={
                    "flag": flag.value,
                    "confidence": flag.confidence,
                    "format_match": flag.format_match,
                    "dedupe_key": flag.dedupe_key,
                    "source_chain": flag.source_chain,
                    "evidence_refs": flag.evidence_refs,
                },
                source="team_runtime_executor",
            )

        # Write SECURITY_VALIDATION events if security shell blocked execution
        for event in events:
            if event.type.value == "security_validation":
                self.blackboard.append_event(
                    project_id=project_id,
                    event_type="security_validation",
                    payload=dict(event.payload),
                    source="team_runtime_executor",
                )

        # Write pattern_graph CHECKPOINT event if pattern graph exists
        if record.pattern_graph is not None:
            pg = record.pattern_graph
            self.blackboard.append_event(
                project_id=project_id,
                event_type="checkpoint",
                payload={
                    "pattern_graph_created": True,
                    "nodes": [
                        {
                            "node_id": n.id,
                            "kind": n.kind.value,
                            "status": n.status,
                            "family": n.family,
                        }
                        for n in pg.nodes.values()
                    ],
                    "active_family": pg.active_family,
                    "family_priority": pg.family_priority,
                },
                source="team_runtime_executor",
            )

        # Write session_state OBSERVATION event if session exists
        if record.session_state is not None:
            ss = record.session_state
            self.blackboard.append_event(
                project_id=project_id,
                event_type="observation",
                payload={
                    "kind": "session_state",
                    "cookies_count": len(ss.cookies),
                    "auth_headers_keys": list(ss.auth_headers.keys()),
                    "base_url": ss.base_url,
                    "summary": f"session_state: {len(ss.cookies)} cookies, {len(ss.auth_headers)} auth headers",
                },
                source="team_runtime_executor",
            )

        # Write stagnation CHECKPOINT if stagnation_counter > 0
        if record.stagnation_counter > 0:
            self.blackboard.append_event(
                project_id=project_id,
                event_type="checkpoint",
                payload={
                    "stagnation_update": True,
                    "stagnation_counter": record.stagnation_counter,
                },
                source="team_runtime_executor",
            )

        return {
            "status": outcome.status,
            "novelty": outcome.novelty,
            "cost": outcome.cost,
            "candidate_flags": [
                {"value": f.value, "confidence": f.confidence}
                for f in outcome.candidate_flags
            ],
            "failure_reason": outcome.failure_reason,
            "observations_count": len(outcome.observations),
        }

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
        # Derive candidate flags from genuine candidate_flag events
        raw_events = self.blackboard.load_events(project_id)
        candidate_flags = [
            ev.payload.get("flag", "")
            for ev in raw_events
            if ev.event_type == EventType.CANDIDATE_FLAG.value
            and is_genuine_candidate_flag(ev.event_type, ev.payload, ev.source)
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
            payload={"flag": flag_value, "idea_id": idea_id, "outcome": "submitted", "result": "submitted"},
            source="team_runtime",
        )

        # Real submission via Controller when available
        if self._controller is not None and self._state_graph is not None:
            record = self._state_graph.projects.get(project_id)
            if record is not None:
                existing_keys = set()
                for dedupe_key, candidate in list(record.candidate_flags.items()):
                    if dedupe_key in existing_keys:
                        continue
                    result = self._controller.submit_candidate(project_id, dedupe_key)
                    existing_keys.add(dedupe_key)
                    if result.get("accepted"):
                        break  # first accepted flag wins

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

    def replay_steps(self, project_id: str) -> list[ReplayStep]:
        """Replay project with intermediate state snapshots."""
        engine = ReplayEngine()
        return engine.replay_project(project_id, self.blackboard)

    def evaluate(self, project_id: str) -> RunMetrics:
        """Compute RunMetrics from project event journal."""
        runner = BenchmarkRunner()
        return runner.evaluate_project(project_id, self.blackboard)

    def compare_runs(self, project_id_a: str, project_id_b: str,
                     other_runtime: TeamRuntime | None = None) -> RunDiffResult:
        """Compare two project event logs.

        If other_runtime is provided, uses its Blackboard for project_id_b;
        otherwise uses self.blackboard for both.
        """
        engine = ReplayEngine()
        bb_b = other_runtime.blackboard if other_runtime else self.blackboard
        return engine.diff_runs(project_id_a, project_id_b, self.blackboard, bb_b)

    # -- tool broker --

    def request_tool(
        self,
        project_id: str,
        solver_id: str,
        primitive_name: str,
        step: dict | None = None,
        risk_level: str = "low",
        budget_request: float = 0.0,
        reason: str = "",
        bundle_ref: dict | None = None,
    ) -> ToolResult | ToolError:
        """Request a primitive execution through the ToolBroker policy gate."""
        req = ToolRequest(
            project_id=project_id,
            solver_id=solver_id,
            primitive_name=primitive_name,
            step=step or {},
            risk_level=risk_level,
            budget_request=budget_request,
            reason=reason,
            bundle_ref=bundle_ref or {},
        )
        return self.tool_broker.request_tool(req)

    def list_available_primitives(self, profile: str = "") -> list[str]:
        """List primitives available to a given worker profile."""
        return self.tool_broker.list_available_primitives(profile)

    # -- cleanup --

    def close(self) -> None:
        """Close the Blackboard database connection."""
        self.blackboard.close()