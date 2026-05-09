"""Tests for MemoryService — Phase D."""

import os
import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.memory import MemoryService
from attack_agent.team.protocol import FailureBoundary, MemoryEntry, MemoryKind


def _make_bb(test_name: str) -> BlackboardService:
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, f"bb_mem_{test_name}.db")
    return BlackboardService(BlackboardConfig(db_path=db_path))


class TestMemoryServiceStoreEntry(unittest.TestCase):
    """store_entry writes MemoryEntry to Blackboard event journal."""

    def setUp(self):
        self.bb = _make_bb("store")
        self.mem = MemoryService(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_store_fact(self):
        entry = MemoryEntry(kind=MemoryKind.FACT, content="found /admin", confidence=0.8)
        result = self.mem.store_entry("p1", entry)
        self.assertEqual(result.project_id, "p1")
        # verify it's in the journal
        state = self.bb.rebuild_state("p1")
        facts = [m for m in state.facts if m.kind == MemoryKind.FACT]
        self.assertTrue(len(facts) >= 1)
        self.assertEqual(facts[0].content, "found /admin")

    def test_store_credential(self):
        entry = MemoryEntry(kind=MemoryKind.CREDENTIAL, content="admin:password123", confidence=0.9)
        self.mem.store_entry("p1", entry)
        state = self.bb.rebuild_state("p1")
        creds = [m for m in state.facts if m.kind == MemoryKind.CREDENTIAL]
        self.assertTrue(len(creds) >= 1)

    def test_store_failure_boundary(self):
        entry = MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY,
            content="SQL injection blocked by WAF",
            confidence=0.0,
        )
        self.mem.store_entry("p1", entry)
        state = self.bb.rebuild_state("p1")
        failures = [m for m in state.facts if m.kind == MemoryKind.FAILURE_BOUNDARY]
        self.assertTrue(len(failures) >= 1)
        self.assertEqual(failures[0].content, "SQL injection blocked by WAF")

    def test_store_endpoint(self):
        entry = MemoryEntry(kind=MemoryKind.ENDPOINT, content="/api/v1/users", confidence=0.7)
        self.mem.store_entry("p1", entry)
        state = self.bb.rebuild_state("p1")
        endpoints = [m for m in state.facts if m.kind == MemoryKind.ENDPOINT]
        self.assertTrue(len(endpoints) >= 1)


class TestMemoryServiceQueryByKind(unittest.TestCase):
    """query_by_kind returns entries filtered by MemoryKind."""

    def setUp(self):
        self.bb = _make_bb("query_kind")
        self.mem = MemoryService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_query_facts(self):
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="fact1"))
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="fact2"))
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.CREDENTIAL, content="cred1"))
        facts = self.mem.query_by_kind("p1", MemoryKind.FACT)
        self.assertTrue(len(facts) >= 2)
        self.assertTrue(all(m.kind == MemoryKind.FACT for m in facts))

    def test_query_credentials(self):
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.CREDENTIAL, content="user:pass"))
        creds = self.mem.query_by_kind("p1", MemoryKind.CREDENTIAL)
        self.assertTrue(len(creds) >= 1)
        self.assertTrue(all(m.kind == MemoryKind.CREDENTIAL for m in creds))

    def test_query_limit(self):
        for i in range(25):
            self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content=f"fact_{i}"))
        facts = self.mem.query_by_kind("p1", MemoryKind.FACT, limit=10)
        self.assertEqual(len(facts), 10)

    def test_query_failure_boundaries(self):
        self.mem.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY, content="path blocked"))
        failures = self.mem.query_by_kind("p1", MemoryKind.FAILURE_BOUNDARY)
        self.assertTrue(len(failures) >= 1)


class TestMemoryServiceQueryByConfidence(unittest.TestCase):
    """query_by_confidence returns high-confidence entries."""

    def setUp(self):
        self.bb = _make_bb("query_conf")
        self.mem = MemoryService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_high_confidence_filter(self):
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="low", confidence=0.3))
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="high", confidence=0.9))
        result = self.mem.query_by_confidence("p1", 0.7)
        self.assertTrue(len(result) >= 1)
        self.assertTrue(all(m.confidence >= 0.7 for m in result))

    def test_ordering_by_confidence(self):
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="med", confidence=0.75))
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="high", confidence=0.95))
        result = self.mem.query_by_confidence("p1", 0.7)
        self.assertTrue(len(result) >= 2)
        self.assertGreaterEqual(result[0].confidence, result[1].confidence)

    def test_no_matches(self):
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="low", confidence=0.2))
        result = self.mem.query_by_confidence("p1", 0.9)
        self.assertEqual(len(result), 0)


class TestMemoryServiceDedupe(unittest.TestCase):
    """dedupe identifies duplicate content entries."""

    def setUp(self):
        self.bb = _make_bb("dedupe")
        self.mem = MemoryService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_dedupe_count(self):
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="found /admin", confidence=0.5))
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="found /admin", confidence=0.8))
        count = self.mem.dedupe("p1")
        self.assertEqual(count, 1)

    def test_no_duplicates(self):
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="unique1"))
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="unique2"))
        count = self.mem.dedupe("p1")
        self.assertEqual(count, 0)

    def test_deduped_entries_keeps_highest_confidence(self):
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="same content", confidence=0.3))
        self.mem.store_entry("p1", MemoryEntry(kind=MemoryKind.FACT, content="same content", confidence=0.9))
        deduped = self.mem.get_deduped_entries("p1", MemoryKind.FACT)
        same_content_entries = [m for m in deduped if m.content == "same content"]
        self.assertEqual(len(same_content_entries), 1)
        self.assertEqual(same_content_entries[0].confidence, 0.9)


class TestMemoryServiceGetFailureBoundaries(unittest.TestCase):
    """get_failure_boundaries extracts FailureBoundary objects."""

    def setUp(self):
        self.bb = _make_bb("fb")
        self.mem = MemoryService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_failure_boundaries_from_stored_entries(self):
        self.mem.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY,
            content="SQLi blocked",
            confidence=0.0,
        ))
        boundaries = self.mem.get_failure_boundaries("p1")
        self.assertTrue(len(boundaries) >= 1)
        self.assertIsInstance(boundaries[0], FailureBoundary)
        self.assertEqual(boundaries[0].description, "SQLi blocked")

    def test_failure_boundary_injection_prevents_repeat(self):
        """After a failure boundary is recorded, deduped entries skip duplicates."""
        self.mem.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY,
            content="path /admin blocked by WAF",
            confidence=0.0,
        ))
        self.mem.store_entry("p1", MemoryEntry(
            kind=MemoryKind.FAILURE_BOUNDARY,
            content="path /admin blocked by WAF",
            confidence=0.0,
        ))
        deduped = self.mem.get_deduped_entries("p1", MemoryKind.FAILURE_BOUNDARY)
        waf_entries = [m for m in deduped if m.content == "path /admin blocked by WAF"]
        self.assertEqual(len(waf_entries), 1)

    def test_no_failure_boundaries_when_none_stored(self):
        boundaries = self.mem.get_failure_boundaries("p1")
        self.assertEqual(len(boundaries), 0)


if __name__ == "__main__":
    unittest.main()