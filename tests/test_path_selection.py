import unittest

from attack_agent.path_selection import PathSelectionStrategy, PathSelectionFactors
from attack_agent.platform_models import DualPathConfig, PathType, PlanningContext
from attack_agent.state_graph import StateGraphService, ProjectRecord
from attack_agent.platform_models import (
    ChallengeDefinition,
    ProjectSnapshot,
    ProjectStage,
    WorkerProfile,
)


class TestPathSelectionFactors(unittest.TestCase):

    def test_dataclass_fields(self):
        """测试因子数据类字段"""
        factors = PathSelectionFactors(
            confidence_low=True,
            complexity_high=False,
            stable_pattern_exists=False,
            exploration_remaining=True,
            fallback_available=True,
        )
        self.assertTrue(factors.confidence_low)
        self.assertFalse(factors.complexity_high)
        self.assertTrue(factors.exploration_remaining)


class TestPathSelectionStrategy(unittest.TestCase):

    def setUp(self):
        self.config = DualPathConfig(
            structured_path_weight=0.7,
            free_exploration_weight=0.3,
            max_exploration_attempts=5,
            exploration_budget_per_project=3,
        )
        self.strategy = PathSelectionStrategy(self.config)

    def _make_context(self, **overrides) -> PlanningContext:
        defaults = {
            "attempt_count": 0,
            "historical_success_rate": 0.5,
            "complexity_score": 0.5,
            "pattern_confidence": 0.5,
            "exploration_budget": 3,
            "current_path": PathType.STRUCTURED,
        }
        for k, v in overrides.items():
            defaults[k] = v
        challenge = ChallengeDefinition(
            id="c1", name="test", category="web",
            difficulty="easy", target="http://127.0.0.1",
        )
        snapshot = ProjectSnapshot(project_id="p1", challenge=challenge)
        sg = StateGraphService()
        sg.upsert_project(snapshot)
        record = sg.projects["p1"]
        return PlanningContext(record=record, **defaults)

    def test_no_exploration_budget_returns_structured(self):
        """测试无探索预算返回结构化路径"""
        ctx = self._make_context(exploration_budget=0)
        result = self.strategy.select_path(ctx)
        self.assertEqual(result, PathType.STRUCTURED)

    def test_low_confidence_no_fallback_returns_structured(self):
        """测试低置信度无回退返回结构化路径"""
        ctx = self._make_context(
            pattern_confidence=0.3,
            current_path=PathType.FREE_EXPLORATION,
        )
        result = self.strategy.select_path(ctx)
        self.assertEqual(result, PathType.STRUCTURED)

    def test_low_confidence_high_complexity_returns_free_exploration(self):
        """测试低置信度+高复杂度返回自由探索路径"""
        ctx = self._make_context(
            pattern_confidence=0.3,
            complexity_score=0.8,
            current_path=PathType.STRUCTURED,
        )
        result = self.strategy.select_path(ctx)
        self.assertEqual(result, PathType.FREE_EXPLORATION)

    def test_stable_pattern_returns_structured(self):
        """测试稳定模式存在返回结构化路径"""
        ctx = self._make_context(pattern_confidence=0.8)
        result = self.strategy.select_path(ctx)
        self.assertEqual(result, PathType.STRUCTURED)

    def test_evaluate_factors_correct_values(self):
        """测试因子评估产生正确的值"""
        ctx = self._make_context(
            pattern_confidence=0.3,
            complexity_score=0.8,
            exploration_budget=2,
            current_path=PathType.STRUCTURED,
        )
        factors = self.strategy._evaluate_factors(ctx)
        self.assertTrue(factors.confidence_low)
        self.assertTrue(factors.complexity_high)
        self.assertFalse(factors.stable_pattern_exists)
        self.assertTrue(factors.exploration_remaining)
        self.assertTrue(factors.fallback_available)

    def test_should_use_free_exploration(self):
        """测试判断是否使用自由探索"""
        factors = PathSelectionFactors(
            confidence_low=True, complexity_high=True,
            stable_pattern_exists=False, exploration_remaining=True,
            fallback_available=True,
        )
        self.assertTrue(self.strategy._should_use_free_exploration(factors))

        factors_no_budget = PathSelectionFactors(
            confidence_low=True, complexity_high=True,
            stable_pattern_exists=False, exploration_remaining=False,
            fallback_available=True,
        )
        self.assertFalse(self.strategy._should_use_free_exploration(factors_no_budget))

    def test_mixed_selection_with_high_ratio_returns_structured(self):
        """测试高权重比例偏向结构化"""
        ctx = self._make_context(pattern_confidence=0.5, complexity_score=0.5)
        # ratio=1.0 always returns STRUCTURED
        result = self.strategy._mixed_selection(ctx, 1.0)
        self.assertEqual(result, PathType.STRUCTURED)

    def test_mixed_selection_with_zero_ratio_returns_free(self):
        """测试零权重比例返回自由探索"""
        ctx = self._make_context(pattern_confidence=0.5, complexity_score=0.5)
        result = self.strategy._mixed_selection(ctx, 0.0)
        self.assertEqual(result, PathType.FREE_EXPLORATION)


if __name__ == "__main__":
    unittest.main()