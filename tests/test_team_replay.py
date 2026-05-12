"""Tests for ReplayEngine — Phase I."""

import os
import tempfile
import unittest

from attack_agent.team.apply_event import apply_event_to_state
from attack_agent.team.blackboard import BlackboardEvent, BlackboardService, MaterializedState
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.protocol import (
    IdeaEntry,
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    SolverStatus,
    TeamProject,
)
from attack_agent.team.replay import (
    ReplayEngine,
    ReplayStep,
    RunDiffResult,
    _event_match_key,
)


class TestApplyEventPureFunction(unittest.TestCase):
    """Verify the extracted pure function produces identical results."""

    def setUp(self):
        self.idea_index: dict[str, IdeaEntry] = {}
        self.session_index: dict[str, SolverSession] = {}
        self.facts: list[MemoryEntry] = []
        self.project: TeamProject | None = None

    def test_project_upserted(self):
        self.project = apply_event_to_state(
            project_id="p1", event_type="project_upserted",
            payload={"challenge_id": "c1", "status": "new"},
            timestamp="2026-01-01T00:00:00Z", event_id="e1",
            state_project=self.project, state_facts=self.facts,
            idea_index=self.idea_index, session_index=self.session_index,
        )
        self.assertIsNotNone(self.project)
        self.assertEqual(self.project.project_id, "p1")
        self.assertEqual(self.project.challenge_id, "c1")

    def test_observation_fact(self):
        self.project = apply_event_to_state(
            project_id="p1", event_type="observation",
            payload={"kind": "fact", "summary": "found endpoint /api", "confidence": 0.8},
            timestamp="2026-01-01T00:01:00Z", event_id="e2",
            state_project=self.project, state_facts=self.facts,
            idea_index=self.idea_index, session_index=self.session_index,
        )
        self.assertEqual(len(self.facts), 1)
        self.assertEqual(self.facts[0].kind, MemoryKind.FACT)
        self.assertEqual(self.facts[0].content, "found endpoint /api")

    def test_candidate_flag_creates_idea_and_fact(self):
        # Legacy candidate_flag with status field — classified as idea event
        self.project = apply_event_to_state(
            project_id="p1", event_type="candidate_flag",
            payload={"flag": "flag{test}", "idea_id": "i1", "status": "pending"},
            timestamp="2026-01-01T00:02:00Z", event_id="e3",
            state_project=self.project, state_facts=self.facts,
            idea_index=self.idea_index, session_index=self.session_index,
            source="idea_service",
        )
        self.assertIn("i1", self.idea_index)
        self.assertEqual(self.idea_index["i1"].description, "flag{test}")
        # idea lifecycle events don't create a fact
        self.assertEqual(len(self.facts), 0)

    def test_genuine_candidate_flag_creates_fact_only(self):
        # Genuine candidate_flag without status — creates fact, not idea
        self.project = apply_event_to_state(
            project_id="p1", event_type="candidate_flag",
            payload={"flag": "flag{genuine}", "confidence": 0.9},
            timestamp="2026-01-01T00:02:00Z", event_id="e3",
            state_project=self.project, state_facts=self.facts,
            idea_index=self.idea_index, session_index=self.session_index,
            source="state_sync",
        )
        self.assertEqual(len(self.facts), 1)
        self.assertTrue(self.facts[0].content.startswith("candidate flag:"))
        # no idea created for genuine flag
        self.assertEqual(len(self.idea_index), 0)

    def test_worker_assigned(self):
        self.project = apply_event_to_state(
            project_id="p1", event_type="worker_assigned",
            payload={"solver_id": "s1", "status": "assigned", "profile": "network"},
            timestamp="2026-01-01T00:03:00Z", event_id="e4",
            state_project=self.project, state_facts=self.facts,
            idea_index=self.idea_index, session_index=self.session_index,
        )
        self.assertIn("s1", self.session_index)
        self.assertEqual(self.session_index["s1"].status, SolverStatus.ASSIGNED)

    def test_action_outcome_failure_creates_boundary(self):
        # First assign the solver
        self.project = apply_event_to_state(
            project_id="p1", event_type="worker_assigned",
            payload={"solver_id": "s1", "status": "assigned", "profile": "network"},
            timestamp="2026-01-01T00:03:00Z", event_id="e4",
            state_project=self.project, state_facts=self.facts,
            idea_index=self.idea_index, session_index=self.session_index,
        )
        # Then produce a failure outcome
        self.project = apply_event_to_state(
            project_id="p1", event_type="action_outcome",
            payload={"solver_id": "s1", "status": "failed", "error": "timeout"},
            timestamp="2026-01-01T00:04:00Z", event_id="e5",
            state_project=self.project, state_facts=self.facts,
            idea_index=self.idea_index, session_index=self.session_index,
        )
        # Should have at least 1 failure boundary fact
        fb_facts = [f for f in self.facts if f.kind == MemoryKind.FAILURE_BOUNDARY]
        self.assertGreater(len(fb_facts), 0)

    def test_security_validation_deny_creates_boundary(self):
        self.project = apply_event_to_state(
            project_id="p1", event_type="security_validation",
            payload={"outcome": "deny", "reason": "critical risk"},
            timestamp="2026-01-01T00:05:00Z", event_id="e6",
            state_project=self.project, state_facts=self.facts,
            idea_index=self.idea_index, session_index=self.session_index,
        )
        self.assertEqual(len(self.facts), 1)
        self.assertEqual(self.facts[0].kind, MemoryKind.FAILURE_BOUNDARY)


class TestReplayEngine(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "bb.db"))
        self.bb = BlackboardService(self.config)
        self.engine = ReplayEngine()

    def tearDown(self):
        self.bb.close()
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def _seed_project(self, project_id: str):
        """Seed a project with a realistic event sequence."""
        self.bb.append_event(project_id, "project_upserted",
                             {"challenge_id": "c1", "status": "new"}, "system")
        self.bb.append_event(project_id, "observation",
                             {"kind": "fact", "summary": "found /login", "confidence": 0.8}, "s1")
        self.bb.append_event(project_id, "observation",
                             {"kind": "endpoint", "summary": "endpoint /api", "confidence": 0.7}, "s1")
        self.bb.append_event(project_id, "idea_proposed",
                             {"flag": "flag{abc}", "idea_id": "i1", "status": "pending"}, "s1")
        self.bb.append_event(project_id, "worker_assigned",
                             {"solver_id": "s1", "status": "assigned", "profile": "network"}, "scheduler")
        self.bb.append_event(project_id, "action_outcome",
                             {"solver_id": "s1", "status": "ok", "summary": "exploit succeeded"}, "s1")
        self.bb.append_event(project_id, "submission",
                             {"flag": "flag{abc}", "result": "solved"}, "s1")

    def test_replay_project_produces_steps(self):
        self._seed_project("p1")
        steps = self.engine.replay_project("p1", self.bb)
        self.assertEqual(len(steps), 7)
        for s in steps:
            self.assertIsInstance(s, ReplayStep)
            self.assertIsInstance(s.state_snapshot, MaterializedState)

    def test_replay_project_state_evolution(self):
        self._seed_project("p1")
        steps = self.engine.replay_project("p1", self.bb)
        # step 0: project created, 0 facts, 0 ideas
        self.assertIsNotNone(steps[0].state_snapshot.project)
        self.assertEqual(len(steps[0].state_snapshot.facts), 0)
        # step 2: 2 observations = 2 facts
        self.assertEqual(len(steps[2].state_snapshot.facts), 2)
        # step 3: idea proposed = 1 idea, no extra fact (2 facts total)
        self.assertEqual(len(steps[3].state_snapshot.ideas), 1)
        self.assertEqual(len(steps[3].state_snapshot.facts), 2)
        # step 5: action outcome ok, no failure boundary
        self.assertEqual(len(steps[5].state_snapshot.facts), 2)
        # step 6: submission → project status "solved"
        self.assertEqual(steps[6].state_snapshot.project.status, "solved")

    def test_replay_to_step(self):
        self._seed_project("p1")
        state = self.engine.replay_to_step("p1", 3, self.bb)
        self.assertIsNotNone(state.project)
        self.assertEqual(len(state.facts), 2)  # 2 observations, idea_proposed doesn't add a fact
        self.assertEqual(len(state.ideas), 1)

    def test_replay_to_step_out_of_range(self):
        self._seed_project("p1")
        with self.assertRaises(ValueError):
            self.engine.replay_to_step("p1", 100, self.bb)
        with self.assertRaises(ValueError):
            self.engine.replay_to_step("p1", -1, self.bb)

    def test_diff_runs_identical(self):
        # Seed same project in two DBs
        self._seed_project("p1")
        config2 = BlackboardConfig(db_path=os.path.join(self.tmpdir, "bb2.db"))
        bb2 = BlackboardService(config2)
        bb2.append_event("p1", "project_upserted",
                         {"challenge_id": "c1", "status": "new"}, "system")
        bb2.append_event("p1", "observation",
                         {"kind": "fact", "summary": "found /login", "confidence": 0.8}, "s1")
        bb2.append_event("p1", "observation",
                         {"kind": "endpoint", "summary": "endpoint /api", "confidence": 0.7}, "s1")
        bb2.append_event("p1", "idea_proposed",
                         {"flag": "flag{abc}", "idea_id": "i1", "status": "pending"}, "s1")
        bb2.append_event("p1", "worker_assigned",
                         {"solver_id": "s1", "status": "assigned", "profile": "network"}, "scheduler")
        bb2.append_event("p1", "action_outcome",
                         {"solver_id": "s1", "status": "ok", "summary": "exploit succeeded"}, "s1")
        bb2.append_event("p1", "submission",
                         {"flag": "flag{abc}", "result": "solved"}, "s1")

        result = self.engine.diff_runs("p1", "p1", self.bb, bb2)
        self.assertIsInstance(result, RunDiffResult)
        self.assertEqual(len(result.added_events), 0)
        self.assertEqual(len(result.removed_events), 0)
        self.assertIsNone(result.diverged_at_step)
        bb2.close()

    def test_diff_runs_different(self):
        self._seed_project("p1")
        config2 = BlackboardConfig(db_path=os.path.join(self.tmpdir, "bb2.db"))
        bb2 = BlackboardService(config2)
        bb2.append_event("p1", "project_upserted",
                         {"challenge_id": "c1", "status": "new"}, "system")
        bb2.append_event("p1", "observation",
                         {"kind": "fact", "summary": "found /login", "confidence": 0.8}, "s1")
        # diverges here: different content
        bb2.append_event("p1", "observation",
                         {"kind": "endpoint", "summary": "different endpoint", "confidence": 0.5}, "s1")
        bb2.append_event("p1", "action_outcome",
                         {"solver_id": "s1", "status": "failed", "error": "timeout"}, "s1")

        result = self.engine.diff_runs("p1", "p1", self.bb, bb2)
        # Should detect divergence at step 2 (different endpoint)
        self.assertEqual(result.diverged_at_step, 2)
        self.assertGreater(len(result.added_events), 0)
        self.assertGreater(len(result.removed_events), 0)
        bb2.close()


class TestEventMatchKey(unittest.TestCase):

    def test_observation_key(self):
        ev = BlackboardEvent(
            event_type="observation",
            payload={"kind": "fact", "summary": "found /login"},
        )
        key = _event_match_key(ev)
        self.assertEqual(key, ("observation", "fact", "found /login"))

    def test_submission_key(self):
        ev = BlackboardEvent(
            event_type="submission",
            payload={"flag": "flag{abc}", "result": "solved"},
        )
        key = _event_match_key(ev)
        self.assertEqual(key, ("submission", "submission", "flag{abc}"))

    def test_candidate_flag_key(self):
        ev = BlackboardEvent(
            event_type="candidate_flag",
            payload={"flag": "flag{abc}", "idea_id": "i1"},
        )
        key = _event_match_key(ev)
        self.assertEqual(key, ("candidate_flag", "candidate_flag", "flag{abc}"))


if __name__ == "__main__":
    unittest.main()