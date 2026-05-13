"""L4 acceptance tests — Memory Drives Solver Continuity.

Acceptance criteria:
1. A Solver's second turn sees facts produced by its first turn
2. A failed approach becomes a failure boundary and prevents immediate repetition
3. A credential discovered by one turn is available as structured context later
4. Context pack length remains bounded while preserving key evidence

Plus backward compatibility and memory reducer tests.
"""

import os
import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.context import ContextCompiler, SolverContextPack, SOLVER_CONTEXT_LIMITS
from attack_agent.team.ideas import IdeaService
from attack_agent.team.memory import MemoryService
from attack_agent.team.memory_reducer import MemoryReducer
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.protocol import (
    FailureBoundary,
    MemoryEntry,
    MemoryKind,
    SolverSession,
)


def _make_bb(test_name: str) -> BlackboardService:
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, f"bb_l4_{test_name}.db")
    return BlackboardService(BlackboardConfig(db_path=db_path))


def _seed_project_and_solver(bb: BlackboardService) -> None:
    bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
    bb.append_event("p1", EventType.WORKER_ASSIGNED.value,
                     {"solver_id": "s1", "profile": "network"})


class TestL4SolverSecondTurnSeesFacts(unittest.TestCase):
    """L4 acceptance criterion 1: second turn sees first turn facts."""

    def setUp(self):
        self.bb = _make_bb("facts_carry")
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
        )
        _seed_project_and_solver(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_solver_second_turn_sees_first_turn_facts(self):
        # Turn 1: store a fact
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FACT, content="discovered admin panel at /admin",
            confidence=0.8))

        # Turn 2: compile context — the fact from turn 1 must appear
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        all_facts = ctx.local_memory + ctx.global_facts
        found = any("admin panel" in f.content for f in all_facts)
        self.assertTrue(found, "Fact from first turn must appear in second turn context")


class TestL4FailureBoundaryPreventsRepetition(unittest.TestCase):
    """L4 acceptance criterion 2: failed approach prevents immediate repetition."""

    def setUp(self):
        self.bb = _make_bb("boundary_rep")
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
        )
        _seed_project_and_solver(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_failed_approach_prevents_immediate_repetition(self):
        # Store a failure boundary from a failed approach
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY,
            content="SQLi blocked by WAF",
            confidence=0.0))

        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)

        # failure_boundaries must contain the boundary
        self.assertTrue(len(ctx.failure_boundaries) >= 1,
                        "Failure boundary must appear in SolverContextPack")

        # Repetition check: trying "SQLi" again should match
        self.assertTrue(ctx.is_boundary_repetition("try SQLi injection"),
                        "Matching failure boundary should be detected as repetition")

        # Non-repetition: a different approach should not match
        self.assertFalse(ctx.is_boundary_repetition("try XSS attack"),
                         "Different approach should not be flagged as repetition")


class TestL4CredentialAvailableAsStructuredContext(unittest.TestCase):
    """L4 acceptance criterion 3: credential appears as structured context."""

    def setUp(self):
        self.bb = _make_bb("cred_ctx")
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
        )
        _seed_project_and_solver(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_credential_available_as_structured_context(self):
        # Store a credential
        self.mem_svc.store_entry("p1", MemoryEntry(
            kind=MemoryKind.CREDENTIAL,
            content="admin:password123",
            confidence=0.9))

        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)

        # Credential must appear in ctx.credentials
        self.assertTrue(len(ctx.credentials) >= 1,
                        "Credential must appear in SolverContextPack.credentials")
        self.assertEqual(ctx.credentials[0].kind, MemoryKind.CREDENTIAL)
        self.assertEqual(ctx.credentials[0].content, "admin:password123")


class TestL4ContextPackBounded(unittest.TestCase):
    """L4 acceptance criterion 4: context pack stays bounded."""

    def setUp(self):
        self.bb = _make_bb("bounded")
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
        )
        _seed_project_and_solver(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_context_pack_bounded(self):
        # Store many entries beyond limits
        for i in range(50):
            self.mem_svc.store_entry("p1", MemoryEntry(
                kind=MemoryKind.FACT, content=f"fact_{i}", confidence=0.7))
        for i in range(20):
            self.mem_svc.store_entry("p1", MemoryEntry(
                kind=MemoryKind.CREDENTIAL, content=f"cred_{i}", confidence=0.9))
        for i in range(20):
            self.mem_svc.store_entry("p1", MemoryEntry(
                kind=MemoryKind.ENDPOINT, content=f"/api/ep{i}", confidence=0.8))
        for i in range(30):
            self.mem_svc.store_entry("p1", MemoryEntry(
                kind=MemoryKind.FAILURE_BOUNDARY, content=f"failed_{i}", confidence=0.0))

        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)

        # All lists must be bounded
        self.assertTrue(len(ctx.local_memory) <= SOLVER_CONTEXT_LIMITS["max_local_memory"])
        self.assertTrue(len(ctx.global_facts) <= SOLVER_CONTEXT_LIMITS["max_global_facts"])
        self.assertTrue(len(ctx.credentials) <= SOLVER_CONTEXT_LIMITS["max_credentials"])
        self.assertTrue(len(ctx.endpoints) <= SOLVER_CONTEXT_LIMITS["max_endpoints"])
        self.assertTrue(len(ctx.failure_boundaries) <= SOLVER_CONTEXT_LIMITS["max_failure_boundaries"])
        self.assertTrue(len(ctx.recent_tool_outcomes) <= SOLVER_CONTEXT_LIMITS["max_recent_tool_outcomes"])

        # Key evidence must be preserved (high-confidence entries survive)
        self.assertTrue(any(c.confidence >= 0.9 for c in ctx.credentials),
                        "High-confidence credentials must be preserved after bounding")


class TestL4BackwardCompatibility(unittest.TestCase):
    """All existing SolverContextPack fields work after L4 expansion."""

    def test_backward_compatibility_existing_fields(self):
        ctx = SolverContextPack()
        # Original fields
        self.assertEqual(ctx.profile, "")
        self.assertIsNone(ctx.active_idea)
        self.assertEqual(ctx.local_memory, [])
        self.assertEqual(ctx.global_facts, [])
        self.assertEqual(ctx.inbox, [])
        self.assertEqual(ctx.failure_boundaries, [])
        self.assertEqual(ctx.solver_id, "")
        self.assertEqual(ctx.project_id, "")
        # L4 new fields
        self.assertEqual(ctx.credentials, [])
        self.assertEqual(ctx.endpoints, [])
        self.assertEqual(ctx.recent_tool_outcomes, [])
        self.assertEqual(ctx.budget_constraints, {})
        self.assertEqual(ctx.scratchpad_summary, "")
        self.assertEqual(ctx.recent_event_ids, [])

    def test_is_boundary_repetition_default(self):
        ctx = SolverContextPack()
        # No boundaries — no repetition detected
        self.assertFalse(ctx.is_boundary_repetition("anything"))


class TestL4MemoryReducer(unittest.TestCase):
    """MemoryReducer extracts structured memory from events."""

    def setUp(self):
        self.bb = _make_bb("reducer")
        self.reducer = MemoryReducer()

    def tearDown(self):
        self.bb.close()

    def test_memory_reducer_extracts_credentials_from_session_state(self):
        # Write a session_state observation event (as _execute_solver_cycle does)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "kind": "session_state",
            "cookies_count": 3,
            "auth_headers_keys": ["Authorization", "X-Token"],
            "summary": "session_state: 3 cookies, 2 auth headers",
        }, source="team_runtime_executor")

        events = self.bb.load_events("p1")
        reduced = self.reducer.reduce_observations(events, "p1")

        # Credential must be extracted
        self.assertTrue(len(reduced.credentials) >= 1,
                        "session_state with cookies/auth must produce CREDENTIAL")
        self.assertEqual(reduced.credentials[0].kind, MemoryKind.CREDENTIAL)

    def test_memory_reducer_extracts_endpoints(self):
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "kind": "http-request",
            "summary": "GET /api/users",
        }, source="executor")
        events = self.bb.load_events("p1")
        reduced = self.reducer.reduce_observations(events, "p1")
        self.assertTrue(len(reduced.endpoints) >= 1)
        self.assertEqual(reduced.endpoints[0].kind, MemoryKind.ENDPOINT)

    def test_memory_reducer_extracts_failure_boundaries(self):
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error",
            "error": "SQLi blocked by WAF",
        }, source="executor")
        events = self.bb.load_events("p1")
        reduced = self.reducer.reduce_observations(events, "p1")
        self.assertTrue(len(reduced.failure_boundaries) >= 1)
        self.assertEqual(reduced.failure_boundaries[0].kind, MemoryKind.FAILURE_BOUNDARY)

    def test_memory_reducer_builds_scratchpad(self):
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "kind": "fact",
            "summary": "found endpoint",
            "confidence": 0.8,
        }, source="executor")
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error",
            "error": "blocked",
        }, source="executor")
        events = self.bb.load_events("p1")
        reduced = self.reducer.reduce_observations(events, "p1")
        self.assertTrue(len(reduced.scratchpad_summary) > 0)
        # Scratchpad must include facts and boundaries
        self.assertIn("Facts", reduced.scratchpad_summary)
        self.assertIn("Boundaries", reduced.scratchpad_summary)

    def test_memory_reducer_scratchpad_bounded(self):
        # Very long summaries should be truncated
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "kind": "fact",
            "summary": "A" * 600,
            "confidence": 0.8,
        }, source="executor")
        events = self.bb.load_events("p1")
        reduced = self.reducer.reduce_observations(events, "p1")
        max_chars = SOLVER_CONTEXT_LIMITS["max_scratchpad_summary_chars"]
        self.assertTrue(len(reduced.scratchpad_summary) <= max_chars)


if __name__ == "__main__":
    unittest.main()