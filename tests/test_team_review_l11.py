"""L11 acceptance tests: review execution path.

Proves:
- Approved submit executes once, no second pending review
- Modified review applies modified payload
- review_consumed event prevents double execution
"""

import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig as BBConfig
from attack_agent.team.protocol import (
    ActionType,
    HumanDecision,
    HumanDecisionChoice,
    PolicyOutcome,
    ReviewRequest,
    ReviewStatus,
    StrategyAction,
)
from attack_agent.team.review import HumanReviewGate
from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig


def _make_bb() -> BlackboardService:
    tmp = tempfile.mkdtemp()
    return BlackboardService(BBConfig(db_path=f"{tmp}/test_review_l11.db"))


def _make_runtime(bb: BlackboardService) -> TeamRuntime:
    return TeamRuntime(TeamRuntimeConfig(blackboard_db_path=bb.config.db_path))


class TestL11ApprovedSubmitOnce(unittest.TestCase):
    """L11: approved submit creates exactly 1 review and 1 execution."""

    def setUp(self):
        self.bb = _make_bb()
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test")
        self.gate = HumanReviewGate()
        self.runtime = _make_runtime(self.bb)

    def tearDown(self):
        self.runtime.close()

    def test_approved_submit_no_second_review_via_runtime(self):
        # Create a high-risk submit review request
        request = ReviewRequest(
            project_id="p1",
            action_type="submit_flag",
            risk_level="high",
            title="Submit flag for p1",
            description="Flag value: flag{test}",
            proposed_action="submit flag{test}",
            proposed_action_payload={"action_type": "submit_flag", "risk_level": "high", "target_idea_id": "flag_1", "reason": "submit flag: flag{test}", "project_id": "p1"},
        )
        self.gate.create_review(request, self.bb)

        # Verify 1 pending review
        pending = self.gate.list_pending_reviews("p1", self.bb)
        self.assertEqual(len(pending), 1)

        # Approve via TeamRuntime.resolve_review — this calls _execute_approved_action
        review = self.runtime.resolve_review(
            request.request_id, HumanDecisionChoice.APPROVED,
            reason="approved for testing", decided_by="test_user",
            project_id="p1",
        )

        # Verify review is APPROVED
        self.assertEqual(review.status, ReviewStatus.APPROVED)

        # Verify no second pending review was created
        pending_after = self.gate.list_pending_reviews("p1", self.bb)
        self.assertEqual(len(pending_after), 0, "No second pending review should be created")

        # Verify review_consumed event exists
        events = self.bb.load_events("p1")
        consumed_events = [
            e for e in events
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("outcome") == "review_consumed"
        ]
        self.assertTrue(len(consumed_events) >= 1, "review_consumed event must exist")

    def test_gate_resolve_does_not_create_second_review(self):
        # Test that HumanReviewGate.resolve_review alone does not
        # create a second review (the gate just resolves the status)
        request = ReviewRequest(
            project_id="p1",
            action_type="submit_flag",
            risk_level="high",
            title="Submit flag",
            proposed_action_payload={"action_type": "submit_flag", "risk_level": "high"},
        )
        self.gate.create_review(request, self.bb)
        pending = self.gate.list_pending_reviews("p1", self.bb)
        self.assertEqual(len(pending), 1)

        decision = HumanDecision(
            request_id=request.request_id,
            decision=HumanDecisionChoice.APPROVED,
            decided_by="test_user",
        )
        review = self.gate.resolve_review(request.request_id, decision, self.bb, project_id="p1")
        self.assertEqual(review.status, ReviewStatus.APPROVED)

        pending_after = self.gate.list_pending_reviews("p1", self.bb)
        self.assertEqual(len(pending_after), 0, "Gate resolve does not create second review")


class TestL11ModifiedReview(unittest.TestCase):
    """L11: modified review applies modified payload and records delta."""

    def setUp(self):
        self.bb = _make_bb()
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test")
        self.gate = HumanReviewGate()

    def tearDown(self):
        self.bb.close()

    def test_modified_review_records_delta_in_event(self):
        original_payload = {
            "action_type": "submit_flag",
            "risk_level": "high",
            "target_idea_id": "flag_1",
            "reason": "submit flag: flag{test}",
        }
        request = ReviewRequest(
            project_id="p1",
            action_type="submit_flag",
            risk_level="high",
            title="Submit flag for p1",
            description="Flag value: flag{test}",
            proposed_action="submit flag{test}",
            proposed_action_payload=original_payload,
        )
        self.gate.create_review(request, self.bb)

        # Modify the review — change risk_level and reason
        decision = HumanDecision(
            request_id=request.request_id,
            decision=HumanDecisionChoice.MODIFIED,
            decided_by="test_user",
            reason="reduce risk level",
            modified_params={"risk_level": "medium", "reason": "submit flag (modified risk)"},
        )
        review = self.gate.resolve_review(request.request_id, decision, self.bb, project_id="p1")

        # Verify review is MODIFIED
        self.assertEqual(review.status, ReviewStatus.MODIFIED)

        # Verify resolution event has delta and modified payload
        events = self.bb.load_events("p1")
        resolution_events = [
            e for e in events
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("outcome") == "review_modified"
        ]
        self.assertTrue(len(resolution_events) >= 1, "review_modified resolution event must exist")

        resolution = resolution_events[0].payload
        # Should contain delta
        self.assertIn("delta", resolution)
        delta = resolution["delta"]
        self.assertTrue(any("risk_level" in d for d in delta), "delta should mention risk_level change")

        # Should contain modified_action_payload
        self.assertIn("modified_action_payload", resolution)
        modified_payload = resolution["modified_action_payload"]
        self.assertEqual(modified_payload["risk_level"], "medium", "modified payload should have medium risk")

        # Verify review.proposed_action_payload was updated
        self.assertEqual(review.proposed_action_payload["risk_level"], "medium")

    def test_modified_review_causal_chain_in_event_log(self):
        original_payload = {"action_type": "launch_solver", "risk_level": "low"}
        request = ReviewRequest(
            project_id="p1",
            action_type="launch_solver",
            risk_level="low",
            title="Launch solver for p1",
            proposed_action_payload=original_payload,
        )
        self.gate.create_review(request, self.bb)

        decision = HumanDecision(
            request_id=request.request_id,
            decision=HumanDecisionChoice.MODIFIED,
            decided_by="test_user",
            reason="change profile",
            modified_params={"target_solver_id": "solver_network_v2"},
        )
        self.gate.resolve_review(request.request_id, decision, self.bb, project_id="p1")

        # Verify causal_ref links the resolution event to the review_id
        events = self.bb.load_events("p1")
        resolution_events = [
            e for e in events
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("outcome") == "review_modified"
            and e.causal_ref == request.request_id
        ]
        self.assertTrue(len(resolution_events) >= 1,
                         "Resolution event should have causal_ref linking to review_id")


class TestL11ReviewConsumedPreventsDoubleExecution(unittest.TestCase):
    """L11: review_consumed event prevents double execution on re-approval."""

    def setUp(self):
        self.bb = _make_bb()
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test")
        self.gate = HumanReviewGate()
        self.runtime = _make_runtime(self.bb)

    def tearDown(self):
        self.runtime.close()

    def test_second_approval_skips_execution(self):
        # Create review
        request = ReviewRequest(
            project_id="p1",
            action_type="launch_solver",
            risk_level="low",
            title="Launch solver",
            proposed_action_payload={"action_type": "launch_solver"},
        )
        self.gate.create_review(request, self.bb)

        # First approval
        decision1 = HumanDecision(
            request_id=request.request_id,
            decision=HumanDecisionChoice.APPROVED,
            decided_by="user1",
        )
        review1 = self.runtime.resolve_review(
            request.request_id, HumanDecisionChoice.APPROVED, reason="ok",
            decided_by="user1", project_id="p1",
        )

        # Count review_consumed events
        events = self.bb.load_events("p1")
        consumed_count = len([
            e for e in events
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("outcome") == "review_consumed"
        ])
        self.assertEqual(consumed_count, 1, "Exactly one review_consumed event")

        # Second approval — should be blocked by review_consumed check
        # (this tests the guard in runtime.resolve_review)
        review2 = self.runtime.resolve_review(
            request.request_id, HumanDecisionChoice.APPROVED, reason="duplicate",
            decided_by="user2", project_id="p1",
        )
        # Should still be APPROVED but no additional execution events
        events_after = self.bb.load_events("p1")
        consumed_after = len([
            e for e in events_after
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("outcome") == "review_consumed"
        ])
        self.assertEqual(consumed_after, 1, "No additional review_consumed on second approval")


if __name__ == "__main__":
    unittest.main()