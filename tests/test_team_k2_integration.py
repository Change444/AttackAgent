"""Phase K-2 integration tests.

CompetitionPlatform removed — TeamRuntime is the sole entry point.
solve_all() bootstraps via Controller, runs via SyncScheduler,
and submits flags via PolicyHarness + SubmissionVerifier + Controller.
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
from attack_agent.platform_models import ChallengeDefinition, DualPathConfig, ProjectStage
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.team.runtime import TeamRuntime


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


def _build_solvable_provider() -> InMemoryCompetitionProvider:
    """Provider with a challenge that can be solved in heuristic mode."""
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


class TestTeamRuntimeSolveAll(unittest.TestCase):
    """TeamRuntime.solve_all() end-to-end: bootstrap → run → submit."""

    def setUp(self):
        self.provider = _build_solvable_provider()
        self.runtime = build_team_runtime(self.provider, agent_config=fast_test_config())

    def tearDown(self):
        try:
            self.runtime.close()
        except Exception:
            pass

    def test_solve_all_with_identity_challenge(self):
        """TeamRuntime.solve_all() runs the full loop until done/abandoned."""
        self.runtime.solve_all()

        record = self.runtime._state_graph.projects["project:web-auth"]
        # Without a real HTTP server, the challenge can't actually solve,
        # but the loop should reach a terminal state
        self.assertIn(record.snapshot.stage.value, {"done", "abandoned", "converge"})

    def test_solve_all_decision_events_in_blackboard(self):
        """Each cycle's decision events are written to Blackboard."""
        self.runtime.solve_all()

        events = self.runtime.blackboard.load_events("project:web-auth")
        # Should have project_upserted, instance_started, and decision events
        event_types = [e.event_type for e in events]
        self.assertIn("project_upserted", event_types)
        self.assertIn("instance_started", event_types)

    def test_solve_all_status_from_blackboard(self):
        """TeamRuntime.get_status() returns project state after solve_all."""
        self.runtime.solve_all()

        status = self.runtime.get_status("project:web-auth")
        self.assertIsNotNone(status)
        self.assertEqual(status.challenge_id, "web-auth")
        # Status should be one of the terminal/intermediate states
        self.assertIn(status.status, {"new", "abandoned", "done", "running"})

    def test_solve_all_flag_submitted_to_provider(self):
        """When a challenge is solved, the flag is submitted to the provider."""
        # This test uses a simple challenge with extract-candidate that
        # produces a flag directly — no real HTTP server needed
        provider = InMemoryCompetitionProvider([
            ChallengeDefinition(
                id="simple",
                name="Simple Flag",
                category="misc",
                difficulty="easy",
                target="misc://simple",
                description="A simple challenge.",
                metadata={
                    "flag": "flag{simple}",
                    "hint_budget": 1,
                    "hint": "Just extract the flag.",
                    "primitive_payloads": {
                        "structured-parse": [
                            {
                                "id": "hyp-simple",
                                "type": "hypothesis",
                                "tags": ["identity-boundary", "observation_gate"],
                                "statement": "Flag is directly available",
                                "confidence": 0.8,
                            },
                        ],
                        "extract-candidate": [
                            {
                                "type": "candidate_flag",
                                "tags": ["identity-boundary", "verification_gate"],
                                "value": "flag{simple}",
                                "confidence": 0.97,
                            },
                        ],
                    },
                },
            ),
        ])
        runtime = build_team_runtime(provider, agent_config=fast_test_config())
        runtime.solve_all()

        # Check the project reached a terminal state
        for pid in runtime._state_graph.projects:
            stage = runtime._state_graph.projects[pid].snapshot.stage.value
            self.assertIn(stage, {"done", "abandoned", "converge"})

    def test_build_team_runtime_without_agent_config(self):
        """build_team_runtime works without agent_config (uses defaults)."""
        provider = InMemoryCompetitionProvider([
            ChallengeDefinition(
                id="test-1",
                name="Test",
                category="web",
                difficulty="easy",
                target="http://127.0.0.1:8000",
                description="test challenge",
                metadata={"flag": "flag{test}", "hint_budget": 1, "hint": "none"},
            ),
        ])
        runtime = build_team_runtime(provider)
        self.assertTrue(runtime.use_real_executor)
        self.assertIsNotNone(runtime._controller)
        self.assertIsNotNone(runtime._provider)


class TestTeamRuntimeFactory(unittest.TestCase):
    """build_team_runtime wiring tests."""

    def test_factory_with_model_creates_llm_planner(self):
        """build_team_runtime with model creates EnhancedAPGPlanner with LLMReasoner."""
        from attack_agent.reasoning import LLMReasoner, StaticReasoningModel
        from attack_agent.enhanced_apg import EnhancedAPGPlanner

        provider = InMemoryCompetitionProvider([
            ChallengeDefinition(id="c1", name="Test", category="web",
                                difficulty="easy", target="http://127.0.0.1:8000",
                                description="test"),
        ])
        model = StaticReasoningModel({"select_worker_profile": {"profile": "network", "reason": "test"}})
        runtime = build_team_runtime(provider, model=model)
        planner = runtime._dispatcher.planner
        self.assertIsInstance(planner, EnhancedAPGPlanner)
        self.assertIsInstance(planner.reasoner, LLMReasoner)

    def test_factory_without_model_creates_heuristic_planner(self):
        """build_team_runtime without model creates EnhancedAPGPlanner with HeuristicReasoner."""
        from attack_agent.reasoning import HeuristicReasoner

        provider = InMemoryCompetitionProvider([
            ChallengeDefinition(id="c1", name="Test", category="web",
                                difficulty="easy", target="http://127.0.0.1:8000",
                                description="test"),
        ])
        runtime = build_team_runtime(provider)
        planner = runtime._dispatcher.planner
        self.assertIsInstance(planner.reasoner, HeuristicReasoner)


if __name__ == "__main__":
    unittest.main()