"""L2 Acceptance Tests — Manager Context Becomes Mandatory.

Four acceptance criteria:
1. Pending review blocks execution of the corresponding action
2. Active failure boundary changes a STEER_SOLVER decision
3. High-confidence candidate flag produces submit intent only when verification data exists
4. Resource exhaustion changes launch/steer behavior
"""

import os
import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.context import ContextCompiler, ManagerContext
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.memory import MemoryService
from attack_agent.team.review import HumanReviewGate
from attack_agent.team.protocol import (
    ActionType,
    HumanDecision,
    HumanDecisionChoice,
    IdeaEntry,
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
    ReviewRequest,
    StrategyAction,
)


def _make_bb(test_name: str) -> BlackboardService:
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, f"bb_l2_{test_name}.db")
    return BlackboardService(BlackboardConfig(db_path=db_path))


class TestPendingReviewBlocksExecution(unittest.TestCase):
    """L2 acceptance: pending review blocks execution of the corresponding action."""

    def setUp(self):
        self.bb = _make_bb("review_blocks")
        self.manager = TeamManager()
        self.review_gate = HumanReviewGate()
        self.compiler = ContextCompiler(review_gate=self.review_gate)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                             {"status": "new", "stage": "explore"})
        # seed a solver
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value,
                             {"solver_id": "s1", "profile": "network"})
        # seed some observation events so explore stage has activity
        self.bb.append_event("p1", EventType.OBSERVATION.value,
                             {"summary": "scanning target"})

    def tearDown(self):
        self.bb.close()

    def test_pending_steer_review_blocks_execution(self):
        """A pending review for steer_solver should block that action."""
        req = ReviewRequest(
            project_id="p1",
            action_type="steer_solver",
            risk_level="high",
            title="Review steer action",
            proposed_action="steer_solver",
        )
        self.review_gate.create_review(req, self.bb)

        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_stage_transition_from_context("p1", "explore", ctx)

        # should NOT be STEER_SOLVER — review blocks it
        self.assertNotEqual(action.action_type, ActionType.STEER_SOLVER)
        self.assertIn("pending review", action.reason)

    def test_no_pending_review_steer_continues(self):
        """Without a pending review, explore stage should steer solver."""
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_stage_transition_from_context("p1", "explore", ctx)

        # no review blocking → normal STEER_SOLVER
        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)


class TestFailureBoundaryChangesSteer(unittest.TestCase):
    """L2 acceptance: active failure boundary changes a STEER_SOLVER decision."""

    def setUp(self):
        self.bb = _make_bb("boundary_changes")
        self.mem_svc = MemoryService(self.bb)
        self.manager = TeamManager()
        self.compiler = ContextCompiler(memory_service=self.mem_svc)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                             {"status": "new", "stage": "explore"})
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value,
                             {"solver_id": "s1", "profile": "network"})
        self.bb.append_event("p1", EventType.OBSERVATION.value,
                             {"summary": "scanning target"})

    def tearDown(self):
        self.bb.close()

    def test_failure_boundary_risk_level_medium(self):
        """STEER_SOLVER with failure boundaries should have risk_level=medium."""
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY,
            content="WAF blocked SQL injection",
            confidence=0.0,
        ))
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_stage_transition_from_context("p1", "explore", ctx)

        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)
        self.assertEqual(action.risk_level, "medium")
        self.assertTrue(len(action.evidence_refs) > 0)
        self.assertIn("boundary_aware", action.policy_tags)

    def test_no_boundary_risk_level_low(self):
        """STEER_SOLVER without failure boundaries should have risk_level=low."""
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_stage_transition_from_context("p1", "explore", ctx)

        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)
        self.assertEqual(action.risk_level, "low")
        self.assertEqual(len(action.evidence_refs), 0)


class TestSubmitRequiresVerification(unittest.TestCase):
    """L2 acceptance: high-confidence candidate flag produces submit intent
    only when verification data exists."""

    def setUp(self):
        self.bb = _make_bb("submit_verify")
        self.manager = TeamManager(ManagerConfig(confidence_threshold=0.6))
        self.compiler = ContextCompiler()
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                             {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_verified_flag_submits(self):
        """High-confidence + verified flag → SUBMIT_FLAG."""
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{verified}", "confidence": 0.9},
                             source="state_sync")
        # add verification event for this flag
        events = self.bb.load_events("p1")
        flag_event_id = None
        for ev in events:
            if ev.event_type == EventType.CANDIDATE_FLAG.value:
                flag_event_id = ev.event_id
                break

        self.bb.append_event("p1", EventType.SECURITY_VALIDATION.value,
                             {"check": "evidence_chain", "outcome": "pass",
                              "candidate_flag_id": flag_event_id},
                             source="submission_verifier")

        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_submit_from_context(ctx)

        self.assertEqual(action.action_type, ActionType.SUBMIT_FLAG)
        self.assertTrue(action.requires_review)
        self.assertIn("verified_submit", action.policy_tags)

    def test_unverified_flag_does_not_submit(self):
        """High-confidence but unverified flag → CONVERGE (wait for verification)."""
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{unverified}", "confidence": 0.9},
                             source="state_sync")
        # NO verification event

        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_submit_from_context(ctx)

        self.assertEqual(action.action_type, ActionType.CONVERGE)
        self.assertIn("waiting for verification", action.reason)

    def test_failed_verification_does_not_submit(self):
        """High-confidence + failed verification → CONVERGE."""
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{failed_v}", "confidence": 0.9},
                             source="state_sync")
        events = self.bb.load_events("p1")
        flag_event_id = None
        for ev in events:
            if ev.event_type == EventType.CANDIDATE_FLAG.value:
                flag_event_id = ev.event_id
                break

        self.bb.append_event("p1", EventType.SECURITY_VALIDATION.value,
                             {"check": "evidence_chain", "outcome": "fail",
                              "candidate_flag_id": flag_event_id},
                             source="submission_verifier")

        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_submit_from_context(ctx)

        self.assertEqual(action.action_type, ActionType.CONVERGE)
        self.assertIn("waiting for verification", action.reason)

    def test_low_confidence_converges(self):
        """Low-confidence flag → CONVERGE regardless of verification."""
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{low_conf}", "confidence": 0.3},
                             source="state_sync")

        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_submit_from_context(ctx)

        self.assertEqual(action.action_type, ActionType.CONVERGE)
        self.assertIn("wait: best confidence", action.reason)


class TestResourceExhaustionChangesBehavior(unittest.TestCase):
    """L2 acceptance: resource exhaustion changes launch/steer behavior."""

    def setUp(self):
        self.bb = _make_bb("resource_exhaust")
        self.manager = TeamManager()
        self.compiler = ContextCompiler()
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                             {"status": "new", "stage": "bootstrap"})
        # seed a solver with budget_remaining = 0
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value,
                             {"solver_id": "s1", "profile": "network",
                              "budget_remaining": 0.0})

    def tearDown(self):
        self.bb.close()

    def test_budget_exhausted_bootstrap_steers_instead_of_launch(self):
        """Bootstrap with exhausted budget → STEER_SOLVER instead of LAUNCH_SOLVER."""
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        action = self.manager.decide_stage_transition_from_context("p1", "bootstrap", ctx)

        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)
        self.assertIn("budget exhausted", action.reason)
        self.assertEqual(action.target_solver_id, "s1")
        self.assertEqual(action.budget_request, 0.0)
        self.assertIn("budget_constrained", action.policy_tags)

    def test_budget_available_bootstrap_launches(self):
        """Bootstrap with available budget → LAUNCH_SOLVER."""
        bb2 = _make_bb("budget_ok")
        bb2.append_event("p1", EventType.PROJECT_UPSERTED.value,
                          {"status": "new", "stage": "bootstrap"})
        # solver with positive budget
        bb2.append_event("p1", EventType.WORKER_ASSIGNED.value,
                          {"solver_id": "s1", "profile": "network",
                           "budget_remaining": 15.0})
        ctx = self.compiler.compile_manager_context("p1", bb2)
        action = self.manager.decide_stage_transition_from_context("p1", "bootstrap", ctx)

        self.assertEqual(action.action_type, ActionType.LAUNCH_SOLVER)
        bb2.close()

    def test_no_solver_bootstrap_launches_normally(self):
        """Bootstrap with no existing solver → LAUNCH_SOLVER (no exhaustion check)."""
        bb3 = _make_bb("no_solver")
        bb3.append_event("p1", EventType.PROJECT_UPSERTED.value,
                          {"status": "new"})
        ctx = self.compiler.compile_manager_context("p1", bb3)
        action = self.manager.decide_stage_transition_from_context("p1", "bootstrap", ctx)

        self.assertEqual(action.action_type, ActionType.LAUNCH_SOLVER)
        bb3.close()


if __name__ == "__main__":
    unittest.main()