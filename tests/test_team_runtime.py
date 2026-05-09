"""Tests for TeamRuntime — Phase H main entry point."""

import os
import tempfile
import unittest

from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.protocol import (
    ActionType,
    HumanDecisionChoice,
    IdeaStatus,
    MemoryKind,
    PolicyOutcome,
    ReviewRequest,
    ReviewStatus,
    StrategyAction,
    TeamProject,
    to_dict,
)
from attack_agent.team.runtime import (
    ProjectStatusReport,
    SubmissionResult,
    TeamRuntime,
    TeamRuntimeConfig,
)


class TestTeamRuntimeInit(unittest.TestCase):
    """TeamRuntime construction and component initialization."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)

    def tearDown(self):
        try:
            self.runtime.close()
        except Exception:
            pass

    def test_runtime_creates_all_components(self):
        self.runtime = TeamRuntime(self.config)
        self.assertIsNotNone(self.runtime.blackboard)
        self.assertIsNotNone(self.runtime.manager)
        self.assertIsNotNone(self.runtime.scheduler)
        self.assertIsNotNone(self.runtime.solver_manager)
        self.assertIsNotNone(self.runtime.memory)
        self.assertIsNotNone(self.runtime.ideas)
        self.assertIsNotNone(self.runtime.context)
        self.assertIsNotNone(self.runtime.policy)
        self.assertIsNotNone(self.runtime.review_gate)
        self.assertIsNotNone(self.runtime.merge)
        self.assertIsNotNone(self.runtime.verifier)
        self.assertIsNotNone(self.runtime.observer)

    def test_config_defaults(self):
        config = TeamRuntimeConfig()
        self.assertEqual(config.max_cycles, 12)
        self.assertEqual(config.max_project_solvers, 1)
        self.assertEqual(config.max_submissions, 3)


class TestTeamRuntimeRunProject(unittest.TestCase):
    """TeamRuntime.run_project and run_all."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        self.runtime = TeamRuntime(self.config)

    def tearDown(self):
        self.runtime.close()

    def test_run_project_creates_project_events(self):
        project = self.runtime.run_project("web-auth-easy")
        self.assertIsNotNone(project)
        self.assertEqual(project.challenge_id, "web-auth-easy")
        # project should be in done or abandoned state after scheduler cycles
        self.assertIn(project.status, ("done", "abandoned", "new"))

    def test_run_all_returns_multiple_projects(self):
        results = self.runtime.run_all(["challenge-1", "challenge-2"])
        self.assertEqual(len(results), 2)
        self.assertIn("challenge-1", results)
        self.assertIn("challenge-2", results)


class TestTeamRuntimeGetStatus(unittest.TestCase):
    """TeamRuntime.get_status and list_projects."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        self.runtime = TeamRuntime(self.config)
        # seed a project into blackboard
        self.project = TeamProject(challenge_id="test-challenge", status="running")
        self.runtime.blackboard.append_event(
            project_id=self.project.project_id,
            event_type="project_upserted",
            payload=to_dict(self.project),
            source="test",
        )

    def tearDown(self):
        self.runtime.close()

    def test_get_status_returns_complete_report(self):
        report = self.runtime.get_status(self.project.project_id)
        self.assertIsInstance(report, ProjectStatusReport)
        self.assertEqual(report.project_id, self.project.project_id)
        self.assertEqual(report.challenge_id, "test-challenge")
        self.assertEqual(report.status, "running")
        self.assertIsInstance(report.solver_count, int)
        self.assertIsInstance(report.idea_count, int)
        self.assertIsInstance(report.fact_count, int)
        self.assertIsInstance(report.pending_review_count, int)

    def test_list_projects_returns_project_ids(self):
        reports = self.runtime.list_projects()
        self.assertGreaterEqual(len(reports), 1)
        found = [r for r in reports if r.project_id == self.project.project_id]
        self.assertEqual(len(found), 1)


class TestTeamRuntimeSubmitFlag(unittest.TestCase):
    """TeamRuntime.submit_flag verification chain."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        self.runtime = TeamRuntime(self.config)
        # seed a project so verifier can find it
        self.project = TeamProject(challenge_id="ctf-1", status="running")
        self.runtime.blackboard.append_event(
            project_id=self.project.project_id,
            event_type="project_upserted",
            payload=to_dict(self.project),
            source="test",
        )

    def tearDown(self):
        self.runtime.close()

    def test_submit_flag_valid_flag_submitted(self):
        result = self.runtime.submit_flag(
            self.project.project_id, "flag{test_flag}"
        )
        self.assertIsInstance(result, SubmissionResult)
        # valid flag format, low risk → should be submitted or needs_review
        self.assertIn(result.status, ("submitted", "needs_review", "rejected", "failed"))

    def test_submit_flag_invalid_format_fails(self):
        result = self.runtime.submit_flag(
            self.project.project_id, "not_a_flag"
        )
        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.verification_result)
        self.assertEqual(result.verification_result.status, "failed")


class TestTeamRuntimeReview(unittest.TestCase):
    """TeamRuntime.resolve_review approve/reject/modify."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        self.runtime = TeamRuntime(self.config)
        self.project = TeamProject(challenge_id="review-test", status="running")
        self.runtime.blackboard.append_event(
            project_id=self.project.project_id,
            event_type="project_upserted",
            payload=to_dict(self.project),
            source="test",
        )
        # create a review request
        self.request = ReviewRequest(
            project_id=self.project.project_id,
            action_type="submit_flag",
            risk_level="high",
            title="Test review",
            description="Review test flag",
            proposed_action="submit flag{review_test}",
        )
        self.runtime.review_gate.create_review(self.request, self.runtime.blackboard)

    def tearDown(self):
        self.runtime.close()

    def test_resolve_review_approve(self):
        result = self.runtime.resolve_review(
            self.request.request_id,
            HumanDecisionChoice.APPROVED,
            reason="looks good",
            project_id=self.project.project_id,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ReviewStatus.APPROVED)

    def test_resolve_review_reject(self):
        result = self.runtime.resolve_review(
            self.request.request_id,
            HumanDecisionChoice.REJECTED,
            reason="bad flag",
            project_id=self.project.project_id,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ReviewStatus.REJECTED)

    def test_get_pending_reviews(self):
        reviews = self.runtime.get_pending_reviews(self.project.project_id)
        self.assertGreaterEqual(len(reviews), 1)


class TestTeamRuntimeObserve(unittest.TestCase):
    """TeamRuntime.observe returns ObservationReport."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        self.runtime = TeamRuntime(self.config)
        self.project = TeamProject(challenge_id="observe-test", status="running")
        self.runtime.blackboard.append_event(
            project_id=self.project.project_id,
            event_type="project_upserted",
            payload=to_dict(self.project),
            source="test",
        )

    def tearDown(self):
        self.runtime.close()

    def test_observe_returns_report(self):
        from attack_agent.team.observer import ObservationReport
        report = self.runtime.observe(self.project.project_id)
        self.assertIsInstance(report, ObservationReport)
        self.assertEqual(report.project_id, self.project.project_id)


class TestTeamRuntimeReplay(unittest.TestCase):
    """TeamRuntime.replay returns event log."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        self.runtime = TeamRuntime(self.config)
        self.project = TeamProject(challenge_id="replay-test", status="running")
        self.runtime.blackboard.append_event(
            project_id=self.project.project_id,
            event_type="project_upserted",
            payload=to_dict(self.project),
            source="test",
        )

    def tearDown(self):
        self.runtime.close()

    def test_replay_returns_event_log(self):
        log = self.runtime.replay(self.project.project_id)
        self.assertIsInstance(log, list)
        self.assertGreaterEqual(len(log), 1)
        # each entry should be a dict with event_type
        self.assertIn("event_type", log[0])


if __name__ == "__main__":
    unittest.main()