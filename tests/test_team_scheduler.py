"""Tests for SyncScheduler — Phase C."""

import os
import unittest
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.protocol import ActionType, StrategyAction, TeamProject
from attack_agent.team.scheduler import SchedulerConfig, SyncScheduler


def _make_bb(test_name: str) -> BlackboardService:
    path = f"data/test_sched_{test_name}.db"
    if os.path.exists(path):
        os.remove(path)
    return BlackboardService(BlackboardConfig(db_path=path))


class TestSyncSchedulerScheduleCycle(unittest.TestCase):
    """schedule_cycle produces StrategyAction list and writes to Blackboard."""

    def setUp(self):
        self.mgr = TeamManager()
        self.sched = SyncScheduler()
        self.bb = _make_bb("cycle")

    def tearDown(self):
        self.bb.close()

    def test_schedule_cycle_empty_project(self):
        # project not yet admitted
        actions = self.sched.schedule_cycle("p_missing", self.mgr, self.bb)
        self.assertEqual(actions, [])

    def test_schedule_cycle_bootstrap_project(self):
        # admit project first
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "new"})
        actions = self.sched.schedule_cycle("p1", self.mgr, self.bb)
        # bootstrap → launch solver
        self.assertTrue(len(actions) > 0)
        self.assertEqual(actions[0].action_type, ActionType.LAUNCH_SOLVER)

    def test_schedule_cycle_writes_events_to_blackboard(self):
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "new"})
        self.sched.schedule_cycle("p1", self.mgr, self.bb)
        # manager decision should be recorded as an event
        events = self.bb.load_events("p1")
        # project_upserted + manager action
        self.assertTrue(len(events) >= 2)
        # at least one event from manager
        manager_events = [e for e in events if e.source == "manager"]
        self.assertTrue(len(manager_events) >= 1)

    def test_schedule_cycle_terminal_project(self):
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "done"})
        actions = self.sched.schedule_cycle("p1", self.mgr, self.bb)
        self.assertEqual(actions, [])


class TestSyncSchedulerRunProject(unittest.TestCase):
    """run_project loops until done / abandoned."""

    def setUp(self):
        self.mgr = TeamManager(ManagerConfig(stagnation_threshold=2))
        self.sched = SyncScheduler(SchedulerConfig(max_cycles=10))
        self.bb = _make_bb("run")

    def tearDown(self):
        self.bb.close()

    def test_run_project_admits_and_runs(self):
        result = self.sched.run_project("p1", self.mgr, self.bb)
        self.assertIsNotNone(result)
        self.assertEqual(result.project_id, "p1")
        # project should have been admitted (has at least project_upserted event)
        events = self.bb.load_events("p1")
        upserted = [e for e in events if e.event_type == "project_upserted"]
        self.assertTrue(len(upserted) >= 1)

    def test_run_project_abandoned_after_max_cycles(self):
        bb = _make_bb("run_abandon")
        mgr = TeamManager(ManagerConfig(stagnation_threshold=8))
        sched = SyncScheduler(SchedulerConfig(max_cycles=3))
        # With high stagnation_threshold and no candidates,
        # project won't converge in 3 cycles → max_cycles exceeded → scheduler marks abandoned
        result = sched.run_project("p1", mgr, bb)
        self.assertEqual(result.status, "abandoned")
        bb.close()

    def test_run_project_with_candidate_converges(self):
        bb = _make_bb("run_candidate")
        mgr = TeamManager(ManagerConfig(stagnation_threshold=2))
        sched = SyncScheduler(SchedulerConfig(max_cycles=10))
        # seed a genuine candidate flag so it converges quickly
        bb.append_event("p1", "project_upserted",
                        {"challenge_id": "c1", "status": "new"})
        bb.append_event("p1", "candidate_flag",
                        {"flag": "flag{test}", "confidence": 0.9},
                        source="state_sync")
        bb.append_event("p1", "worker_assigned",
                        {"solver_id": "s1", "profile": "network"})
        result = sched.run_project("p1", mgr, bb)
        # project should reach some terminal state
        self.assertIn(result.status, ("done", "abandoned", "new", "submitted"))
        bb.close()


class TestSyncSchedulerRunAll(unittest.TestCase):
    """run_all processes multiple projects."""

    def setUp(self):
        self.mgr = TeamManager()
        self.sched = SyncScheduler(SchedulerConfig(max_cycles=5))
        self.bb = _make_bb("all")

    def tearDown(self):
        self.bb.close()

    def test_run_all_multiple_projects(self):
        results = self.sched.run_all(self.mgr, self.bb, ["p1", "p2"])
        self.assertEqual(len(results), 2)
        self.assertIn("p1", results)
        self.assertIn("p2", results)

    def test_run_all_sequential_processing(self):
        results = self.sched.run_all(self.mgr, self.bb, ["p1", "p2", "p3"])
        # all projects processed
        self.assertEqual(len(results), 3)
        for pid in ["p1", "p2", "p3"]:
            self.assertEqual(results[pid].project_id, pid)


class TestSyncSchedulerActionsQueryable(unittest.TestCase):
    """All StrategyAction events queryable from Blackboard."""

    def setUp(self):
        self.mgr = TeamManager()
        self.sched = SyncScheduler()
        self.bb = _make_bb("query")

    def tearDown(self):
        self.bb.close()

    def test_manager_actions_written_and_readable(self):
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "new"})
        actions = self.sched.schedule_cycle("p1", self.mgr, self.bb)
        # check all actions are in blackboard events
        events = self.bb.load_events("p1")
        manager_events = [e for e in events if e.source == "manager"]
        self.assertEqual(len(manager_events), len(actions))
        # each manager event payload contains the action
        for me in manager_events:
            payload = me.payload
            self.assertIn("action_type", payload)

    def test_strategy_action_types_in_journal(self):
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "new"})
        self.sched.schedule_cycle("p1", self.mgr, self.bb)
        events = self.bb.load_events("p1")
        manager_events = [e for e in events if e.source == "manager"]
        # bootstrap project → launch_solver
        self.assertTrue(any(
            e.payload.get("action_type") == "launch_solver"
            for e in manager_events
        ))


if __name__ == "__main__":
    unittest.main()