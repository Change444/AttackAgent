"""Tests for BenchmarkRunner — Phase I."""

import os
import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.protocol import MemoryKind
from attack_agent.team.benchmark import BenchmarkRunner, RunMetrics, MetricsComparison, RegressionReport


class TestBenchmarkRunnerEvaluate(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "bb.db"))
        self.bb = BlackboardService(self.config)
        self.runner = BenchmarkRunner()

    def tearDown(self):
        self.bb.close()
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def _seed_solved_project(self, pid: str):
        """Seed a project that solves successfully."""
        self.bb.append_event(pid, "project_upserted",
                             {"challenge_id": "c1", "status": "new"}, "system")
        self.bb.append_event(pid, "observation",
                             {"kind": "fact", "summary": "found endpoint", "confidence": 0.8}, "s1")
        self.bb.append_event(pid, "worker_assigned",
                             {"solver_id": "s1", "status": "assigned", "profile": "network"}, "scheduler")
        self.bb.append_event(pid, "action_outcome",
                             {"solver_id": "s1", "status": "ok", "summary": "exploit ok", "budget_used": 2.0}, "s1")
        self.bb.append_event(pid, "action_outcome",
                             {"solver_id": "s1", "status": "ok", "summary": "verify ok", "budget_used": 1.0}, "s1")
        self.bb.append_event(pid, "candidate_flag",
                             {"flag": "flag{abc}", "idea_id": "i1", "status": "claimed", "solver_id": "s1"}, "s1")
        self.bb.append_event(pid, "submission",
                             {"flag": "flag{abc}", "result": "solved"}, "s1")

    def _seed_failed_project(self, pid: str):
        """Seed a project that fails."""
        self.bb.append_event(pid, "project_upserted",
                             {"challenge_id": "c2", "status": "new"}, "system")
        self.bb.append_event(pid, "observation",
                             {"kind": "fact", "summary": "found endpoint", "confidence": 0.5}, "s1")
        self.bb.append_event(pid, "worker_assigned",
                             {"solver_id": "s1", "status": "assigned", "profile": "network"}, "scheduler")
        self.bb.append_event(pid, "action_outcome",
                             {"solver_id": "s1", "status": "failed", "error": "timeout", "budget_used": 5.0}, "s1")
        self.bb.append_event(pid, "action_outcome",
                             {"solver_id": "s1", "status": "failed", "error": "timeout", "budget_used": 3.0}, "s1")
        self.bb.append_event(pid, "security_validation",
                             {"outcome": "deny", "reason": "critical risk"}, "policy")

    def test_evaluate_solved_project(self):
        self._seed_solved_project("p1")
        metrics = self.runner.evaluate_project("p1", self.bb)
        self.assertIsInstance(metrics, RunMetrics)
        self.assertTrue(metrics.solve_success)
        self.assertEqual(metrics.total_cycles, 2)  # 2 action_outcome events
        self.assertEqual(metrics.failed_attempts, 0)
        self.assertEqual(metrics.submission_attempts, 1)
        self.assertEqual(metrics.budget_consumed, 3.0)
        self.assertGreater(metrics.idea_claim_rate, 0.0)

    def test_evaluate_failed_project(self):
        self._seed_failed_project("p2")
        metrics = self.runner.evaluate_project("p2", self.bb)
        self.assertFalse(metrics.solve_success)
        self.assertEqual(metrics.failed_attempts, 2)
        self.assertEqual(metrics.policy_blocks, 1)
        self.assertEqual(metrics.budget_consumed, 8.0)
        self.assertEqual(metrics.submission_attempts, 0)

    def test_evaluate_stagnation(self):
        self.bb.append_event("p3", "project_upserted",
                             {"challenge_id": "c3", "status": "new"}, "system")
        self.bb.append_event("p3", "checkpoint",
                             {"severity": "warning",
                              "observations": [{"kind": "stagnation", "severity": "warning"}]}, "observer")
        metrics = self.runner.evaluate_project("p3", self.bb)
        self.assertEqual(metrics.stagnation_events, 1)
        self.assertIn("warning", metrics.observation_severity_counts)

    def test_evaluate_empty_project(self):
        metrics = self.runner.evaluate_project("nonexistent", self.bb)
        self.assertFalse(metrics.solve_success)
        self.assertEqual(metrics.total_cycles, 0)

    def test_evaluate_repeated_failure_rate(self):
        """Projects with repeated identical errors should have high repeated_failure rate."""
        self.bb.append_event("p4", "project_upserted",
                             {"challenge_id": "c4", "status": "new"}, "system")
        for _ in range(3):
            self.bb.append_event("p4", "action_outcome",
                                 {"solver_id": "s1", "status": "failed", "error": "timeout"}, "s1")
        metrics = self.runner.evaluate_project("p4", self.bb)
        self.assertEqual(metrics.failed_attempts, 3)
        # All failures are identical → repeated_failure_rate = 1 - 1/3 = 2/3
        self.assertAlmostEqual(metrics.repeated_failure_rate, 2/3, places=2)

    def test_evaluate_distinct_failures(self):
        """Projects with different errors should have low repeated_failure rate."""
        self.bb.append_event("p5", "project_upserted",
                             {"challenge_id": "c5", "status": "new"}, "system")
        self.bb.append_event("p5", "action_outcome",
                             {"solver_id": "s1", "status": "failed", "error": "timeout"}, "s1")
        self.bb.append_event("p5", "action_outcome",
                             {"solver_id": "s1", "status": "failed", "error": "auth fail"}, "s1")
        metrics = self.runner.evaluate_project("p5", self.bb)
        self.assertEqual(metrics.failed_attempts, 2)
        # 2 distinct failures → repeated_failure_rate = 1 - 2/2 = 0
        self.assertAlmostEqual(metrics.repeated_failure_rate, 0.0, places=2)


class TestMetricsComparison(unittest.TestCase):

    def setUp(self):
        self.runner = BenchmarkRunner()

    def test_compare_identical_metrics(self):
        m1 = RunMetrics(solve_success=True, total_cycles=5, failed_attempts=1)
        m2 = RunMetrics(solve_success=True, total_cycles=5, failed_attempts=1)
        comp = self.runner.compare_metrics(m1, m2)
        self.assertIsInstance(comp, MetricsComparison)
        self.assertEqual(comp.deltas["total_cycles"], 0)
        self.assertEqual(comp.deltas["solve_success"], False)
        self.assertAlmostEqual(comp.overall_score, 0.0, places=1)

    def test_compare_improved_metrics(self):
        m1 = RunMetrics(solve_success=False, total_cycles=10, failed_attempts=5)
        m2 = RunMetrics(solve_success=True, total_cycles=3, failed_attempts=1)
        comp = self.runner.compare_metrics(m1, m2)
        # solve_success: False→True = True
        self.assertEqual(comp.deltas["solve_success"], True)
        # total_cycles decreased by 7 (improvement)
        self.assertEqual(comp.deltas["total_cycles"], -7)
        # overall_score should be positive (improvement)
        self.assertGreater(comp.overall_score, 0.0)

    def test_compare_regressed_metrics(self):
        m1 = RunMetrics(solve_success=True, total_cycles=3, failed_attempts=1)
        m2 = RunMetrics(solve_success=False, total_cycles=10, failed_attempts=5)
        comp = self.runner.compare_metrics(m1, m2)
        self.assertEqual(comp.deltas["solve_success"], False)
        self.assertEqual(comp.deltas["total_cycles"], 7)
        # overall_score should be negative (regression)
        self.assertLess(comp.overall_score, 0.0)


class TestRegression(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # baseline DB: solved project
        self.baseline_config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "baseline.db"))
        self.baseline_bb = BlackboardService(self.baseline_config)
        self.baseline_bb.append_event("c1", "project_upserted",
                                      {"challenge_id": "c1", "status": "new"}, "system")
        self.baseline_bb.append_event("c1", "action_outcome",
                                      {"solver_id": "s1", "status": "ok", "summary": "done", "budget_used": 2.0}, "s1")
        self.baseline_bb.append_event("c1", "submission",
                                      {"flag": "flag{abc}", "result": "solved"}, "s1")

        # current DB: same project, worse performance
        self.current_config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "current.db"))
        self.current_bb = BlackboardService(self.current_config)
        self.current_bb.append_event("c1", "project_upserted",
                                     {"challenge_id": "c1", "status": "new"}, "system")
        self.current_bb.append_event("c1", "action_outcome",
                                     {"solver_id": "s1", "status": "failed", "error": "timeout", "budget_used": 5.0}, "s1")
        self.current_bb.append_event("c1", "action_outcome",
                                     {"solver_id": "s1", "status": "failed", "error": "timeout", "budget_used": 4.0}, "s1")
        self.current_bb.append_event("c1", "action_outcome",
                                     {"solver_id": "s1", "status": "ok", "summary": "retry ok", "budget_used": 3.0}, "s1")

        self.runner = BenchmarkRunner()

    def tearDown(self):
        self.baseline_bb.close()
        self.current_bb.close()
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_regression_detects_regression(self):
        report = self.runner.run_regression(["c1"], self.current_bb, self.baseline_bb)
        self.assertIsInstance(report, RegressionReport)
        # The current run is worse — has regressions
        self.assertGreater(len(report.regressions), 0)
        # Status is fail or mixed (there may be some improvements alongside regressions)
        self.assertIn(report.overall_status, ("fail", "mixed"))

    def test_regression_detects_improvement(self):
        # Create improved current run
        self.current_bb.close()
        # remove current db and recreate
        os.remove(os.path.join(self.tmpdir, "current.db"))
        improved_config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "current.db"))
        improved_bb = BlackboardService(improved_config)
        improved_bb.append_event("c1", "project_upserted",
                                 {"challenge_id": "c1", "status": "new"}, "system")
        improved_bb.append_event("c1", "action_outcome",
                                 {"solver_id": "s1", "status": "ok", "summary": "done fast", "budget_used": 1.0}, "s1")
        improved_bb.append_event("c1", "submission",
                                 {"flag": "flag{abc}", "result": "solved"}, "s1")

        report = self.runner.run_regression(["c1"], improved_bb, self.baseline_bb)
        self.assertEqual(report.overall_status, "pass")
        self.assertGreater(len(report.improvements), 0)
        improved_bb.close()

    def test_regression_mixed(self):
        # Add another challenge where current is worse
        self.baseline_bb.append_event("c2", "project_upserted",
                                      {"challenge_id": "c2", "status": "new"}, "system")
        self.baseline_bb.append_event("c2", "submission",
                                      {"flag": "flag{def}", "result": "solved"}, "s1")

        self.current_bb.append_event("c2", "project_upserted",
                                     {"challenge_id": "c2", "status": "new"}, "system")

        # c1 is regressed, c2 is lost solve — overall fail
        report = self.runner.run_regression(["c1", "c2"], self.current_bb, self.baseline_bb)
        # depends on specific metrics, but at least has regressions
        self.assertIn(report.overall_status, ("fail", "mixed"))
        self.assertGreater(len(report.regressions), 0)


if __name__ == "__main__":
    unittest.main()