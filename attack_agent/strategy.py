from __future__ import annotations

import re
from dataclasses import dataclass

from .apg import APGPlanner
from .platform_models import ActionProgram, CandidateFlag, PatternNodeKind, ProjectSnapshot, ProjectStage, TaskBundle, WorkerProfile


@dataclass(slots=True)
class SubmitDecision:
    accepted: bool
    reason: str


class TaskPromptCompiler:
    def compile_bundle(self, record, program: ActionProgram, profile: WorkerProfile, visible_primitives: list[str], memory_hits) -> TaskBundle:
        handoff = record.handoff.summary if record.handoff is not None else "fresh project"
        return TaskBundle(
            project_id=record.snapshot.project_id,
            run_id=f"run-{record.snapshot.project_id}-{program.id}",
            action_program=program,
            stage=record.snapshot.stage,
            worker_profile=profile,
            target=record.snapshot.instance.target if record.snapshot.instance is not None else record.snapshot.challenge.target,
            challenge=record.snapshot.challenge,
            instance=record.snapshot.instance,
            handoff_summary=handoff,
            visible_primitives=visible_primitives,
            memory_hits=memory_hits,
            known_observation_ids=list(record.observations.keys()),
            known_artifact_ids=list(record.artifacts.keys()),
            known_hypothesis_ids=list(record.hypotheses.keys()),
            known_candidate_keys=list(record.candidate_flags.keys()),
        )


class StateCompressor:
    def compress(self, record) -> str:
        handoff = record.handoff.summary if record.handoff else "no handoff"
        return f"{handoff}; observations={len(record.observations)}; artifacts={len(record.artifacts)}; flags={len(record.candidate_flags)}"


class RetryComposer:
    def compose(self, record) -> str:
        if record.handoff is None:
            return "no retry context"
        dead_ends = ",".join(record.handoff.dead_ends) if record.handoff.dead_ends else "none"
        return f"retry from {record.handoff.summary}; dead_ends={dead_ends}; stagnation={record.stagnation_counter}"


class SubmitClassifier:
    def __init__(self, confidence_threshold: float = 0.6) -> None:
        self.confidence_threshold = confidence_threshold

    def classify(self, project: ProjectSnapshot, candidate: CandidateFlag, existing_keys: set[str]) -> SubmitDecision:
        if candidate.dedupe_key in existing_keys and candidate.submitted:
            return SubmitDecision(False, "duplicate candidate")
        if candidate.confidence < self.confidence_threshold:
            return SubmitDecision(False, "confidence too low")
        if not candidate.format_match:
            return SubmitDecision(False, "flag format mismatch")
        if not re.fullmatch(project.challenge.flag_pattern, candidate.value):
            return SubmitDecision(False, "pattern validation failed")
        return SubmitDecision(True, "candidate accepted for submit queue")


class StrategyLayer:
    def __init__(self, planner, stagnation_threshold: int = 8, confidence_threshold: float = 0.6) -> None:
        self.planner = planner
        self.stagnation_threshold = stagnation_threshold
        self.task_compiler = TaskPromptCompiler()
        self.compressor = StateCompressor()
        self.retry_composer = RetryComposer()
        self.submit_classifier = SubmitClassifier(confidence_threshold)

    def select_profile(self, project: ProjectSnapshot) -> WorkerProfile:
        profile, _reason = self.planner.reasoner.choose_profile(project)
        return profile

    def initialize_graph(self, record) -> None:
        record.pattern_graph = self.planner.create_graph(record.snapshot)
        record.snapshot.stage = ProjectStage.EXPLORE

    def next_program(self, record) -> tuple[ActionProgram | None, list]:
        return self.planner.plan(record)

    def update_after_outcome(self, record, program: ActionProgram, outcome) -> None:
        self.planner.update_graph(record, program, outcome)
        if outcome.status == "ok" and outcome.novelty > 0.0:
            record.stagnation_counter = 0
            return
        record.stagnation_counter += 1

    def stage_after_program(self, record) -> ProjectStage:
        if record.candidate_flags:
            return ProjectStage.CONVERGE
        if record.pattern_graph is None:
            return ProjectStage.CONVERGE
        unfinished = [node for node in record.pattern_graph.nodes.values() if node.kind != PatternNodeKind.GOAL and node.status in {"pending", "active"}]
        return ProjectStage.EXPLORE if unfinished else ProjectStage.CONVERGE

    def should_abandon(self, record) -> bool:
        recent_failures = record.world_state.recent_failures(limit=4)
        if record.stagnation_counter < self.stagnation_threshold:
            return False
        repeated_dead_ends = len(record.tombstones) >= 2
        low_novelty = all(failure.status == "failed" for failure in recent_failures) if recent_failures else True
        return repeated_dead_ends or low_novelty
