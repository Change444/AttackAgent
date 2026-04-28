from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .models import new_id, utc_now
from .platform_models import EpisodeEntry, PrimitiveActionStep

if TYPE_CHECKING:
    from .pattern_injector import PatternInjector


@dataclass(slots=True)
class ParameterSpec:
    """参数规范"""
    name: str
    type: str
    default_value: Any
    description: str
    required: bool


@dataclass(slots=True)
class StepTemplate:
    """步骤模板"""
    primitive: str
    instruction_template: str
    parameter_defaults: dict[str, Any]


@dataclass(slots=True)
class PatternTemplate:
    """动态模式模板"""
    id: str
    name: str
    description: str
    applicability_conditions: list[str]
    steps_template: list[StepTemplate]
    parameters: dict[str, ParameterSpec]
    created_at: str
    usage_count: int = 0
    success_rate: float = 0.0


class PatternDiscoveryAlgorithm:
    """模式发现算法"""

    def find_common_sequences(self, sequences: list[list[str]], min_support: int = 3) -> list[list[str]]:
        """发现常见的步骤序列"""
        if not sequences:
            return []

        results: list[list[str]] = []
        for length in range(2, min(5, max(len(s) for s in sequences) + 1)):
            counts: dict[tuple[str, ...], int] = {}
            for seq in sequences:
                if len(seq) < length:
                    continue
                for i in range(len(seq) - length + 1):
                    sub = tuple(seq[i:i + length])
                    counts[sub] = counts.get(sub, 0) + 1

            for sub, count in counts.items():
                if count >= min_support:
                    results.append(list(sub))

        return results

    def parameterize_sequence(self, sequence: list[str], examples: list[list[dict]]) -> dict:
        """参数化步骤序列"""
        if not examples:
            return {"fixed_params": {}, "variable_params": {}}

        variable_params: dict[str, list[Any]] = {}
        fixed_params: dict[str, Any] = {}

        for step_name in sequence:
            values: list[Any] = []
            for example in examples:
                for step_data in example:
                    if step_data.get("primitive") == step_name:
                        for key, val in step_data.get("parameters", {}).items():
                            values.append(val)
                        break

            if not values:
                continue

            unique = set(str(v) for v in values)
            param_key = f"{step_name}_param"
            if len(unique) == 1:
                fixed_params[param_key] = values[0]
            else:
                variable_params[param_key] = values

        return {"fixed_params": fixed_params, "variable_params": variable_params}

    def compute_pattern_confidence(self, pattern: list[str], success_cases: list[EpisodeEntry]) -> float:
        """计算模式置信度"""
        if not success_cases:
            return 0.0

        pattern_str = ",".join(pattern)
        containing = 0
        for case in success_cases:
            case_str = case.feature_text
            if pattern_str in case_str:
                containing += 1

        return containing / len(success_cases)


class DynamicPatternComposer:
    """动态模式组合器：从成功案例发现和应用模式"""

    def __init__(self, discovery_threshold: int = 3, injector: PatternInjector | None = None) -> None:
        self.discovery_threshold = discovery_threshold
        self._algorithm = PatternDiscoveryAlgorithm()
        self._patterns: dict[str, PatternTemplate] = {}
        self._injector = injector

    def compose_pattern(self, steps: list[PrimitiveActionStep]) -> PatternTemplate:
        """从具体步骤抽象出模式模板"""
        templates: list[StepTemplate] = []
        for step in steps:
            templates.append(StepTemplate(
                primitive=step.primitive,
                instruction_template=step.instruction,
                parameter_defaults=dict(step.parameters),
            ))

        primitives = [s.primitive for s in steps]
        name = "-".join(primitives[:3]) if primitives else "empty"
        conditions = [f"需要 {p} 原始动作" for p in primitives[:3]]

        return PatternTemplate(
            id=f"pattern-{new_id('pat')}",
            name=name,
            description=f"从 {len(steps)} 个步骤中发现的模式",
            applicability_conditions=conditions,
            steps_template=templates,
            parameters={},
            created_at=utc_now(),
        )

    def apply_pattern(self, template: PatternTemplate, context: dict) -> list[PrimitiveActionStep]:
        """应用模式模板到具体上下文"""
        steps: list[PrimitiveActionStep] = []
        for step_template in template.steps_template:
            instruction = step_template.instruction_template
            for key, value in context.items():
                instruction = instruction.replace(f"{{{{{key}}}}}", str(value))

            params = dict(step_template.parameter_defaults)
            for key, value in context.items():
                if key in params:
                    params[key] = value

            steps.append(PrimitiveActionStep(
                primitive=step_template.primitive,
                instruction=instruction,
                parameters=params,
            ))

        template.usage_count += 1
        return steps

    def discover_patterns(self, success_cases: list[EpisodeEntry]) -> list[PatternTemplate]:
        """从成功案例中发现新模式"""
        if len(success_cases) < self.discovery_threshold:
            return []

        sequences: list[list[str]] = []
        for case in success_cases:
            primitives = case.feature_text.split(",")
            sequences.append([p.strip() for p in primitives if p.strip()])

        common = self._algorithm.find_common_sequences(
            sequences, min_support=self.discovery_threshold
        )

        patterns: list[PatternTemplate] = []
        for seq in common:
            confidence = self._algorithm.compute_pattern_confidence(seq, success_cases)
            name = "-".join(seq)
            conditions = [f"包含序列: {name}"]

            templates: list[StepTemplate] = []
            for primitive in seq:
                templates.append(StepTemplate(
                    primitive=primitive,
                    instruction_template=f"使用 {primitive} 执行操作",
                    parameter_defaults={},
                ))

            pattern = PatternTemplate(
                id=f"pattern-discovered-{new_id('pat')}",
                name=name,
                description=f"从 {len(success_cases)} 个成功案例中发现的模式",
                applicability_conditions=conditions,
                steps_template=templates,
                parameters={},
                created_at=utc_now(),
                success_rate=confidence,
            )

            self.store_pattern(pattern)
            patterns.append(pattern)

        return patterns

    def store_pattern(self, pattern: PatternTemplate) -> None:
        """存储发现的模式，并回注到 PatternLibrary"""
        self._patterns[pattern.id] = pattern
        if self._injector is not None:
            self._injector.inject_pattern(pattern)

    def retrieve_patterns(self, context: dict) -> list[PatternTemplate]:
        """检索适用的模式"""
        results: list[PatternTemplate] = []
        context_str = str(context)
        context_lower = context_str.lower()
        for pattern in self._patterns.values():
            matched = True
            for condition in pattern.applicability_conditions:
                cond_lower = condition.lower()
                if cond_lower not in context_lower:
                    keywords = [k for k in cond_lower.split() if len(k) > 2]
                    if not any(k in context_lower for k in keywords):
                        matched = False
                        break

            if matched:
                results.append(pattern)

        results.sort(key=lambda p: p.success_rate, reverse=True)
        return results