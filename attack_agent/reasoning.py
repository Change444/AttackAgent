from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .platform_models import PrimitiveActionStep, ProjectSnapshot, WorkerProfile


@dataclass(slots=True)
class PlanCandidate:
    family: str
    node_id: str
    node_kind: str
    steps: list[PrimitiveActionStep]
    score: float
    secondary_families: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReasoningContext:
    challenge_id: str
    challenge_name: str
    category: str
    description: str
    signals: list[str]
    observation_kinds: list[str] = field(default_factory=list)
    observation_summaries: list[str] = field(default_factory=list)
    hypothesis_statements: list[str] = field(default_factory=list)
    artifact_kinds: list[str] = field(default_factory=list)
    memory_summaries: list[str] = field(default_factory=list)
    family_scores: dict[str, float] = field(default_factory=dict)
    candidates: list[PlanCandidate] = field(default_factory=list)


@dataclass(slots=True)
class ProgramDecision:
    family: str
    node_id: str
    steps: list[PrimitiveActionStep]
    rationale: str
    source: str
    secondary_families: list[str] = field(default_factory=list)


class ReasoningModel(Protocol):
    def complete_json(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class HeuristicReasoner:
    def choose_profile(self, project: ProjectSnapshot) -> tuple[WorkerProfile, str]:
        text = " ".join([project.challenge.category, project.challenge.description, " ".join(project.challenge.metadata.get("signals", []))]).lower()
        if any(token in text for token in ("browser", "dom", "render", "script", "comment")) or project.challenge.metadata.get("requires_browser", False):
            return WorkerProfile.BROWSER, "browser clues detected"
        if any(token in text for token in ("archive", "file", "pcap", "stego")):
            return WorkerProfile.ARTIFACT, "artifact clues detected"
        if any(token in text for token in ("binary", "reverse", "elf", "symbol")):
            return WorkerProfile.BINARY, "binary clues detected"
        if any(token in text for token in ("decode", "cipher", "xor", "hash", "base64")):
            return WorkerProfile.SOLVER, "solver clues detected"
        return WorkerProfile.NETWORK, "default network profile"

    def choose_program(self, context: ReasoningContext) -> ProgramDecision | None:
        if not context.candidates:
            return None
        ordered = _order_candidates(context.candidates)
        selected = ordered[0]
        rationale = f"selected {selected.family} / {selected.node_kind} from heuristic family ranking"
        return ProgramDecision(
            family=selected.family,
            node_id=selected.node_id,
            steps=list(selected.steps),
            rationale=rationale,
            source="heuristic",
        )


class LLMReasoner(HeuristicReasoner):
    def __init__(self, model: ReasoningModel, fallback: HeuristicReasoner | None = None) -> None:
        self.model = model
        self.fallback = fallback or HeuristicReasoner()

    def choose_profile(self, project: ProjectSnapshot) -> tuple[WorkerProfile, str]:
        fallback_profile, fallback_reason = self.fallback.choose_profile(project)
        payload = {
            "challenge_id": project.challenge.id,
            "name": project.challenge.name,
            "category": project.challenge.category,
            "description": project.challenge.description,
            "signals": list(project.challenge.metadata.get("signals", [])),
            "allowed_profiles": [profile.value for profile in WorkerProfile],
            "fallback_profile": fallback_profile.value,
        }
        response = self.model.complete_json("select_worker_profile", payload)
        selected = str(response.get("profile", fallback_profile.value))
        reason = str(response.get("reason", fallback_reason))
        try:
            return WorkerProfile(selected), reason
        except ValueError:
            return fallback_profile, fallback_reason

    def choose_program(self, context: ReasoningContext) -> ProgramDecision | None:
        fallback = self.fallback.choose_program(context)
        if fallback is None:
            return None
        ordered_candidates = _order_candidates(context.candidates)
        payload = {
            "challenge_id": context.challenge_id,
            "challenge_name": context.challenge_name,
            "category": context.category,
            "description": context.description,
            "signals": context.signals,
            "observation_kinds": context.observation_kinds,
            "observation_summaries": context.observation_summaries,
            "hypothesis_statements": context.hypothesis_statements,
            "artifact_kinds": context.artifact_kinds,
            "memory_summaries": context.memory_summaries,
            "family_scores": context.family_scores,
            "candidates": [
                {
                    "candidate_index": index,
                    "family": candidate.family,
                    "node_id": candidate.node_id,
                    "node_kind": candidate.node_kind,
                    "step_primitives": [step.primitive for step in candidate.steps],
                    "instructions": [step.instruction for step in candidate.steps],
                    "step_parameters": [step.parameters for step in candidate.steps],
                    "score": candidate.score,
                }
                for index, candidate in enumerate(ordered_candidates)
            ],
            "fallback": {
                "family": fallback.family,
                "node_id": fallback.node_id,
                "step_primitives": [step.primitive for step in fallback.steps],
                "rationale": fallback.rationale,
            },
        }
        response = self.model.complete_json("choose_program", payload)
        selected = self._validate_program_response(context, response)
        return selected or fallback

    def _validate_program_response(self, context: ReasoningContext, response: dict[str, Any]) -> ProgramDecision | None:
        rationale = str(response.get("rationale", "") or "selected by llm")
        requested_steps = response.get("step_primitives", [])
        candidate: PlanCandidate | None = None
        ordered_candidates = _order_candidates(context.candidates)
        candidate_index = response.get("candidate_index")
        if isinstance(candidate_index, int) and 0 <= candidate_index < len(ordered_candidates):
            candidate = ordered_candidates[candidate_index]
        else:
            family = str(response.get("family", ""))
            node_id = str(response.get("node_id", ""))
            for existing in ordered_candidates:
                if existing.family == family and existing.node_id == node_id:
                    candidate = existing
                    break
        if candidate is None:
            return None
        if not isinstance(requested_steps, list) or not requested_steps:
            steps = list(candidate.steps)
        else:
            allowed = {step.primitive: step for step in candidate.steps}
            if any(not isinstance(name, str) or name not in allowed for name in requested_steps):
                return None
            steps = []
            for name in requested_steps:
                step = allowed[name]
                if step not in steps:
                    steps.append(step)
        return ProgramDecision(
            family=candidate.family,
            node_id=candidate.node_id,
            steps=steps,
            rationale=rationale,
            source="llm",
            secondary_families=candidate.secondary_families,
        )
        return None


class StaticReasoningModel:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses

    def complete_json(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(self.responses.get(task, {}))


def _order_candidates(candidates: list[PlanCandidate]) -> list[PlanCandidate]:
    return sorted(candidates, key=lambda candidate: (-candidate.score, -len(candidate.steps), candidate.node_id))
