from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .apg import FAMILY_KEYWORDS, FAMILY_PROGRAMS, FAMILY_PROFILES, EpisodeMemory
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
        """生成启发式自由探索计划"""
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
        best_family = max(family_scores, key=lambda f: family_scores[f])
        if family_scores[best_family] <= 1:
            return None

        # 5. Assemble steps from FAMILY_PROGRAMS
        steps: list[PrimitiveActionStep] = []
        phases = [
            PatternNodeKind.OBSERVATION_GATE,
            PatternNodeKind.ACTION_TEMPLATE,
            PatternNodeKind.VERIFICATION_GATE,
        ]
        family_programs = FAMILY_PROGRAMS.get(best_family, {})
        for phase in phases:
            phase_steps = family_programs.get(phase, [])
            steps.extend(phase_steps)

        # 6. Try to enrich with discovered patterns
        pattern_context = {"primitives": [s.primitive for s in steps]}
        discovered = self.pattern_composer.retrieve_patterns(pattern_context)
        for pattern in discovered[:1]:
            applied = self.pattern_composer.apply_pattern(pattern, pattern_context)
            # Add 1-2 enrichment steps (avoid duplication)
            existing_primitives = {s.primitive for s in steps}
            for applied_step in applied[:2]:
                if applied_step.primitive not in existing_primitives:
                    steps.append(applied_step)

        # 7. Ensure observation-first if required
        if constraints.observation_before_action:
            obs_steps = [s for s in steps if s.primitive in {
                "http-request", "browser-inspect", "artifact-scan", "binary-inspect",
            }]
            action_steps = [s for s in steps if s not in obs_steps]
            if obs_steps and action_steps and steps[0] not in obs_steps:
                steps = obs_steps + action_steps

        # 8. Trim to max_steps
        steps = steps[:max_steps]

        if not steps:
            return None

        # 9. Build rationale
        rationale = f"启发式自由探索: 基于 {best_family} 族模板生成，关键词匹配得分={family_scores[best_family]}"
        if discovered:
            rationale += f"，辅助模式={discovered[0].name}"

        return ActionProgram(
            id=f"plan-heuristic-free-{new_id('plan')}",
            goal=f"启发式探索: {challenge.name}",
            pattern_nodes=[f"{best_family}:observe", f"{best_family}:act", f"{best_family}:verify"],
            steps=steps,
            allowed_primitives=list(PRIMITIVE_DESCRIPTIONS.keys()),
            verification_rules=[f"flag匹配: {challenge.flag_pattern}"],
            required_profile=FAMILY_PROFILES.get(best_family, WorkerProfile.HYBRID),
            rationale=rationale,
            planner_source="free_exploration_heuristic",
        )