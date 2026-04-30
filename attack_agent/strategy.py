from __future__ import annotations

import re
from dataclasses import dataclass

from .platform_models import ActionProgram, CandidateFlag, ProjectSnapshot, ProjectStage, TaskBundle, WorkerProfile


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