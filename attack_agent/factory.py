"""Factory function for building TeamRuntime with all executor components.

Extracted from CompetitionPlatform.__init__ wiring logic.
"""

from __future__ import annotations

from .apg import APGPlanner
from .config import AttackAgentConfig, BrowserConfig, HttpConfig, SecurityConfig
from .constraint_aware_reasoner import ConstraintAwareReasoner, ConstraintContextBuilder
from .constraints import LightweightSecurityShell
from .controller import Controller
from .dynamic_pattern_composer import DynamicPatternComposer
from .embedding_adapter import build_embedding_from_config
from .enhanced_apg import EnhancedAPGPlanner
from .heuristic_free_exploration import HeuristicFreeExplorationPlanner
from .observation_summarizer import ObservationSummarizer, ObservationSummarizerConfig
from .pattern_injector import PatternInjector
from .platform_models import DualPathConfig
from .provider import CompetitionProvider
from .reasoning import HeuristicReasoner, LLMReasoner, ReasoningModel
from .runtime import WorkerRuntime
from .semantic_retrieval import InMemoryVectorStore, SemanticRetrievalEngine
from .state_graph import StateGraphService
from .dispatcher import Dispatcher
from .team.runtime import TeamRuntime, TeamRuntimeConfig


def build_team_runtime(
    provider: CompetitionProvider,
    reasoner: HeuristicReasoner | None = None,
    model: ReasoningModel | None = None,
    config: DualPathConfig | None = None,
    agent_config: AttackAgentConfig | None = None,
) -> TeamRuntime:
    """Build a TeamRuntime with real executor components.

    Reproduces CompetitionPlatform.__init__ wiring logic, returning a
    TeamRuntime instead of CompetitionPlatform.
    """
    state_graph = StateGraphService()
    controller = Controller(provider, state_graph)
    runtime = WorkerRuntime(
        browser_config=agent_config.browser if agent_config is not None else BrowserConfig(),
        http_config=agent_config.http if agent_config is not None else HttpConfig(),
    )

    # Extract strategy thresholds from AttackAgentConfig
    if agent_config is not None:
        stag_thr = agent_config.platform.stagnation_threshold
        conf_thr = agent_config.platform.flag_confidence_threshold
    else:
        stag_thr = 8
        conf_thr = 0.6

    # Build security config, dual config, summarizer, semantic retrieval
    if agent_config is not None:
        security_config = agent_config.security
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
        security_config = SecurityConfig()
        dual_config = config or DualPathConfig()
        summarizer = ObservationSummarizer()
        semantic = SemanticRetrievalEngine()

    # Share summarizer to StateGraphService
    state_graph.observation_summarizer = summarizer

    # Build EnhancedAPGPlanner (dual-path)
    if model is not None:
        llm_reasoner = LLMReasoner(model)
        shell = LightweightSecurityShell(security_config)
        builder = ConstraintContextBuilder(security_config)
        constraint_reasoner = ConstraintAwareReasoner(model, builder, shell, summarizer=summarizer)
        structured = APGPlanner(state_graph.episode_memory, reasoner=llm_reasoner, summarizer=summarizer)
        injector = PatternInjector(structured.pattern_library)
        composer = DynamicPatternComposer(injector=injector)
        enhanced = EnhancedAPGPlanner(
            structured_planner=structured,
            free_exploration_planner=constraint_reasoner,
            semantic_retrieval=semantic,
            pattern_composer=composer,
            config=dual_config,
        )
    else:
        heuristic = reasoner or HeuristicReasoner()
        shell = LightweightSecurityShell(security_config)
        builder = ConstraintContextBuilder(security_config)
        structured = APGPlanner(state_graph.episode_memory, reasoner=heuristic, summarizer=summarizer)
        injector = PatternInjector(structured.pattern_library)
        composer = DynamicPatternComposer(injector=injector)
        heuristic_free_planner = HeuristicFreeExplorationPlanner(
            context_builder=builder,
            validator=shell,
            pattern_composer=composer,
            episode_memory=state_graph.episode_memory,
            summarizer=summarizer,
        )
        enhanced = EnhancedAPGPlanner(
            structured_planner=structured,
            free_exploration_planner=heuristic_free_planner,
            semantic_retrieval=semantic,
            pattern_composer=heuristic_free_planner.pattern_composer,
            config=dual_config,
        )

    dispatcher = Dispatcher(
        state_graph, runtime, enhanced,
        security_config=security_config,
        stagnation_threshold=stag_thr,
        confidence_threshold=conf_thr,
    )

    # Build TeamRuntimeConfig from agent_config
    if agent_config is not None:
        bb_path = "data/blackboard.db"
        rt_config = TeamRuntimeConfig(
            blackboard_db_path=bb_path,
            max_project_solvers=1,
            max_cycles=agent_config.platform.max_cycles,
            stagnation_threshold=stag_thr,
            confidence_threshold=conf_thr,
            use_real_executor=True,
        )
    else:
        rt_config = TeamRuntimeConfig(
            stagnation_threshold=stag_thr,
            confidence_threshold=conf_thr,
            use_real_executor=True,
        )

    team_runtime = TeamRuntime(
        config=rt_config,
        worker_runtime=runtime,
        dispatcher=dispatcher,
        state_graph=state_graph,
        enhanced_planner=enhanced,
    )
    team_runtime._controller = controller
    team_runtime._provider = provider

    return team_runtime