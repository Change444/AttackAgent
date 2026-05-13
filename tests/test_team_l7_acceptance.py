"""L7 acceptance tests — Observer in the Scheduling Loop.

Acceptance criteria:
1. Repeated action report causes a steering action
2. Ignored failure boundary can stop or reassign a Solver
3. Observer never directly mutates facts or stops a Solver
4. Critical observer reports create review or policy-block events
5. Observer report changes Manager's next scheduling decision
"""

import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService, BlackboardConfig
from attack_agent.team.context import ContextCompiler
from attack_agent.team.ideas import IdeaService
from attack_agent.team.manager import TeamManager
from attack_agent.team.memory import MemoryService
from attack_agent.team.observer import Observer, ObservationReport
from attack_agent.team.policy import PolicyHarness, PolicyOutcome
from attack_agent.team.protocol import (
    ActionType,
    InterventionLevel,
    MemoryKind,
    SolverSession,
    SolverStatus,
    StrategyAction,
)


def _make_bb() -> BlackboardService:
    return BlackboardService(BlackboardConfig(db_path=":memory:"))


def _seed_project(bb: BlackboardService, project_id: str = "p1") -> None:
    bb.append_event(project_id, EventType.PROJECT_UPSERTED.value,
                     {"challenge_id": "c1", "status": "new"})


def _seed_solver(bb: BlackboardService, project_id: str, solver_id: str,
                  profile: str = "network", status: str = "running") -> None:
    bb.append_event(project_id, EventType.WORKER_ASSIGNED.value, {
        "solver_id": solver_id,
        "profile": profile,
        "status": status,
    })


class TestL7RepeatedActionCausesSteering(unittest.TestCase):
    """L7 criterion 1: repeated action report causes a steering action."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        _seed_solver(self.bb, "p1", "s1")
        # Create 3 repeated action outcomes (same solver, primitive, target)
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "solver_id": "s1", "primitive": "http-request",
                "target": "/login", "status": "ok",
            })
        self.observer = Observer(self.bb)
        self.observer.generate_report("p1")
        self.compiler = ContextCompiler(
            memory_service=MemoryService(self.bb),
            idea_service=IdeaService(self.bb),
            manager=TeamManager(),
        )
        self.ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.manager = TeamManager()

    def tearDown(self):
        self.bb.close()

    def test_repeated_action_report_produces_steer_decision(self):
        action = self.manager.decide_observer_response("p1", self.ctx)
        self.assertIsNotNone(action)
        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)

    def test_steer_targets_the_repeating_solver(self):
        action = self.manager.decide_observer_response("p1", self.ctx)
        self.assertEqual(action.target_solver_id, "s1")

    def test_steer_has_observer_policy_tag(self):
        action = self.manager.decide_observer_response("p1", self.ctx)
        self.assertIn("observer_steered", action.policy_tags)

    def test_steer_has_medium_risk(self):
        action = self.manager.decide_observer_response("p1", self.ctx)
        self.assertEqual(action.risk_level, "medium")


class TestL7IgnoredBoundaryStopsOrReassigns(unittest.TestCase):
    """L7 criterion 2: ignored failure boundary can stop or reassign a Solver."""

    def setUp(self):
        # Multi-solver scenario: two solvers hit same boundary → REASSIGN
        self.bb = _make_bb()
        _seed_project(self.bb)
        _seed_solver(self.bb, "p1", "s1")
        _seed_solver(self.bb, "p1", "s2", "browser", "running")
        # Create an ignored failure boundary (2 solvers hit same boundary)
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked by WAF",
            "summary": "RCE blocked by WAF", "solver_id": "s1",
        })
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked by WAF",
            "summary": "RCE blocked by WAF", "solver_id": "s2",
        })
        self.observer = Observer(self.bb)
        self.observer.generate_report("p1")
        self.compiler = ContextCompiler(
            memory_service=MemoryService(self.bb),
            idea_service=IdeaService(self.bb),
            manager=TeamManager(),
        )
        self.ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.manager = TeamManager()

    def tearDown(self):
        self.bb.close()

    def test_ignored_boundary_reassigns_when_multiple_solvers(self):
        action = self.manager.decide_observer_response("p1", self.ctx)
        self.assertIsNotNone(action)
        self.assertEqual(action.action_type, ActionType.REASSIGN_SOLVER)
        self.assertTrue(action.requires_review)
        self.assertIn("observer_reassigned", action.policy_tags)

    def test_ignored_boundary_stops_when_single_solver(self):
        bb_single = _make_bb()
        _seed_project(bb_single)
        _seed_solver(bb_single, "p1", "s1")
        bb_single.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "WAF blocked injection",
            "summary": "WAF blocked injection", "solver_id": "s1",
        })
        # Need 2 solvers hitting same boundary for ignored_boundary to trigger
        # Add second outcome from same solver_id won't trigger, need second solver_id
        # For single-solver case: STOP_SOLVER when only 1 solver exists
        bb_single.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "WAF blocked injection",
            "summary": "WAF blocked injection", "solver_id": "s2",
        })
        observer_single = Observer(bb_single)
        observer_single.generate_report("p1")
        compiler_single = ContextCompiler(
            memory_service=MemoryService(bb_single),
            idea_service=IdeaService(bb_single),
            manager=TeamManager(),
        )
        ctx_single = compiler_single.compile_manager_context("p1", bb_single)
        # ctx_single has only 1 solver session in solver_states (s1), s2 has no session
        action = TeamManager().decide_observer_response("p1", ctx_single)
        self.assertIsNotNone(action)
        # With only 1 solver in solver_states → STOP_SOLVER
        self.assertEqual(action.action_type, ActionType.STOP_SOLVER)
        bb_single.close()


class TestL7ObserverNeverMutates(unittest.TestCase):
    """L7 criterion 3: Observer never directly mutates facts or stops a Solver."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        _seed_solver(self.bb, "p1", "s1")
        # Create a severe scenario (tool misuse)
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "error", "solver_id": "s1", "primitive": "http-request",
            })
        self.observer = Observer(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_observer_report_does_not_add_facts(self):
        state_before = self.bb.rebuild_state("p1")
        fact_count_before = len(state_before.facts)
        self.observer.generate_report("p1")
        state_after = self.bb.rebuild_state("p1")
        fact_count_after = len(state_after.facts)
        self.assertEqual(fact_count_before, fact_count_after)

    def test_observer_report_does_not_change_solver_status(self):
        self.observer.generate_report("p1")
        state_after = self.bb.rebuild_state("p1")
        for s in state_after.sessions:
            self.assertEqual(s.status, SolverStatus.RUNNING)

    def test_observer_only_writes_observer_report_events(self):
        self.observer.generate_report("p1")
        events = self.bb.load_events("p1")
        observer_events = [e for e in events if e.source == "observer"]
        self.assertTrue(len(observer_events) > 0)
        for ev in observer_events:
            self.assertEqual(ev.event_type, EventType.OBSERVER_REPORT.value)

    def test_apply_event_handles_observer_report_without_mutation(self):
        """Verify that OBSERVER_REPORT events pass through apply_event_to_state
        without adding facts or changing sessions."""
        from attack_agent.team.apply_event import apply_event_to_state
        from attack_agent.team.protocol import TeamProject

        # Create state components
        project = TeamProject(project_id="p1", status="active")
        facts: list = []
        ideas: dict = {}
        sessions: dict = {}
        packets: dict = {}

        # Apply an OBSERVER_REPORT event
        result = apply_event_to_state(
            "p1", EventType.OBSERVER_REPORT.value,
            {"severity": "critical", "intervention_level": "safety_block"},
            "2026-01-01T00:00:00", "ev_l7",
            project, facts, ideas, sessions, packets,
        )

        # No facts should have been added
        self.assertEqual(len(facts), 0)
        # Project status unchanged
        self.assertEqual(result.status, "active")


class TestL7CriticalReportsCreateReviewOrBlock(unittest.TestCase):
    """L7 criterion 4: critical observer reports create review or policy-block events."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        _seed_solver(self.bb, "p1", "s1")
        # Create SAFETY_BLOCK scenario: tool_misuse + ignored_boundary
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "error", "solver_id": "s1", "primitive": "http-request",
            })
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "WAF block",
            "summary": "WAF block", "solver_id": "s1",
        })
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "WAF block",
            "summary": "WAF block", "solver_id": "s2",
        })
        self.observer = Observer(self.bb)
        self.observer.generate_report("p1")
        self.compiler = ContextCompiler(
            memory_service=MemoryService(self.bb),
            idea_service=IdeaService(self.bb),
            manager=TeamManager(),
        )
        self.ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.manager = TeamManager()
        self.policy = PolicyHarness()

    def tearDown(self):
        self.bb.close()

    def test_safety_block_report_creates_review_action(self):
        action = self.manager.decide_observer_response("p1", self.ctx)
        self.assertIsNotNone(action)
        self.assertEqual(action.action_type, ActionType.STOP_SOLVER)
        self.assertTrue(action.requires_review)
        self.assertTrue(any(t.startswith("observer_") for t in action.policy_tags))

    def test_observer_safety_block_passes_policy_as_needs_review(self):
        """Safety-block actions should be needs_review, NOT deny."""
        action = self.manager.decide_observer_response("p1", self.ctx)
        decision = self.policy.validate_action(action, "p1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.NEEDS_REVIEW)

    def test_ignored_boundary_also_requires_review(self):
        """STOP_REASSIGN level actions require review."""
        bb2 = _make_bb()
        _seed_project(bb2)
        _seed_solver(bb2, "p1", "s1")
        _seed_solver(bb2, "p1", "s2", "browser", "running")
        bb2.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "WAF block",
            "summary": "WAF block", "solver_id": "s1",
        })
        bb2.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "WAF block",
            "summary": "WAF block", "solver_id": "s2",
        })
        Observer(bb2).generate_report("p1")
        ctx2 = ContextCompiler(
            memory_service=MemoryService(bb2),
            idea_service=IdeaService(bb2),
            manager=TeamManager(),
        ).compile_manager_context("p1", bb2)
        action = TeamManager().decide_observer_response("p1", ctx2)
        self.assertTrue(action.requires_review)
        bb2.close()


class TestL7ObserverReportChangesSchedulingDecision(unittest.TestCase):
    """L7 criterion 5: Observer report changes Manager's next scheduling decision."""

    def setUp(self):
        # Without observer: normal explore state with a fact
        self.bb_no_obs = _make_bb()
        _seed_project(self.bb_no_obs)
        _seed_solver(self.bb_no_obs, "p1", "s1")
        self.bb_no_obs.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "new fact", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.8,
        })

        # With observer: same project but with repeated actions anomaly
        self.bb_with_obs = _make_bb()
        _seed_project(self.bb_with_obs)
        _seed_solver(self.bb_with_obs, "p1", "s1")
        # Repeated action outcomes (anomaly)
        for i in range(3):
            self.bb_with_obs.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "solver_id": "s1", "primitive": "http-request",
                "target": "/login", "status": "ok",
            })
        # Also add a normal fact so exploration isn't stagnation
        self.bb_with_obs.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "new fact", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.8,
        })
        # Generate observer report
        self.observer = Observer(self.bb_with_obs)
        self.observer.generate_report("p1")

    def tearDown(self):
        self.bb_no_obs.close()
        self.bb_with_obs.close()

    def test_observer_report_changes_decision(self):
        """The decision with observer report must differ from the decision without it."""
        # Without observer: Manager decides normal explore continuation
        compiler_no_obs = ContextCompiler(
            memory_service=MemoryService(self.bb_no_obs),
            idea_service=IdeaService(self.bb_no_obs),
            manager=TeamManager(),
        )
        ctx_no_obs = compiler_no_obs.compile_manager_context("p1", self.bb_no_obs)
        action_no_obs = TeamManager().decide_stage_transition_from_context(
            "p1", "explore", ctx_no_obs
        )

        # With observer: repeated action triggers steer override
        compiler_with_obs = ContextCompiler(
            memory_service=MemoryService(self.bb_with_obs),
            idea_service=IdeaService(self.bb_with_obs),
            manager=TeamManager(),
        )
        ctx_with_obs = compiler_with_obs.compile_manager_context("p1", self.bb_with_obs)
        action_with_obs = TeamManager().decide_stage_transition_from_context(
            "p1", "explore", ctx_with_obs
        )

        # The decision must differ because of observer report
        # Either: different action type, or observer-specific policy_tags
        differs_by_type = action_no_obs.action_type != action_with_obs.action_type
        differs_by_tags = any(t.startswith("observer_") for t in action_with_obs.policy_tags) and \
                          not any(t.startswith("observer_") for t in action_no_obs.policy_tags)
        self.assertTrue(differs_by_type or differs_by_tags,
                        "Observer report must change Manager's scheduling decision")

    def test_observer_overrides_normal_explore_flow(self):
        """Observer L2+ report preempts normal stage progression."""
        compiler_with_obs = ContextCompiler(
            memory_service=MemoryService(self.bb_with_obs),
            idea_service=IdeaService(self.bb_with_obs),
            manager=TeamManager(),
        )
        ctx_with_obs = compiler_with_obs.compile_manager_context("p1", self.bb_with_obs)
        action_with_obs = TeamManager().decide_stage_transition_from_context(
            "p1", "explore", ctx_with_obs
        )
        # Observer override should produce an action with observer-specific tags
        self.assertTrue(any(t.startswith("observer_") for t in action_with_obs.policy_tags))

    def test_no_observer_no_observer_tags(self):
        """Without observer reports, decisions should not have observer tags."""
        compiler_no_obs = ContextCompiler(
            memory_service=MemoryService(self.bb_no_obs),
            idea_service=IdeaService(self.bb_no_obs),
            manager=TeamManager(),
        )
        ctx_no_obs = compiler_no_obs.compile_manager_context("p1", self.bb_no_obs)
        action_no_obs = TeamManager().decide_stage_transition_from_context(
            "p1", "explore", ctx_no_obs
        )
        self.assertFalse(any(t.startswith("observer_") for t in action_no_obs.policy_tags))


if __name__ == "__main__":
    unittest.main()