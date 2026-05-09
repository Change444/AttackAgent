"""Tests for TeamManager — Phase C."""

import os
import unittest
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.protocol import (
    ActionType,
    StrategyAction,
    TeamProject,
)


def _make_bb(test_name: str) -> BlackboardService:
    path = f"data/test_mgr_{test_name}.db"
    if os.path.exists(path):
        os.remove(path)
    return BlackboardService(BlackboardConfig(db_path=path))


class TestTeamManagerAdmitProject(unittest.TestCase):
    """TeamManager.admit_project returns launch_solver StrategyAction."""

    def test_admit_returns_launch_solver(self):
        mgr = TeamManager()
        proj = TeamProject(project_id="p1", challenge_id="c1", status="new")
        action = mgr.admit_project(proj)
        self.assertEqual(action.action_type, ActionType.LAUNCH_SOLVER)
        self.assertEqual(action.project_id, "p1")
        self.assertIn("admitted", action.reason)


class TestTeamManagerStageTransition(unittest.TestCase):
    """TeamManager.decide_stage_transition for all stage transitions."""

    def setUp(self):
        self.mgr = TeamManager()
        self.bb = _make_bb("stage")

    def tearDown(self):
        self.bb.close()

    def test_bootstrap_to_reason(self):
        action = self.mgr.decide_stage_transition("p1", "bootstrap", [])
        self.assertIsNotNone(action)
        self.assertEqual(action.action_type, ActionType.LAUNCH_SOLVER)

    def test_reason_to_explore(self):
        action = self.mgr.decide_stage_transition("p1", "reason", [])
        self.assertIsNotNone(action)
        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)

    def test_explore_to_converge_with_candidates(self):
        self.bb.append_event("p1", "candidate_flag",
                             {"flag": "flag{test}", "confidence": 0.8})
        events = self.bb.load_events("p1")
        action = self.mgr.decide_stage_transition("p1", "explore", events)
        self.assertEqual(action.action_type, ActionType.CONVERGE)

    def test_explore_continue_without_candidates(self):
        action = self.mgr.decide_stage_transition("p1", "explore", [])
        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)

    def test_explore_to_abandon_on_stagnation(self):
        # create enough failed outcomes to trigger stagnation
        for i in range(8):
            self.bb.append_event("p1", "action_outcome",
                                 {"status": "failed", "novelty": 0.0})
        events = self.bb.load_events("p1")
        action = self.mgr.decide_stage_transition("p1", "explore", events)
        self.assertEqual(action.action_type, ActionType.ABANDON)


class TestTeamManagerSolverTimeout(unittest.TestCase):
    """TeamManager.handle_solver_timeout returns requeue / abandon."""

    def setUp(self):
        self.mgr = TeamManager(ManagerConfig(stagnation_threshold=3))
        self.bb = _make_bb("timeout")

    def tearDown(self):
        self.bb.close()

    def test_timeout_requeue_when_not_stagnant(self):
        action = self.mgr.handle_solver_timeout("p1", "s1", [])
        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)
        self.assertIn("requeue", action.reason)

    def test_timeout_abandon_when_stagnant(self):
        for i in range(4):
            self.bb.append_event("p1", "action_outcome",
                                 {"status": "failed", "novelty": 0.0})
        events = self.bb.load_events("p1")
        action = self.mgr.handle_solver_timeout("p1", "s1", events)
        self.assertEqual(action.action_type, ActionType.ABANDON)


class TestTeamManagerDecideSubmit(unittest.TestCase):
    """TeamManager.decide_submit returns submit_flag / converge."""

    def setUp(self):
        self.mgr = TeamManager(ManagerConfig(confidence_threshold=0.6))
        self.bb = _make_bb("submit")

    def tearDown(self):
        self.bb.close()

    def test_submit_flag_when_confidence_high(self):
        self.bb.append_event("p1", "candidate_flag",
                             {"flag": "flag{high}", "confidence": 0.9})
        events = self.bb.load_events("p1")
        action = self.mgr.decide_submit("p1", events)
        self.assertEqual(action.action_type, ActionType.SUBMIT_FLAG)
        self.assertTrue(action.requires_review)

    def test_converge_when_confidence_low(self):
        self.bb.append_event("p1", "candidate_flag",
                             {"flag": "flag{low}", "confidence": 0.3})
        events = self.bb.load_events("p1")
        action = self.mgr.decide_submit("p1", events)
        self.assertEqual(action.action_type, ActionType.CONVERGE)

    def test_abandon_when_no_candidates(self):
        action = self.mgr.decide_submit("p1", [])
        self.assertEqual(action.action_type, ActionType.ABANDON)

    def test_submit_best_candidate(self):
        self.bb.append_event("p1", "candidate_flag",
                             {"flag": "flag{low}", "confidence": 0.2})
        self.bb.append_event("p1", "candidate_flag",
                             {"flag": "flag{best}", "confidence": 0.95})
        events = self.bb.load_events("p1")
        action = self.mgr.decide_submit("p1", events)
        self.assertEqual(action.action_type, ActionType.SUBMIT_FLAG)


class TestTeamManagerDecisionsWrittenToBlackboard(unittest.TestCase):
    """Verify that Manager decisions can be recorded in Blackboard."""

    def setUp(self):
        self.mgr = TeamManager()
        self.bb = _make_bb("bb_write")

    def tearDown(self):
        self.bb.close()

    def test_action_written_and_queryable(self):
        from attack_agent.team.protocol import to_dict
        proj = TeamProject(project_id="p1")
        action = self.mgr.admit_project(proj)
        self.bb.append_event("p1", "worker_assigned",
                             to_dict(action), source="manager")
        events = self.bb.load_events("p1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "worker_assigned")
        self.assertEqual(events[0].source, "manager")


class TestTeamManagerAssignSolver(unittest.TestCase):
    """TeamManager.assign_solver returns launch_solver action."""

    def test_assign_solver(self):
        mgr = TeamManager()
        action = mgr.assign_solver("p1", "network")
        self.assertEqual(action.action_type, ActionType.LAUNCH_SOLVER)
        self.assertIn("network", action.reason)

    def test_assign_solver_browser_profile(self):
        mgr = TeamManager()
        action = mgr.assign_solver("p1", "browser")
        self.assertIn("browser", action.reason)


class TestTeamManagerHeartbeat(unittest.TestCase):
    """TeamManager.handle_solver_heartbeat returns steer action."""

    def test_heartbeat_acknowledged(self):
        mgr = TeamManager()
        action = mgr.handle_solver_heartbeat("p1", "s1")
        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)
        self.assertEqual(action.target_solver_id, "s1")
        self.assertIn("heartbeat", action.reason)


class TestTeamManagerDecideConvergence(unittest.TestCase):
    """TeamManager.decide_convergence for converge / abandon / keep exploring."""

    def setUp(self):
        self.mgr = TeamManager()
        self.bb = _make_bb("convergence")

    def tearDown(self):
        self.bb.close()

    def test_converge_with_candidates(self):
        self.bb.append_event("p1", "candidate_flag",
                             {"flag": "flag{test}", "confidence": 0.8})
        events = self.bb.load_events("p1")
        action = self.mgr.decide_convergence("p1", events)
        self.assertEqual(action.action_type, ActionType.CONVERGE)

    def test_abandon_on_stagnation(self):
        mgr = TeamManager(ManagerConfig(stagnation_threshold=3))
        bb = _make_bb("convergence_abandon")
        for i in range(5):
            bb.append_event("p1", "action_outcome",
                             {"status": "failed", "novelty": 0.0})
        events = bb.load_events("p1")
        action = mgr.decide_convergence("p1", events)
        self.assertEqual(action.action_type, ActionType.ABANDON)
        bb.close()

    def test_keep_exploring_no_candidates_no_stagnation(self):
        action = self.mgr.decide_convergence("p1", [])
        self.assertEqual(action.action_type, ActionType.STEER_SOLVER)


if __name__ == "__main__":
    unittest.main()