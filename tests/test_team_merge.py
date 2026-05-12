"""Tests for Phase G MergeHub."""

import unittest
import tempfile
import os

from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.merge import MergeHub, MergeResult, MergeDecision, ArbitrationResult
from attack_agent.team.protocol import MemoryEntry, MemoryKind, IdeaEntry, IdeaStatus, TeamProject
from attack_agent.platform_models import EventType


class TestMergeFacts(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.hub = MergeHub(self.bb)
        # create project
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_merge_facts_no_duplicates(self):
        # single fact — no merge needed
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.9,
        })
        result = self.hub.merge_facts("p1")
        self.assertEqual(result.merged_count, 0)
        self.assertEqual(result.conflict_count, 0)
        self.assertEqual(len(result.decisions), 0)

    def test_merge_facts_duplicate_same_confidence(self):
        # two facts with same content and same confidence → discard
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.9,
        })
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f2", "confidence": 0.9,
        })
        result = self.hub.merge_facts("p1")
        self.assertEqual(result.merged_count, 1)  # one duplicate discarded
        self.assertEqual(result.conflict_count, 0)
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(result.decisions[0].decision, "discard")

    def test_merge_facts_conflict_different_confidence(self):
        # two facts with same content but different confidence → conflict
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.9,
        })
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f2", "confidence": 0.5,
        })
        result = self.hub.merge_facts("p1")
        self.assertEqual(result.merged_count, 0)
        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.decisions[0].decision, "conflict")
        self.assertEqual(result.decisions[0].kept_entry_id, "f1")

    def test_merge_facts_empty_project(self):
        result = self.hub.merge_facts("p_empty")
        self.assertEqual(result.merged_count, 0)
        self.assertEqual(result.conflict_count, 0)

    def test_merge_facts_writes_dedup_event(self):
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.9,
        })
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f2", "confidence": 0.5,
        })
        result = self.hub.merge_facts("p1")
        # dedup event written to blackboard
        events = self.bb.load_events("p1")
        dedup_events = [e for e in events if e.source == "merge_hub" and e.event_type == EventType.OBSERVATION.value]
        self.assertEqual(len(dedup_events), 1)
        self.assertIn("merged_from_ids", dedup_events[0].payload)


class TestMergeIdeas(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.hub = MergeHub(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_merge_ideas_duplicate_description(self):
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "SQL injection on login", "idea_id": "i1",
            "priority": 100, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
        }, source="idea_service")
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "SQL injection on login", "idea_id": "i2",
            "priority": 80, "status": IdeaStatus.PENDING.value, "confidence": 0.4,
        }, source="idea_service")
        result = self.hub.merge_ideas("p1")
        self.assertEqual(result.merged_count, 1)
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(result.decisions[0].decision, "merge")
        self.assertEqual(result.decisions[0].kept_entry_id, "i1")

    def test_merge_ideas_no_duplicates(self):
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "SQL injection", "idea_id": "i1",
            "priority": 100, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
        }, source="idea_service")
        result = self.hub.merge_ideas("p1")
        self.assertEqual(result.merged_count, 0)
        self.assertEqual(len(result.decisions), 0)

    def test_merge_ideas_empty(self):
        result = self.hub.merge_ideas("p_empty")
        self.assertEqual(result.merged_count, 0)


class TestMergeFailureBoundaries(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.hub = MergeHub(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_merge_failure_boundaries_duplicate(self):
        # create two failure boundaries with same description
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked by WAF",
            "summary": "RCE blocked by WAF", "entry_id": "fb1",
            "kind": MemoryKind.FAILURE_BOUNDARY.value,
        })
        self.bb.append_event("p1", EventType.ACTION_OUTCOME.value, {
            "status": "error", "error": "RCE blocked by WAF",
            "summary": "RCE blocked by WAF", "entry_id": "fb2",
            "kind": MemoryKind.FAILURE_BOUNDARY.value,
        })
        result = self.hub.merge_failure_boundaries("p1")
        self.assertEqual(result.merged_count, 1)
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(result.decisions[0].decision, "discard")

    def test_merge_failure_boundaries_empty(self):
        result = self.hub.merge_failure_boundaries("p_empty")
        self.assertEqual(result.merged_count, 0)


class TestArbitrateFlags(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.hub = MergeHub(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_arbitrate_single_flag(self):
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "flag{test1}", "idea_id": "i1",
            "priority": 100, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
        }, source="idea_service")
        result = self.hub.arbitrate_flags("p1")
        self.assertEqual(result.selected_flag, "flag{test1}")
        self.assertEqual(result.selected_idea_id, "i1")
        self.assertFalse(result.consensus)

    def test_arbitrate_consensus_boost(self):
        # same flag from 2 solvers → consensus boost
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "flag{secret}", "idea_id": "i1",
            "priority": 100, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
            "solver_id": "s1",
        }, source="idea_service")
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "flag{secret}", "idea_id": "i2",
            "priority": 90, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
            "solver_id": "s2",
        }, source="idea_service")
        result = self.hub.arbitrate_flags("p1")
        self.assertEqual(result.selected_flag, "flag{secret}")
        self.assertTrue(result.consensus)
        self.assertEqual(result.solver_count, 2)
        # boosted confidence: 0.5 + 0.1*(2-1) = 0.6
        self.assertAlmostEqual(result.confidence, 0.6)

    def test_arbitrate_different_flags_selects_highest_confidence(self):
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "flag{a}", "idea_id": "i1",
            "priority": 100, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
            "solver_id": "s1",
        }, source="idea_service")
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "flag{b}", "idea_id": "i2",
            "priority": 80, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
            "solver_id": "s2",
        }, source="idea_service")
        # s1 has 2 submissions for flag{a} → consensus boost
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "flag{a}", "idea_id": "i3",
            "priority": 100, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
            "solver_id": "s3",
        }, source="idea_service")
        result = self.hub.arbitrate_flags("p1")
        self.assertEqual(result.selected_flag, "flag{a}")
        self.assertTrue(result.consensus)
        # 2 solvers for flag{a}: 0.5 + 0.1*(2-1) = 0.6
        self.assertAlmostEqual(result.confidence, 0.6)
        # flag{b} as alternative
        self.assertEqual(len(result.alternatives), 1)

    def test_arbitrate_no_candidates(self):
        result = self.hub.arbitrate_flags("p_empty")
        self.assertEqual(result.selected_flag, "")
        self.assertEqual(result.confidence, 0.0)

    def test_arbitrate_writes_event(self):
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value, {
            "flag": "flag{test}", "idea_id": "i1",
            "priority": 100, "status": IdeaStatus.PENDING.value, "confidence": 0.5,
        }, source="idea_service")
        self.hub.arbitrate_flags("p1")
        events = self.bb.load_events("p1")
        arb_events = [e for e in events if e.source == "merge_hub"
                      and e.event_type == EventType.IDEA_PROPOSED.value]
        self.assertEqual(len(arb_events), 1)
        self.assertEqual(arb_events[0].payload["solver_id"], "merged")
        self.assertTrue(arb_events[0].payload.get("arbitration", False))


class TestMergeDecisionAuditability(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = BlackboardConfig(db_path=os.path.join(self.tmp, "bb.db"))
        self.bb = BlackboardService(cfg)
        self.hub = MergeHub(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {
            "challenge_id": "c1", "status": "new"
        })

    def tearDown(self):
        self.bb.close()

    def test_merge_decisions_from_events(self):
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f1", "confidence": 0.9,
        })
        self.bb.append_event("p1", EventType.OBSERVATION.value, {
            "summary": "found endpoint /api", "kind": MemoryKind.FACT.value,
            "entry_id": "f2", "confidence": 0.5,
        })
        result = self.hub.merge_facts("p1")
        # all decisions should be traceable from blackboard events
        events = self.bb.load_events("p1")
        merge_events = [e for e in events if e.source == "merge_hub"]
        self.assertTrue(len(merge_events) >= 1)
        # check that merged_from_ids is in the event payload
        dedup = merge_events[0]
        self.assertIn("merged_from_ids", dedup.payload)
        self.assertIn("f2", dedup.payload["merged_from_ids"])


if __name__ == "__main__":
    unittest.main()