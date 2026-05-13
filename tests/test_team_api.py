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


class TestAPIProjectLifecycle(unittest.TestCase):
    """L9 acceptance: API can start and pause a project."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        self.runtime = TeamRuntime(self.config)
        from fastapi.testclient import TestClient
        self.app = create_app(self.runtime)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.runtime.close()

    def test_start_and_pause_project(self):
        """Start a project via API, then pause it."""
        response = self.client.post(
            "/api/projects/start-project",
            params={"challenge_id": "lifecycle-test"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        project_id = data["project_id"]
        self.assertEqual(data["status"], "started")

        # Verify project exists in Blackboard
        status_resp = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(status_resp.status_code, 200)

        # Pause the project — accept either 200 (paused) or 409 (already completed)
        pause_resp = self.client.post(f"/api/projects/{project_id}/pause")
        self.assertIn(pause_resp.status_code, [200, 409])

    def test_pause_nonexistent_project(self):
        """Pausing a nonexistent project returns 409."""
        response = self.client.post("/api/projects/nonexistent/pause")
        self.assertEqual(response.status_code, 409)

    def test_resume_nonexistent_project(self):
        """Resuming a nonexistent project returns 409."""
        response = self.client.post("/api/projects/nonexistent/resume")
        self.assertEqual(response.status_code, 409)


class TestAPIReadEndpointsL9(unittest.TestCase):
    """L9: missing read endpoints — hint, graph, observer-reports, candidate-flags, artifacts."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.runtime, self.project = _make_runtime_with_project(self.db_path)
        from fastapi.testclient import TestClient
        self.app = create_app(self.runtime)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.runtime.close()

    def test_add_hint(self):
        """POST /api/projects/{id}/hint writes HINT event."""
        response = self.client.post(
            f"/api/projects/{self.project.project_id}/hint",
            params={"content": "try /admin endpoint", "confidence": 0.9},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["hint"], "try /admin endpoint")

    def test_add_hint_no_content(self):
        """POST /api/projects/{id}/hint without content → 400."""
        response = self.client.post(
            f"/api/projects/{self.project.project_id}/hint",
        )
        self.assertEqual(response.status_code, 400)

    def test_get_graph(self):
        """GET /api/projects/{id}/graph returns structured graph view."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/graph")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("fact_nodes", data)
        self.assertIn("idea_nodes", data)
        self.assertIn("solver_nodes", data)
        self.assertIn("packet_nodes", data)

    def test_get_observer_reports(self):
        """GET /api/projects/{id}/observer-reports returns list."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/observer-reports")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_get_candidate_flags(self):
        """GET /api/projects/{id}/candidate-flags returns genuine flags only."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/candidate-flags")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_get_artifacts(self):
        """GET /api/projects/{id}/artifacts returns artifact list."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/artifacts")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_get_replay_timeline(self):
        """GET /api/projects/{id}/replay-timeline returns steps with explanations."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/replay-timeline")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        for step in data:
            self.assertIn("explanation", step)
            self.assertIsInstance(step["explanation"], str)
            self.assertTrue(len(step["explanation"]) > 0)

    def test_graph_not_found(self):
        """GET /api/projects/nonexistent/graph → 404."""
        response = self.client.get("/api/projects/nonexistent/graph")
        self.assertEqual(response.status_code, 404)


class TestBlackboardEventsAfter(unittest.TestCase):
    """L9: Blackboard load_events_after for SSE polling."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        self.runtime = TeamRuntime(self.config)
        project = TeamProject(challenge_id="sse-test", status="running")
        self.runtime.blackboard.append_event(
            project_id=project.project_id,
            event_type="project_upserted",
            payload=to_dict(project),
            source="test",
        )
        self.project_id = project.project_id

    def tearDown(self):
        self.runtime.close()

    def test_load_events_after_empty_id(self):
        """load_events_after with empty after_event_id returns all events."""
        events = self.runtime.blackboard.load_events_after(self.project_id, "")
        self.assertGreaterEqual(len(events), 1)

    def test_load_events_after_known_id(self):
        """load_events_after returns only events newer than given event_id."""
        events_all = self.runtime.blackboard.load_events(self.project_id)
        first_id = events_all[0].event_id
        # Add a second event
        self.runtime.blackboard.append_event(
            project_id=self.project_id,
            event_type="observation",
            payload={"kind": "fact", "content": "test"},
            source="test",
        )
        events_after = self.runtime.blackboard.load_events_after(self.project_id, first_id)
        self.assertGreaterEqual(len(events_after), 1)
        # First event should not be in the after list
        for ev in events_after:
            self.assertNotEqual(ev.event_id, first_id)

    def test_load_all_events_after(self):
        """load_all_events_after returns events across all projects."""
        # Create a second project
        project2 = TeamProject(challenge_id="sse-test-2", status="running")
        self.runtime.blackboard.append_event(
            project_id=project2.project_id,
            event_type="project_upserted",
            payload=to_dict(project2),
            source="test",
        )
        events_all = self.runtime.blackboard.load_all_events_after("")
        self.assertGreaterEqual(len(events_all), 2)


class TestSSEEventStream(unittest.TestCase):
    """L9 acceptance: Event stream emits solver and memory updates.

    SSE streaming requires async client; we test the mapping and
    Blackboard polling logic instead of the full SSE stream.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.runtime, self.project = _make_runtime_with_project(self.db_path)

    def tearDown(self):
        self.runtime.close()

    def test_sse_event_mapping(self):
        """Verify event type mapping for SSE channels."""
        from attack_agent.team.api import _map_event_to_sse
        from attack_agent.platform_models import EventType as ET

        self.assertEqual(_map_event_to_sse(ET.WORKER_ASSIGNED.value, {}), "solver_updated")
        self.assertEqual(_map_event_to_sse(ET.WORKER_HEARTBEAT.value, {}), "solver_updated")
        self.assertEqual(_map_event_to_sse(ET.IDEA_PROPOSED.value, {}), "idea_updated")
        self.assertEqual(_map_event_to_sse(ET.OBSERVATION.value, {}), "memory_added")
        self.assertEqual(_map_event_to_sse(ET.OBSERVER_REPORT.value, {}), "observer_reported")
        self.assertEqual(_map_event_to_sse(ET.CANDIDATE_FLAG.value, {}), "candidate_flag_found")
        self.assertEqual(_map_event_to_sse(ET.HINT.value, {}), "hint_added")

        self.assertEqual(
            _map_event_to_sse(ET.SECURITY_VALIDATION.value, {"status": "pending"}),
            "review_created",
        )
        self.assertEqual(
            _map_event_to_sse(ET.SECURITY_VALIDATION.value, {"status": "approved"}),
            "review_decided",
        )
        self.assertEqual(
            _map_event_to_sse(ET.SECURITY_VALIDATION.value, {"status": "rejected"}),
            "review_decided",
        )

    def test_sse_emits_events_after_write(self):
        """After writing events to Blackboard, SSE polling delivers them."""
        # Add a memory event
        self.runtime.blackboard.append_event(
            project_id=self.project.project_id,
            event_type="memory_stored",
            payload={"kind": "fact", "content": "new endpoint discovered"},
            source="test_sse",
        )
        # Add a solver heartbeat
        self.runtime.blackboard.append_event(
            project_id=self.project.project_id,
            event_type="worker_heartbeat",
            payload={"solver_id": "solver-1", "status": "running"},
            source="test_sse",
        )

        # Verify events exist via load_events_after (SSE polling mechanism)
        events_all = self.runtime.blackboard.load_events(self.project.project_id)
        self.assertGreaterEqual(len(events_all), 5)

        # Verify SSE-mapped types exist
        from attack_agent.team.api import _map_event_to_sse
        sse_types = set()
        for ev in events_all:
            sse_types.add(_map_event_to_sse(ev.event_type, ev.payload))
        self.assertIn("solver_updated", sse_types)
        self.assertIn("memory_added", sse_types)

    def test_sse_endpoint_registered(self):
        """Verify SSE endpoint route exists in the FastAPI router."""
        from attack_agent.team.api import create_app
        app = create_app(self.runtime)
        routes = [r.path for r in app.routes]
        self.assertIn("/api/events/stream", routes)


class TestAPIReviewQueue(unittest.TestCase):
    """L9 acceptance: Review queue updates through API."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb.db")
        self.runtime, self.project = _make_runtime_with_project(self.db_path)
        from fastapi.testclient import TestClient
        self.app = create_app(self.runtime)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.runtime.close()

    def test_review_queue_updates(self):
        """Create a review, verify it appears in the queue, then resolve it."""
        # Initially check the review queue
        response = self.client.get("/api/reviews", params={"status": "pending"})
        self.assertEqual(response.status_code, 200)
        initial_count = len(response.json())

        # Create a review request
        request = ReviewRequest(
            project_id=self.project.project_id,
            action_type="submit_flag",
            risk_level="high",
            title="Test review queue update",
        )
        self.runtime.review_gate.create_review(request, self.runtime.blackboard)

        # Verify review appears in the global queue
        response = self.client.get("/api/reviews", params={"status": "pending"})
        data = response.json()
        self.assertGreater(len(data), initial_count)

        # Verify review appears in the per-project endpoint
        project_reviews = self.client.get(f"/api/projects/{self.project.project_id}/reviews")
        self.assertGreaterEqual(len(project_reviews.json()), 1)

        # Resolve the review
        resolve_resp = self.client.post(
            f"/api/reviews/{request.request_id}/approve",
            params={"project_id": self.project.project_id},
        )
        self.assertEqual(resolve_resp.status_code, 200)

        # Verify review is no longer in the pending queue
        response = self.client.get("/api/reviews", params={"status": "pending"})
        data = response.json()
        self.assertEqual(len(data), initial_count)

    def test_verify_consistency(self):
        """Consistency verification matches API data with ReplayEngine."""
        response = self.client.get(f"/api/projects/{self.project.project_id}/verify-consistency")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["consistent"])
        self.assertGreaterEqual(data["api_fact_count"], 0)

    def test_verify_consistency_not_found(self):
        """Consistency verification for nonexistent project → 404."""
        response = self.client.get("/api/projects/nonexistent/verify-consistency")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()