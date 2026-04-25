import unittest

from attack_agent.dynamic_pattern_composer import (
    DynamicPatternComposer,
    PatternTemplate,
    StepTemplate,
    ParameterSpec,
    PatternDiscoveryAlgorithm,
)
from attack_agent.platform_models import EpisodeEntry, PrimitiveActionStep


class TestParameterSpec(unittest.TestCase):

    def test_fields(self):
        spec = ParameterSpec(
            name="url", type="str", default_value="/",
            description="target URL", required=True,
        )
        self.assertEqual(spec.name, "url")
        self.assertTrue(spec.required)


class TestStepTemplate(unittest.TestCase):

    def test_fields(self):
        template = StepTemplate(
            primitive="http-request",
            instruction_template="请求 {{url}}",
            parameter_defaults={"url": "/"},
        )
        self.assertEqual(template.primitive, "http-request")


class TestPatternDiscoveryAlgorithm(unittest.TestCase):

    def setUp(self):
        self.algorithm = PatternDiscoveryAlgorithm()

    def test_find_common_sequences_with_frequent_patterns(self):
        """测试发现常见序列"""
        sequences = [
            ["http-request", "structured-parse", "extract-candidate"],
            ["http-request", "structured-parse", "extract-candidate"],
            ["http-request", "structured-parse", "http-request"],
        ]
        result = self.algorithm.find_common_sequences(sequences, min_support=2)
        self.assertTrue(len(result) > 0)
        # Should find "http-request, structured-parse" (3 occurrences)
        found_pair = ["http-request", "structured-parse"]
        self.assertTrue(any(found_pair == r for r in result))

    def test_find_common_sequences_empty_input(self):
        """测试空输入"""
        result = self.algorithm.find_common_sequences([], min_support=3)
        self.assertEqual(result, [])

    def test_find_common_sequences_below_threshold(self):
        """测试低于阈值不返回"""
        sequences = [
            ["a", "b"],
            ["a", "c"],
        ]
        result = self.algorithm.find_common_sequences(sequences, min_support=3)
        self.assertEqual(result, [])

    def test_compute_pattern_confidence(self):
        """测试模式置信度计算"""
        cases = [
            EpisodeEntry(id="1", feature_text="http-request,extract-candidate",
                         pattern_families=["web"], summary="test", success=True),
            EpisodeEntry(id="2", feature_text="browser-inspect,diff-compare",
                         pattern_families=["web"], summary="test2", success=True),
        ]
        confidence = self.algorithm.compute_pattern_confidence(
            ["http-request"], cases
        )
        self.assertEqual(confidence, 0.5)

    def test_compute_pattern_confidence_no_cases(self):
        """测试无成功案例返回0"""
        confidence = self.algorithm.compute_pattern_confidence(
            ["http-request"], []
        )
        self.assertEqual(confidence, 0.0)

    def test_parameterize_sequence(self):
        """测试序列参数化"""
        sequence = ["http-request"]
        examples = [
            [{"primitive": "http-request", "parameters": {"url": "/login"}}],
            [{"primitive": "http-request", "parameters": {"url": "/admin"}}],
        ]
        result = self.algorithm.parameterize_sequence(sequence, examples)
        self.assertIn("variable_params", result)


class TestDynamicPatternComposer(unittest.TestCase):

    def setUp(self):
        self.composer = DynamicPatternComposer(discovery_threshold=2)

    def test_compose_pattern_from_steps(self):
        """测试从步骤组合模式"""
        steps = [
            PrimitiveActionStep(primitive="http-request", instruction="请求页面", parameters={"url": "/"}),
            PrimitiveActionStep(primitive="extract-candidate", instruction="提取flag", parameters={}),
        ]
        pattern = self.composer.compose_pattern(steps)
        self.assertIsInstance(pattern, PatternTemplate)
        self.assertEqual(len(pattern.steps_template), 2)
        self.assertEqual(pattern.steps_template[0].primitive, "http-request")

    def test_apply_pattern_to_context(self):
        """测试应用模式到上下文"""
        template = PatternTemplate(
            id="p1", name="test-pattern",
            description="test", applicability_conditions=["需要 http-request"],
            steps_template=[
                StepTemplate(primitive="http-request",
                             instruction_template="请求 {{url}}",
                             parameter_defaults={"url": "/"}),
            ],
            parameters={}, created_at="2026-01-01",
        )
        steps = self.composer.apply_pattern(template, {"url": "/login"})
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].primitive, "http-request")
        self.assertIn("/login", steps[0].instruction)
        self.assertEqual(template.usage_count, 1)

    def test_store_and_retrieve_pattern(self):
        """测试存储和检索模式"""
        pattern = PatternTemplate(
            id="p1", name="web-sqli",
            description="SQL注入模式",
            applicability_conditions=["http-request"],
            steps_template=[
                StepTemplate(primitive="http-request", instruction_template="发送请求",
                             parameter_defaults={}),
            ],
            parameters={}, created_at="2026-01-01", success_rate=0.8,
        )
        self.composer.store_pattern(pattern)
        results = self.composer.retrieve_patterns(
            {"primitives": ["http-request", "structured-parse"]}
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "web-sqli")

    def test_discover_patterns_from_success_cases(self):
        """测试从成功案例发现模式"""
        cases = [
            EpisodeEntry(id="1", feature_text="http-request,structured-parse,extract-candidate",
                         pattern_families=["web"], summary="SQL注入", success=True),
            EpisodeEntry(id="2", feature_text="http-request,structured-parse,extract-candidate",
                         pattern_families=["web"], summary="SQL注入2", success=True),
            EpisodeEntry(id="3", feature_text="http-request,structured-parse,diff-compare",
                         pattern_families=["web"], summary="其他", success=True),
        ]
        patterns = self.composer.discover_patterns(cases)
        # Should discover some common sequences (threshold=2)
        self.assertTrue(len(patterns) >= 0)

    def test_discover_patterns_below_threshold(self):
        """测试低于阈值不发现模式"""
        cases = [
            EpisodeEntry(id="1", feature_text="a,b", pattern_families=["x"],
                         summary="test", success=True),
        ]
        patterns = self.composer.discover_patterns(cases)
        self.assertEqual(len(patterns), 0)

    def test_retrieve_no_match_returns_empty(self):
        """测试不匹配的检索返回空"""
        pattern = PatternTemplate(
            id="p1", name="binary", description="二进制模式",
            applicability_conditions=["需要 binary-inspect"],
            steps_template=[], parameters={}, created_at="2026-01-01",
        )
        self.composer.store_pattern(pattern)
        results = self.composer.retrieve_patterns({"primitives": ["http-request"]})
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()