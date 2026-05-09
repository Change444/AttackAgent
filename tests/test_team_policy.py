"""Tests for PolicyHarness — Phase E."""

import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.policy import PolicyConfig, PolicyHarness, RiskThresholds
from attack_agent.team.protocol import (
    ActionType,
    PolicyDecision,
    PolicyOutcome,
    StrategyAction,
)


class TestPolicyHarnessBasic(unittest.TestCase):
    """Basic PolicyHarness validate_action tests."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        self.harness = PolicyHarness()

    def tearDown(self) -> None:
        self.bb.close()

    def test_medium_risk_action_allowed(self) -> None:
        action = StrategyAction(
            action_type=ActionType.STEER_SOLVER,
            project_id="proj1",
            risk_level="medium",
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.ALLOW)

    def test_low_risk_action_allowed(self) -> None:
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="low",
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.ALLOW)

    def test_critical_risk_denied(self) -> None:
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="critical",
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.DENY)

    def test_high_risk_needs_review(self) -> None:
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="high",
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.NEEDS_REVIEW)

    def test_submit_flag_high_risk_needs_review(self) -> None:
        action = StrategyAction(
            action_type=ActionType.SUBMIT_FLAG,
            project_id="proj1",
            risk_level="high",
            requires_review=True,
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.NEEDS_REVIEW)

    def test_submit_flag_medium_risk_needs_review_by_requires_review(self) -> None:
        """Even medium-risk submit with requires_review=True → needs_review."""
        action = StrategyAction(
            action_type=ActionType.SUBMIT_FLAG,
            project_id="proj1",
            risk_level="medium",
            requires_review=True,
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.NEEDS_REVIEW)

    def test_submit_flag_low_without_requires_review_allowed(self) -> None:
        """Low-risk submit without requires_review → allow."""
        action = StrategyAction(
            action_type=ActionType.SUBMIT_FLAG,
            project_id="proj1",
            risk_level="low",
            requires_review=False,
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.ALLOW)


class TestPolicyHarnessBudget(unittest.TestCase):
    """Budget exceeded tests."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        policy_config = PolicyConfig(budget_limit=5.0)
        self.harness = PolicyHarness(policy_config)

    def tearDown(self) -> None:
        self.bb.close()

    def test_budget_exceeded(self) -> None:
        # create sessions to exceed budget
        for i in range(3):
            self.bb.append_event(
                "proj1", EventType.WORKER_ASSIGNED.value,
                {"solver_id": f"s{i}", "profile": "network"},
            )
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="low",
            budget_request=1.0,
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        # 3 sessions × 5.0 baseline each = 15.0 > 5.0 limit
        self.assertEqual(decision.decision, PolicyOutcome.BUDGET_EXCEEDED)


class TestPolicyHarnessRateLimit(unittest.TestCase):
    """Rate limit tests."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        policy_config = PolicyConfig(rate_limit_window=60, rate_limit_max=2)
        self.harness = PolicyHarness(policy_config)

    def tearDown(self) -> None:
        self.bb.close()

    def test_rate_limit_exceeded(self) -> None:
        # push 2 worker assignments to fill rate limit
        self.bb.append_event(
            "proj1", EventType.WORKER_ASSIGNED.value,
            {"solver_id": "s1", "profile": "network"},
        )
        self.bb.append_event(
            "proj1", EventType.WORKER_ASSIGNED.value,
            {"solver_id": "s2", "profile": "network"},
        )
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="low",
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.RATE_LIMIT)


class TestPolicyHarnessBlackboardRecording(unittest.TestCase):
    """PolicyDecision written to Blackboard event journal."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        self.harness = PolicyHarness()

    def tearDown(self) -> None:
        self.bb.close()

    def test_decision_recorded_in_journal(self) -> None:
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="medium",
        )
        self.harness.validate_action(action, "proj1", self.bb)
        events = self.bb.load_events("proj1")
        sec_events = [e for e in events if e.event_type == EventType.SECURITY_VALIDATION.value]
        self.assertTrue(len(sec_events) >= 1)
        # payload should contain PolicyDecision fields
        payload = sec_events[-1].payload
        self.assertEqual(payload["decision"], PolicyOutcome.ALLOW.value)

    def test_deny_decision_recorded_with_reason(self) -> None:
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="critical",
        )
        self.harness.validate_action(action, "proj1", self.bb)
        events = self.bb.load_events("proj1")
        sec_events = [e for e in events if e.event_type == EventType.SECURITY_VALIDATION.value]
        payload = sec_events[-1].payload
        self.assertEqual(payload["decision"], PolicyOutcome.DENY.value)
        self.assertTrue("critical" in payload["reason"])


class TestPolicyHarnessCustomThresholds(unittest.TestCase):
    """Custom risk threshold mapping."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        thresholds = RiskThresholds(critical="deny", high="deny", medium="needs_review", low="allow")
        policy_config = PolicyConfig(risk_thresholds=thresholds)
        self.harness = PolicyHarness(policy_config)

    def tearDown(self) -> None:
        self.bb.close()

    def test_high_risk_custom_threshold_deny(self) -> None:
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="high",
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.DENY)

    def test_medium_risk_custom_threshold_needs_review(self) -> None:
        action = StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id="proj1",
            risk_level="medium",
        )
        decision = self.harness.validate_action(action, "proj1", self.bb)
        self.assertEqual(decision.decision, PolicyOutcome.NEEDS_REVIEW)


if __name__ == "__main__":
    unittest.main()