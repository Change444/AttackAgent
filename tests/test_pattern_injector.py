import unittest

from attack_agent.apg import PatternLibrary, FAMILY_KEYWORDS, FAMILY_PROGRAMS, APGPlanner, EpisodeMemory
from attack_agent.dynamic_pattern_composer import PatternTemplate, StepTemplate, ParameterSpec
from attack_agent.pattern_injector import PatternInjector, _map_steps_to_node_kinds
from attack_agent.platform_models import (
    ChallengeDefinition,
    PatternNodeKind,
    PrimitiveActionStep,
    ProjectSnapshot,
)


class TestPatternInjector(unittest.TestCase):

    def setUp(self) -> None:
        self.library = PatternLibrary()
        self.injector = PatternInjector(self.library)

    def test_inject_pattern_creates_dynamic_family(self):
        """Injected pattern creates dynamic family name"""
        pattern = PatternTemplate(
            id="p1", name="http-extract", description="http then extract candidate",
            applicability_conditions=["sql", "http"],
            steps_template=[
                StepTemplate(primitive="http-request", instruction_template="Fetch target", parameter_defaults={"method": "GET"}),
                StepTemplate(primitive="extract-candidate", instruction_template="Find flag", parameter_defaults={}),
            ],
            parameters={},
            created_at="2026-01-01",
        )
        family = self.injector.inject_pattern(pattern)
        self.assertEqual(family, "dynamic:http-extract")
        self.assertIn("dynamic:http-extract", self.library._dynamic_keywords)
        self.assertEqual(self.library._dynamic_keywords["dynamic:http-extract"], ("sql", "http"))

    def test_inject_pattern_distinguishes_dynamic_prefix(self):
        """Dynamic families have 'dynamic:' prefix"""
        pattern = PatternTemplate(
            id="p2", name="xss-inspect", description="xss inspection",
            applicability_conditions=["xss"],
            steps_template=[
                StepTemplate(primitive="browser-inspect", instruction_template="Check page", parameter_defaults={}),
                StepTemplate(primitive="extract-candidate", instruction_template="Find flag", parameter_defaults={}),
            ],
            parameters={},
            created_at="2026-01-01",
        )
        family = self.injector.inject_pattern(pattern)
        self.assertTrue(family.startswith("dynamic:"))

    def test_pattern_library_build_includes_dynamic(self):
        """PatternLibrary.build() includes dynamic families"""
        # Inject a dynamic pattern
        pattern = PatternTemplate(
            id="p3", name="sql-inject", description="SQL injection attack",
            applicability_conditions=["sql", "injection"],
            steps_template=[
                StepTemplate(primitive="http-request", instruction_template="Probe injection", parameter_defaults={"method": "GET"}),
                StepTemplate(primitive="structured-parse", instruction_template="Parse response", parameter_defaults={}),
                StepTemplate(primitive="extract-candidate", instruction_template="Find flag", parameter_defaults={}),
            ],
            parameters={},
            created_at="2026-01-01",
        )
        self.injector.inject_pattern(pattern)

        # Build graph with a SQL challenge
        project = ProjectSnapshot(
            project_id="test",
            challenge=ChallengeDefinition(id="c1", name="SQL Inject", category="web",
                                           difficulty="easy", target="http://127.0.0.1:8000",
                                           description="sql injection challenge"),
        )
        graph = self.library.build(project)

        # Dynamic family should be in the graph
        self.assertIn("dynamic:sql-inject", graph.family_priority)
        self.assertIn("dynamic:sql-inject:observe", graph.nodes)
        self.assertIn("dynamic:sql-inject:act", graph.nodes)

    def test_get_program_steps_returns_dynamic(self):
        """get_program_steps returns dynamic steps for dynamic families"""
        pattern = PatternTemplate(
            id="p4", name="test-steps", description="test",
            applicability_conditions=["test"],
            steps_template=[
                StepTemplate(primitive="http-request", instruction_template="Fetch", parameter_defaults={"method": "GET"}),
            ],
            parameters={},
            created_at="2026-01-01",
        )
        self.injector.inject_pattern(pattern)

        steps = self.library.get_program_steps("dynamic:test-steps", PatternNodeKind.OBSERVATION_GATE)
        self.assertTrue(len(steps) > 0)
        self.assertEqual(steps[0].primitive, "http-request")

    def test_get_program_steps_falls_back_to_hardcoded(self):
        """get_program_steps falls back to FAMILY_PROGRAMS for hardcoded families"""
        steps = self.library.get_program_steps("identity-boundary", PatternNodeKind.OBSERVATION_GATE)
        self.assertTrue(len(steps) > 0)
        self.assertEqual(steps[0].primitive, "http-request")

    def test_get_program_steps_returns_empty_for_missing(self):
        """get_program_steps returns empty list for unknown family/kind"""
        steps = self.library.get_program_steps("unknown-family", PatternNodeKind.OBSERVATION_GATE)
        self.assertEqual(steps, [])

    def test_map_steps_to_node_kinds_short(self):
        """1-2 steps → all to OBSERVATION_GATE"""
        templates = [
            StepTemplate(primitive="http-request", instruction_template="Fetch", parameter_defaults={}),
        ]
        result = _map_steps_to_node_kinds(templates)
        self.assertIn(PatternNodeKind.OBSERVATION_GATE, result)
        self.assertEqual(len(result[PatternNodeKind.OBSERVATION_GATE]), 1)
        self.assertIn(PatternNodeKind.FALLBACK, result)

    def test_map_steps_to_node_kinds_medium(self):
        """3-4 steps → first→OBS, middle→ACT, last→VER"""
        templates = [
            StepTemplate(primitive="http-request", instruction_template="Fetch", parameter_defaults={}),
            StepTemplate(primitive="structured-parse", instruction_template="Parse", parameter_defaults={}),
            StepTemplate(primitive="extract-candidate", instruction_template="Find", parameter_defaults={}),
        ]
        result = _map_steps_to_node_kinds(templates)
        self.assertIn(PatternNodeKind.OBSERVATION_GATE, result)
        self.assertIn(PatternNodeKind.ACTION_TEMPLATE, result)
        self.assertIn(PatternNodeKind.VERIFICATION_GATE, result)

    def test_map_steps_to_node_kinds_empty(self):
        """Empty template list returns empty dict"""
        result = _map_steps_to_node_kinds([])
        self.assertEqual(result, {})


class TestDynamicPatternComposerInjection(unittest.TestCase):

    def test_store_pattern_triggers_injection(self):
        """DynamicPatternComposer.store_pattern triggers PatternInjector"""
        library = PatternLibrary()
        injector = PatternInjector(library)
        composer = DynamicPatternComposer(injector=injector)

        pattern = PatternTemplate(
            id="p5", name="composer-inject", description="injected by composer",
            applicability_conditions=["injection", "test"],
            steps_template=[
                StepTemplate(primitive="http-request", instruction_template="Probe", parameter_defaults={}),
            ],
            parameters={},
            created_at="2026-01-01",
        )
        composer.store_pattern(pattern)

        self.assertIn("dynamic:composer-inject", library._dynamic_keywords)


if __name__ == "__main__":
    unittest.main()


from attack_agent.dynamic_pattern_composer import DynamicPatternComposer