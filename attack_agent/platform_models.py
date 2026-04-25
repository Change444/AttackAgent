from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import utc_now


class ProjectStage(str, Enum):
    BOOTSTRAP = "bootstrap"
    REASON = "reason"
    EXPLORE = "explore"
    CONVERGE = "converge"
    DONE = "done"
    ABANDONED = "abandoned"


class WorkerProfile(str, Enum):
    NETWORK = "network"
    BROWSER = "browser"
    ARTIFACT = "artifact"
    BINARY = "binary"
    SOLVER = "solver"
    HYBRID = "hybrid"


class EventType(str, Enum):
    PROJECT_UPSERTED = "project_upserted"
    INSTANCE_STARTED = "instance_started"
    OBSERVATION = "observation"
    ARTIFACT_ADDED = "artifact_added"
    HYPOTHESIS_ADDED = "hypothesis_added"
    CANDIDATE_FLAG = "candidate_flag"
    PROGRAM_COMPILED = "program_compiled"
    ACTION_OUTCOME = "action_outcome"
    SUBMISSION = "submission"
    HINT = "hint"
    WORKER_ASSIGNED = "worker_assigned"
    WORKER_HEARTBEAT = "worker_heartbeat"
    WORKER_TIMEOUT = "worker_timeout"
    REQUEUE = "requeue"
    CHECKPOINT = "checkpoint"
    MEMORY_STORED = "memory_stored"
    PROJECT_DONE = "project_done"
    PROJECT_ABANDONED = "project_abandoned"


class PatternNodeKind(str, Enum):
    GOAL = "goal"
    HYPOTHESIS = "hypothesis"
    OBSERVATION_GATE = "observation_gate"
    ACTION_TEMPLATE = "action_template"
    VERIFICATION_GATE = "verification_gate"
    FALLBACK = "fallback"


@dataclass(slots=True)
class ChallengeDefinition:
    id: str
    name: str
    category: str
    difficulty: str
    target: str
    description: str = ""
    flag_pattern: str = r"flag\{[^}]+\}"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChallengeInstance:
    instance_id: str
    challenge_id: str
    target: str
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SubmissionResult:
    accepted: bool
    message: str
    status: str


@dataclass(slots=True)
class HintResult:
    hint: str
    remaining: int


@dataclass(slots=True)
class CandidateFlag:
    value: str
    source_chain: list[str]
    confidence: float
    format_match: bool
    dedupe_key: str
    evidence_refs: list[str] = field(default_factory=list)
    submitted: bool = False


@dataclass(slots=True)
class Observation:
    id: str
    kind: str
    source: str
    target: str
    payload: dict[str, Any]
    confidence: float
    novelty: float


@dataclass(slots=True)
class Artifact:
    id: str
    kind: str
    location: str
    fingerprint: str
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Hypothesis:
    id: str
    statement: str
    preconditions: list[str]
    supporting_observations: list[str]
    confidence: float


@dataclass(slots=True)
class PrimitiveActionSpec:
    name: str
    capability: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    cost: float
    risk: str


@dataclass(slots=True)
class PrimitiveActionStep:
    primitive: str
    instruction: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PatternNode:
    id: str
    family: str
    kind: PatternNodeKind
    label: str
    keywords: tuple[str, ...] = ()
    capability_hints: tuple[str, ...] = ()
    status: str = "pending"


@dataclass(slots=True)
class PatternEdge:
    source: str
    target: str
    condition: str


@dataclass(slots=True)
class PatternGraph:
    graph_id: str
    nodes: dict[str, PatternNode]
    edges: list[PatternEdge]
    family_priority: list[str]
    active_family: str | None = None


@dataclass(slots=True)
class RetrievalHit:
    episode_id: str
    score: float
    summary: str
    pattern_families: list[str]
    stop_reason: str


@dataclass(slots=True)
class EpisodeEntry:
    id: str
    feature_text: str
    pattern_families: list[str]
    summary: str
    success: bool
    stop_reason: str = ""
    candidate_keys: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ActionProgram:
    id: str
    goal: str
    pattern_nodes: list[str]
    steps: list[PrimitiveActionStep]
    allowed_primitives: list[str]
    verification_rules: list[str]
    required_profile: WorkerProfile
    memory_refs: list[str] = field(default_factory=list)
    rationale: str = ""
    planner_source: str = "heuristic"


@dataclass(slots=True)
class ActionOutcome:
    status: str
    observations: list[Observation] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    derived_hypotheses: list[Hypothesis] = field(default_factory=list)
    candidate_flags: list[CandidateFlag] = field(default_factory=list)
    cost: float = 0.0
    failure_reason: str | None = None
    novelty: float = 0.0


@dataclass(slots=True)
class Event:
    type: EventType
    project_id: str
    run_id: str
    payload: dict[str, Any]
    cost: float = 0.0
    source: str = "system"
    timestamp: Any = field(default_factory=utc_now)


@dataclass(slots=True)
class ProjectSnapshot:
    project_id: str
    challenge: ChallengeDefinition
    priority: int = 100
    stage: ProjectStage = ProjectStage.BOOTSTRAP
    status: str = "new"
    worker_profile: WorkerProfile = WorkerProfile.NETWORK
    instance: ChallengeInstance | None = None


@dataclass(slots=True)
class TaskBundle:
    project_id: str
    run_id: str
    action_program: ActionProgram
    stage: ProjectStage
    worker_profile: WorkerProfile
    target: str
    challenge: ChallengeDefinition
    instance: ChallengeInstance
    handoff_summary: str
    visible_primitives: list[str]
    memory_hits: list[RetrievalHit] = field(default_factory=list)
    known_observation_ids: list[str] = field(default_factory=list)
    known_artifact_ids: list[str] = field(default_factory=list)
    known_hypothesis_ids: list[str] = field(default_factory=list)
    known_candidate_keys: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkerLease:
    worker_id: str
    profile: WorkerProfile
    project_id: str | None = None
    healthy: bool = True
    last_seen_at: Any = field(default_factory=utc_now)
