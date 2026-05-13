"""Tests for Phase G Observer."""

import unittest
import tempfile
import os

from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.observer import Observer, ObservationReport, ObservationNote
from attack_agent.team.protocol import ActionType, InterventionLevel, MemoryKind, IdeaStatus
from attack_agent.platform_models import EventType


class TestDetectRepeatedAction(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.observer = Observer(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_detect_repeated_action_below_threshold(self):
        # 2 same outcomes — below threshold=3
        for i in range(2):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "solver_id": "s1", "primitive": "http-request",
                "target": "/login", "status": "ok",
            })
        notes = self.observer.detect_repeated_action("p1", threshold=3)
        self.assertEqual(len(notes), 0)

    def test_detect_repeated_action_at_threshold(self):
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "solver_id": "s1", "primitive": "http-request",
                "target": "/login", "status": "ok",
            })
        notes = self.observer.detect_repeated_action("p1", threshold=3)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].kind, "repeated_action")
        self.assertEqual(notes[0].solver_id, "s1")

    def test_detect_repeated_action_no_outcomes(self):
        notes = self.observer.detect_repeated_action("p_empty")
        self.assertEqual(len(notes), 0)


class TestDetectLowNovelty(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.observer = Observer(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_detect_low_novelty_all_low_confidence(self):
        # add 3 facts all with very low confidence
        for i in range(3):
            self.bb.append_event("p1", EventType.OBSERVATION.value, {
                "summary": f"fact_{i}", "kind": MemoryKind.FACT.value,
                "entry_id": f"f{i}", "confidence": 0.05,
            })
        notes = self.observer.detect_low_novelty("p1", min_novelty=0.1)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].kind, "low_novelty")

    def test_detect_low_novelty_some_high_confidence(self):
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "important fact", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.8,
        })
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "minor fact", "kind": MemoryKind.FACT.value,
            "entry_id": "f2", "confidence": 0.05,
        })
        notes = self.observer.detect_low_novelty("p1", min_novelty=0.1)
        self.assertEqual(len(notes), 0)  # not ALL low


class TestDetectIgnoredFailureBoundary(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.observer = Observer(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_detect_ignored_boundary_two_solvers(self):
        # create a failure boundary
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked by WAF",
            "summary": "RCE blocked by WAF", "solver_id": "s1",
        })
        # same boundary description attempted by second solver
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked by WAF",
            "summary": "RCE blocked by WAF", "solver_id": "s2",
        })
        notes = self.observer.detect_ignored_failure_boundary("p1")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].kind, "ignored_boundary")

    def test_detect_ignored_boundary_single_solver(self):
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked", "solver_id": "s1",
        })
        notes = self.observer.detect_ignored_failure_boundary("p1")
        self.assertEqual(len(notes), 0)  # only 1 solver


class TestDetectStagnation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.observer = Observer(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_detect_stagnation_no_new_facts_or_ideas(self):
        # 5 events with only action outcomes — no new facts/ideas
        for i in range(5):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "ok", "solver_id": "s1",
            })
        notes = self.observer.detect_stagnation("p1", cycle_threshold=5)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].kind, "stagnation")

    def test_detect_stagnation_with_new_fact(self):
        # add observation event in last 5 → not stagnating
        for i in range(4):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "ok", "solver_id": "s1",
            })
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "new fact", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.8,
        })
        notes = self.observer.detect_stagnation("p1", cycle_threshold=5)
        self.assertEqual(len(notes), 0)

    def test_detect_stagnation_with_new_idea(self):
        for i in range(4):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "ok", "solver_id": "s1",
            })
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "flag{test}", "idea_id": "i1",
            "priority": 100, "status": IdeaStatus.PENDING.value,
        }, source="idea_service")
        notes = self.observer.detect_stagnation("p1", cycle_threshold=5)
        self.assertEqual(len(notes), 0)


class TestDetectToolMisuse(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.observer = Observer(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_detect_tool_misuse_consecutive_failures(self):
        # 3 failures with same primitive
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "error", "solver_id": "s1", "primitive": "http-request",
            })
        notes = self.observer.detect_tool_misuse("p1")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].kind, "tool_misuse")
        self.assertEqual(notes[0].solver_id, "s1")

    def test_detect_tool_misuse_below_threshold(self):
        # only 2 failures
        for i in range(2):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "error", "solver_id": "s1", "primitive": "http-request",
            })
        notes = self.observer.detect_tool_misuse("p1")
        self.assertEqual(len(notes), 0)


class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.observer = Observer(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_generate_report_empty(self):
        report = self.observer.generate_report("p1")
        self.assertEqual(report.severity, "info")
        self.assertEqual(len(report.observations), 0)

    def test_generate_report_with_stagnation(self):
        # 5 outcome-only events → stagnation
        for i in range(5):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "ok", "solver_id": "s1",
            })
        report = self.observer.generate_report("p1")
        self.assertEqual(report.severity, "warning")
        self.assertTrue(any(n.kind == "stagnation" for n in report.observations))

    def test_generate_report_with_tool_misuse(self):
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "error", "solver_id": "s1", "primitive": "http-request",
            })
        report = self.observer.generate_report("p1")
        self.assertEqual(report.severity, "critical")
        self.assertTrue(any(n.kind == "tool_misuse" for n in report.observations))

    def test_generate_report_writes_observer_report_event(self):
        report = self.observer.generate_report("p1")
        events = self.bb.load_events("p1")
        report_events = [e for e in events if e.event_type == EventType.OBSERVER_REPORT.value
                         and e.source == "observer"]
        self.assertEqual(len(report_events), 1)
        self.assertEqual(report_events[0].payload["report_id"], report.report_id)
        self.assertEqual(report_events[0].payload["severity"], report.severity)
        # L7: verify intervention_level and recommended_action in payload
        self.assertIn("intervention_level", report_events[0].payload)
        self.assertIn("recommended_action", report_events[0].payload)

    def test_generate_report_intervention_level_stagnation(self):
        # 5 outcome-only events → stagnation → STEER
        for i in range(5):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "ok", "solver_id": "s1",
            })
        report = self.observer.generate_report("p1")
        self.assertEqual(report.intervention_level, InterventionLevel.STEER)
        self.assertEqual(report.recommended_action, ActionType.STEER_SOLVER)

    def test_generate_report_intervention_level_tool_misuse(self):
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "error", "solver_id": "s1", "primitive": "http-request",
            })
        report = self.observer.generate_report("p1")
        self.assertEqual(report.intervention_level, InterventionLevel.THROTTLE)
        self.assertEqual(report.recommended_action, ActionType.THROTTLE_SOLVER)

    def test_generate_report_intervention_level_ignored_boundary(self):
        # create ignored boundary: same error from two solvers
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked by WAF",
            "summary": "RCE blocked by WAF", "solver_id": "s1",
        })
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked by WAF",
            "summary": "RCE blocked by WAF", "solver_id": "s2",
        })
        report = self.observer.generate_report("p1")
        self.assertEqual(report.intervention_level, InterventionLevel.STOP_REASSIGN)
        self.assertEqual(report.recommended_action, ActionType.REASSIGN_SOLVER)

    def test_generate_report_intervention_level_safety_block(self):
        # tool_misuse + ignored_boundary → SAFETY_BLOCK
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "error", "solver_id": "s1", "primitive": "http-request",
            })
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "WAF block",
            "summary": "WAF block", "solver_id": "s1",
        })
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "WAF block",
            "summary": "WAF block", "solver_id": "s2",
        })
        report = self.observer.generate_report("p1")
        self.assertEqual(report.intervention_level, InterventionLevel.SAFETY_BLOCK)
        self.assertEqual(report.recommended_action, ActionType.STOP_SOLVER)

    def test_generate_report_intervention_level_empty_report(self):
        report = self.observer.generate_report("p1")
        self.assertEqual(report.intervention_level, InterventionLevel.OBSERVE)
        self.assertIsNone(report.recommended_action)

    def test_generate_report_suggested_actions(self):
        # create stagnation scenario
        for i in range(5):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "status": "ok", "solver_id": "s1",
            })
        report = self.observer.generate_report("p1")
        self.assertTrue(len(report.suggested_actions) > 0)
        # stagnation suggestion
        self.assertTrue(any("switch path" in a or "abandon" in a for a in report.suggested_actions))

    def test_generate_report_with_repeated_action(self):
        for i in range(3):
            self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
                "solver_id": "s1", "primitive": "http-request",
                "target": "/login", "status": "ok",
            })
        report = self.observer.generate_report("p1")
        self.assertEqual(report.severity, "warning")
        self.assertTrue(any(n.kind == "repeated_action" for n in report.observations))


if __name__ == "__main__":
    unittest.main()