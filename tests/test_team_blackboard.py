"""Tests for attack_agent.team.blackboard — Phase B Blackboard Event Journal."""

import json
import os
import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardEvent, BlackboardService, MaterializedState
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.protocol import IdeaStatus, MemoryKind, SolverStatus


def _make_service(tmp_dir: str) -> BlackboardService:
    db_path = os.path.join(tmp_dir, "bb_test.db")
    return BlackboardService(BlackboardConfig(db_path=db_path))


class TestAppendLoadRoundtrip(unittest.TestCase):
    """SQLite append / load round-trip."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = _make_service(self.tmp)

    def tearDown(self):
        self.svc.close()

    def test_append_and_load(self):
        ev = self.svc.append_event(
            project_id="p1",
            event_type=EventType.PROJECT_UPSERTED.value,
            payload={"challenge_id": "c1", "status": "new"},
        )
        self.assertTrue(ev.event_id)
        self.assertEqual(ev.project_id, "p1")

        loaded = self.svc.load_events("p1")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].event_id, ev.event_id)
        self.assertEqual(loaded[0].payload["challenge_id"], "c1")

    def test_multiple_events_ordering(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.OBSERVATION.value, {"summary": "found /admin"})
        self.svc.append_event("p1", EventType.CANDIDATE_FLAG.value, {"flag": "flag{test}"})

        loaded = self.svc.load_events("p1")
        self.assertEqual(len(loaded), 3)
        # timestamps should be ascending
        for i in range(1, len(loaded)):
            self.assertLessEqual(loaded[i - 1].timestamp, loaded[i].timestamp)

    def test_payload_preserved(self):
        payload = {"key": "value", "nested": {"a": 1}, "list": [1, 2, 3]}
        self.svc.append_event("p1", EventType.OBSERVATION.value, payload)
        loaded = self.svc.load_events("p1")
        self.assertEqual(loaded[0].payload, payload)


class TestRebuildState(unittest.TestCase):
    """rebuild_state from events produces correct TeamProject + facts / ideas / sessions."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = _make_service(self.tmp)

    def tearDown(self):
        self.svc.close()

    def test_rebuild_project(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        state = self.svc.rebuild_state("p1")
        self.assertIsNotNone(state.project)
        self.assertEqual(state.project.project_id, "p1")
        self.assertEqual(state.project.challenge_id, "c1")
        self.assertEqual(state.project.status, "new")

    def test_rebuild_observations_as_facts(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.OBSERVATION.value, {"summary": "found login page", "confidence": 0.8})
        state = self.svc.rebuild_state("p1")
        facts = state.facts
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].kind, MemoryKind.FACT)
        self.assertEqual(facts[0].content, "found login page")
        self.assertEqual(facts[0].confidence, 0.8)

    def test_rebuild_candidate_flag(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.CANDIDATE_FLAG.value, {"flag": "flag{x}", "confidence": 0.9})
        state = self.svc.rebuild_state("p1")
        # genuine candidate_flag creates a fact, not an IdeaEntry
        self.assertEqual(len(state.ideas), 0)
        self.assertEqual(len(state.facts), 1)
        self.assertTrue(state.facts[0].content.startswith("candidate flag:"))

    def test_rebuild_idea_proposed(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.IDEA_PROPOSED.value,
                              {"flag": "try SQLi", "idea_id": "i1", "priority": 100,
                               "confidence": 0.5, "status": "pending"},
                              source="idea_service")
        state = self.svc.rebuild_state("p1")
        # idea_proposed creates IdeaEntry, not a fact
        self.assertEqual(len(state.ideas), 1)
        self.assertEqual(state.ideas[0].description, "try SQLi")
        self.assertEqual(state.ideas[0].status, IdeaStatus.PENDING)
        self.assertEqual(len(state.facts), 0)

    def test_rebuild_legacy_candidate_flag_as_idea(self):
        """Legacy candidate_flag with status field is correctly routed as idea event."""
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.CANDIDATE_FLAG.value,
                              {"flag": "old idea", "idea_id": "i1", "status": "pending",
                               "confidence": 0.5, "priority": 100},
                              source="idea_service")
        state = self.svc.rebuild_state("p1")
        # legacy idea lifecycle event routed correctly — idea, not fact
        self.assertEqual(len(state.ideas), 1)
        self.assertEqual(state.ideas[0].description, "old idea")

    def test_rebuild_worker_assigned(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.WORKER_ASSIGNED.value, {"solver_id": "s1", "profile": "network"})
        state = self.svc.rebuild_state("p1")
        self.assertEqual(len(state.sessions), 1)
        self.assertEqual(state.sessions[0].solver_id, "s1")
        self.assertEqual(state.sessions[0].status, SolverStatus.ASSIGNED)

    def test_rebuild_failed_action_outcome(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.ACTION_OUTCOME.value, {"status": "error", "error": "connection refused"})
        state = self.svc.rebuild_state("p1")
        self.assertEqual(len(state.facts), 1)
        self.assertEqual(state.facts[0].kind, MemoryKind.FAILURE_BOUNDARY)
        self.assertEqual(state.facts[0].content, "connection refused")

    def test_successful_action_outcome_not_in_facts(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.ACTION_OUTCOME.value, {"status": "ok"})
        state = self.svc.rebuild_state("p1")
        self.assertEqual(len(state.facts), 0)

    def test_rebuild_security_validation_deny(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.SECURITY_VALIDATION.value, {"outcome": "deny", "reason": "unsafe command"})
        state = self.svc.rebuild_state("p1")
        self.assertEqual(len(state.facts), 1)
        self.assertEqual(state.facts[0].kind, MemoryKind.FAILURE_BOUNDARY)

    def test_rebuild_submission_updates_project(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.SUBMISSION.value, {"result": "accepted"})
        state = self.svc.rebuild_state("p1")
        self.assertEqual(state.project.status, "accepted")

    def test_list_facts_filters_by_kind(self):
        self.svc.append_event("p1", EventType.OBSERVATION.value, {"summary": "fact1"})
        self.svc.append_event("p1", EventType.ACTION_OUTCOME.value, {"status": "error", "error": "failure1"})
        facts = self.svc.list_facts("p1")
        # only MemoryKind.FACT entries, not FAILURE_BOUNDARY
        self.assertTrue(all(f.kind == MemoryKind.FACT for f in facts))
        self.assertEqual(len(facts), 1)


class TestCrashReloadRecovery(unittest.TestCase):
    """Write → close → reopen → read is consistent."""

    def test_crash_reload(self):
        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "bb_crash.db")
        svc1 = BlackboardService(BlackboardConfig(db_path=db_path))
        svc1.append_event("p1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"})
        svc1.append_event("p1", EventType.OBSERVATION.value, {"summary": "recovered fact"})
        svc1.close()

        svc2 = BlackboardService(BlackboardConfig(db_path=db_path))
        loaded = svc2.load_events("p1")
        self.assertEqual(len(loaded), 2)
        state = svc2.rebuild_state("p1")
        self.assertEqual(state.project.challenge_id, "c1")
        self.assertEqual(len(state.facts), 1)
        self.assertEqual(state.facts[0].content, "recovered fact")
        svc2.close()


class TestCausalRefChain(unittest.TestCase):
    """causal_ref links events into a causality chain."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = _make_service(self.tmp)

    def tearDown(self):
        self.svc.close()

    def test_causal_ref_chain(self):
        ev1 = self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        ev2 = self.svc.append_event("p1", EventType.OBSERVATION.value, {"summary": "obs"}, causal_ref=ev1.event_id)
        ev3 = self.svc.append_event("p1", EventType.CANDIDATE_FLAG.value, {"flag": "flag{a}"}, causal_ref=ev2.event_id)

        loaded = self.svc.load_events("p1")
        self.assertIsNone(loaded[0].causal_ref)
        self.assertEqual(loaded[1].causal_ref, ev1.event_id)
        self.assertEqual(loaded[2].causal_ref, ev2.event_id)


class TestExportRunLog(unittest.TestCase):
    """export_run_log produces complete JSON event log."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = _make_service(self.tmp)

    def tearDown(self):
        self.svc.close()

    def test_export(self):
        self.svc.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.svc.append_event("p1", EventType.OBSERVATION.value, {"summary": "obs"})

        log = self.svc.export_run_log("p1")
        self.assertEqual(len(log), 2)
        self.assertIsInstance(log[0], dict)
        self.assertEqual(log[0]["event_type"], EventType.PROJECT_UPSERTED.value)
        self.assertEqual(log[1]["payload"]["summary"], "obs")
        # verify JSON-serializable
        json_str = json.dumps(log)
        parsed = json.loads(json_str)
        self.assertEqual(len(parsed), 2)


if __name__ == "__main__":
    unittest.main()