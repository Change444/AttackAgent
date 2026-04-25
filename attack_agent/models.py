from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentStage(str, Enum):
    RECON = "stage_1_recon"
    MAPPING = "stage_2_mapping"
    CHAINING = "stage_3_chaining"
    CONVERGENCE = "stage_4_convergence"


class ToolCategory(str, Enum):
    RECON = "recon"
    ANALYSIS = "analysis"
    EXECUTION = "execution"
    VALIDATION = "validation"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class Verdict(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(slots=True)
class Evidence:
    id: str
    description: str
    source: str
    confidence: float
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class BaseEntity:
    id: str
    source: str
    timestamp: datetime = field(default_factory=utc_now)
    confidence: float = 0.5
    evidence_ref: str | None = None
    ttl_seconds: int | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.ttl_seconds is None:
            return False
        now = now or utc_now()
        return now > self.timestamp + timedelta(seconds=self.ttl_seconds)


@dataclass(slots=True)
class Asset(BaseEntity):
    hostname: str = ""
    tags: tuple[str, ...] = ()


@dataclass(slots=True)
class Service(BaseEntity):
    asset_id: str = ""
    name: str = ""
    port: int = 0
    protocol: str = "tcp"


@dataclass(slots=True)
class Endpoint(BaseEntity):
    asset_id: str = ""
    service_id: str | None = None
    path: str = "/"
    method: str = "GET"


@dataclass(slots=True)
class Credential(BaseEntity):
    asset_id: str = ""
    username: str = ""
    secret_ref: str = ""
    privilege: str = "user"


@dataclass(slots=True)
class Session(BaseEntity):
    asset_id: str = ""
    credential_id: str = ""
    session_type: str = "http"
    valid: bool = True


@dataclass(slots=True)
class Finding(BaseEntity):
    asset_id: str = ""
    title: str = ""
    severity: str = "info"
    structured_details: dict[str, Any] = field(default_factory=dict)
    hypothesis_status: str = "observed"


@dataclass(slots=True)
class ActionRecord(BaseEntity):
    tool_name: str = ""
    category: ToolCategory = ToolCategory.RECON
    target: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    error_type: str | None = None
    cost: float = 0.0


@dataclass(slots=True)
class StageState(BaseEntity):
    stage: AgentStage = AgentStage.RECON
    unlocked_capabilities: tuple[str, ...] = ()
    notes: str = ""


@dataclass(slots=True)
class PlanStep:
    id: str
    goal: str
    action_type: ToolCategory
    expected_evidence: str
    preconditions: tuple[str, ...] = ()
    target: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    success_predicate: str = ""
    abort_predicate: str = ""
    status: PlanStepStatus = PlanStepStatus.PENDING


@dataclass(slots=True)
class ToolResult:
    status: str
    structured_output: dict[str, Any]
    artifacts: list[str] = field(default_factory=list)
    confidence: float = 0.5
    cost: float = 0.0
    error_type: str | None = None
    retriable: bool = False
    next_hints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DecisionContext:
    current_stage: AgentStage
    candidate_targets: list[str]
    budget: dict[str, Any]
    recent_failures: list[ActionRecord]
    unlocked_capabilities: tuple[str, ...]


@dataclass(slots=True)
class CandidateAction:
    step_id: str
    tool_name: str
    category: ToolCategory
    target: str
    score: float
    rationale: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VerificationResult:
    verdict: Verdict
    reason: str
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AuditEntry:
    id: str
    observation: str
    hypothesis: str
    next_action: str
    evidence: list[str]
    compiler_notes: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"
