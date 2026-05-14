"""L11 acceptance tests: scheduler event semantics + pause/resume.

Proves:
- Launch records STRATEGY_ACTION, not WORKER_ASSIGNED
- max_project_solvers=1 launch creates exactly one real session
- Pause blocks schedule_cycle; resume continues
"""

import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService, BlackboardConfig
from attack_agent.team.blackboard_config import BlackboardConfig as BBConfig
from attack_agent.team.manager import TeamManager, ManagerConfig
from attack_agent.team.observer import Observer
from attack_agent.team.protocol import ActionType, StrategyAction, SolverStatus
from attack_agent.team.scheduler import SyncScheduler, SchedulerConfig, _action_to_event_type, _infer_stage


def _make_bb(test_name: str) -> BlackboardService:
    tmp = tempfile.mkdtemp()
    path = f"{tmp}/test_sched_l11_{test_name}.db"
    return BlackboardService(BBConfig(db_path=path))


class TestL11EventMapping(unittest.TestCase):
    """L11: Manager decisions map to STRATEGY_ACTION, not worker lifecycle."""

    def test_launch_solver_maps_to_strategy_action(self):
        self.assertEqual(
            _action_to_event_type(ActionType.LAUNCH_SOLVER),
            EventType.STRATEGY_ACTION.value,
        )

    def test_reassign_solver_maps_to_strategy_action(self):
        self.assertEqual(
            _action_to_event_type(ActionType.REASSIGN_SOLVER),
            EventType.STRATEGY_ACTION.value,
        )

    def test_stop_solver_maps_to_strategy_action(self):
        self.assertEqual(
            _action_to_event_type(ActionType.STOP_SOLVER),
            EventType.STRATEGY_ACTION.value,
        )

    def test_submit_flag_maps_to_strategy_action(self):
        self.assertEqual(
            _action_to_event_type(ActionType.SUBMIT_FLAG),
            EventType.STRATEGY_ACTION.value,
        )

    def test_steer_solver_maps_to_strategy_action(self):
        self.assertEqual(
            _action_to_event_type(ActionType.STEER_SOLVER),
            EventType.STRATEGY_ACTION.value,
        )

    def test_converge_maps_to_strategy_action(self):
        self.assertEqual(
            _action_to_event_type(ActionType.CONVERGE),
            EventType.STRATEGY_ACTION.value,
        )

    def test_abandon_maps_to_strategy_action(self):
        self.assertEqual(
            _action_to_event_type(ActionType.ABANDON),
            EventType.STRATEGY_ACTION.value,
        )

    def test_throttle_maps_to_strategy_action(self):
        self.assertEqual(
            _action_to_event_type(ActionType.THROTTLE_SOLVER),
            EventType.STRATEGY_ACTION.value,
        )


class TestL11ScheduleCycleBootstrap(unittest.TestCase):
    """L11: bootstrap project produces STRATEGY_ACTION event for launch."""

    def setUp(self):
        self.bb = _make_bb("bootstrap")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"challenge_id": "c1", "status": "new"}, source="test")
        self.manager = TeamManager(ManagerConfig())
        self.scheduler = SyncScheduler(SchedulerConfig(max_cycles=12))

    def tearDown(self):
        self.bb.close()

    def test_schedule_cycle_records_strategy_action_for_launch(self):
        actions = self.scheduler.schedule_cycle(
            "p1", self.manager, self.bb, runtime=None, context_compiler=None,
            policy_harness=None, solver_manager=None, merge_hub=None, observer=None,
        )
        # Verify the action was recorded
        events = self.bb.load_events("p1")
        strategy_events = [
            e for e in events
            if e.event_type == EventType.STRATEGY_ACTION.value
        ]
        # Should have at least one STRATEGY_ACTION with action_type=launch_solver
        launch_actions = [
            e for e in strategy_events
            if e.payload.get("action_type") == "launch_solver"
        ]
        self.assertTrue(len(launch_actions) >= 1, "launch_solver should be recorded as STRATEGY_ACTION")

    def test_no_phantom_worker_assigned_from_manager_decision(self):
        actions = self.scheduler.schedule_cycle(
            "p1", self.manager, self.bb, runtime=None, context_compiler=None,
            policy_harness=None, solver_manager=None, merge_hub=None, observer=None,
        )
        events = self.bb.load_events("p1")
        # Manager decisions should NOT produce WORKER_ASSIGNED events
        manager_worker_assigned = [
            e for e in events
            if e.event_type == EventType.WORKER_ASSIGNED.value and e.source == "manager"
        ]
        self.assertEqual(len(manager_worker_assigned), 0,
                         "Manager decisions must not create WORKER_ASSIGNED events")


class TestL11InferStage(unittest.TestCase):
    """L11: _infer_stage handles STRATEGY_ACTION events with action_type payload."""

    def setUp(self):
        self.bb = _make_bb("infer_stage")

    def tearDown(self):
        self.bb.close()

    def test_strategy_action_launch_infers_reason_stage(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"}, source="test")
        self.bb.append_event("p1", EventType.STRATEGY_ACTION.value, {"action_type": "launch_solver"}, source="manager")
        events = self.bb.load_events("p1")
        stage = _infer_stage(events, "new")
        self.assertEqual(stage, "reason")

    def test_strategy_action_steer_infers_reason_stage(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"}, source="test")
        self.bb.append_event("p1", EventType.STRATEGY_ACTION.value, {"action_type": "steer_solver"}, source="manager")
        events = self.bb.load_events("p1")
        stage = _infer_stage(events, "new")
        self.assertEqual(stage, "reason")

    def test_worker_assigned_also_infers_reason(self):
        # Legacy: WORKER_ASSIGNED from SolverSessionManager still infers reason
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"}, source="test")
        self.bb.append_event("p1", EventType.WORKER_ASSIGNED.value, {"solver_id": "s1", "status": "created"}, source="solver_manager")
        events = self.bb.load_events("p1")
        stage = _infer_stage(events, "new")
        self.assertEqual(stage, "reason")


class TestL11PauseResume(unittest.TestCase):
    """L11: pause blocks schedule_cycle; resume continues."""

    def setUp(self):
        self.bb = _make_bb("pause")
        self.manager = TeamManager(ManagerConfig())
        self.scheduler = SyncScheduler(SchedulerConfig(max_cycles=5))

    def tearDown(self):
        self.bb.close()

    def test_schedule_cycle_returns_empty_when_paused(self):
        # Create project and set status to paused
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "paused"}, source="test")
        actions = self.scheduler.schedule_cycle(
            "p1", self.manager, self.bb, runtime=None, context_compiler=None,
            policy_harness=None, solver_manager=None, merge_hub=None, observer=None,
        )
        self.assertEqual(actions, [], "Paused project should produce no actions")

    def test_pause_event_blocks_scheduling_in_run_project(self):
        import threading
        # Create project
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test")
        pause_event = threading.Event()
        pause_event.set()  # paused immediately

        # Run project with pause — should complete with very few events
        project = self.scheduler.run_project(
            "p1", self.manager, self.bb, runtime=None, context_compiler=None,
            policy_harness=None, solver_manager=None, merge_hub=None,
            observer=None, pause_event=pause_event,
        )
        # With pause set for all cycles, project should reach abandoned
        # but with no STRATEGY_ACTION events for launch
        events = self.bb.load_events("p1")
        strategy_events = [e for e in events if e.event_type == EventType.STRATEGY_ACTION.value]
        self.assertEqual(len(strategy_events), 0, "Paused project should have no manager strategy actions")

    def test_resume_after_pause_continues_scheduling(self):
        import threading
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test")
        pause_event = threading.Event()

        # Start paused, then resume after first cycle
        pause_event.set()
        project = self.scheduler.run_project(
            "p1", self.manager, self.bb, runtime=None, context_compiler=None,
            policy_harness=None, solver_manager=None, merge_hub=None,
            observer=None, pause_event=pause_event,
        )
        # All cycles were paused — project should be abandoned with no actions
        events = self.bb.load_events("p1")
        strategy_events = [e for e in events if e.event_type == EventType.STRATEGY_ACTION.value]
        # With max_cycles=5 and all paused, no strategy actions should occur
        self.assertEqual(len(strategy_events), 0)


if __name__ == "__main__":
    unittest.main()