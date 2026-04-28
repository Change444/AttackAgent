from __future__ import annotations

from .apg import APGPlanner
from .config import AttackAgentConfig
from .constraint_aware_reasoner import ConstraintAwareReasoner, ConstraintContextBuilder
from .constraints import LightweightSecurityShell, SecurityConstraints
from .controller import Controller
from .dispatcher import Dispatcher
from .dynamic_pattern_composer import DynamicPatternComposer
from .enhanced_apg import EnhancedAPGPlanner
from .heuristic_free_exploration import HeuristicFreeExplorationPlanner
from .observation_summarizer import ObservationSummarizer, ObservationSummarizerConfig
from .pattern_injector import PatternInjector
from .platform_models import DualPathConfig, PatternNodeKind, ProjectStage
from .provider import CompetitionProvider
from .reasoning import HeuristicReasoner, LLMReasoner, ReasoningModel
from .embedding_adapter import build_embedding_from_config
from .semantic_retrieval import SemanticRetrievalEngine, InMemoryVectorStore
from .runtime import WorkerRuntime
from .state_graph import StateGraphService
from .strategy import StrategyLayer


class CompetitionPlatform:
    def __init__(self, provider: CompetitionProvider,
                 reasoner: HeuristicReasoner | None = None,
                 model: ReasoningModel | None = None,
                 config: DualPathConfig | None = None,
                 agent_config: AttackAgentConfig | None = None) -> None:
        self.provider = provider
        self.state_graph = StateGraphService()
        self.controller = Controller(provider, self.state_graph)
        self.runtime = WorkerRuntime()

        # 从 AttackAgentConfig.security 构建 SecurityConstraints（单一真实源）
        if agent_config is not None:
            security_constraints = SecurityConstraints.from_config(agent_config.security)
            dual_config = config or agent_config.dual_path
            budget_chars = agent_config.model.observation_summary_budget_chars
            summarizer = ObservationSummarizer(ObservationSummarizerConfig(max_total_chars=budget_chars))
            embedding_model = build_embedding_from_config(
                agent_config.model, agent_config.semantic_retrieval.embedding_model
            )
            sem_config = agent_config.semantic_retrieval
            semantic = SemanticRetrievalEngine(
                vector_store=InMemoryVectorStore(),
                hybrid_alpha=sem_config.hybrid_alpha,
                embedding_model=embedding_model,
            )
        else:
            security_constraints = SecurityConstraints()
            dual_config = config or DualPathConfig()
            summarizer = ObservationSummarizer()
            semantic = SemanticRetrievalEngine()

        # Share summarizer to StateGraphService
        self.state_graph.observation_summarizer = summarizer

        if model is not None:
            llm_reasoner = LLMReasoner(model)
            shell = LightweightSecurityShell(security_constraints)
            builder = ConstraintContextBuilder(security_constraints)
            constraint_reasoner = ConstraintAwareReasoner(model, builder, shell, summarizer=summarizer)
            structured = APGPlanner(self.state_graph.episode_memory, reasoner=llm_reasoner, summarizer=summarizer)
            injector = PatternInjector(structured.pattern_library)
            composer = DynamicPatternComposer(injector=injector)
            enhanced = EnhancedAPGPlanner(
                structured_planner=structured,
                free_exploration_planner=constraint_reasoner,
                semantic_retrieval=semantic,
                pattern_composer=composer,
                config=dual_config,
            )
            self.strategy = StrategyLayer(enhanced)
        else:
            heuristic = reasoner or HeuristicReasoner()
            shell = LightweightSecurityShell(security_constraints)
            builder = ConstraintContextBuilder(security_constraints)
            structured = APGPlanner(self.state_graph.episode_memory, reasoner=heuristic, summarizer=summarizer)
            injector = PatternInjector(structured.pattern_library)
            composer = DynamicPatternComposer(injector=injector)
            heuristic_free_planner = HeuristicFreeExplorationPlanner(
                context_builder=builder,
                validator=shell,
                pattern_composer=composer,
                episode_memory=self.state_graph.episode_memory,
                summarizer=summarizer,
            )
            enhanced = EnhancedAPGPlanner(
                structured_planner=structured,
                free_exploration_planner=heuristic_free_planner,
                semantic_retrieval=semantic,
                pattern_composer=heuristic_free_planner.pattern_composer,
                config=dual_config,
            )
            self.strategy = StrategyLayer(enhanced)

        self.dispatcher = Dispatcher(
            self.state_graph, self.runtime, self.strategy,
            security_constraints=security_constraints,
        )

    def bootstrap(self) -> list[str]:
        project_ids = self.controller.sync_challenges()
        for project_id in project_ids:
            self.controller.ensure_instance(project_id)
        return project_ids

    def run_cycle(self, project_id: str) -> None:
        record = self.state_graph.projects[project_id]
        if record.snapshot.stage.value in {"done", "abandoned"}:
            return
        self.dispatcher.schedule(project_id)
        record = self.state_graph.projects[project_id]
        if record.snapshot.stage.value == "converge":
            accepted = False
            existing_keys = set()
            for dedupe_key, candidate in list(record.candidate_flags.items()):
                decision = self.strategy.submit_classifier.classify(record.snapshot, candidate, existing_keys)
                if not decision.accepted:
                    continue
                self.controller.submit_candidate(project_id, dedupe_key)
                existing_keys.add(dedupe_key)
                accepted = True
                break
            if record.snapshot.stage.value != "done":
                if self.controller.maybe_request_hint(project_id):
                    self.dispatcher.requeue(project_id, "hint")
                elif not accepted:
                    has_more_patterns = record.pattern_graph is not None and any(
                        node.kind != PatternNodeKind.GOAL and node.status in {"pending", "active"} for node in record.pattern_graph.nodes.values()
                    )
                    record.snapshot.stage = ProjectStage.EXPLORE if has_more_patterns else ProjectStage.ABANDONED

    def solve_all(self, max_cycles: int = 12) -> None:
        project_ids = self.bootstrap()
        for _ in range(max_cycles):
            pending = 0
            for project_id in project_ids:
                stage = self.state_graph.projects[project_id].snapshot.stage.value
                if stage not in {"done", "abandoned"}:
                    pending += 1
                    self.run_cycle(project_id)
            if pending == 0:
                break