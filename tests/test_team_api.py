"""Tests for Team API — Phase H FastAPI endpoints."""

import os
import tempfile
import unittest

from attack_agent.team.api import create_app, make_api_router
from attack_agent.team.protocol import (
    HumanDecisionChoice,
    IdeaEntry,
    IdeaStatus,
    MemoryKind,
    ReviewRequest,
    SolverSession,
    SolverStatus,
    TeamProject,
    to_dict,
)
from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig


def _make_runtime_with_project(db_path: str) -> tuple[TeamRuntime, TeamProject]:
    """Create a TeamRuntime with a seeded project + observations."""
    config = TeamRuntimeConfig(blackboard_db_path=db_path)
    runtime = TeamRuntime(config)
    project = TeamProject(challenge_id="api-test", status="running")
    runtime.blackboard.append_event(
        project_id=project.project_id,
        event_type="project_upserted",
        payload=to_dict(project),
        source="test",
    )
    # seed a fact
    runtime.blackboard.append_event(
        project_id=project.project_id,
        event_type="observation",
        payload={
            "kind": MemoryKind.FACT.value,
            "entry_id": "fact-1",
            "content": "endpoint /admin exposed",
            "confidence": 0.8,
        },
        source="test_solver",
    )
    # seed an idea
    runtime.blackboard.append_event(
        project_id=project.project_id,
        event_type="candidate_flag",
        payload={
            "idea_id": "idea-1",
            "description": "flag{api_test}",
            "status": IdeaStatus.PENDING.value,
            "priority": 100,
        },
        source="test_solver",
    )
    # seed a solver session
    runtime.blackboard.append_event(
        project_id=project.project_id,
        event_type="worker_assigned",
        payload={
            "solver_id": "solver-1",
            "profile": "network",
            "status": SolverStatus.RUNNING.value,
        },
        source="test",
    )
    return runtime, project


class TestAPIProjects(unittest.TestCase):
    """GET /api/projects endpoints."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.runtime, self.project = _make_runtime_with_project(self.db_path)
        from fastapi.testclient import TestClient
        self.app = create_app(self.runtime)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.runtime.close()

    def test_list_projects(self):
        """GET /api/projects → list of project status reports."""
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

    def test_get_project_status(self):
        """GET /api/projects/{id} → detailed status report."""
        response = self.client.get(f"/api/projects/{self.project.project_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["project_id"], self.project.project_id)
        self.assertEqual(data["challenge_id"], "api-test")

    def test_get_project_not_found(self):
        """GET /api/projects/{nonexistent} → 404."""
        response = self.client.get("/api/projects/nonexistent-id")
        self.assertEqual(response.status_code, 404)


class TestAPIGetEndpoints(unittest.TestCase):
    """GET /api/projects/{id}/ideas, memory, solvers, reviews, events, observe."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.runtime, self.project = _make_runtime_with_project(self.db_path)
        from fastapi.testclient import TestClient
        self.app = create_app(self.runtime)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.runtime.close()

    def test_get_ideas(self):
        """GET /api/projects/{id}/ideas → idea list."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/ideas")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

    def test_get_memory(self):
        """GET /api/projects/{id}/memory → deduped fact entries."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/memory")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_get_solvers(self):
        """GET /api/projects/{id}/solvers → solver session list."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/solvers")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_get_reviews(self):
        """GET /api/projects/{id}/reviews → pending reviews."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/reviews")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_get_events(self):
        """GET /api/projects/{id}/events → full event log."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/events")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

    def test_get_observation(self):
        """GET /api/projects/{id}/observe → observation report."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/observe")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("report_id", data)

    def test_get_endpoints_do_not_modify_state(self):
        """All GET endpoints should not add new events to Blackboard."""
        events_before = len(self.runtime.blackboard.load_events(self.project.project_id))
        # hit all GET endpoints
        self.client.get(f"/api/projects/{self.project.project_id}/ideas")
        self.client.get(f"/api/projects/{self.project.project_id}/memory")
        self.client.get(f"/api/projects/{self.project.project_id}/solvers")
        self.client.get(f"/api/projects/{self.project.project_id}/reviews")
        self.client.get(f"/api/projects/{self.project.project_id}/events")
        self.client.get(f"/api/projects/{self.project.project_id}/observe")
        events_after = len(self.runtime.blackboard.load_events(self.project.project_id))
        # observe generates a CHECKPOINT event, so we allow +1
        self.assertLessEqual(events_after, events_before + 1)


class TestAPIReviewActions(unittest.TestCase):
    """POST /api/reviews/{id}/approve, reject, modify."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.runtime, self.project = _make_runtime_with_project(self.db_path)
        # create a review request
        self.request = ReviewRequest(
            project_id=self.project.project_id,
            action_type="submit_flag",
            risk_level="high",
            title="API review test",
            description="Test flag submission review",
            proposed_action="submit flag{api_test}",
        )
        self.runtime.review_gate.create_review(self.request, self.runtime.blackboard)
        from fastapi.testclient import TestClient
        self.app = create_app(self.runtime)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.runtime.close()

    def test_approve_review(self):
        """POST /api/reviews/{id}/approve → approved ReviewRequest."""
        response = self.client.post(
            f"/api/reviews/{self.request.request_id}/approve",
            params={"project_id": self.project.project_id, "reason": "looks good"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "approved")

    def test_reject_review(self):
        """POST /api/reviews/{id}/reject → rejected ReviewRequest."""
        # create another review for this test
        request2 = ReviewRequest(
            project_id=self.project.project_id,
            action_type="submit_flag",
            risk_level="high",
            title="API reject test",
            description="Test flag rejection",
            proposed_action="submit flag{reject}",
        )
        self.runtime.review_gate.create_review(request2, self.runtime.blackboard)

        response = self.client.post(
            f"/api/reviews/{request2.request_id}/reject",
            params={"project_id": self.project.project_id, "reason": "bad flag"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "rejected")

    def test_modify_review(self):
        """POST /api/reviews/{id}/modify → modified ReviewRequest."""
        request3 = ReviewRequest(
            project_id=self.project.project_id,
            action_type="submit_flag",
            risk_level="high",
            title="API modify test",
            description="Test flag modification",
            proposed_action="submit flag{modify}",
        )
        self.runtime.review_gate.create_review(request3, self.runtime.blackboard)

        response = self.client.post(
            f"/api/reviews/{request3.request_id}/modify",
            params={"project_id": self.project.project_id, "reason": "adjust approach"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "modified")

    def test_review_not_found(self):
        """POST /api/reviews/{nonexistent}/approve → 404."""
        response = self.client.post(
            "/api/reviews/nonexistent-id/approve",
            params={"project_id": self.project.project_id},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()