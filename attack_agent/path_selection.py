from __future__ import annotations

import random
from dataclasses import dataclass

from .platform_models import DualPathConfig, PathType, PlanningContext


@dataclass(slots=True)
class PathSelectionFactors:
    """路径选择因子"""
    confidence_low: bool
    complexity_high: bool
    stable_pattern_exists: bool
    exploration_remaining: bool
    fallback_available: bool


class PathSelectionStrategy:
    """路径选择策略：评估当前状态适合哪条路径"""

    def __init__(self, config: DualPathConfig) -> None:
        self.config = config

    def select_path(self, context: PlanningContext) -> PathType:
        """选择规划路径"""
        factors = self._evaluate_factors(context)

        if not factors.exploration_remaining:
            return PathType.STRUCTURED

        if not factors.fallback_available and factors.confidence_low:
            return PathType.STRUCTURED

        if factors.confidence_low and factors.complexity_high:
            return PathType.FREE_EXPLORATION

        if factors.stable_pattern_exists:
            return PathType.STRUCTURED

        return self._mixed_selection(context, self.config.structured_path_weight)

    def _evaluate_factors(self, context: PlanningContext) -> PathSelectionFactors:
        """评估路径选择因子"""
        confidence_low = context.pattern_confidence < 0.5
        complexity_high = context.complexity_score > 0.7
        stable_pattern_exists = context.pattern_confidence >= 0.7
        exploration_remaining = context.exploration_budget > 0
        fallback_available = context.current_path == PathType.STRUCTURED

        return PathSelectionFactors(
            confidence_low=confidence_low,
            complexity_high=complexity_high,
            stable_pattern_exists=stable_pattern_exists,
            exploration_remaining=exploration_remaining,
            fallback_available=fallback_available,
        )

    def _should_use_free_exploration(self, factors: PathSelectionFactors) -> bool:
        """判断是否使用自由探索路径"""
        return factors.exploration_remaining and factors.confidence_low and factors.complexity_high

    def _mixed_selection(self, context: PlanningContext, ratio: float = 0.7) -> PathType:
        """混合选择策略"""
        if random.random() < ratio:
            return PathType.STRUCTURED
        return PathType.FREE_EXPLORATION