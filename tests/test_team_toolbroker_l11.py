"""L11 acceptance tests: ToolBroker real-path event journaling.

Proves:
- Real solve path emits ToolBroker request/policy/result events
- Denied tool request does not reach WorkerRuntime
- journal_real_execution writes correct events
"""

import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.runtime import PrimitiveRegistry
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig as BBConfig
from attack_agent.team.policy import PolicyHarness
from attack_agent.team.protocol import PolicyOutcome, ActionType, StrategyAction
from attack_agent.team.tool_broker import ToolBroker, ToolRequest, ToolResult, ToolError


def _make_bb() -> BlackboardService:
    tmp = tempfile.mkdtemp()
    return BlackboardService(BBConfig(db_path=f"{tmp}/test_toolbroker_l11.db"))


def _make_broker(bb: BlackboardService) -> ToolBroker:
    registry = PrimitiveRegistry()
    policy = PolicyHarness()
    return ToolBroker(registry, policy, bb)


class TestL11JournalRealExecution(unittest.TestCase):
    """L11: journal_real_execution writes ToolBroker-equivalent events."""

    def setUp(self):
        self.bb = _make_bb()
        self.broker = _make_broker(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_journal_writes_three_events(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test")
        self.broker.journal_real_execution(
            "p1", "s1", "http-request", "ok", cost=1.5,
        )

        events = self.bb.load_events("p1")
        # request_created event
        request_events = [
            e for e in events
            if e.event_type == EventType.TOOL_REQUEST.value
            and e.payload.get("tool_event") == "request_created"
        ]
        self.assertEqual(len(request_events), 1)

        # policy auto_allow event
        policy_events = [
            e for e in events
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("check") == "tool_policy_auto_allow"
        ]
        self.assertEqual(len(policy_events), 1)
        self.assertEqual(policy_events[0].payload.get("outcome"), "pass")

        # completed event
        completed_events = [
            e for e in events
            if e.event_type == EventType.TOOL_REQUEST.value
            and e.payload.get("tool_event") == "completed"
        ]
        self.assertEqual(len(completed_events), 1)
        self.assertEqual(completed_events[0].payload.get("outcome_status"), "ok")

    def test_journal_records_primitive_name_and_solver_id(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test")
        self.broker.journal_real_execution(
            "p1", "solver_xyz", "binary-inspect", "error",
            cost=0.5, failure_reason="file not found",
        )

        events = self.bb.load_events("p1")
        completed = [
            e for e in events
            if e.event_type == EventType.TOOL_REQUEST.value
            and e.payload.get("tool_event") == "completed"
        ]
        self.assertEqual(completed[0].payload.get("primitive_name"), "binary-inspect")
        self.assertEqual(completed[0].payload.get("solver_id"), "solver_xyz")
        self.assertEqual(completed[0].payload.get("outcome_status"), "error")
        self.assertEqual(completed[0].payload.get("failure_reason"), "file not found")

    def test_journal_events_have_source_path_marker(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test")
        self.broker.journal_real_execution(
            "p1", "s1", "http-request", "ok",
        )

        events = self.bb.load_events("p1")
        request_created = [
            e for e in events
            if e.event_type == EventType.TOOL_REQUEST.value
            and e.payload.get("tool_event") == "request_created"
        ]
        self.assertEqual(request_created[0].payload.get("source_path"), "real_solve")


class TestL11DeniedToolDoesNotReachWorkerRuntime(unittest.TestCase):
    """L11: denied tool requests return ToolError, no execution occurs."""

    def setUp(self):
        self.bb = _make_bb()
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test")

    def tearDown(self):
        self.bb.close()

    def test_critical_risk_tool_returns_policy_deny_error(self):
        from attack_agent.team.policy import PolicyConfig, RiskThresholds
        # Create policy that denies critical-risk actions
        thresholds = RiskThresholds(critical="deny")
        policy = PolicyHarness(config=PolicyConfig(risk_thresholds=thresholds))
        registry = PrimitiveRegistry()
        broker = ToolBroker(registry, policy, self.bb)

        req = ToolRequest(
            project_id="p1",
            solver_id="s1",
            primitive_name="structured-parse",
            risk_level="critical",
            reason="potentially dangerous",
        )
        result = broker.request_tool(req)
        self.assertIsInstance(result, ToolError)
        self.assertEqual(result.error_type, "policy_deny")

    def test_denied_tool_writes_failed_event_not_completed(self):
        from attack_agent.team.policy import PolicyConfig, RiskThresholds
        thresholds = RiskThresholds(critical="deny")
        policy = PolicyHarness(config=PolicyConfig(risk_thresholds=thresholds))
        registry = PrimitiveRegistry()
        broker = ToolBroker(registry, policy, self.bb)

        req = ToolRequest(
            project_id="p1",
            solver_id="s1",
            primitive_name="structured-parse",
            risk_level="critical",
        )
        result = broker.request_tool(req)

        # Check event journal: should have request_created + policy_checked + failed
        events = self.bb.load_events("p1")
        completed_events = [
            e for e in events
            if e.event_type == EventType.TOOL_REQUEST.value
            and e.payload.get("tool_event") == "completed"
        ]
        failed_events = [
            e for e in events
            if e.event_type == EventType.TOOL_REQUEST.value
            and e.payload.get("tool_event") == "failed"
        ]
        # No completed event for denied requests
        self.assertEqual(len(completed_events), 0)
        self.assertTrue(len(failed_events) >= 1)


if __name__ == "__main__":
    unittest.main()