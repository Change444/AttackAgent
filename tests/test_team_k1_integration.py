"""Phase K-1 integration tests.

TeamRuntime receives real WorkerRuntime + Dispatcher + StateGraphService,
execute_solver_cycle runs real Dispatcher.schedule(skip_stage_decisions=True),
and outcomes are written to Blackboard.
"""

import os
import tempfile
import unittest

from attack_agent.config import (
    AttackAgentConfig,
    BrowserConfig,
    HttpConfig,
    LoggingConfig,
    MemoryConfig,
    ModelConfig,
    PatternDiscoveryConfig,
    PlatformConfig,
    SecurityConfig,
    SemanticRetrievalConfig,
)
from attack_agent.factory import build_team_runtime
from attack_agent.platform_models import (
    ChallengeDefinition,
    DualPathConfig,
    ProjectStage,
    WorkerProfile,
)
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig


def fast_test_config() -> AttackAgentConfig:
    return AttackAgentConfig(
        platform=PlatformConfig(max_cycles=3, stagnation_threshold=3),
        dual_path=DualPathConfig(path_switch_stagnation_threshold=2),
        pattern_discovery=PatternDiscoveryConfig(),
        semantic_retrieval=SemanticRetrievalConfig(),
        security=SecurityConfig(),
        memory=MemoryConfig(),
        logging=LoggingConfig(),
        model=ModelConfig(),
        browser=BrowserConfig(engine="stdlib", timeout_seconds=0.2),
        http=HttpConfig(engine="stdlib", timeout_seconds=0.2),
    )


def _build_identity_provider() -> InMemoryCompetitionProvider:
    return InMemoryCompetitionProvider([
        ChallengeDefinition(
            id="web-auth",
            name="JWT Role Boundary",
            category="web",
            difficulty="medium",
            target="http://127.0.0.1:8080",
            description="A local challenge with login, cookie-based auth, role checks, and an admin page.",
            metadata={
                "hint_budget": 1,
                "hint": "Look at the session material.",
                "flag": "flag{integration}",
                "signals": ["login", "cookie", "token", "admin", "role"],
                "primitive_payloads": {
                    "http-request": [
                        {
                            "id": "obs-auth-surface",
                            "type": "observation",
                            "kind": "http-surface",
                            "tags": ["identity-boundary", "observation_gate"],
                            "payload": {
                                "services": [{"name": "http", "port": 8080}],
                                "endpoints": [
                                    {"path": "/"},
                                    {"path": "/login"},
                                    {"path": "/profile"},
                                    {"path": "/admin"},
                                ],
                            },
                        },
                    ],
                    "structured-parse": [
                        {
                            "id": "hyp-auth",
                            "type": "hypothesis",
                            "tags": ["identity-boundary", "observation_gate"],
                            "statement": "Authorization depends on reusable session material",
                            "confidence": 0.8,
                        },
                    ],
                    "session-materialize": [
                        {
                            "id": "obs-session-state",
                            "type": "observation",
                            "kind": "session-state",
                            "tags": ["identity-boundary", "action_template"],
                            "payload": {
                                "sessions": [
                                    {
                                        "username": "admin",
                                        "privilege": "admin",
                                        "secret_ref": "vault://admin",
                                    }
                                ],
                            },
                        },
                    ],
                    "extract-candidate": [
                        {
                            "type": "candidate_flag",
                            "tags": ["identity-boundary", "verification_gate"],
                            "value": "flag{integration}",
                            "confidence": 0.97,
                        },
                    ],
                },
            },
        ),
    ])


class TestDispatcherSkipStageDecisions(unittest.TestCase):
    """Dispatcher.schedule(skip_stage_decisions=True) behavior."""

    def setUp(self):
        self.provider = _build_identity_provider()
        self.runtime = build_team_runtime(self.provider, agent_config=fast_test_config())
        self.project_ids = self._bootstrap()

    def _bootstrap(self) -> list[str]:
        project_ids = self.runtime._controller.sync_challenges()
        for pid in project_ids:
            self.runtime._controller.ensure_instance(pid)
        return project_ids

    def test_skip_stage_decisions_returns_tuple(self):
        """When skip_stage_decisions=True, Dispatcher returns (outcome, events) tuple."""
        pid = self.project_ids[0]
        # Run bootstrap + reason manually first
        self.runtime._dispatcher.schedule(pid)  # bootstrap → reason
        self.runtime._dispatcher.schedule(pid)  # reason → explore

        # Now in EXPLORE — call with skip_stage_decisions=True
        result = self.runtime._dispatcher.schedule(pid, skip_stage_decisions=True)
        # Should return a tuple (outcome, events), not None
        self.assertIsNotNone(result)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        outcome, events = result
        self.assertIsNotNone(outcome)

    def test_skip_stage_decisions_skips_abandon(self):
        """skip_stage_decisions=True never sets project to ABANDONED."""
        pid = self.project_ids[0]
        self.runtime._dispatcher.schedule(pid)  # bootstrap
        self.runtime._dispatcher.schedule(pid)  # reason
        self.runtime._dispatcher.schedule(pid, skip_stage_decisions=True)  # explore cycle 1

        record = self.runtime._state_graph.projects[pid]
        # Stage should still be EXPLORE — not changed by Dispatcher
        self.assertEqual(record.snapshot.stage, ProjectStage.EXPLORE)

    def test_default_schedule_no_skip(self):
        """skip_stage_decisions=False (default): original behavior unchanged."""
        pid = self.project_ids[0]
        result = self.runtime._dispatcher.schedule(pid)  # bootstrap → reason
        # Default returns None
        self.assertIsNone(result)
        record = self.runtime._state_graph.projects[pid]
        # Stage transitioned to REASON (original behavior)
        self.assertEqual(record.snapshot.stage, ProjectStage.REASON)

    def test_skip_stage_bootstrap_returns_none(self):
        """skip_stage_decisions=True on BOOTSTRAP stage returns None (TeamManager handles)."""
        pid = self.project_ids[0]
        result = self.runtime._dispatcher.schedule(pid, skip_stage_decisions=True)
        self.assertIsNone(result)

    def test_skip_stage_reason_returns_none(self):
        """skip_stage_decisions=True on REASON stage returns None (TeamManager handles)."""
        pid = self.project_ids[0]
        self.runtime._dispatcher.schedule(pid)  # bootstrap → reason
        result = self.runtime._dispatcher.schedule(pid, skip_stage_decisions=True)
        self.assertIsNone(result)


class TestTeamRuntimeRealExecutor(unittest.TestCase):
    """TeamRuntime with real WorkerRuntime + Dispatcher + StateGraphService."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_bb_k1.db")
        self.provider = _build_identity_provider()
        self.runtime = build_team_runtime(self.provider, agent_config=fast_test_config())
        self.project_ids = self.runtime._controller.sync_challenges()
        for pid in self.project_ids:
            self.runtime._controller.ensure_instance(pid)

    def tearDown(self):
        try:
            self.runtime.close()
        except Exception:
            pass

    def test_use_real_executor_property(self):
        """use_real_executor returns True when all components are provided."""
        self.assertTrue(self.runtime.use_real_executor)

    def test_use_real_executor_false_by_default(self):
        """use_real_executor returns False when no executor components."""
        config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        rt = TeamRuntime(config)
        self.assertFalse(rt.use_real_executor)

    def test_use_real_executor_false_when_config_false(self):
        """use_real_executor returns False even with components if config says False."""
        rt = TeamRuntime(
            config=TeamRuntimeConfig(
                blackboard_db_path=self.db_path,
                use_real_executor=False,
            ),
            worker_runtime=self.runtime._worker_runtime,
            dispatcher=self.runtime._dispatcher,
            state_graph=self.runtime._state_graph,
            enhanced_planner=self.runtime._enhanced_planner,
        )
        self.assertFalse(rt.use_real_executor)

    def test_execute_solver_cycle_bootstrap(self):
        """_execute_solver_cycle handles BOOTSTRAP: advances through BOOTSTRAP→REASON→EXPLORE
        and executes first EXPLORE cycle, matching CompetitionPlatform.run_cycle behavior."""
        pid = self.project_ids[0]
        # Inject project into Blackboard first
        from attack_agent.team.protocol import to_dict, TeamProject

        project = TeamProject(challenge_id="web-auth", status="new")
        self.runtime.blackboard.append_event(
            project_id=project.project_id,
            event_type="project_upserted",
            payload=to_dict(project),
            source="test",
        )
        result = self.runtime._execute_solver_cycle(pid)
        self.assertIsNotNone(result)
        # Full advancement + execution returns outcome dict
        self.assertIn("status", result)
        self.assertIn("novelty", result)
        # Verify Blackboard received stage transition events
        events = self.runtime.blackboard.load_events(pid)
        stage_events = [e for e in events if e.payload.get("stage") in ("reason", "explore")]
        self.assertTrue(len(stage_events) >= 2)

    def test_execute_solver_cycle_explore(self):
        """_execute_solver_cycle in EXPLORE: Dispatcher executes, Blackboard gets outcome."""
        pid = self.project_ids[0]
        # Bootstrap + Reason manually through Dispatcher (so project reaches EXPLORE)
        self.runtime._dispatcher.schedule(pid)  # bootstrap
        self.runtime._dispatcher.schedule(pid)  # reason

        # Inject project into Blackboard
        from attack_agent.team.protocol import to_dict, TeamProject

        project = TeamProject(project_id=pid, challenge_id="web-auth", status="new")
        self.runtime.blackboard.append_event(
            project_id=pid,
            event_type="project_upserted",
            payload=to_dict(project),
            source="test",
        )

        result = self.runtime._execute_solver_cycle(pid)
        self.assertIsNotNone(result)
        self.assertIn("status", result)
        self.assertIn("novelty", result)
        self.assertIn("cost", result)

        # Verify Blackboard received ACTION_OUTCOME event
        events = self.runtime.blackboard.load_events(pid)
        outcome_events = [
            e for e in events if e.event_type == "action_outcome"
        ]
        self.assertTrue(len(outcome_events) > 0)
        self.assertIn("broker_execution", outcome_events[-1].payload)
        self.assertTrue(outcome_events[-1].payload["broker_execution"])

    def test_execute_solver_cycle_no_executor_returns_none(self):
        """_execute_solver_cycle returns None when use_real_executor=False."""
        config = TeamRuntimeConfig(blackboard_db_path=self.db_path)
        rt = TeamRuntime(config)
        result = rt._execute_solver_cycle("nonexistent")
        self.assertIsNone(result)


class TestTeamRuntimeSolveAllUnchanged(unittest.TestCase):
    """Verify TeamRuntime.solve_all() behavior equivalent to former CompetitionPlatform.solve_all()."""

    def setUp(self):
        self.provider = _build_identity_provider()
        self.runtime = build_team_runtime(self.provider, agent_config=fast_test_config())

    def test_solve_all_api_unchanged(self):
        """TeamRuntime.solve_all() works correctly."""
        self.runtime.solve_all()
        # At least one project should reach done or abandoned
        for pid, record in self.runtime._state_graph.projects.items():
            self.assertIn(
                record.snapshot.stage.value,
                {"done", "abandoned", "converge"},
            )


if __name__ == "__main__":
    unittest.main()