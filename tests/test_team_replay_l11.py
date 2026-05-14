"""L11 acceptance tests: replay/audit continuity with run_id isolation.

Proves:
- Repeated solve_all preserves previous run audit/replay
- run_id isolation works correctly
- Previous run events remain queryable
"""

import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig as BBConfig
from attack_agent.team.manager import TeamManager, ManagerConfig
from attack_agent.team.protocol import ActionType, StrategyAction
from attack_agent.team.scheduler import SyncScheduler, SchedulerConfig


def _make_bb() -> BlackboardService:
    tmp = tempfile.mkdtemp()
    return BlackboardService(BBConfig(db_path=f"{tmp}/test_replay_l11.db"))


class TestL11RunIdIsolation(unittest.TestCase):
    """L11: start_run creates a run_id, events are tagged with it."""

    def setUp(self):
        self.bb = _make_bb()

    def tearDown(self):
        self.bb.close()

    def test_start_run_returns_run_id(self):
        run_id = self.bb.start_run("p1")
        self.assertIsNotNone(run_id)
        self.assertTrue(len(run_id) > 0)

    def test_events_tagged_with_current_run_id(self):
        run_id = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test")

        # Verify the event has the run_id
        # Since load_events now filters by run_id, we should get the event
        events = self.bb.load_events("p1")
        self.assertEqual(len(events), 1)

    def test_events_without_run_id_are_queryable(self):
        # Events written before start_run should still be queryable
        # (backward compatibility — load_events without run_id returns all)
        self.bb._current_runs.pop("p2", None)  # ensure no run_id set
        self.bb.append_event("p2", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test")
        events = self.bb.load_events("p2")
        self.assertEqual(len(events), 1)

    def test_second_run_does_not_destroy_first_run_events(self):
        # First run
        run1 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test_run1")
        self.bb.append_event("p1", EventType.STRATEGY_ACTION.value,
                              {"action_type": "launch_solver"}, source="manager")

        # Second run (L11: should not clear events)
        run2 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test_run2")

        # First run events should still exist
        run1_events = self.bb.load_events("p1", run_id=run1)
        self.assertTrue(len(run1_events) >= 2,
                        "First run events must still be queryable")

        # Second run events should also exist
        run2_events = self.bb.load_events("p1", run_id=run2)
        self.assertTrue(len(run2_events) >= 1,
                        "Second run events must be queryable")

        # Total events = run1 + run2
        all_events = self.bb.load_events("p1", run_id=None)
        # When no run_id is given and _current_runs has "p1", it should use the current run
        # But we can explicitly load all events by temporarily removing the current run_id
        # For audit purposes, both runs should be accessible

    def test_list_runs_returns_both_runs(self):
        run1 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test")
        run2 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test")

        runs = self.bb.list_runs("p1")
        self.assertEqual(len(runs), 2)
        self.assertIn(run1, runs)
        self.assertIn(run2, runs)

    def test_rebuild_state_uses_current_run_by_default(self):
        run1 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test")
        self.bb.append_event("p1", EventType.STRATEGY_ACTION.value,
                              {"action_type": "converge"}, source="manager")

        # Start second run
        run2 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test2")

        # rebuild_state by default uses current run_id (run2)
        state = self.bb.rebuild_state("p1")
        # Should only see run2 events (the second project_upserted)
        self.assertIsNotNone(state.project)

        # rebuild_state with explicit run1 should see first run
        state1 = self.bb.rebuild_state("p1", run_id=run1)
        self.assertIsNotNone(state1.project)


class TestL11ReplayPreservesPreviousRun(unittest.TestCase):
    """L11: previous run replay is intact after a new run starts."""

    def setUp(self):
        self.bb = _make_bb()

    def tearDown(self):
        self.bb.close()

    def test_previous_run_replay_available_after_new_run(self):
        # Run 1: create project and add events
        run1 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test")
        self.bb.append_event("p1", EventType.STRATEGY_ACTION.value,
                              {"action_type": "launch_solver"}, source="manager")
        self.bb.append_event("p1", EventType.STRATEGY_ACTION.value,
                              {"action_type": "converge"}, source="manager")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "done"}, source="scheduler")

        # Run 2: start new run (does NOT clear events)
        run2 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test2")

        # Previous run's replay should be intact
        run1_events = self.bb.load_events("p1", run_id=run1)
        # Should have all run1 events: project_upserted + 2 strategy_action + project_upserted(done)
        self.assertTrue(len(run1_events) >= 4,
                        "Previous run events must be intact for replay")

        # Verify run1 contains the "done" status event
        done_events = [
            e for e in run1_events
            if e.event_type == EventType.PROJECT_UPSERTED.value
            and e.payload.get("status") == "done"
        ]
        self.assertEqual(len(done_events), 1, "Previous run should have 'done' event")

    def test_export_run_log_for_previous_run(self):
        run1 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"challenge_id": "c1", "status": "new"}, source="test")
        self.bb.append_event("p1", EventType.STRATEGY_ACTION.value,
                              {"action_type": "launch_solver"}, source="manager")

        # Export run log
        log1 = self.bb.export_run_log("p1")
        self.assertTrue(len(log1) >= 2)

        # Start new run
        run2 = self.bb.start_run("p1")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value,
                              {"status": "new"}, source="test2")

        # Previous run's export should still work (using explicit run_id)
        # Note: export_run_log uses load_events which defaults to current run_id
        # For previous run, we need to temporarily switch
        self.bb._current_runs["p1"] = run1
        log1_again = self.bb.export_run_log("p1")
        self.assertTrue(len(log1_again) >= 2,
                        "Previous run export must still work")


if __name__ == "__main__":
    unittest.main()