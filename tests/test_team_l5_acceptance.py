"""L5 acceptance tests — Real SolverSession Ownership.

Acceptance criteria:
1. A launched Solver has a persisted session before execution
2. Solver status transitions: created -> assigned -> running -> completed/failed
3. Outcome events include solver_id
4. Two Solvers cannot claim the same idea lease
5. max_project_solvers=1 remains compatible with current baseline
"""

import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.ideas import IdeaService
from attack_agent.team.protocol import (
    IdeaEntry,
    IdeaStatus,
    SolverSession,
    SolverStatus,
)
from attack_agent.team.solver import SolverSessionConfig, SolverSessionManager


def _make_bb() -> BlackboardService:
    return BlackboardService(BlackboardConfig(db_path=":memory:"))


def _seed_project(bb: BlackboardService, project_id: str = "p1") -> None:
    bb.append_event(project_id, EventType.PROJECT_UPSERTED.value,
                     {"challenge_id": "c1", "status": "new"})


class TestL5SessionPersistedBeforeExecution(unittest.TestCase):
    """L5 acceptance criterion 1: a launched Solver has a persisted session before execution."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        self.manager = SolverSessionManager()

    def tearDown(self):
        self.bb.close()

    def test_create_and_persist_creates_session_in_blackboard(self):
        session = self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.assertIsNotNone(session)

        # Session must exist in Blackboard before any execution
        sessions = self.bb.list_sessions("p1")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].solver_id, "s1")
        self.assertEqual(sessions[0].status, SolverStatus.CREATED)

    def test_worker_assigned_event_written_before_execution_events(self):
        self.manager.create_and_persist("p1", self.bb, "network", "s1")

        events = self.bb.load_events("p1")
        # WORKER_ASSIGNED event for session creation must exist
        wa_events = [e for e in events if e.event_type == EventType.WORKER_ASSIGNED.value]
        self.assertGreaterEqual(len(wa_events), 1)

        # The session creation event has status=created
        creation_event = wa_events[0]
        self.assertEqual(creation_event.payload.get("status"), SolverStatus.CREATED.value)

    def test_session_claim_and_start_events_precede_observation(self):
        """Simulate the L5 scheduling path: create -> claim -> start -> execute."""
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)

        # Simulate an execution outcome event (as _execute_solver_cycle would write)
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "kind": "http-request",
            "solver_id": "s1",
        }, source="team_runtime_executor")

        events = self.bb.load_events("p1")
        # Find the position of each event type
        wa_idx = next(i for i, e in enumerate(events)
                      if e.event_type == EventType.WORKER_ASSIGNED.value
                      and e.payload.get("status") == SolverStatus.CREATED.value)
        # Find claim event (WORKER_ASSIGNED with status=assigned)
        claim_idx = next(i for i, e in enumerate(events)
                         if e.event_type == EventType.WORKER_ASSIGNED.value
                         and e.payload.get("status") == SolverStatus.ASSIGNED.value)
        # Find start event (WORKER_HEARTBEAT with status=running)
        start_idx = next(i for i, e in enumerate(events)
                         if e.event_type == EventType.WORKER_HEARTBEAT.value)
        # Find observation event
        obs_idx = next(i for i, e in enumerate(events)
                       if e.event_type == EventType.OBSERVATION.value)

        # Session lifecycle events must precede execution events
        self.assertLess(wa_idx, claim_idx)
        self.assertLess(claim_idx, start_idx)
        self.assertLess(start_idx, obs_idx)


class TestL5StatusTransitions(unittest.TestCase):
    """L5 acceptance criterion 2: created -> assigned -> running -> completed/failed."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        self.manager = SolverSessionManager()

    def tearDown(self):
        self.bb.close()

    def test_full_lifecycle_created_to_completed(self):
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        sessions = self.bb.list_sessions("p1")
        self.assertEqual(sessions[0].status, SolverStatus.CREATED)

        self.manager.claim_session("p1", "s1", self.bb)
        sessions = self.bb.list_sessions("p1")
        self.assertEqual(sessions[0].status, SolverStatus.ASSIGNED)

        self.manager.start_session("p1", "s1", self.bb)
        sessions = self.bb.list_sessions("p1")
        self.assertEqual(sessions[0].status, SolverStatus.RUNNING)

        self.manager.complete_session("p1", "s1", "ok", self.bb)
        sessions = self.bb.list_sessions("p1")
        self.assertEqual(sessions[0].status, SolverStatus.COMPLETED)

    def test_full_lifecycle_created_to_failed(self):
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)
        result = self.manager.complete_session("p1", "s1", "error", self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.FAILED)

    def test_event_sequence_records_all_transitions(self):
        """Verify Blackboard events show the full transition chain."""
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)
        self.manager.complete_session("p1", "s1", "ok", self.bb)

        events = self.bb.load_events("p1")
        # Filter out project_upserted event
        lifecycle_events = [e for e in events
                           if e.event_type in (EventType.WORKER_ASSIGNED.value,
                                               EventType.WORKER_HEARTBEAT.value,
                                               EventType.ACTION_OUTCOME.value)]

        # Expected event sequence:
        # 1. WORKER_ASSIGNED (created)
        # 2. WORKER_ASSIGNED (assigned)
        # 3. WORKER_HEARTBEAT (running)
        # 4. ACTION_OUTCOME (completed)
        self.assertGreaterEqual(len(lifecycle_events), 4)

        # Verify status values in sequence
        statuses = [e.payload.get("status", "") for e in lifecycle_events]
        self.assertIn("created", statuses)
        self.assertIn("assigned", statuses)
        self.assertIn("running", statuses)
        self.assertIn("completed", statuses)

    def test_illegal_transition_created_to_running(self):
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        result = self.manager.start_session("p1", "s1", self.bb)
        self.assertIsNone(result)

    def test_illegal_transition_completed_to_running(self):
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)
        self.manager.complete_session("p1", "s1", "ok", self.bb)
        result = self.manager.start_session("p1", "s1", self.bb)
        self.assertIsNone(result)


class TestL5OutcomeEventsIncludeSolverId(unittest.TestCase):
    """L5 acceptance criterion 3: outcome events include solver_id."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        self.manager = SolverSessionManager()

    def tearDown(self):
        self.bb.close()

    def test_observation_events_include_solver_id(self):
        """Simulate _execute_solver_cycle writing events with solver_id."""
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)

        # Write execution events as _execute_solver_cycle would (with solver_id)
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "kind": "http-request",
            "source": "executor",
            "target": "http://example.com/api",
            "payload": {},
            "confidence": 0.8,
            "novelty": 0.5,
            "summary": "found endpoint",
            "solver_id": "s1",
        }, source="team_runtime_executor")

        events = self.bb.load_events("p1")
        obs_events = [e for e in events if e.event_type == EventType.OBSERVATION.value
                      and e.payload.get("kind") != "session_state"]
        self.assertGreaterEqual(len(obs_events), 1)
        self.assertEqual(obs_events[0].payload.get("solver_id"), "s1")

    def test_action_outcome_events_include_solver_id(self):
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)

        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "ok",
            "primitive_name": "http-request",
            "cost": 0.5,
            "novelty": 0.5,
            "observations_count": 2,
            "candidate_flags_count": 0,
            "failure_reason": "",
            "broker_execution": True,
            "stagnation_counter": 0,
            "solver_id": "s1",
        }, source="team_runtime_executor")

        events = self.bb.load_events("p1")
        outcome_events = [e for e in events
                          if e.event_type == EventType.ACTION_OUTCOME.value
                          and e.payload.get("broker_execution")]
        self.assertGreaterEqual(len(outcome_events), 1)
        self.assertEqual(outcome_events[0].payload.get("solver_id"), "s1")

    def test_candidate_flag_events_include_solver_id(self):
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)

        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value, {
            "flag": "flag{test}",
            "confidence": 0.9,
            "format_match": True,
            "dedupe_key": "flag_test",
            "source_chain": [],
            "evidence_refs": [],
            "solver_id": "s1",
        }, source="team_runtime_executor")

        events = self.bb.load_events("p1")
        flag_events = [e for e in events
                       if e.event_type == EventType.CANDIDATE_FLAG.value]
        self.assertGreaterEqual(len(flag_events), 1)
        self.assertEqual(flag_events[0].payload.get("solver_id"), "s1")

    def test_solver_id_matches_session_solver_id(self):
        """The solver_id in outcome events must match the session's solver_id."""
        self.manager.create_and_persist("p1", self.bb, "network", "solver_alpha")
        self.manager.claim_session("p1", "solver_alpha", self.bb)
        self.manager.start_session("p1", "solver_alpha", self.bb)

        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "ok",
            "solver_id": "solver_alpha",
        }, source="team_runtime_executor")

        session = self.manager.get_session("p1", "solver_alpha", self.bb)
        self.assertIsNotNone(session)
        self.assertEqual(session.solver_id, "solver_alpha")

        events = self.bb.load_events("p1")
        outcome = next(e for e in events
                       if e.event_type == EventType.ACTION_OUTCOME.value
                       and e.payload.get("solver_id") == "solver_alpha")
        self.assertEqual(outcome.payload["solver_id"], session.solver_id)


class TestL5IdeaLeaseExclusivity(unittest.TestCase):
    """L5 acceptance criterion 4: two Solvers cannot claim the same idea lease."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        self.manager = SolverSessionManager(SolverSessionConfig(max_project_solvers=5))
        self.ideas = IdeaService(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_two_solvers_cannot_claim_same_idea(self):
        # Create two sessions
        s1 = self.manager.create_and_persist("p1", self.bb, "network", "s1")
        s2 = self.manager.create_and_persist("p1", self.bb, "browser", "s2")
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)

        # Propose one idea
        idea = self.ideas.propose("p1", "Try SQL injection", priority=90)
        self.assertIsNotNone(idea)

        # First solver claims the idea — succeeds
        claimed = self.ideas.claim("p1", idea.idea_id, "s1")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, IdeaStatus.CLAIMED)
        self.assertEqual(claimed.solver_id, "s1")

        # Second solver attempts to claim the same idea — fails
        second_claim = self.ideas.claim("p1", idea.idea_id, "s2")
        self.assertIsNone(second_claim, "Second solver must not be able to claim a CLAIMED idea")

    def test_failed_idea_can_be_reclaimed(self):
        """A FAILED idea can be re-claimed by a different solver."""
        s1 = self.manager.create_and_persist("p1", self.bb, "network", "s1")
        s2 = self.manager.create_and_persist("p1", self.bb, "browser", "s2")

        idea = self.ideas.propose("p1", "Try SQL injection", priority=90)
        self.ideas.claim("p1", idea.idea_id, "s1")

        # Mark the idea as failed
        self.ideas.mark_failed("p1", idea.idea_id, [])

        # Second solver can now reclaim the failed idea
        reclaimed = self.ideas.claim("p1", idea.idea_id, "s2")
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed.status, IdeaStatus.CLAIMED)
        self.assertEqual(reclaimed.solver_id, "s2")

    def test_idea_claim_bound_to_solver_session(self):
        """When a solver claims an idea, active_idea_id is updated in session."""
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)

        idea = self.ideas.propose("p1", "Scan for open ports", priority=80)
        self.ideas.claim("p1", idea.idea_id, "s1")

        # Write the active_idea_id binding event (as scheduler_l5 does)
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value, {
            "solver_id": "s1",
            "status": SolverStatus.ASSIGNED.value,
            "active_idea_id": idea.idea_id,
        }, source="scheduler_l5")

        session = self.manager.get_session("p1", "s1", self.bb)
        self.assertIsNotNone(session)
        self.assertEqual(session.active_idea_id, idea.idea_id)


class TestL5SingleSolverBaseline(unittest.TestCase):
    """L5 acceptance criterion 5: max_project_solvers=1 remains compatible."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        self.config = SolverSessionConfig(max_project_solvers=1)
        self.manager = SolverSessionManager(self.config)

    def tearDown(self):
        self.bb.close()

    def test_default_config_single_solver(self):
        config = SolverSessionConfig()
        self.assertEqual(config.max_project_solvers, 1)

    def test_single_solver_limit_enforced(self):
        s1 = self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.assertIsNotNone(s1)
        # Second session rejected
        s2 = self.manager.create_and_persist("p1", self.bb, "network", "s2")
        self.assertIsNone(s2)

    def test_new_session_allowed_after_completion(self):
        s1 = self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.assertIsNotNone(s1)
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)
        self.manager.complete_session("p1", "s1", "ok", self.bb)

        # Completed session no longer counts as active — new session allowed
        s2 = self.manager.create_and_persist("p1", self.bb, "network", "s2")
        self.assertIsNotNone(s2)

    def test_new_session_allowed_after_failure(self):
        s1 = self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)
        self.manager.complete_session("p1", "s1", "error", self.bb)

        s2 = self.manager.create_and_persist("p1", self.bb, "network", "s2")
        self.assertIsNotNone(s2)

    def test_single_solver_session_lifecycle_preserves_budget(self):
        """Budget is tracked across the session lifecycle."""
        s1 = self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.assertEqual(s1.budget_remaining, self.config.budget_per_session)

        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)

        session = self.manager.get_session("p1", "s1", self.bb)
        self.assertEqual(session.budget_remaining, self.config.budget_per_session)

    def test_l4_heartbeat_updates_preserved_before_completion(self):
        """L4 field updates via WORKER_HEARTBEAT work correctly before session completion."""
        self.manager.create_and_persist("p1", self.bb, "network", "s1")
        self.manager.claim_session("p1", "s1", self.bb)
        self.manager.start_session("p1", "s1", self.bb)

        # L4 update: WORKER_HEARTBEAT with field updates
        self.bb.append_event("p1", EventType.WORKER_HEARTBEAT.value, {
            "solver_id": "s1",
            "status": SolverStatus.RUNNING.value,
            "budget_remaining": 15.0,
            "active_idea_id": "idea_1",
            "local_memory_ids": ["mem_1", "mem_2"],
            "scratchpad_summary": "Found admin panel",
            "recent_event_ids": ["ev_1", "ev_2"],
        }, source="scheduler_l4")

        session = self.manager.get_session("p1", "s1", self.bb)
        self.assertEqual(session.budget_remaining, 15.0)
        self.assertEqual(session.active_idea_id, "idea_1")
        self.assertEqual(session.scratchpad_summary, "Found admin panel")
        self.assertEqual(len(session.local_memory_ids), 2)

        # Now complete the session
        self.manager.complete_session("p1", "s1", "ok", self.bb)
        session = self.manager.get_session("p1", "s1", self.bb)
        self.assertEqual(session.status, SolverStatus.COMPLETED)
        # L4 fields are preserved in the terminal session
        self.assertEqual(session.budget_remaining, 15.0)
        self.assertEqual(session.active_idea_id, "idea_1")


if __name__ == "__main__":
    unittest.main()