"""Team Runtime vNext protocol — minimal subset for Phase A.

Defines core dataclass types and legacy → vNext mapping functions.
All types support serialization (to_dict / from_dict) for future SQLite use.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

__all__ = [
    "ActionType",
    "SolverStatus",
    "MemoryKind",
    "IdeaStatus",
    "PolicyOutcome",
    "ReviewStatus",
    "HumanDecisionChoice",
    "TeamProject",
    "StrategyAction",
    "SolverSession",
    "MemoryEntry",
    "IdeaEntry",
    "FailureBoundary",
    "PolicyDecision",
    "ReviewRequest",
    "HumanDecision",
    "legacy_project_to_team_project",
    "legacy_bundle_to_solver_session",
    "legacy_submit_decision_to_policy",
    "legacy_episode_to_memory_entry",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    LAUNCH_SOLVER = "launch_solver"
    STOP_SOLVER = "stop_solver"
    STEER_SOLVER = "steer_solver"
    SUBMIT_FLAG = "submit_flag"
    CONVERGE = "converge"
    ABANDON = "abandon"
    USE_PRIMITIVE = "use_primitive"


class SolverStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class MemoryKind(str, Enum):
    FACT = "fact"
    CREDENTIAL = "credential"
    ENDPOINT = "endpoint"
    FAILURE_BOUNDARY = "failure_boundary"
    HINT = "hint"
    SESSION_STATE = "session_state"


class IdeaStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    TESTING = "testing"
    VERIFIED = "verified"
    FAILED = "failed"
    shelved = "shelved"


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEEDS_REVIEW = "needs_review"
    NEEDS_HUMAN = "needs_human"
    REDACT = "redact"
    RATE_LIMIT = "rate_limit"
    BUDGET_EXCEEDED = "budget_exceeded"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    EXPIRED = "expired"


class HumanDecisionChoice(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


def _to_dict(obj: Any) -> dict[str, Any]:
    """Serialize a dataclass to a plain dict. Enums are stored as their value."""
    result: dict[str, Any] = {}
    for f in obj.__dataclass_fields__:
        val = getattr(obj, f)
        if isinstance(val, Enum):
            result[f] = val.value
        elif isinstance(val, list):
            result[f] = [_to_dict_item(v) for v in val]
        elif hasattr(val, "__dataclass_fields__"):
            result[f] = _to_dict(val)
        else:
            result[f] = val
    return result


def _to_dict_item(v: Any) -> Any:
    if isinstance(v, Enum):
        return v.value
    if hasattr(v, "__dataclass_fields__"):
        return _to_dict(v)
    return v


def _from_dict(cls: type, d: dict[str, Any]) -> Any:
    """Deserialize a dict back to a dataclass, resolving enums by value."""
    kwargs: dict[str, Any] = {}
    field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}
    for key, val in d.items():
        ft = field_types.get(key)
        if ft is None:
            continue
        # Resolve enums
        if isinstance(ft, str) and ft in globals() and isinstance(globals()[ft], type) and issubclass(globals()[ft], Enum):
            enum_cls = globals()[ft]
            if isinstance(val, str):
                kwargs[key] = enum_cls(val)
            else:
                kwargs[key] = val
        else:
            kwargs[key] = val
    return cls(**kwargs)


# ---------------------------------------------------------------------------
# Protocol dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TeamProject:
    project_id: str = field(default_factory=_gen_id)
    challenge_id: str = ""
    status: str = "new"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)


@dataclass
class StrategyAction:
    action_type: ActionType = ActionType.LAUNCH_SOLVER
    project_id: str = ""
    target_solver_id: str = ""
    target_idea_id: str = ""
    priority: int = 100
    risk_level: str = "low"
    budget_request: float = 0.0
    reason: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    requires_review: bool = False
    policy_tags: list[str] = field(default_factory=list)


@dataclass
class SolverSession:
    solver_id: str = field(default_factory=_gen_id)
    project_id: str = ""
    profile: str = "network"
    status: SolverStatus = SolverStatus.CREATED
    active_idea_id: str = ""
    local_memory_ids: list[str] = field(default_factory=list)
    budget_remaining: float = 0.0
    scratchpad_summary: str = ""
    recent_event_ids: list[str] = field(default_factory=list)


@dataclass
class MemoryEntry:
    entry_id: str = field(default_factory=_gen_id)
    project_id: str = ""
    kind: MemoryKind = MemoryKind.FACT
    content: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: str = field(default_factory=_utc_now)


@dataclass
class IdeaEntry:
    idea_id: str = field(default_factory=_gen_id)
    project_id: str = ""
    description: str = ""
    status: IdeaStatus = IdeaStatus.PENDING
    solver_id: str = ""
    priority: int = 100
    failure_boundary_refs: list[str] = field(default_factory=list)


@dataclass
class FailureBoundary:
    boundary_id: str = field(default_factory=_gen_id)
    project_id: str = ""
    description: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)


@dataclass
class PolicyDecision:
    decision: PolicyOutcome = PolicyOutcome.ALLOW
    action_type: str = ""
    risk_level: str = "low"
    reason: str = ""
    constraints: list[str] = field(default_factory=list)


@dataclass
class ReviewRequest:
    request_id: str = field(default_factory=_gen_id)
    project_id: str = ""
    requested_by: str = ""
    action_type: str = ""
    risk_level: str = "low"
    title: str = ""
    description: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    proposed_action: str = ""
    proposed_action_payload: dict[str, Any] = field(default_factory=dict)
    alternatives: list[str] = field(default_factory=list)
    timeout_policy: str = "auto_reject"
    status: ReviewStatus = ReviewStatus.PENDING
    decision: str = ""
    decided_by: str = ""
    decided_at: str = ""


@dataclass
class HumanDecision:
    request_id: str = ""
    decision: HumanDecisionChoice = HumanDecisionChoice.APPROVED
    modified_params: dict[str, Any] = field(default_factory=dict)
    decided_by: str = ""
    decided_at: str = field(default_factory=_utc_now)
    reason: str = ""


# ---------------------------------------------------------------------------
# Serialization entry points
# ---------------------------------------------------------------------------

def to_dict(obj: Any) -> dict[str, Any]:
    """Public serialization: dataclass → dict."""
    return _to_dict(obj)


def from_dict(cls: type, d: dict[str, Any]) -> Any:
    """Public deserialization: dict → dataclass."""
    return _from_dict(cls, d)


# ---------------------------------------------------------------------------
# Legacy → vNext mapping functions
# ---------------------------------------------------------------------------

def legacy_project_to_team_project(record) -> TeamProject:
    """Map ProjectRecord → TeamProject.

    Uses ProjectRecord.snapshot.project_id and
    ProjectRecord.snapshot.challenge.id.
    """
    snap = record.snapshot
    return TeamProject(
        project_id=snap.project_id,
        challenge_id=snap.challenge.id,
        status=snap.status,
    )


def legacy_bundle_to_solver_session(bundle, session_id: str) -> SolverSession:
    """Map TaskBundle → SolverSession.

    Uses bundle.worker_profile, bundle.project_id, bundle.stage.
    """
    return SolverSession(
        solver_id=session_id,
        project_id=bundle.project_id,
        profile=bundle.worker_profile.value,
        status=SolverStatus.ASSIGNED,
    )


def legacy_submit_decision_to_policy(decision) -> PolicyDecision:
    """Map SubmitDecision → PolicyDecision.

    accepted=True → ALLOW; accepted=False → DENY.
    """
    return PolicyDecision(
        decision=PolicyOutcome.ALLOW if decision.accepted else PolicyOutcome.DENY,
        action_type="submit_flag",
        reason=decision.reason,
    )


def legacy_episode_to_memory_entry(entry) -> MemoryEntry:
    """Map EpisodeEntry → MemoryEntry.

    success=True → FACT; success=False → FAILURE_BOUNDARY.
    content is the summary field.
    """
    kind = MemoryKind.FACT if entry.success else MemoryKind.FAILURE_BOUNDARY
    return MemoryEntry(
        entry_id=entry.id,
        kind=kind,
        content=entry.summary,
        confidence=1.0 if entry.success else 0.0,
    )