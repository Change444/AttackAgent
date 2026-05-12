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
from attack_agent.team.protocol import (
    FailureBoundary,
    IdeaEntry,
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
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


if __name__ == "__main__":
    unittest.main()