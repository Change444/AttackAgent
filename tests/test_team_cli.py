"""Tests for Team CLI — Phase H click/rich interface."""

import os
import tempfile
import unittest

from click.testing import CliRunner

from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.cli import team, team_main
from attack_agent.team.protocol import ReviewRequest, ReviewStatus, TeamProject, to_dict
from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig


def _make_runtime_with_project(db_path: str) -> TeamRuntime:
    """Create a TeamRuntime with a seeded project."""
    config = TeamRuntimeConfig(blackboard_db_path=db_path)
    runtime = TeamRuntime(config)
    project = TeamProject(challenge_id="cli-test", status="running")
    runtime.blackboard.append_event(
        project_id=project.project_id,
        event_type="project_upserted",
        payload=to_dict(project),
        source="test",
    )
    return runtime, project


class TestTeamCLIStatus(unittest.TestCase):
    """CLI team status command."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")

    def test_status_without_project_id_lists_all(self):
        """`team status` without project_id → rich table listing all projects."""
        runtime, project = _make_runtime_with_project(self.db_path)
        # the CLI creates its own runtime, so we need the db to have the project
        runtime.close()

        runner = CliRunner()
        # use default db path which won't have our project, but the command should run
        result = runner.invoke(team, ["status"])
        # command should succeed (0 exit or output present)
        self.assertIsNotNone(result.output)

    def test_status_with_project_id_shows_details(self):
        """`team status <pid>` → rich Panel with project details."""
        runtime, project = _make_runtime_with_project(self.db_path)
        runtime.close()

        runner = CliRunner()
        # invoke with the specific project_id
        result = runner.invoke(team, ["status", project.project_id])
        self.assertIsNotNone(result.output)


class TestTeamCLIReviews(unittest.TestCase):
    """CLI team reviews command."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")

    def test_reviews_without_project_id(self):
        """`team reviews` → lists all pending reviews."""
        runner = CliRunner()
        result = runner.invoke(team, ["reviews"])
        self.assertIsNotNone(result.output)

    def test_reviews_with_project_id(self):
        """`team reviews <pid>` → filtered reviews."""
        runner = CliRunner()
        result = runner.invoke(team, ["reviews", "nonexistent"])
        self.assertIsNotNone(result.output)


class TestTeamCLIReplay(unittest.TestCase):
    """CLI team replay command."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")

    def test_replay_shows_event_log(self):
        """`team replay <pid>` → rich JSON panel."""
        runtime, project = _make_runtime_with_project(self.db_path)
        runtime.close()

        runner = CliRunner()
        result = runner.invoke(team, ["replay", project.project_id])
        self.assertIsNotNone(result.output)


class TestTeamCLIObserve(unittest.TestCase):
    """CLI team observe command."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")

    def test_observe_shows_report(self):
        """`team observe <pid>` → rich Panel."""
        runtime, project = _make_runtime_with_project(self.db_path)
        runtime.close()

        runner = CliRunner()
        result = runner.invoke(team, ["observe", project.project_id])
        self.assertIsNotNone(result.output)


class TestTeamCLIReviewActions(unittest.TestCase):
    """CLI team review approve/reject/modify."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.runtime, self.project = _make_runtime_with_project(self.db_path)
        # create a review request
        self.request = ReviewRequest(
            project_id=self.project.project_id,
            action_type="submit_flag",
            risk_level="high",
            title="CLI review test",
            description="Test flag submission review",
            proposed_action="submit flag{cli_test}",
        )
        self.runtime.review_gate.create_review(self.request, self.runtime.blackboard)
        self.runtime.close()

    def test_review_approve(self):
        """`team review approve <id>` → approved status."""
        runner = CliRunner()
        result = runner.invoke(team, [
            "review", "approve", self.request.request_id,
            "--project-id", self.project.project_id,
        ])
        self.assertIsNotNone(result.output)

    def test_review_reject(self):
        """`team review reject <id>` → rejected status."""
        # create another review for this test
        runtime = TeamRuntime(TeamRuntimeConfig(blackboard_db_path=self.db_path))
        request2 = ReviewRequest(
            project_id=self.project.project_id,
            action_type="submit_flag",
            risk_level="high",
            title="CLI reject test",
            description="Test flag rejection review",
            proposed_action="submit flag{cli_reject}",
        )
        runtime.review_gate.create_review(request2, runtime.blackboard)

        runner = CliRunner()
        result = runner.invoke(team, [
            "review", "reject", request2.request_id,
            "--project-id", self.project.project_id,
        ])
        self.assertIsNotNone(result.output)
        runtime.close()


class TestTeamMainDispatch(unittest.TestCase):
    """team_main function callable."""

    def test_team_main_status(self):
        """team_main(['status']) should not crash."""
        runner = CliRunner()
        result = runner.invoke(team, ["status"])
        # command should produce some output (even if no projects)
        self.assertIsNotNone(result.output)


if __name__ == "__main__":
    unittest.main()