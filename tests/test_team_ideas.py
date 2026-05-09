"""Tests for IdeaService — Phase D."""

import os
import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.ideas import IdeaService
from attack_agent.team.protocol import IdeaEntry, IdeaStatus, MemoryKind


def _make_bb(test_name: str) -> BlackboardService:
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, f"bb_idea_{test_name}.db")
    return BlackboardService(BlackboardConfig(db_path=db_path))


class TestIdeaServicePropose(unittest.TestCase):
    """propose creates IdeaEntry and writes to Blackboard."""

    def setUp(self):
        self.bb = _make_bb("propose")
        self.idea_svc = IdeaService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_propose_idea(self):
        idea = self.idea_svc.propose("p1", "try SQL injection on /login")
        self.assertIsNotNone(idea)
        self.assertTrue(idea.idea_id)
        self.assertEqual(idea.description, "try SQL injection on /login")
        self.assertEqual(idea.status, IdeaStatus.PENDING)
        self.assertEqual(idea.priority, 100)

    def test_propose_with_custom_priority(self):
        idea = self.idea_svc.propose("p1", "check cookie", priority=50)
        self.assertEqual(idea.priority, 50)

    def test_propose_writes_to_blackboard(self):
        self.idea_svc.propose("p1", "brute force admin")
        ideas = self.bb.list_ideas("p1")
        self.assertTrue(len(ideas) >= 1)
        self.assertEqual(ideas[0].description, "brute force admin")


class TestIdeaServiceClaim(unittest.TestCase):
    """claim marks an idea as claimed by a solver."""

    def setUp(self):
        self.bb = _make_bb("claim")
        self.idea_svc = IdeaService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.idea = self.idea_svc.propose("p1", "test XSS")

    def tearDown(self):
        self.bb.close()

    def test_claim_idea(self):
        result = self.idea_svc.claim("p1", self.idea.idea_id, "solver_1")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, IdeaStatus.CLAIMED)
        self.assertEqual(result.solver_id, "solver_1")

    def test_claim_unknown_idea(self):
        result = self.idea_svc.claim("p1", "nonexistent", "solver_1")
        self.assertIsNone(result)

    def test_claim_already_claimed_returns_none(self):
        self.idea_svc.claim("p1", self.idea.idea_id, "solver_1")
        # second claim should fail since status is now CLAIMED
        result = self.idea_svc.claim("p1", self.idea.idea_id, "solver_2")
        # claimed ideas can't be re-claimed (only PENDING/FAILED/SHELVED)
        self.assertIsNone(result)


class TestIdeaServiceMarkVerified(unittest.TestCase):
    """mark_verified marks an idea as verified (flag success)."""

    def setUp(self):
        self.bb = _make_bb("verified")
        self.idea_svc = IdeaService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.idea = self.idea_svc.propose("p1", "flag found in cookie")

    def tearDown(self):
        self.bb.close()

    def test_mark_verified(self):
        result = self.idea_svc.mark_verified("p1", self.idea.idea_id)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, IdeaStatus.VERIFIED)

    def test_mark_verified_unknown_idea(self):
        result = self.idea_svc.mark_verified("p1", "nonexistent")
        self.assertIsNone(result)


class TestIdeaServiceMarkFailed(unittest.TestCase):
    """mark_failed marks an idea as failed with FailureBoundary refs."""

    def setUp(self):
        self.bb = _make_bb("failed")
        self.idea_svc = IdeaService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.idea = self.idea_svc.propose("p1", "try SQLi")

    def tearDown(self):
        self.bb.close()

    def test_mark_failed(self):
        result = self.idea_svc.mark_failed(
            "p1", self.idea.idea_id, ["fb_001", "fb_002"]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, IdeaStatus.FAILED)
        self.assertEqual(result.failure_boundary_refs, ["fb_001", "fb_002"])

    def test_mark_failed_writes_failure_boundary_event(self):
        self.idea_svc.mark_failed("p1", self.idea.idea_id, ["fb_001"])
        state = self.bb.rebuild_state("p1")
        # should have a failure_boundary entry from the action_outcome event
        failures = [m for m in state.facts if m.kind == MemoryKind.FAILURE_BOUNDARY]
        self.assertTrue(len(failures) >= 1)

    def test_mark_failed_unknown_idea(self):
        result = self.idea_svc.mark_failed("p1", "nonexistent", [])
        self.assertIsNone(result)


class TestIdeaServiceListAvailable(unittest.TestCase):
    """list_available returns unclaimed or solver-specific ideas."""

    def setUp(self):
        self.bb = _make_bb("list")
        self.idea_svc = IdeaService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.idea1 = self.idea_svc.propose("p1", "idea A", priority=80)
        self.idea2 = self.idea_svc.propose("p1", "idea B", priority=120)

    def tearDown(self):
        self.bb.close()

    def test_list_available_unclaimed(self):
        available = self.idea_svc.list_available("p1")
        # at least the two we proposed (they start as PENDING)
        self.assertTrue(len(available) >= 2)

    def test_list_available_for_solver(self):
        self.idea_svc.claim("p1", self.idea1.idea_id, "solver_1")
        available = self.idea_svc.list_available("p1", solver_id="solver_1")
        # solver_1 sees its claimed idea + remaining pending ideas
        claimed_by_solver = [i for i in available if i.solver_id == "solver_1"]
        self.assertTrue(len(claimed_by_solver) >= 1)

    def test_list_available_excludes_verified(self):
        self.idea_svc.mark_verified("p1", self.idea1.idea_id)
        available = self.idea_svc.list_available("p1")
        verified = [i for i in available if i.status == IdeaStatus.VERIFIED]
        self.assertEqual(len(verified), 0)


class TestIdeaServiceGetBestUnclaimed(unittest.TestCase):
    """get_best_unclaimed returns highest-priority unclaimed idea."""

    def setUp(self):
        self.bb = _make_bb("best")
        self.idea_svc = IdeaService(self.bb)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.idea_low = self.idea_svc.propose("p1", "low priority idea", priority=30)
        self.idea_high = self.idea_svc.propose("p1", "high priority idea", priority=200)

    def tearDown(self):
        self.bb.close()

    def test_best_unclaimed_is_highest_priority(self):
        best = self.idea_svc.get_best_unclaimed("p1")
        self.assertIsNotNone(best)
        self.assertEqual(best.description, "high priority idea")
        self.assertEqual(best.priority, 200)

    def test_best_unclaimed_none_when_all_claimed(self):
        self.idea_svc.claim("p1", self.idea_low.idea_id, "s1")
        self.idea_svc.claim("p1", self.idea_high.idea_id, "s2")
        best = self.idea_svc.get_best_unclaimed("p1")
        self.assertIsNone(best)

    def test_best_unclaimed_none_when_no_ideas(self):
        bb2 = _make_bb("best_empty")
        idea_svc2 = IdeaService(bb2)
        best = idea_svc2.get_best_unclaimed("p_empty")
        self.assertIsNone(best)
        bb2.close()


if __name__ == "__main__":
    unittest.main()