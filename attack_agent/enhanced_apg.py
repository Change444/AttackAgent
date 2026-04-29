from __future__ import annotations

from typing import Any

from .apg import APGPlanner
from .constraint_aware_reasoner import ConstraintContextBuilder
from .dynamic_pattern_composer import DynamicPatternComposer, PatternTemplate
from .models import new_id
from .observation_summarizer import ObservationSummarizer
from .path_selection import PathSelectionStrategy, PathSelectionFactors
from .platform_models import (
    ActionProgram,
    DualPathConfig,
    Event,
    EventType,
    FreeExplorationPlanner,
    PathType,
    PatternGraph,
    PatternNodeKind,
    PlanningContext,
    ProjectSnapshot,
    RetrievalHit,
    WorkerProfile,
)
from .semantic_retrieval import SemanticRetrievalEngine


class EnhancedAPGPlanner:
    """增强型规划器：协调双路径规划"""

    def __init__(self,
                 structured_planner: APGPlanner,
                 free_exploration_planner: FreeExplorationPlanner,
                 semantic_retrieval: SemanticRetrievalEngine,
                 pattern_composer: DynamicPatternComposer,
                 config: DualPathConfig | None = None) -> None:
        self.structured_planner = structured_planner
        self.free_exploration_planner = free_exploration_planner
        self.semantic_retrieval = semantic_retrieval
        self.pattern_composer = pattern_composer
        self.config = config or DualPathConfig()
        self._path_strategy = PathSelectionStrategy(self.config)
        self._exploration_attempts: dict[str, int] = {}
        self._current_paths: dict[str, PathType] = {}
        self._stagnation_counters: dict[str, int] = {}

    @property
    def reasoner(self):
        """访问结构化规划器的推理器"""
        return self.structured_planner.reasoner

    def plan(self, record) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        """双路径规划"""
        project_id = record.snapshot.project_id
        current_path = self._current_paths.get(project_id, PathType.STRUCTURED)
        context = self._build_planning_context(record, current_path)

        # Auto-switch if stagnation threshold reached on current path
        stagnation = self._stagnation_counters.get(project_id, 0)
        if stagnation >= self.config.path_switch_stagnation_threshold and current_path != PathType.FREE_EXPLORATION:
            switched = self.switch_path(record, reason="structured_path_stagnation")
            if switched:
                current_path = PathType.FREE_EXPLORATION
                context = self._build_planning_context(record, current_path)

        path_type = self.select_path(context)
        # Honor explicit switch_path overrides; otherwise use strategy result
        if current_path == PathType.FREE_EXPLORATION and stagnation >= self.config.path_switch_stagnation_threshold:
            path_type = PathType.FREE_EXPLORATION
        self._current_paths[project_id] = path_type
        self._record_path_selection(record, path_type, context)

        program: ActionProgram | None = None
        hits: list[RetrievalHit] = []

        if path_type == PathType.STRUCTURED:
            program, hits = self._plan_structured(record, context)
        elif path_type == PathType.FREE_EXPLORATION:
            program, hits = self._plan_free_exploration(record, context)
            self._exploration_attempts[project_id] = self._exploration_attempts.get(project_id, 0) + 1
        else:  # HYBRID
            program, hits = self._plan_hybrid(record, context)
            if program is not None and program.planner_source.startswith("free_exploration"):
                self._exploration_attempts[project_id] = self._exploration_attempts.get(project_id, 0) + 1

        return program, hits

    def select_path(self, context: PlanningContext) -> PathType:
        """选择规划路径"""
        return self._path_strategy.select_path(context)

    def switch_path(self, record, reason: str) -> bool:
        """切换规划路径 — 从结构化切换到自由探索，或从自由探索回到结构化"""
        project_id = record.snapshot.project_id
        current_path = self._current_paths.get(project_id, PathType.STRUCTURED)
        exploration_count = self._exploration_attempts.get(project_id, 0)

        new_path: PathType | None = None

        if current_path == PathType.STRUCTURED:
            # Switch to free exploration if budget remains
            budget = self.config.exploration_budget_per_project - exploration_count
            if budget > 0:
                new_path = PathType.FREE_EXPLORATION
        elif current_path == PathType.FREE_EXPLORATION:
            # Switch back to structured if exploration budget exhausted or exploration found good pattern
            if exploration_count >= self.config.max_exploration_attempts:
                new_path = PathType.STRUCTURED
            # Also switch back if pattern confidence is now high (exploration paid off)
            context = self._build_planning_context(record, current_path)
            if context.pattern_confidence >= 0.7:
                new_path = PathType.STRUCTURED

        if new_path is None:
            return False

        self._current_paths[project_id] = new_path
        # Reset stagnation counter on switch to give new path a fresh chance
        self._stagnation_counters[project_id] = 0

        # Record path switch event
        if record.run_journal is not None:
            event = Event(
                type=EventType.PATH_SELECTION,
                project_id=project_id,
                run_id="path-switch",
                payload={
                    "path_type": new_path.value,
                    "previous_path": current_path.value,
                    "reason": reason,
                    "exploration_attempts": exploration_count,
                },
                source="enhanced_apg_switch",
            )
            record.run_journal.append(event)

        return True

    def create_graph(self, project: ProjectSnapshot) -> PatternGraph:
        """创建模式图（委托给结构化规划器）"""
        return self.structured_planner.create_graph(project)

    def update_graph(self, record, program: ActionProgram, outcome) -> None:
        """更新模式图（委托给结构化规划器）"""
        self.structured_planner.update_graph(record, program, outcome)

    def record_outcome(self, record, program: ActionProgram, outcome) -> None:
        """记录执行结果，更新停滞计数器用于路径切换"""
        project_id = record.snapshot.project_id
        stagnation = self._stagnation_counters.get(project_id, 0)
        if outcome.status == "ok" and (outcome.novelty > 0.0 or outcome.candidate_flags):
            self._stagnation_counters[project_id] = 0
        else:
            self._stagnation_counters[project_id] = stagnation + 1

    def _build_planning_context(self, record, current_path: PathType = PathType.STRUCTURED) -> PlanningContext:
        """构建规划上下文"""
        project_id = record.snapshot.project_id
        attempt_count = self._exploration_attempts.get(project_id, 0)

        journal = record.run_journal
        compiled_events = [e for e in journal if e.type == EventType.PROGRAM_COMPILED]
        total_attempts = len(compiled_events) + attempt_count

        success_rate = 0.0
        memory = self.structured_planner.memory
        if memory.entries:
            successful = [e for e in memory.entries if e.success]
            success_rate = len(successful) / len(memory.entries)

        complexity = self._compute_complexity(record)

        pattern_confidence = 0.0
        if record.pattern_graph is not None:
            non_goal = [n for n in record.pattern_graph.nodes.values()
                        if n.kind != PatternNodeKind.GOAL]
            if non_goal:
                resolved = [n for n in non_goal if n.status == "resolved"]
                pattern_confidence = len(resolved) / len(non_goal)

        budget = self.config.exploration_budget_per_project - self._exploration_attempts.get(project_id, 0)

        return PlanningContext(
            record=record,
            attempt_count=total_attempts,
            historical_success_rate=success_rate,
            complexity_score=complexity,
            pattern_confidence=pattern_confidence,
            exploration_budget=budget,
            current_path=current_path,
        )

    def _compute_complexity(self, record) -> float:
        """计算挑战复杂度"""
        challenge = record.snapshot.challenge
        text = f"{challenge.name} {challenge.description} {challenge.category}"
        tokens = set(text.lower().split())
        if not tokens:
            return 0.5
        return min(1.0, len(tokens) / 20.0)

    def _record_path_selection(self, record, path_type: PathType, context: PlanningContext) -> None:
        """记录路径选择事件"""
        if record.run_journal is not None:
            from .platform_models import Event
            event = Event(
                type=EventType.PATH_SELECTION,
                project_id=record.snapshot.project_id,
                run_id="path-selection",
                payload={
                    "path_type": path_type.value,
                    "attempt_count": context.attempt_count,
                    "complexity_score": context.complexity_score,
                    "pattern_confidence": context.pattern_confidence,
                    "exploration_budget": context.exploration_budget,
                },
                source="enhanced_apg",
            )
            record.run_journal.append(event)

    def _plan_structured(self, record, context: PlanningContext) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        """结构化路径规划"""
        return self.structured_planner.plan(record)

    def _plan_free_exploration(self, record, context: PlanningContext) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        """自由探索路径规划"""
        program = self.free_exploration_planner.generate_constrained_plan(context)
        hits: list[RetrievalHit] = []

        if program is not None and self.config.enable_semantic_retrieval:
            challenge = record.snapshot.challenge
            semantic_hits = self.semantic_retrieval.search(
                f"{challenge.name} {challenge.category}",
                limit=self.config.semantic_retrieval_limit,
            )
            for s_hit in semantic_hits[:3]:
                hits.append(RetrievalHit(
                    episode_id=s_hit.episode_id,
                    score=s_hit.hybrid_score,
                    summary=s_hit.summary,
                    pattern_families=s_hit.pattern_families,
                    stop_reason=s_hit.stop_reason,
                ))

        if program is not None and self.config.enable_pattern_discovery:
            patterns = self.pattern_composer.retrieve_patterns(
                {"primitives": [s.primitive for s in program.steps]}
            )
            for pattern in patterns[:2]:
                hits.append(RetrievalHit(
                    episode_id=f"pattern-{pattern.id}",
                    score=pattern.success_rate,
                    summary=pattern.description,
                    pattern_families=[pattern.name],
                    stop_reason="pattern",
                ))

        return program, hits

    def _plan_hybrid(self, record, context: PlanningContext) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        """混合路径规划：先尝试结构化，失败后自由探索"""
        program, hits = self._plan_structured(record, context)
        if program is not None:
            return program, hits

        return self._plan_free_exploration(record, context)