from __future__ import annotations

from .apg import PatternLibrary, FAMILY_KEYWORDS, PrimitiveActionStep
from .dynamic_pattern_composer import PatternTemplate, StepTemplate
from .platform_models import (
    PatternNode,
    PatternNodeKind,
    PatternEdge,
    PatternGraph,
)


class PatternInjector:
    """将动态发现的模式回注到 PatternLibrary，使结构化路径可用"""

    def __init__(self, pattern_library: PatternLibrary) -> None:
        self._pattern_library = pattern_library

    def inject_pattern(self, pattern: PatternTemplate) -> str:
        """将 PatternTemplate 注入到 PatternLibrary 的动态族中。

        Returns: 动态族名 (e.g. 'dynamic:http-request-extract-candidate')
        """
        family_name = f"dynamic:{pattern.name}"

        # Register dynamic keywords from applicability_conditions
        keywords = tuple(pattern.applicability_conditions)
        self._pattern_library.add_dynamic_family(family_name, keywords)

        # Convert steps_template to PrimitiveActionStep lists for each node kind
        programs = _map_steps_to_node_kinds(pattern.steps_template)
        for kind, steps in programs.items():
            self._pattern_library.add_dynamic_program(family_name, kind, steps)

        return family_name


def _map_steps_to_node_kinds(
    steps_template: list[StepTemplate],
) -> dict[PatternNodeKind, list[PrimitiveActionStep]]:
    """将 StepTemplate 列表映射到 PatternNodeKind -> PrimitiveActionStep 列表"""
    n = len(steps_template)
    result: dict[PatternNodeKind, list[PrimitiveActionStep]] = {}

    if n == 0:
        return result

    if n <= 2:
        # All steps go to OBSERVATION_GATE
        result[PatternNodeKind.OBSERVATION_GATE] = [
            PrimitiveActionStep(s.primitive, s.instruction_template, s.parameter_defaults)
            for s in steps_template
        ]
    elif n <= 4:
        # First → OBSERVATION_GATE, middle → ACTION_TEMPLATE, last → VERIFICATION_GATE
        first = steps_template[0]
        middle = steps_template[1:n - 1]
        last = steps_template[n - 1]

        result[PatternNodeKind.OBSERVATION_GATE] = [
            PrimitiveActionStep(first.primitive, first.instruction_template, first.parameter_defaults)
        ]
        result[PatternNodeKind.ACTION_TEMPLATE] = [
            PrimitiveActionStep(s.primitive, s.instruction_template, s.parameter_defaults)
            for s in middle
        ]
        result[PatternNodeKind.VERIFICATION_GATE] = [
            PrimitiveActionStep(last.primitive, last.instruction_template, last.parameter_defaults)
        ]
    else:
        # 1-2 → OBSERVATION_GATE, 3..n-2 → ACTION_TEMPLATE, n-1..n → VERIFICATION_GATE
        obs = steps_template[:2]
        act = steps_template[2:n - 2]
        ver = steps_template[n - 2:]

        result[PatternNodeKind.OBSERVATION_GATE] = [
            PrimitiveActionStep(s.primitive, s.instruction_template, s.parameter_defaults)
            for s in obs
        ]
        result[PatternNodeKind.ACTION_TEMPLATE] = [
            PrimitiveActionStep(s.primitive, s.instruction_template, s.parameter_defaults)
            for s in act
        ]
        result[PatternNodeKind.VERIFICATION_GATE] = [
            PrimitiveActionStep(s.primitive, s.instruction_template, s.parameter_defaults)
            for s in ver
        ]

    # Always add a generic FALLBACK
    result[PatternNodeKind.FALLBACK] = [
        PrimitiveActionStep(
            "structured-parse",
            f"Summarize dead ends from {steps_template[0].primitive} chain",
            {},
        )
    ]

    return result