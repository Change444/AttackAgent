import unittest

from attack_agent.constraint_aware_reasoner import ConstraintContextBuilder, PRIMITIVE_DESCRIPTIONS
from attack_agent.constraints import LightweightSecurityShell, SecurityConstraints
from attack_agent.dynamic_pattern_composer import DynamicPatternComposer, PatternTemplate, StepTemplate, ParameterSpec
from attack_agent.heuristic_free_exploration import HeuristicFreeExplorationPlanner
from attack_agent.observation_summarizer import ObservationSummarizer
from attack_agent.platform_models import (
    ChallengeDefinition,
    ChallengeInstance,
    DualPathConfig,
    PlanningContext,
    PrimitiveActionStep,
    ProjectSnapshot,
    ProjectStage,
    WorkerProfile,
)
from attack_agent.state_graph import StateGraphService


def _make_record(challenge: ChallengeDefinition) -> tuple[StateGraphService, object]:
    sg = StateGraphService()
    snapshot = ProjectSnapshot(
        project_id=f"project-{challenge.id}",
        challenge=challenge,
        stage=ProjectStage.EXPLORE,
        instance=ChallengeInstance(
            instance_id="inst-1",
            challenge_id=challenge.id,
            target=challenge.target,
            status="running",
            metadata={},
        ),
    )
    sg.upsert_project(snapshot)
    record = sg.projects[snapshot.project_id]
    # Initialize pattern graph for structured path
    from attack_agent.apg import APGPlanner
    APGPlanner(sg.episode_memory).create_graph(snapshot)
    return sg, record


class TestHeuristicFreeExplorationPlanner(unittest.TestCase):

    def setUp(self) -> None:
        self.security_constraints = SecurityConstraints()
        self.shell = LightweightSecurityShell(self.security_constraints)
        self.builder = ConstraintContextBuilder(self.security_constraints)
        self.composer = DynamicPatternComposer()
        self.summarizer = ObservationSummarizer()
        self.sg = StateGraphService()

    def _make_planner(self, episode_memory=None) -> HeuristicFreeExplorationPlanner:
        return HeuristicFreeExplorationPlanner(
            context_builder=self.builder,
            validator=self.shell,
            pattern_composer=self.composer,
            episode_memory=episode_memory or self.sg.episode_memory,
            summarizer=self.summarizer,
        )

    def test_generate_plan_returns_program_for_keyword_match(self):
        """Challenge with SQL keywords should produce a plan"""
        challenge = ChallengeDefinition(
            id="c1", name="SQL Injection", category="web",
            difficulty="easy", target="http://127.0.0.1:8000",
            description="sql query parser injection challenge",
        )
        sg, record = _make_record(challenge)
        planner = self._make_planner(sg.episode_memory)
        context = PlanningContext(
            record=record, attempt_count=0,
            historical_success_rate=0.0, complexity_score=0.5,
            pattern_confidence=0.0, exploration_budget=3,
        )
        program = planner.generate_constrained_plan(context)
        self.assertIsNotNone(program)
        self.assertEqual(program.planner_source, "free_exploration_heuristic")
        self.assertTrue(len(program.steps) > 0)

    def test_generate_plan_returns_none_for_no_keyword_match(self):
        """Challenge with no keyword overlap returns None"""
        challenge = ChallengeDefinition(
            id="c2", name="Gibberish", category="unknown",
            difficulty="easy", target="http://127.0.0.1:8000",
            description="xyzzy foo bar quux nothing relevant",
        )
        sg, record = _make_record(challenge)
        planner = self._make_planner(sg.episode_memory)
        context = PlanningContext(
            record=record, attempt_count=0,
            historical_success_rate=0.0, complexity_score=0.5,
            pattern_confidence=0.0, exploration_budget=3,
        )
        program = planner.generate_constrained_plan(context)
        # score <= 1 (only the base score) → returns None
        self.assertIsNone(program)

    def test_generate_plan_respects_max_steps(self):
        """Plan steps should not exceed max_steps from constraints"""
        challenge = ChallengeDefinition(
            id="c3", name="SQL Auth Login", category="web",
            difficulty="easy", target="http://127.0.0.1:8000",
            description="sql injection login challenge with auth tokens",
        )
        sg, record = _make_record(challenge)
        planner = self._make_planner(sg.episode_memory)
        context = PlanningContext(
            record=record, attempt_count=0,
            historical_success_rate=0.0, complexity_score=0.5,
            pattern_confidence=0.0, exploration_budget=3,
        )
        program = planner.generate_constrained_plan(context)
        self.assertIsNotNone(program)
        self.assertTrue(len(program.steps) <= 15)

    def test_generate_plan_with_discovered_patterns(self):
        """Discovered patterns should enrich the plan"""
        challenge = ChallengeDefinition(
            id="c4", name="SQL Attack", category="web",
            difficulty="medium", target="http://127.0.0.1:8000",
            description="sql query injection",
        )
        sg, record = _make_record(challenge)
        # Add a pattern to the composer
        pattern = PatternTemplate(
            id="p1", name="http-extract", description="http then extract",
            applicability_conditions=["http-request"],
            steps_template=[
                StepTemplate(primitive="http-request", instruction_template="Fetch {{url}}", parameter_defaults={"method": "GET"}),
                StepTemplate(primitive="extract-candidate", instruction_template="Find flag", parameter_defaults={}),
            ],
            parameters={"url": ParameterSpec(name="url", type="str", default_value="/", description="target path", required=True)},
            created_at="2026-01-01",
        )
        self.composer.store_pattern(pattern)
        planner = self._make_planner(sg.episode_memory)
        context = PlanningContext(
            record=record, attempt_count=0,
            historical_success_rate=0.0, complexity_score=0.5,
            pattern_confidence=0.0, exploration_budget=3,
        )
        program = planner.generate_constrained_plan(context)
        self.assertIsNotNone(program)

    def test_generate_plan_returns_program_for_ssrf_match(self):
        """Challenge with SSRF keywords should produce a plan"""
        challenge = ChallengeDefinition(
            id="c5", name="Internal Proxy", category="web",
            difficulty="medium", target="http://127.0.0.1:8000",
            description="ssrf internal proxy fetch metadata cloud redirect challenge",
        )
        sg, record = _make_record(challenge)
        planner = self._make_planner(sg.episode_memory)
        context = PlanningContext(
            record=record, attempt_count=0,
            historical_success_rate=0.0, complexity_score=0.5,
            pattern_confidence=0.0, exploration_budget=3,
        )
        program = planner.generate_constrained_plan(context)
        self.assertIsNotNone(program)
        self.assertEqual(program.planner_source, "free_exploration_heuristic")
        self.assertTrue(len(program.steps) > 0)

    def test_generate_plan_returns_program_for_crypto_match(self):
        """Challenge with crypto keywords should produce a plan"""
        challenge = ChallengeDefinition(
            id="c6", name="RSA Padding", category="crypto",
            difficulty="hard", target="http://127.0.0.1:8000",
            description="rsa aes padding oracle ciphertext crypto challenge",
        )
        sg, record = _make_record(challenge)
        planner = self._make_planner(sg.episode_memory)
        context = PlanningContext(
            record=record, attempt_count=0,
            historical_success_rate=0.0, complexity_score=0.5,
            pattern_confidence=0.0, exploration_budget=3,
        )
        program = planner.generate_constrained_plan(context)
        self.assertIsNotNone(program)
        self.assertEqual(program.planner_source, "free_exploration_heuristic")
        self.assertTrue(len(program.steps) > 0)

    def test_integration_model_none_creates_enhanced_planner(self):
        """model=None should now create EnhancedAPGPlanner with HeuristicFreeExplorationPlanner"""
        from attack_agent.platform import CompetitionPlatform
        from attack_agent.enhanced_apg import EnhancedAPGPlanner
        provider = InMemoryCompetitionProvider([
            ChallengeDefinition(id="c1", name="Test", category="web",
                                difficulty="easy", target="http://127.0.0.1:8000",
                                description="test"),
        ])
        platform = CompetitionPlatform(provider, model=None)
        self.assertIsInstance(platform.strategy.planner, EnhancedAPGPlanner)
        self.assertIsInstance(platform.strategy.planner.free_exploration_planner, HeuristicFreeExplorationPlanner)

    def test_generate_plan_steps_have_challenge_target_urls(self):
        """Steps in generated plan should have challenge target URL injected"""
        challenge = ChallengeDefinition(
            id="c7", name="SQL Auth", category="web",
            difficulty="easy", target="http://sql-target:9000",
            description="sql query injection challenge",
        )
        sg, record = _make_record(challenge)
        planner = self._make_planner(sg.episode_memory)
        context = PlanningContext(
            record=record, attempt_count=0,
            historical_success_rate=0.0, complexity_score=0.5,
            pattern_confidence=0.0, exploration_budget=3,
        )
        program = planner.generate_constrained_plan(context)
        self.assertIsNotNone(program)
        http_steps = [s for s in program.steps if s.primitive == "http-request"]
        self.assertTrue(len(http_steps) > 0)
        for step in http_steps:
            self.assertEqual(step.parameters.get("url"), "http://sql-target:9000")


if __name__ == "__main__":
    unittest.main()


# Import InMemoryCompetitionProvider for integration test
from attack_agent.provider import InMemoryCompetitionProvider