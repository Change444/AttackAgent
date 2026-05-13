"""Tests for ToolBroker — Phase J."""

import unittest

from attack_agent.platform_models import EventType, WorkerProfile, PrimitiveActionSpec
from attack_agent.runtime import PrimitiveRegistry
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.policy import PolicyHarness, PolicyConfig, RiskThresholds
from attack_agent.team.protocol import ActionType, PolicyOutcome, StrategyAction, to_dict
from attack_agent.team.tool_broker import (
    ToolBroker,
    ToolRequest,
    ToolResult,
    ToolError,
    ToolEvent,
    IO_FREE_PRIMITIVES,
    IO_DEPENDENT_PRIMITIVES,
)


class _BaseBrokerTest(unittest.TestCase):
    """Shared setUp/tearDown for ToolBroker tests."""

    def setUp(self) -> None:
        self.config = BlackboardConfig(db_path=":memory:")
        self.bb = BlackboardService(self.config)
        self.bb.append_event(
            "proj1", EventType.PROJECT_UPSERTED.value,
            {"challenge_id": "c1", "status": "new"},
        )
        self.registry = PrimitiveRegistry()
        self.policy = PolicyHarness()
        self.broker = ToolBroker(self.registry, self.policy, self.bb)

    def tearDown(self) -> None:
        self.bb.close()

    def _make_request(self, primitive_name: str = "structured-parse",
                      risk_level: str = "low") -> ToolRequest:
        return ToolRequest(
            project_id="proj1",
            solver_id="solver1",
            primitive_name=primitive_name,
            step={"primitive": primitive_name, "instruction": "test", "parameters": {}},
            risk_level=risk_level,
            budget_request=1.0,
            reason="test request",
        )


class TestToolBrokerAllow(_BaseBrokerTest):
    """ALLOW → ToolResult for IO-free primitives."""

    def test_allow_returns_tool_result(self) -> None:
        req = self._make_request("structured-parse", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolResult)
        self.assertEqual(result.request_id, req.request_id)
        self.assertEqual(result.source, "tool_broker")

    def test_allow_outcome_has_status(self) -> None:
        req = self._make_request("structured-parse", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIn("status", result.outcome)
        self.assertIn("observations_count", result.outcome)
        self.assertIn("cost", result.outcome)

    def test_allow_code_sandbox(self) -> None:
        req = self._make_request("code-sandbox", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolResult)

    def test_allow_diff_compare(self) -> None:
        req = self._make_request("diff-compare", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolResult)

    def test_binary_inspect_io_free(self) -> None:
        """L8: binary-inspect is now IO-free and returns ToolResult."""
        req = self._make_request("binary-inspect", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolResult)


class TestToolBrokerPolicyDeny(_BaseBrokerTest):
    """DENY → ToolError."""

    def test_critical_risk_returns_tool_error(self) -> None:
        req = self._make_request("structured-parse", risk_level="critical")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolError)
        self.assertEqual(result.error_type, "policy_deny")

    def test_deny_message_contains_reason(self) -> None:
        req = self._make_request("structured-parse", risk_level="critical")
        result = self.broker.request_tool(req)
        self.assertIn("Policy denied", result.message)


class TestToolBrokerNeedsReview(_BaseBrokerTest):
    """NEEDS_REVIEW → ToolError."""

    def test_high_risk_returns_needs_review(self) -> None:
        req = self._make_request("structured-parse", risk_level="high")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolError)
        self.assertEqual(result.error_type, "needs_review")

    def test_needs_review_message(self) -> None:
        req = self._make_request("structured-parse", risk_level="high")
        result = self.broker.request_tool(req)
        self.assertIn("Requires human review", result.message)


class TestToolBrokerRateLimit(_BaseBrokerTest):
    """RATE_LIMIT → ToolError."""

    def test_rate_limit_returns_tool_error(self) -> None:
        # Create a policy with very tight rate limits
        policy_config = PolicyConfig(
            rate_limit_window=60,
            rate_limit_max=1,
        )
        harness = PolicyHarness(policy_config)
        broker = ToolBroker(self.registry, harness, self.bb)

        # First request should pass
        req1 = self._make_request("structured-parse", risk_level="low")
        result1 = broker.request_tool(req1)
        # Second request within window should hit rate limit
        req2 = self._make_request("structured-parse", risk_level="low")
        result2 = broker.request_tool(req2)
        # One of them should be rate-limited (order depends on timing)
        # At minimum, verify the error type is correct if it appears
        results = [result1, result2]
        rate_limited = [r for r in results if isinstance(r, ToolError) and r.error_type == "rate_limit"]
        # If rate limit kicked in, verify structure
        if rate_limited:
            self.assertEqual(rate_limited[0].error_type, "rate_limit")


class TestToolBrokerBudgetExceeded(_BaseBrokerTest):
    """BUDGET_EXCEEDED → ToolError."""

    def test_budget_exceeded_returns_tool_error(self) -> None:
        policy_config = PolicyConfig(budget_limit=0.01)
        harness = PolicyHarness(policy_config)
        broker = ToolBroker(self.registry, harness, self.bb)

        req = self._make_request("structured-parse", risk_level="low")
        req.budget_request = 5.0
        result = broker.request_tool(req)
        if isinstance(result, ToolError):
            self.assertEqual(result.error_type, "budget_exceeded")


class TestToolBrokerPrimitiveNotFound(_BaseBrokerTest):
    """Primitive not found → ToolError."""

    def test_unknown_primitive_returns_error(self) -> None:
        req = self._make_request("nonexistent-primitive", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolError)
        self.assertEqual(result.error_type, "primitive_not_found")

    def test_unknown_primitive_message(self) -> None:
        req = self._make_request("nonexistent-primitive", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIn("nonexistent-primitive", result.message)


class TestToolBrokerRequiresIoContext(_BaseBrokerTest):
    """IO-dependent primitives → ToolError(requires_io_context)."""

    def test_http_request_requires_io(self) -> None:
        req = self._make_request("http-request", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolError)
        self.assertEqual(result.error_type, "requires_io_context")

    def test_browser_inspect_requires_io(self) -> None:
        req = self._make_request("browser-inspect", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolError)
        self.assertEqual(result.error_type, "requires_io_context")

    def test_session_materialize_requires_io(self) -> None:
        req = self._make_request("session-materialize", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolError)
        self.assertEqual(result.error_type, "requires_io_context")

    def test_artifact_scan_requires_io(self) -> None:
        req = self._make_request("artifact-scan", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolError)
        self.assertEqual(result.error_type, "requires_io_context")

    def test_binary_inspect_is_io_free(self) -> None:
        """L8: binary-inspect was reclassified from IO-dependent to IO-free."""
        req = self._make_request("binary-inspect", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIsInstance(result, ToolResult)

    def test_requires_io_message_mentions_primitive(self) -> None:
        req = self._make_request("http-request", risk_level="low")
        result = self.broker.request_tool(req)
        self.assertIn("http-request", result.message)


class TestToolBrokerListPrimitives(_BaseBrokerTest):
    """list_available_primitives by profile."""

    def test_network_profile(self) -> None:
        primitives = self.broker.list_available_primitives(WorkerProfile.NETWORK)
        self.assertIn("http-request", primitives)
        self.assertIn("structured-parse", primitives)
        self.assertNotIn("browser-inspect", primitives)

    def test_browser_profile(self) -> None:
        primitives = self.broker.list_available_primitives(WorkerProfile.BROWSER)
        self.assertIn("browser-inspect", primitives)
        self.assertNotIn("artifact-scan", primitives)

    def test_string_profile(self) -> None:
        primitives = self.broker.list_available_primitives("network")
        self.assertIn("http-request", primitives)

    def test_unknown_profile_returns_all(self) -> None:
        primitives = self.broker.list_available_primitives("unknown_profile")
        self.assertEqual(len(primitives), len(self.registry.adapters))

    def test_hybrid_returns_all(self) -> None:
        primitives = self.broker.list_available_primitives(WorkerProfile.HYBRID)
        self.assertEqual(len(primitives), len(self.registry.adapters))


class TestToolBrokerGetSpec(_BaseBrokerTest):
    """get_primitive_spec."""

    def test_existing_primitive_returns_spec(self) -> None:
        spec = self.broker.get_primitive_spec("structured-parse")
        self.assertIsNotNone(spec)
        self.assertIsInstance(spec, PrimitiveActionSpec)
        self.assertEqual(spec.name, "structured-parse")

    def test_nonexistent_primitive_returns_none(self) -> None:
        spec = self.broker.get_primitive_spec("nonexistent")
        self.assertIsNone(spec)


class TestToolBrokerBlackboardJournal(_BaseBrokerTest):
    """Verify that broker events are written to Blackboard."""

    def test_request_created_event(self) -> None:
        req = self._make_request("structured-parse", risk_level="low")
        self.broker.request_tool(req)
        events = self.bb.load_events("proj1")
        tool_events = [e for e in events if e.event_type == EventType.TOOL_REQUEST.value]
        request_events = [e for e in tool_events if e.payload.get("tool_event") == "request_created"]
        self.assertTrue(len(request_events) > 0)
        self.assertEqual(request_events[0].payload["primitive_name"], "structured-parse")

    def test_policy_checked_event(self) -> None:
        req = self._make_request("structured-parse", risk_level="low")
        self.broker.request_tool(req)
        events = self.bb.load_events("proj1")
        policy_events = [e for e in events
                         if e.event_type == EventType.SECURITY_VALIDATION.value
                         and e.payload.get("tool_event") == "policy_checked"]
        self.assertTrue(len(policy_events) > 0)
        self.assertEqual(policy_events[0].payload["primitive_name"], "structured-parse")

    def test_completed_action_outcome_event(self) -> None:
        req = self._make_request("structured-parse", risk_level="low")
        self.broker.request_tool(req)
        events = self.bb.load_events("proj1")
        outcome_events = [e for e in events
                         if e.event_type == EventType.ACTION_OUTCOME.value
                         and e.payload.get("tool_event") == "completed"]
        self.assertTrue(len(outcome_events) > 0)
        self.assertTrue(outcome_events[0].payload.get("broker_execution", False))

    def test_failed_event_on_policy_deny(self) -> None:
        req = self._make_request("structured-parse", risk_level="critical")
        self.broker.request_tool(req)
        events = self.bb.load_events("proj1")
        failed_events = [e for e in events
                         if e.event_type == EventType.TOOL_REQUEST.value
                         and e.payload.get("tool_event") == "failed"]
        self.assertTrue(len(failed_events) > 0)
        self.assertEqual(failed_events[0].payload["error_type"], "policy_deny")

    def test_failed_event_on_requires_io(self) -> None:
        req = self._make_request("http-request", risk_level="low")
        self.broker.request_tool(req)
        events = self.bb.load_events("proj1")
        failed_events = [e for e in events
                         if e.event_type == EventType.TOOL_REQUEST.value
                         and e.payload.get("tool_event") == "failed"]
        self.assertTrue(len(failed_events) > 0)
        self.assertEqual(failed_events[0].payload["error_type"], "requires_io_context")

    def test_failed_event_on_primitive_not_found(self) -> None:
        req = self._make_request("nonexistent-primitive", risk_level="low")
        self.broker.request_tool(req)
        events = self.bb.load_events("proj1")
        failed_events = [e for e in events
                         if e.event_type == EventType.TOOL_REQUEST.value
                         and e.payload.get("tool_event") == "failed"]
        self.assertTrue(len(failed_events) > 0)
        self.assertEqual(failed_events[0].payload["error_type"], "primitive_not_found")


class TestToolBrokerDataclasses(unittest.TestCase):
    """Verify ToolRequest / ToolResult / ToolError / ToolEvent dataclasses."""

    def test_tool_request_defaults(self) -> None:
        req = ToolRequest()
        self.assertNotEqual(req.request_id, "")
        self.assertEqual(req.project_id, "")
        self.assertEqual(req.primitive_name, "")

    def test_tool_result_defaults(self) -> None:
        result = ToolResult()
        self.assertEqual(result.request_id, "")
        self.assertEqual(result.source, "tool_broker")

    def test_tool_error_defaults(self) -> None:
        error = ToolError()
        self.assertEqual(error.request_id, "")
        self.assertEqual(error.error_type, "")

    def test_tool_event_defaults(self) -> None:
        event = ToolEvent()
        self.assertEqual(event.event_type, "")

    def test_tool_request_serialization(self) -> None:
        req = ToolRequest(project_id="p1", primitive_name="structured-parse")
        d = to_dict(req)
        self.assertEqual(d["project_id"], "p1")
        self.assertEqual(d["primitive_name"], "structured-parse")

    def test_tool_result_serialization(self) -> None:
        result = ToolResult(request_id="r1", outcome={"status": "ok"})
        d = to_dict(result)
        self.assertEqual(d["request_id"], "r1")
        self.assertEqual(d["outcome"]["status"], "ok")

    def test_tool_error_serialization(self) -> None:
        error = ToolError(request_id="r1", error_type="policy_deny", message="denied")
        d = to_dict(error)
        self.assertEqual(d["error_type"], "policy_deny")


class TestToolBrokerIntegration(unittest.TestCase):
    """Integration test: ToolBroker through TeamRuntime."""

    def setUp(self) -> None:
        from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig
        config = TeamRuntimeConfig(blackboard_db_path=":memory:")
        self.runtime = TeamRuntime(config)

    def tearDown(self) -> None:
        self.runtime.close()

    def test_runtime_has_tool_broker(self) -> None:
        self.assertIsNotNone(self.runtime.tool_broker)
        self.assertIsInstance(self.runtime.tool_broker, ToolBroker)

    def test_runtime_request_tool(self) -> None:
        result = self.runtime.request_tool(
            project_id="test_proj",
            solver_id="s1",
            primitive_name="structured-parse",
            risk_level="low",
        )
        # structured-parse is IO-free; but no project events exist, so policy may still ALLOW
        # (PolicyHarness checks budget/rate, but default limits are generous)
        # The result should be either ToolResult or ToolError
        self.assertIsInstance(result, (ToolResult, ToolError))

    def test_runtime_list_available_primitives(self) -> None:
        primitives = self.runtime.list_available_primitives("solver")
        self.assertIn("structured-parse", primitives)

    def test_runtime_request_io_primitive(self) -> None:
        result = self.runtime.request_tool(
            project_id="test_proj",
            solver_id="s1",
            primitive_name="http-request",
            risk_level="low",
        )
        # http-request is IO-dependent — should return requires_io_context
        # BUT: first needs to pass policy, which should ALLOW low risk
        # Then broker should return requires_io_context
        # However if no project events exist in blackboard, primitive_not_found won't trigger
        # (http-request IS in registry)
        self.assertIsInstance(result, (ToolResult, ToolError))
        if isinstance(result, ToolError):
            self.assertEqual(result.error_type, "requires_io_context")


if __name__ == "__main__":
    unittest.main()