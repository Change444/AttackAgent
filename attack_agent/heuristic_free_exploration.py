from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .apg import FAMILY_KEYWORDS, FAMILY_PROGRAMS, FAMILY_PROFILES, EpisodeMemory, _inject_challenge_params
from .constraint_aware_reasoner import ConstraintContextBuilder, PRIMITIVE_DESCRIPTIONS
from .constraints import LightweightSecurityShell
from .dynamic_pattern_composer import DynamicPatternComposer
from .models import new_id
from .observation_summarizer import ObservationSummarizer
from .platform_models import (
    ActionProgram,
    PlanningContext,
    PrimitiveActionStep,
    PatternNodeKind,
    WorkerProfile,
)


def _tokenize_with_cjk(text: str) -> list[str]:
    """分词：CJK 整词 + ASCII token"""
    lowered = text.lower()
    cjk = re.findall(r"[一-鿿㐀-䶿豈-﫿]+", lowered)
    ascii_tokens = re.findall(r"[a-z0-9_-]+", lowered)
    return cjk + ascii_tokens


class HeuristicFreeExplorationPlanner:
    """启发式自由探索规划器 — 无 LLM 时基于模式模板生成自由探索计划"""

    def __init__(self,
                 context_builder: ConstraintContextBuilder,
                 validator: LightweightSecurityShell,
                 pattern_composer: DynamicPatternComposer,
                 episode_memory: EpisodeMemory,
                 summarizer: ObservationSummarizer | None = None) -> None:
        self.context_builder = context_builder
        self.validator = validator
        self.pattern_composer = pattern_composer
        self.episode_memory = episode_memory
        self._summarizer = summarizer or ObservationSummarizer()

    def generate_constrained_plan(self, context: PlanningContext) -> ActionProgram | None:
        """生成启发式自由探索计划，支持多族融合"""
        record = context.record
        challenge = record.snapshot.challenge

        # 1. Build constraint context for max_steps limit
        constraints = self.context_builder.build(context)
        max_steps = constraints.max_steps

        # 2. Score families by keyword overlap with challenge text
        challenge_text = " ".join([
            challenge.name, challenge.description, challenge.category,
            " ".join(challenge.metadata.get("signals", [])),
        ])
        tokens = set(_tokenize_with_cjk(challenge_text))

        family_scores: dict[str, int] = {}
        for family, keywords in FAMILY_KEYWORDS.items():
            family_scores[family] = 1 + sum(1 for kw in keywords if kw in tokens)

        # 3. Enrich scores with episode memory hits
        memory_hits = self.episode_memory.search(challenge_text)
        for hit in memory_hits:
            for family in hit.pattern_families:
                if family in family_scores:
                    family_scores[family] += hit.score * 1.5

        # 4. Select best family; if no match, return None
        if not family_scores:
            return None
        sorted_families = sorted(family_scores, key=lambda f: family_scores[f], reverse=True)
        best_family = sorted_families[0]
        if family_scores[best_family] <= 1:
            return None

        # 5. Try multi-family composition if second family is close enough
        secondary_family: str | None = None
        multi_family_ratio = 0.7
        if len(sorted_families) >= 2:
            second_family = sorted_families[1]
            second_score = family_scores[second_family]
            if second_score >= multi_family_ratio * family_scores[best_family]:
                secondary_family = second_family

        # 6. Assemble steps from FAMILY_PROGRAMS
        steps: list[PrimitiveActionStep] = []
        phases = [
            PatternNodeKind.OBSERVATION_GATE,
            PatternNodeKind.ACTION_TEMPLATE,
            PatternNodeKind.VERIFICATION_GATE,
        ]
        family_programs = FAMILY_PROGRAMS.get(best_family, {})
        for phase in phases:
            phase_steps = family_programs.get(phase, [])
            # For multi-family: use secondary family's action template instead of primary's
            if phase == PatternNodeKind.ACTION_TEMPLATE and secondary_family is not None:
                secondary_programs = FAMILY_PROGRAMS.get(secondary_family, {})
                secondary_act_steps = secondary_programs.get(PatternNodeKind.ACTION_TEMPLATE, [])
                if secondary_act_steps:
                    phase_steps = secondary_act_steps
            steps.extend(phase_steps)

        # 7. Inject challenge-specific parameters into template steps
        steps = _inject_challenge_params(steps, challenge, record.snapshot.instance)

        # 8. Try to enrich with discovered patterns
        pattern_context = {"primitives": [s.primitive for s in steps]}
        discovered = self.pattern_composer.retrieve_patterns(pattern_context)
        for pattern in discovered[:1]:
            applied = self.pattern_composer.apply_pattern(pattern, pattern_context)
            # Add 1-2 enrichment steps (avoid duplication)
            existing_primitives = {s.primitive for s in steps}
            for applied_step in applied[:2]:
                if applied_step.primitive not in existing_primitives:
                    steps.append(applied_step)

        # 9. Ensure observation-first if required
        if constraints.observation_before_action:
            obs_steps = [s for s in steps if s.primitive in {
                "http-request", "browser-inspect", "artifact-scan", "binary-inspect",
            }]
            action_steps = [s for s in steps if s not in obs_steps]
            if obs_steps and action_steps and steps[0] not in obs_steps:
                steps = obs_steps + action_steps

        # 10. Trim to max_steps
        steps = steps[:max_steps]

        if not steps:
            return None

        # 11. Build rationale
        rationale = f"启发式自由探索: 基于 {best_family} 族模板生成，关键词匹配得分={family_scores[best_family]}"
        if secondary_family:
            rationale += f"，融合 {secondary_family} 族操作步骤(得分={family_scores[secondary_family]})"
        if discovered:
            rationale += f"，辅助模式={discovered[0].name}"

        pattern_nodes = [f"{best_family}:observe", f"{best_family}:act", f"{best_family}:verify"]
        if secondary_family:
            pattern_nodes.extend([f"{secondary_family}:act"])

        return ActionProgram(
            id=f"plan-heuristic-free-{new_id('plan')}",
            goal=f"启发式探索: {challenge.name}" + (f" (融合 {secondary_family})" if secondary_family else ""),
            pattern_nodes=pattern_nodes,
            steps=steps,
            allowed_primitives=list(PRIMITIVE_DESCRIPTIONS.keys()),
            verification_rules=[f"flag匹配: {challenge.flag_pattern}"],
            required_profile=FAMILY_PROFILES.get(best_family, WorkerProfile.HYBRID),
            rationale=rationale,
            planner_source="free_exploration_heuristic",
        )