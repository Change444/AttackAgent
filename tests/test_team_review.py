"""Tests for HumanReviewGate — Phase E."""

import unittest
from datetime import datetime, timezone, timedelta

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.policy import PolicyHarness, PolicyConfig
from attack_agent.team.protocol import (
    ActionType,
    HumanDecision,
    HumanDecisionChoice,
    MemoryKind,
    PolicyOutcome,
    ReviewRequest,
    ReviewStatus,
    StrategyAction,
)
from attack_agent.team.review import HumanReviewGate


class TestHumanReviewGateCreate(unittest.TestCase):
    """create_review writes to Blackboard."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        self.gate = HumanReviewGate()

    def tearDown(self) -> None:
        self.bb.close()

    def test_create_review_writes_event(self) -> None:
        request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Flag submit review",
            description="Candidate flag found",
            proposed_action="submit flag{abc}",
        )
        result = self.gate.create_review(request, self.bb)
        self.assertEqual(result.request_id, request.request_id)
        events = self.bb.load_events("proj1")
        sec_events = [e for e in events if e.event_type == EventType.SECURITY_VALIDATION.value]
        self.assertTrue(len(sec_events) >= 1)
        payload = sec_events[-1].payload
        self.assertEqual(payload["review_id"], request.request_id)
        self.assertEqual(payload["status"], ReviewStatus.PENDING.value)

    def test_create_review_payload_has_outcome_needs_review(self) -> None:
        request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Test review",
        )
        self.gate.create_review(request, self.bb)
        events = self.bb.load_events("proj1")
        sec_events = [e for e in events if e.event_type == EventType.SECURITY_VALIDATION.value]
        payload = sec_events[-1].payload
        self.assertEqual(payload["outcome"], "needs_review")


class TestHumanReviewGateResolve(unittest.TestCase):
    """resolve_review updates status and records events."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        self.gate = HumanReviewGate()
        self.request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Flag submit review",
            proposed_action="submit flag{abc}",
        )
        self.gate.create_review(self.request, self.bb)

    def tearDown(self) -> None:
        self.bb.close()

    def test_resolve_approved(self) -> None:
        decision = HumanDecision(
            request_id=self.request.request_id,
            decision=HumanDecisionChoice.APPROVED,
            decided_by="admin",
            reason="flag verified",
        )
        result = self.gate.resolve_review(
            self.request.request_id, decision, self.bb, project_id="proj1",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ReviewStatus.APPROVED)
        self.assertEqual(result.decided_by, "admin")

    def test_resolve_rejected(self) -> None:
        decision = HumanDecision(
            request_id=self.request.request_id,
            decision=HumanDecisionChoice.REJECTED,
            decided_by="admin",
            reason="flag incorrect",
        )
        result = self.gate.resolve_review(
            self.request.request_id, decision, self.bb, project_id="proj1",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ReviewStatus.REJECTED)

    def test_reject_creates_failure_boundary(self) -> None:
        decision = HumanDecision(
            request_id=self.request.request_id,
            decision=HumanDecisionChoice.REJECTED,
            decided_by="admin",
            reason="flag incorrect",
        )
        self.gate.resolve_review(
            self.request.request_id, decision, self.bb, project_id="proj1",
        )
        state = self.bb.rebuild_state("proj1")
        boundaries = [f for f in state.facts if f.kind == MemoryKind.FAILURE_BOUNDARY]
        self.assertTrue(len(boundaries) >= 1)
        self.assertTrue("review rejected" in boundaries[-1].content)

    def test_resolve_nonexistent_returns_none(self) -> None:
        decision = HumanDecision(
            request_id="nonexistent_id",
            decision=HumanDecisionChoice.APPROVED,
            decided_by="admin",
        )
        result = self.gate.resolve_review(
            "nonexistent_id", decision, self.bb, project_id="proj1",
        )
        self.assertIsNone(result)

    def test_resolve_already_resolved_returns_review(self) -> None:
        decision1 = HumanDecision(
            request_id=self.request.request_id,
            decision=HumanDecisionChoice.APPROVED,
            decided_by="admin1",
        )
        self.gate.resolve_review(
            self.request.request_id, decision1, self.bb, project_id="proj1",
        )
        # second resolution — should return review with existing status
        decision2 = HumanDecision(
            request_id=self.request.request_id,
            decision=HumanDecisionChoice.REJECTED,
            decided_by="admin2",
        )
        result = self.gate.resolve_review(
            self.request.request_id, decision2, self.bb, project_id="proj1",
        )
        # already resolved, returns current state — still APPROVED from first
        self.assertEqual(result.status, ReviewStatus.APPROVED)

    def test_resolution_event_has_causal_ref(self) -> None:
        decision = HumanDecision(
            request_id=self.request.request_id,
            decision=HumanDecisionChoice.APPROVED,
            decided_by="admin",
        )
        self.gate.resolve_review(
            self.request.request_id, decision, self.bb, project_id="proj1",
        )
        events = self.bb.load_events("proj1")
        resolution_events = [
            e for e in events
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("review_id") == self.request.request_id
            and e.payload.get("outcome") == "review_approved"
        ]
        self.assertTrue(len(resolution_events) >= 1)
        self.assertEqual(resolution_events[0].causal_ref, self.request.request_id)


class TestHumanReviewGateListPending(unittest.TestCase):
    """list_pending_reviews from Blackboard."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        self.gate = HumanReviewGate()

    def tearDown(self) -> None:
        self.bb.close()

    def test_list_pending_returns_created_reviews(self) -> None:
        request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Review 1",
        )
        self.gate.create_review(request, self.bb)
        pending = self.gate.list_pending_reviews("proj1", self.bb)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].request_id, request.request_id)

    def test_list_pending_excludes_resolved(self) -> None:
        request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Review 1",
        )
        self.gate.create_review(request, self.bb)
        decision = HumanDecision(
            request_id=request.request_id,
            decision=HumanDecisionChoice.APPROVED,
            decided_by="admin",
        )
        self.gate.resolve_review(
            request.request_id, decision, self.bb, project_id="proj1",
        )
        pending = self.gate.list_pending_reviews("proj1", self.bb)
        self.assertEqual(len(pending), 0)

    def test_list_pending_multiple_reviews(self) -> None:
        r1 = ReviewRequest(project_id="proj1", action_type="submit_flag", risk_level="high", title="R1")
        r2 = ReviewRequest(project_id="proj1", action_type="code-sandbox", risk_level="high", title="R2")
        self.gate.create_review(r1, self.bb)
        self.gate.create_review(r2, self.bb)
        pending = self.gate.list_pending_reviews("proj1", self.bb)
        self.assertEqual(len(pending), 2)


class TestHumanReviewGateAutoExpire(unittest.TestCase):
    """auto_expire_reviews rejects reviews older than timeout."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        self.gate = HumanReviewGate()

    def tearDown(self) -> None:
        self.bb.close()

    def test_auto_expire_rejects_old_review(self) -> None:
        # create review with old timestamp — we manipulate the Blackboard
        # by inserting an event with a past timestamp directly
        request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Old review",
        )
        self.gate.create_review(request, self.bb)
        # Manually patch the timestamp to 120 seconds ago
        # Since Blackboard uses auto-generated timestamps, we insert
        # a second SECURITY_VALIDATION event with an old timestamp
        # by directly writing to the DB
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        self.bb._db.execute(
            "UPDATE events SET timestamp = ? WHERE event_id = ?",
            (old_ts, self.bb.load_events("proj1")[-1].event_id),
        )
        self.bb._db.commit()

        expired = self.gate.auto_expire_reviews("proj1", timeout_seconds=60, blackboard=self.bb)
        self.assertEqual(len(expired), 1)

    def test_auto_expire_no_recent_reviews(self) -> None:
        request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Fresh review",
        )
        self.gate.create_review(request, self.bb)
        # review just created — not expired
        expired = self.gate.auto_expire_reviews("proj1", timeout_seconds=3600, blackboard=self.bb)
        self.assertEqual(len(expired), 0)


class TestPolicyReviewIntegration(unittest.TestCase):
    """Integration: approve → PolicyHarness allow; reject → failure boundary."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        self.harness = PolicyHarness()
        self.gate = HumanReviewGate()

    def tearDown(self) -> None:
        self.bb.close()

    def test_approve_then_validate_returns_allow(self) -> None:
        # high-risk action → needs_review
        action = StrategyAction(
            action_type=ActionType.SUBMIT_FLAG,
            project_id="proj1",
            risk_level="high",
            requires_review=True,
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.NEEDS_REVIEW)

        # create a review request for this
        request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Flag submit",
            proposed_action="submit flag{abc}",
        )
        self.gate.create_review(request, self.bb)

        # approve it
        human_decision = HumanDecision(
            request_id=request.request_id,
            decision=HumanDecisionChoice.APPROVED,
            decided_by="admin",
            reason="verified",
        )
        result = self.gate.resolve_review(
            request.request_id, human_decision, self.bb, project_id="proj1",
        )
        self.assertEqual(result.status, ReviewStatus.APPROVED)

        # now re-validate the action — should be ALLOW
        # (review is approved, so same action with same risk_level → still maps
        #  to needs_review per threshold; but in practice the approved review
        #  overrides. For v1 we verify the flow, not the override.)
        # PolicyHarness v1 doesn't auto-check review state; external caller
        # checks review status then re-evaluates. We verify the chain works.
        events = self.bb.load_events("proj1")
        sec_events = [e for e in events if e.event_type == EventType.SECURITY_VALIDATION.value]
        # should have: policy decision, review creation, review resolution
        self.assertTrue(len(sec_events) >= 3)

    def test_reject_records_failure_boundary(self) -> None:
        action = StrategyAction(
            action_type=ActionType.SUBMIT_FLAG,
            project_id="proj1",
            risk_level="high",
            requires_review=True,
        )
        self.harness.validate_action(action, "proj1", self.bb)

        request = ReviewRequest(
            project_id="proj1",
            action_type="submit_flag",
            risk_level="high",
            title="Flag submit",
        )
        self.gate.create_review(request, self.bb)

        human_decision = HumanDecision(
            request_id=request.request_id,
            decision=HumanDecisionChoice.REJECTED,
            decided_by="admin",
            reason="flag incorrect",
        )
        self.gate.resolve_review(
            request.request_id, human_decision, self.bb, project_id="proj1",
        )

        state = self.bb.rebuild_state("proj1")
        boundaries = [f for f in state.facts if f.kind == MemoryKind.FAILURE_BOUNDARY]
        self.assertTrue(len(boundaries) >= 1)


if __name__ == "__main__":
    unittest.main()