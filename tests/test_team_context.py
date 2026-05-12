"""Tests for ContextCompiler + ContextPack — Phase D."""

import os
import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.context import ContextCompiler, ManagerContext, SolverContextPack
from attack_agent.team.ideas import IdeaService
from attack_agent.team.memory import MemoryService
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.review import HumanReviewGate
from attack_agent.team.protocol import (
    FailureBoundary,
    IdeaEntry,
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
    ReviewRequest,
    SolverSession,
    TeamProject,
)


def _make_bb(test_name: str) -> BlackboardService:
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, f"bb_ctx_{test_name}.db")
    return BlackboardService(BlackboardConfig(db_path=db_path))


class TestManagerContext(unittest.TestCase):
    """ManagerContext fields are populated from Blackboard state."""

    def setUp(self):
        self.bb = _make_bb("mgr_ctx")
        self.compiler = ContextCompiler()

    def tearDown(self):
        self.bb.close()

    def test_manager_context_with_project(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                             {"challenge_id": "c1", "status": "new"})
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertIsNotNone(ctx.project_state)
        self.assertEqual(ctx.project_state.project_id, "p1")
        self.assertEqual(ctx.project_state.challenge_id, "c1")

    def test_manager_context_empty_project(self):
        ctx = self.compiler.compile_manager_context("p_missing", self.bb)
        self.assertIsNone(ctx.project_state)

    def test_manager_context_solver_states(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value,
                             {"solver_id": "s1", "profile": "network"})
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.solver_states) >= 1)
        self.assertEqual(ctx.solver_states[0].solver_id, "s1")

    def test_manager_context_candidate_flags(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        # genuine candidate_flag creates a flag entry, not an IdeaEntry
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{test}", "confidence": 0.8},
                             source="state_sync")
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        # genuine flag appears as candidate flag
        self.assertTrue(len(ctx.candidate_flags) >= 1)

    def test_manager_context_stagnation_points(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        for i in range(5):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value,
                                 {"status": "failed", "novelty": 0.0})
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.stagnation_points) > 0)

    def test_manager_context_resource_status(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.bb.append_event("p1", EventType.OBSERVATION.value,
                             {"summary": "found endpoint"})
        # genuine candidate_flag creates a fact, not an idea
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{x}", "confidence": 0.5},
                             source="state_sync")
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        # genuine flag doesn't create IdeaEntry, so idea_count = 0
        self.assertTrue(ctx.resource_status["fact_count"] >= 1)
        self.assertEqual(ctx.resource_status["idea_count"], 0)


class TestSolverContextPack(unittest.TestCase):
    """SolverContextPack fields populated from Blackboard + services."""

    def setUp(self):
        self.bb = _make_bb("solver_ctx")
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
        )
        # seed project + solver
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value,
                             {"solver_id": "s1", "profile": "network"})

    def tearDown(self):
        self.bb.close()

    def test_solver_context_profile(self):
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertEqual(ctx.profile, "network")

    def test_solver_context_solver_id(self):
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertEqual(ctx.solver_id, "s1")
        self.assertEqual(ctx.project_id, "p1")

    def test_solver_context_local_memory(self):
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FACT, content="found login page", confidence=0.7))
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertTrue(len(ctx.local_memory) >= 1)

    def test_solver_context_failure_boundaries(self):
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY, content="WAF blocked", confidence=0.0))
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertTrue(len(ctx.failure_boundaries) >= 1)
        self.assertIsInstance(ctx.failure_boundaries[0], FailureBoundary)

    def test_solver_context_global_facts(self):
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FACT, content="admin endpoint", confidence=0.9))
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertTrue(len(ctx.global_facts) >= 1)

    def test_solver_context_active_idea(self):
        self.idea_svc.propose("p1", "try XSS", priority=150)
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertIsNotNone(ctx.active_idea)
        self.assertEqual(ctx.active_idea.description, "try XSS")

    def test_solver_context_no_active_idea(self):
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertIsNone(ctx.active_idea)


class TestContextCompilerWithoutServices(unittest.TestCase):
    """ContextCompiler works with only Blackboard (no memory/idea services)."""

    def setUp(self):
        self.bb = _make_bb("minimal")
        self.compiler = ContextCompiler()  # no services
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_manager_context_with_no_services(self):
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertIsNotNone(ctx.project_state)
        self.assertEqual(ctx.resource_status["fact_count"], 0)

    def test_solver_context_with_no_services(self):
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertEqual(ctx.local_memory, [])
        self.assertEqual(ctx.failure_boundaries, [])
        self.assertIsNone(ctx.active_idea)


class TestContextPackGolden(unittest.TestCase):
    """Golden snapshot tests for ManagerContext and SolverContextPack field completeness."""

    def setUp(self):
        self.bb = _make_bb("golden")
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
        )
        # seed rich state
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                             {"challenge_id": "c1", "status": "new"})
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value,
                             {"solver_id": "s1", "profile": "network"})
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FACT, content="endpoint /api/users", confidence=0.85))
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.CREDENTIAL, content="admin:pass", confidence=0.9))
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY, content="SQLi blocked", confidence=0.0))
        self.idea_svc.propose("p1", "brute force login", priority=80)

    def tearDown(self):
        self.bb.close()

    def test_manager_context_golden(self):
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        # verify all ManagerContext fields populated
        self.assertIsNotNone(ctx.project_state)
        self.assertIsInstance(ctx.solver_states, list)
        self.assertIsInstance(ctx.candidate_flags, list)
        self.assertIsInstance(ctx.stagnation_points, list)
        self.assertIsInstance(ctx.resource_status, dict)
        self.assertIsInstance(ctx.pending_reviews, list)
        # L2 fields
        self.assertIsInstance(ctx.active_ideas, list)
        self.assertIsInstance(ctx.failure_boundaries, list)
        self.assertIsInstance(ctx.verification_state, dict)
        self.assertIsInstance(ctx.recent_human_decisions, list)
        self.assertIsInstance(ctx.observer_reports, list)
        self.assertIsInstance(ctx.high_value_facts, list)
        self.assertIsInstance(ctx.high_value_credentials, list)
        # resource_status has expected keys
        self.assertIn("idea_count", ctx.resource_status)
        self.assertIn("fact_count", ctx.resource_status)
        self.assertIn("session_count", ctx.resource_status)

    def test_solver_context_golden(self):
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        # verify all SolverContextPack fields populated
        self.assertEqual(ctx.profile, "network")
        self.assertIsNotNone(ctx.active_idea)
        self.assertIsInstance(ctx.local_memory, list)
        self.assertIsInstance(ctx.global_facts, list)
        self.assertIsInstance(ctx.failure_boundaries, list)
        self.assertIsInstance(ctx.inbox, list)
        self.assertEqual(ctx.solver_id, "s1")
        self.assertEqual(ctx.project_id, "p1")


class TestL2ManagerContextExpansion(unittest.TestCase):
    """L2: verify new ManagerContext fields are populated correctly."""

    def setUp(self):
        self.bb = _make_bb("l2_ctx")
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.review_gate = HumanReviewGate()
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
            review_gate=self.review_gate,
        )
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_compile_populates_pending_reviews(self):
        req = ReviewRequest(
            project_id="p1",
            action_type="steer_solver",
            risk_level="high",
            title="review steer",
            proposed_action="steer_solver",
        )
        self.review_gate.create_review(req, self.bb)
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.pending_reviews) >= 1)
        self.assertEqual(ctx.pending_reviews[0]["action_type"], "steer_solver")

    def test_compile_populates_failure_boundaries(self):
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY,
            content="WAF blocked",
            confidence=0.0,
        ))
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.failure_boundaries) >= 1)
        self.assertEqual(ctx.failure_boundaries[0].description, "WAF blocked")

    def test_compile_populates_active_ideas(self):
        self.idea_svc.propose("p1", "try XSS", priority=80)
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.active_ideas) >= 1)

    def test_compile_populates_verification_state(self):
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{test}", "confidence": 0.9},
                             source="state_sync")
        self.bb.append_event("p1", EventType.SECURITY_VALIDATION.value,
                             {"check": "evidence_chain", "outcome": "pass",
                              "candidate_flag_id": "cf_1"},
                             source="submission_verifier")
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertEqual(ctx.verification_state.get("cf_1"), "pass")

    def test_compile_populates_budget_remaining(self):
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value,
                             {"solver_id": "s1", "profile": "network", "budget_remaining": 15.0})
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertEqual(ctx.budget_remaining, 15.0)

    def test_compile_populates_high_value_facts(self):
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FACT, content="found admin page", confidence=0.85))
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.high_value_facts) >= 1)

    def test_compile_populates_high_value_credentials(self):
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.CREDENTIAL, content="admin:pass", confidence=0.9))
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.high_value_credentials) >= 1)

    def test_compile_populates_recent_human_decisions(self):
        req = ReviewRequest(
            project_id="p1",
            action_type="submit_flag",
            risk_level="high",
            title="submit review",
            proposed_action="submit flag",
        )
        self.review_gate.create_review(req, self.bb)
        from attack_agent.team.protocol import HumanDecision, HumanDecisionChoice
        self.review_gate.resolve_review(req.request_id, HumanDecision(
            request_id=req.request_id,
            decision=HumanDecisionChoice.APPROVED,
            decided_by="test_user",
        ), self.bb, "p1")
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.recent_human_decisions) >= 1)

    def test_compile_populates_observer_reports(self):
        self.bb.append_event("p1", EventType.CHECKPOINT.value,
                             {"severity": "warning", "suggested_actions": ["reassign"]},
                             source="observer")
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        self.assertTrue(len(ctx.observer_reports) >= 1)
        self.assertEqual(ctx.observer_reports[0].severity, "warning")

    def test_compile_without_review_gate_defaults_empty(self):
        compiler_no_gate = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
        )
        ctx = compiler_no_gate.compile_manager_context("p1", self.bb)
        self.assertEqual(ctx.pending_reviews, [])

    def test_failure_boundaries_from_state_facts(self):
        """When memory_service is None, boundaries come from state.facts (action_outcome errors)."""
        bb2 = _make_bb("l2_fallback")
        bb2.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        # action_outcome with status=error creates FAILURE_BOUNDARY in state.facts
        bb2.append_event("p1", EventType.ACTION_OUTCOME.value,
                         {"status": "error", "error": "blocked by WAF",
                          "entry_id": "fb1"})
        compiler = ContextCompiler()
        ctx = compiler.compile_manager_context("p1", bb2)
        self.assertTrue(len(ctx.failure_boundaries) >= 1)
        self.assertEqual(ctx.failure_boundaries[0].description, "blocked by WAF")
        bb2.close()


if __name__ == "__main__":
    unittest.main()