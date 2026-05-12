"""Tests for event_compat — L1 event classification adapter."""

import unittest

from attack_agent.team.event_compat import classify_candidate_flag_event, is_genuine_candidate_flag
from attack_agent.team.protocol import IdeaStatus


class TestClassifyCandidateFlagEvent(unittest.TestCase):
    """classify_candidate_flag_event routes old candidate_flag events correctly."""

    def test_pending_status_routes_to_idea_proposed(self):
        result = classify_candidate_flag_event(
            {"flag": "try SQLi", "idea_id": "i1", "status": "pending"},
            source="idea_service",
        )
        self.assertEqual(result, "idea_proposed")

    def test_claimed_status_routes_to_idea_claimed(self):
        result = classify_candidate_flag_event(
            {"flag": "try SQLi", "idea_id": "i1", "status": "claimed", "solver_id": "s1"},
            source="idea_service",
        )
        self.assertEqual(result, "idea_claimed")

    def test_verified_status_routes_to_idea_verified(self):
        result = classify_candidate_flag_event(
            {"flag": "flag{abc}", "idea_id": "i1", "status": "verified"},
            source="idea_service",
        )
        self.assertEqual(result, "idea_verified")

    def test_failed_status_routes_to_idea_failed(self):
        result = classify_candidate_flag_event(
            {"flag": "try SQLi", "idea_id": "i1", "status": "failed"},
            source="idea_service",
        )
        self.assertEqual(result, "idea_failed")

    def test_shelved_status_routes_to_idea_proposed(self):
        result = classify_candidate_flag_event(
            {"flag": "old idea", "idea_id": "i1", "status": "shelved"},
            source="idea_service",
        )
        self.assertEqual(result, "idea_proposed")

    def test_state_sync_without_status_is_genuine_flag(self):
        result = classify_candidate_flag_event(
            {"flag": "flag{abc}", "confidence": 0.9},
            source="state_sync",
        )
        self.assertEqual(result, "candidate_flag")

    def test_runtime_without_status_is_genuine_flag(self):
        result = classify_candidate_flag_event(
            {"flag": "flag{abc}", "confidence": 0.8},
            source="runtime",
        )
        self.assertEqual(result, "candidate_flag")

    def test_merge_hub_with_arbitration_is_idea(self):
        result = classify_candidate_flag_event(
            {"flag": "flag{abc}", "arbitration": True},
            source="merge_hub",
        )
        self.assertEqual(result, "idea_proposed")

    def test_merge_hub_with_merged_from_ids_is_idea(self):
        result = classify_candidate_flag_event(
            {"flag": "merged idea", "merged_from_ids": ["i1", "i2"]},
            source="merge_hub",
        )
        self.assertEqual(result, "idea_proposed")

    def test_merge_hub_with_idea_id_is_idea(self):
        result = classify_candidate_flag_event(
            {"flag": "some idea", "idea_id": "i1"},
            source="merge_hub",
        )
        self.assertEqual(result, "idea_proposed")

    def test_idea_service_with_idea_id_no_status_is_idea(self):
        result = classify_candidate_flag_event(
            {"flag": "idea without status", "idea_id": "i1"},
            source="idea_service",
        )
        self.assertEqual(result, "idea_proposed")

    def test_system_source_no_status_is_genuine_flag(self):
        result = classify_candidate_flag_event(
            {"flag": "flag{abc}", "confidence": 0.9},
            source="system",
        )
        self.assertEqual(result, "candidate_flag")


class TestIsGenuineCandidateFlag(unittest.TestCase):
    """is_genuine_candidate_flag returns True only for real flags."""

    def test_genuine_flag_from_state_sync(self):
        self.assertTrue(is_genuine_candidate_flag(
            "candidate_flag",
            {"flag": "flag{abc}", "confidence": 0.9},
            source="state_sync",
        ))

    def test_idea_service_event_is_not_genuine(self):
        self.assertFalse(is_genuine_candidate_flag(
            "candidate_flag",
            {"flag": "idea", "status": "pending", "idea_id": "i1"},
            source="idea_service",
        ))

    def test_non_candidate_flag_event_type_is_not_genuine(self):
        self.assertFalse(is_genuine_candidate_flag(
            "idea_proposed",
            {"flag": "idea"},
            source="idea_service",
        ))

    def test_merge_hub_event_is_not_genuine(self):
        self.assertFalse(is_genuine_candidate_flag(
            "candidate_flag",
            {"flag": "merged", "arbitration": True},
            source="merge_hub",
        ))


if __name__ == "__main__":
    unittest.main()