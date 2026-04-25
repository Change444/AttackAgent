from __future__ import annotations

from .apg import APGPlanner
from .controller import Controller
from .dispatcher import Dispatcher
from .platform_models import PatternNodeKind, ProjectStage
from .provider import CompetitionProvider
from .reasoning import HeuristicReasoner
from .runtime import WorkerRuntime
from .state_graph import StateGraphService
from .strategy import StrategyLayer


class CompetitionPlatform:
    def __init__(self, provider: CompetitionProvider, reasoner: HeuristicReasoner | None = None) -> None:
        self.provider = provider
        self.state_graph = StateGraphService()
        self.controller = Controller(provider, self.state_graph)
        self.runtime = WorkerRuntime()
        self.strategy = StrategyLayer(APGPlanner(self.state_graph.episode_memory, reasoner=reasoner))
        self.dispatcher = Dispatcher(self.state_graph, self.runtime, self.strategy)

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
