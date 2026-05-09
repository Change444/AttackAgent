"""Tests for SolverSessionManager — Phase F."""

import unittest

from attack_agent.platform_models import (
    ActionProgram,
    ChallengeDefinition,
    ChallengeInstance,
    EventType,
    PrimitiveActionStep,
    ProjectStage,
    TaskBundle,
    WorkerProfile,
)
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.protocol import SolverSession, SolverStatus
from attack_agent.team.solver import SolverSessionConfig, SolverSessionManager


def _make_bundle(project_id: str = "proj1") -> TaskBundle:
    """Create a minimal TaskBundle for testing create_session_from_bundle."""
    return TaskBundle(
        project_id=project_id,
        run_id="run1",
        action_program=ActionProgram(
            id="ap1",
            goal="test",
            pattern_nodes=["n1"],
            steps=[PrimitiveActionStep(primitive="http-request", instruction="do it")],
            allowed_primitives=["http-request"],
            verification_rules=["v1"],
            required_profile=WorkerProfile.NETWORK,
        ),
        stage=ProjectStage.BOOTSTRAP,
        worker_profile=WorkerProfile.NETWORK,
        target="http://example.com",
        challenge=ChallengeDefinition(
            id="c1", name="test", category="web", difficulty="easy", target="http://example.com",
        ),
        instance=ChallengeInstance(
            instance_id="i1", challenge_id="c1", target="http://example.com", status="active",
        ),
        handoff_summary="",
        visible_primitives=["http-request"],
    )


class TestSolverSessionCreate(unittest.TestCase):
    """SolverSessionManager.create_session and create_and_persist."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def test_create_session_returns_solver_session(self) -> None:
        session = self.manager.create_session("proj1", "network", "solver1")
        self.assertIsNotNone(session)
        self.assertEqual(session.solver_id, "solver1")
        self.assertEqual(session.project_id, "proj1")
        self.assertEqual(session.profile, "network")
        self.assertEqual(session.status, SolverStatus.CREATED)
        self.assertEqual(session.budget_remaining, SolverSessionConfig().budget_per_session)

    def test_create_and_persist_writes_to_blackboard(self) -> None:
        session = self.manager.create_and_persist("proj1", self.bb, "network", "solver1")
        self.assertIsNotNone(session)
        sessions = self.bb.list_sessions("proj1")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].solver_id, "solver1")
        self.assertEqual(sessions[0].status, SolverStatus.CREATED)

    def test_create_and_persist_rejects_when_max_solvers_reached(self) -> None:
        config = SolverSessionConfig(max_project_solvers=1)
        manager = SolverSessionManager(config)
        session1 = manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.assertIsNotNone(session1)
        # Second session should be rejected (max_project_solvers=1, one active)
        session2 = manager.create_and_persist("proj1", self.bb, "network", "s2")
        self.assertIsNone(session2)

    def test_create_and_persist_allows_when_active_session_completed(self) -> None:
        config = SolverSessionConfig(max_project_solvers=1)
        manager = SolverSessionManager(config)
        session1 = manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.assertIsNotNone(session1)
        # Complete the first session
        manager.claim_session("proj1", "s1", self.bb)
        manager.start_session("proj1", "s1", self.bb)
        manager.complete_session("proj1", "s1", "ok", self.bb)
        # Now a new session should be allowed
        session2 = manager.create_and_persist("proj1", self.bb, "network", "s2")
        self.assertIsNotNone(session2)

    def test_concurrency_limit_with_max_project_solvers_2(self) -> None:
        config = SolverSessionConfig(max_project_solvers=2)
        manager = SolverSessionManager(config)
        s1 = manager.create_and_persist("proj1", self.bb, "network", "s1")
        s2 = manager.create_and_persist("proj1", self.bb, "network", "s2")
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        # Third session rejected
        s3 = manager.create_and_persist("proj1", self.bb, "network", "s3")
        self.assertIsNone(s3)


class TestSolverStateMachine(unittest.TestCase):
    """SolverSession state machine transitions: created→assigned→running→completed/failed."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def _create_and_claim_and_start(self, solver_id: str = "s1") -> SolverSession:
        self.manager.create_and_persist("proj1", self.bb, "network", solver_id)
        self.manager.claim_session("proj1", solver_id, self.bb)
        return self.manager.start_session("proj1", solver_id, self.bb)

    def test_created_to_assigned(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        session = self.manager.claim_session("proj1", "s1", self.bb)
        self.assertIsNotNone(session)
        self.assertEqual(session.status, SolverStatus.ASSIGNED)

    def test_assigned_to_running(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        session = self.manager.start_session("proj1", "s1", self.bb)
        self.assertIsNotNone(session)
        self.assertEqual(session.status, SolverStatus.RUNNING)

    def test_running_to_completed(self) -> None:
        session = self._create_and_claim_and_start("s1")
        result = self.manager.complete_session("proj1", "s1", "ok", self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.COMPLETED)

    def test_running_to_failed(self) -> None:
        session = self._create_and_claim_and_start("s1")
        result = self.manager.complete_session("proj1", "s1", "error", self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.FAILED)

    def test_illegal_created_to_running(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        # Skip claim — going directly created→running is illegal
        result = self.manager.start_session("proj1", "s1", self.bb)
        self.assertIsNone(result)

    def test_illegal_completed_to_running(self) -> None:
        self._create_and_claim_and_start("s1")
        self.manager.complete_session("proj1", "s1", "ok", self.bb)
        # Can't transition completed→running
        result = self.manager.start_session("proj1", "s1", self.bb)
        self.assertIsNone(result)


class TestDuplicateCompletionRejection(unittest.TestCase):
    """Duplicate completion rejection: terminal sessions reject second complete."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def test_duplicate_completion_rejected(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        result1 = self.manager.complete_session("proj1", "s1", "ok", self.bb)
        self.assertIsNotNone(result1)
        result2 = self.manager.complete_session("proj1", "s1", "ok", self.bb)
        self.assertIsNone(result2)

    def test_duplicate_completion_on_failed_session(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        self.manager.complete_session("proj1", "s1", "error", self.bb)
        result = self.manager.complete_session("proj1", "s1", "ok", self.bb)
        self.assertIsNone(result)


class TestExpireSession(unittest.TestCase):
    """expire_session: timed-out sessions marked as expired."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def test_expire_running_session(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        result = self.manager.expire_session("proj1", "s1", 300, self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.EXPIRED)

    def test_expire_created_session(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        result = self.manager.expire_session("proj1", "s1", 300, self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.EXPIRED)

    def test_expire_assigned_session(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        result = self.manager.expire_session("proj1", "s1", 300, self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.EXPIRED)

    def test_expire_terminal_session_rejected(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        self.manager.complete_session("proj1", "s1", "ok", self.bb)
        result = self.manager.expire_session("proj1", "s1", 300, self.bb)
        self.assertIsNone(result)


class TestCancelSession(unittest.TestCase):
    """cancel_session: sessions can be cancelled from non-terminal states."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def test_cancel_created_session(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        result = self.manager.cancel_session("proj1", "s1", "no longer needed", self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.CANCELLED)

    def test_cancel_running_session(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        result = self.manager.cancel_session("proj1", "s1", "aborted", self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.CANCELLED)

    def test_cancel_terminal_session_rejected(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        self.manager.complete_session("proj1", "s1", "ok", self.bb)
        result = self.manager.cancel_session("proj1", "s1", "too late", self.bb)
        self.assertIsNone(result)


class TestHeartbeat(unittest.TestCase):
    """heartbeat: writes WORKER_HEARTBEAT event for running sessions."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def test_heartbeat_running_session(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        result = self.manager.heartbeat("proj1", "s1", self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SolverStatus.RUNNING)
        # Verify heartbeat event was written
        events = self.bb.load_events("proj1")
        heartbeat_events = [e for e in events if e.event_type == EventType.WORKER_HEARTBEAT.value]
        # At least 2: one for start_session (running), one for heartbeat
        self.assertGreaterEqual(len(heartbeat_events), 2)

    def test_heartbeat_non_running_session_rejected(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        result = self.manager.heartbeat("proj1", "s1", self.bb)
        self.assertIsNone(result)


class TestCreateSessionFromBundle(unittest.TestCase):
    """create_session_from_bundle: TaskBundle → SolverSession bridge."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def test_create_session_from_bundle(self) -> None:
        bundle = _make_bundle("proj1")
        session = self.manager.create_session_from_bundle(bundle, "proj1", self.bb)
        self.assertIsNotNone(session)
        self.assertEqual(session.profile, "network")
        self.assertEqual(session.status, SolverStatus.CREATED)
        self.assertEqual(session.budget_remaining, SolverSessionConfig().budget_per_session)

    def test_create_from_bundle_rejected_when_limit_reached(self) -> None:
        config = SolverSessionConfig(max_project_solvers=1)
        manager = SolverSessionManager(config)
        bundle1 = _make_bundle("proj1")
        s1 = manager.create_session_from_bundle(bundle1, "proj1", self.bb)
        self.assertIsNotNone(s1)
        bundle2 = _make_bundle("proj1")
        s2 = manager.create_session_from_bundle(bundle2, "proj1", self.bb)
        self.assertIsNone(s2)


class TestGetAndListSessions(unittest.TestCase):
    """get_session / list_sessions query methods."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def test_get_session_returns_correct_session(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        session = self.manager.get_session("proj1", "s1", self.bb)
        self.assertIsNotNone(session)
        self.assertEqual(session.solver_id, "s1")
        self.assertEqual(session.status, SolverStatus.CREATED)

    def test_get_session_returns_none_for_unknown_solver(self) -> None:
        session = self.manager.get_session("proj1", "nonexistent", self.bb)
        self.assertIsNone(session)

    def test_list_sessions_returns_all_sessions(self) -> None:
        config = SolverSessionConfig(max_project_solvers=5)
        manager = SolverSessionManager(config)
        manager.create_and_persist("proj1", self.bb, "network", "s1")
        manager.create_and_persist("proj1", self.bb, "browser", "s2")
        sessions = manager.list_sessions("proj1", self.bb)
        self.assertEqual(len(sessions), 2)
        solver_ids = {s.solver_id for s in sessions}
        self.assertEqual(solver_ids, {"s1", "s2"})

    def test_list_sessions_empty_project(self) -> None:
        sessions = self.manager.list_sessions("proj1", self.bb)
        self.assertEqual(len(sessions), 0)


class TestDefaultSingleSessionBaseline(unittest.TestCase):
    """Default max_project_solvers=1 ensures existing baseline behavior."""

    def test_default_config_is_single_solver(self) -> None:
        config = SolverSessionConfig()
        self.assertEqual(config.max_project_solvers, 1)

    def test_default_session_timeout(self) -> None:
        config = SolverSessionConfig()
        self.assertEqual(config.session_timeout_seconds, 300)

    def test_default_budget(self) -> None:
        config = SolverSessionConfig()
        self.assertEqual(config.budget_per_session, 20.0)


class TestSessionMaterializedState(unittest.TestCase):
    """Blackboard materialized state correctly tracks session lifecycle transitions."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event("proj1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        self.manager = SolverSessionManager()

    def tearDown(self) -> None:
        self.bb.close()

    def test_full_lifecycle_materialized_state(self) -> None:
        # created → assigned → running → completed
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        sessions = self.bb.list_sessions("proj1")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].status, SolverStatus.CREATED)

        self.manager.claim_session("proj1", "s1", self.bb)
        sessions = self.bb.list_sessions("proj1")
        self.assertEqual(sessions[0].status, SolverStatus.ASSIGNED)

        self.manager.start_session("proj1", "s1", self.bb)
        sessions = self.bb.list_sessions("proj1")
        self.assertEqual(sessions[0].status, SolverStatus.RUNNING)

        self.manager.complete_session("proj1", "s1", "ok", self.bb)
        sessions = self.bb.list_sessions("proj1")
        self.assertEqual(sessions[0].status, SolverStatus.COMPLETED)

    def test_failed_lifecycle_materialized_state(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        self.manager.complete_session("proj1", "s1", "timeout", self.bb)
        sessions = self.bb.list_sessions("proj1")
        self.assertEqual(sessions[0].status, SolverStatus.FAILED)

    def test_expired_lifecycle_materialized_state(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        self.manager.expire_session("proj1", "s1", 300, self.bb)
        sessions = self.bb.list_sessions("proj1")
        self.assertEqual(sessions[0].status, SolverStatus.EXPIRED)

    def test_cancelled_lifecycle_materialized_state(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.cancel_session("proj1", "s1", "aborted", self.bb)
        sessions = self.bb.list_sessions("proj1")
        self.assertEqual(sessions[0].status, SolverStatus.CANCELLED)

    def test_budget_remaining_preserved_across_transitions(self) -> None:
        self.manager.create_and_persist("proj1", self.bb, "network", "s1")
        self.manager.claim_session("proj1", "s1", self.bb)
        self.manager.start_session("proj1", "s1", self.bb)
        session = self.manager.get_session("proj1", "s1", self.bb)
        self.assertEqual(session.budget_remaining, SolverSessionConfig().budget_per_session)


if __name__ == "__main__":
    unittest.main()