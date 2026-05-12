"""Phase J — ToolBroker: unified policy gate + event journal for primitive execution.

Every tool request must pass PolicyHarness before execution.
I/O-free primitives (structured-parse, diff-compare, code-sandbox, extract-candidate)
are executed with minimal stub context.
I/O-dependent primitives return requires_io_context until Phase J-2.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..platform_models import (
    ActionOutcome,
    PrimitiveActionStep,
    PrimitiveActionSpec,
    EventType,
    WorkerProfile,
    TaskBundle,
)
from ..runtime import PrimitiveRegistry, CodeSandbox
from .protocol import (
    ActionType,
    PolicyOutcome,
    StrategyAction,
    to_dict,
)
from .policy import PolicyHarness
from .blackboard import BlackboardService

# Primitives that can run without session_manager / browser_inspector / http_client
IO_FREE_PRIMITIVES = {"structured-parse", "diff-compare", "code-sandbox", "extract-candidate"}

# Primitives that need I/O context and cannot execute through broker yet
IO_DEPENDENT_PRIMITIVES = {"http-request", "browser-inspect", "session-materialize", "artifact-scan", "binary-inspect"}


@dataclass
class ToolRequest:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_id: str = ""
    solver_id: str = ""
    primitive_name: str = ""
    step: dict[str, Any] = field(default_factory=dict)
    bundle_ref: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    budget_request: float = 0.0
    reason: str = ""


@dataclass
class ToolResult:
    request_id: str = ""
    outcome: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "tool_broker"


@dataclass
class ToolError:
    request_id: str = ""
    error_type: str = ""
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ToolEvent:
    event_type: str = ""  # request_created / policy_checked / executing / completed / failed
    request_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ToolBroker:
    """Unified policy gate for primitive execution.

    Flow: ToolRequest → PolicyHarness.validate_action →
      - non-ALLOW → ToolError
      - ALLOW + IO-free → execute via PrimitiveAdapter → ToolResult
      - ALLOW + IO-dependent → ToolError(requires_io_context)
    Every step is recorded in Blackboard event journal.
    """

    def __init__(self, registry: PrimitiveRegistry, policy: PolicyHarness, blackboard: BlackboardService) -> None:
        self.registry = registry
        self.policy = policy
        self.blackboard = blackboard

    def request_tool(self, req: ToolRequest) -> ToolResult | ToolError:
        """Core method: policy gate → journal → execute (if allowed and IO-free)."""

        # (1) Record request_created event
        self.blackboard.append_event(
            project_id=req.project_id,
            event_type=EventType.TOOL_REQUEST.value,
            payload={
                "tool_event": "request_created",
                "request_id": req.request_id,
                "solver_id": req.solver_id,
                "primitive_name": req.primitive_name,
                "risk_level": req.risk_level,
                "budget_request": req.budget_request,
                "reason": req.reason,
            },
            source="tool_broker",
        )

        # (2) Check primitive existence
        adapter = self.registry.adapters.get(req.primitive_name)
        if adapter is None:
            error = ToolError(
                request_id=req.request_id,
                error_type="primitive_not_found",
                message=f"Primitive '{req.primitive_name}' not found in registry",
            )
            self._record_error(req, error)
            return error

        # (3) Build StrategyAction for policy validation
        action = StrategyAction(
            action_type=ActionType.USE_PRIMITIVE,
            project_id=req.project_id,
            target_solver_id=req.solver_id,
            risk_level=req.risk_level,
            budget_request=req.budget_request,
            reason=req.reason or f"execute primitive: {req.primitive_name}",
        )

        # (4) Policy gate
        decision = self.policy.validate_action(action, req.project_id, self.blackboard)

        # (5) Record policy_checked event
        self.blackboard.append_event(
            project_id=req.project_id,
            event_type=EventType.SECURITY_VALIDATION.value,
            payload={
                "tool_event": "policy_checked",
                "request_id": req.request_id,
                "decision": decision.decision.value,
                "risk_level": decision.risk_level,
                "reason": decision.reason,
                "primitive_name": req.primitive_name,
            },
            source="tool_broker",
        )

        # (6) Handle non-ALLOW outcomes
        if decision.decision == PolicyOutcome.DENY:
            return self._policy_error(req, "policy_deny", f"Policy denied: {decision.reason}")
        if decision.decision == PolicyOutcome.NEEDS_REVIEW:
            return self._policy_error(req, "needs_review", f"Requires human review: {decision.reason}")
        if decision.decision == PolicyOutcome.RATE_LIMIT:
            return self._policy_error(req, "rate_limit", f"Rate limit exceeded: {decision.reason}")
        if decision.decision == PolicyOutcome.BUDGET_EXCEEDED:
            return self._policy_error(req, "budget_exceeded", f"Budget exceeded: {decision.reason}")
        if decision.decision == PolicyOutcome.NEEDS_HUMAN:
            return self._policy_error(req, "needs_human", f"Requires human approval: {decision.reason}")
        if decision.decision == PolicyOutcome.REDACT:
            return self._policy_error(req, "redact", f"Action redacted: {decision.reason}")

        # (7) ALLOW — check I/O dependency
        if req.primitive_name in IO_DEPENDENT_PRIMITIVES:
            error = ToolError(
                request_id=req.request_id,
                error_type="requires_io_context",
                message=f"Primitive '{req.primitive_name}' requires I/O context (session_manager/browser_inspector/http_client). Not supported through broker yet.",
            )
            self._record_error(req, error)
            return error

        # (8) Execute IO-free primitive with minimal stub context
        try:
            step = PrimitiveActionStep(
                primitive=req.step.get("primitive", req.primitive_name),
                instruction=req.step.get("instruction", ""),
                parameters=req.step.get("parameters", {}),
            )
            bundle = self._build_stub_bundle(req)
            sandbox = CodeSandbox()

            outcome = adapter.execute(step, bundle, sandbox)

            result = ToolResult(
                request_id=req.request_id,
                outcome={
                    "status": outcome.status,
                    "observations_count": len(outcome.observations),
                    "candidate_flags_count": len(outcome.candidate_flags),
                    "cost": outcome.cost,
                    "failure_reason": outcome.failure_reason,
                },
                source="tool_broker",
            )

            # Record completed event + action outcome
            self.blackboard.append_event(
                project_id=req.project_id,
                event_type=EventType.ACTION_OUTCOME.value,
                payload={
                    "tool_event": "completed",
                    "request_id": req.request_id,
                    "primitive_name": req.primitive_name,
                    "status": outcome.status,
                    "observations_count": len(outcome.observations),
                    "candidate_flags_count": len(outcome.candidate_flags),
                    "cost": outcome.cost,
                    "broker_execution": True,
                },
                source="tool_broker",
            )
            return result

        except Exception as exc:
            error = ToolError(
                request_id=req.request_id,
                error_type="execution_failed",
                message=f"Primitive execution failed: {exc}",
            )
            self._record_error(req, error)
            return error

    def list_available_primitives(self, profile: WorkerProfile | str) -> list[str]:
        """List primitives visible to a given worker profile."""
        if isinstance(profile, str):
            try:
                profile = WorkerProfile(profile)
            except ValueError:
                return list(self.registry.adapters.keys())
        return self.registry.visible_primitives(profile)

    def get_primitive_spec(self, name: str) -> PrimitiveActionSpec | None:
        """Get the spec for a named primitive, or None if not found."""
        adapter = self.registry.adapters.get(name)
        return adapter.spec if adapter else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _policy_error(self, req: ToolRequest, error_type: str, message: str) -> ToolError:
        error = ToolError(request_id=req.request_id, error_type=error_type, message=message)
        self._record_error(req, error)
        return error

    def _record_error(self, req: ToolRequest, error: ToolError) -> None:
        self.blackboard.append_event(
            project_id=req.project_id,
            event_type=EventType.TOOL_REQUEST.value,
            payload={
                "tool_event": "failed",
                "request_id": req.request_id,
                "error_type": error.error_type,
                "message": error.message,
                "primitive_name": req.primitive_name,
            },
            source="tool_broker",
        )

    def _build_stub_bundle(self, req: ToolRequest) -> TaskBundle:
        """Build a minimal stub TaskBundle for IO-free primitive execution.

        Only contains fields needed by structured-parse / diff-compare / code-sandbox / extract-candidate.
        challenge/instance are placeholder stubs — broker execution is not a real solve path.
        """
        from ..platform_models import (
            ChallengeDefinition,
            ChallengeInstance,
            ActionProgram,
            ProjectStage,
        )

        challenge = ChallengeDefinition(
            id=req.bundle_ref.get("challenge_id", "broker_stub"),
            name="broker_stub",
            category="broker",
            difficulty="easy",
            target=req.bundle_ref.get("target", ""),
        )
        instance = ChallengeInstance(
            instance_id="broker_stub",
            challenge_id=challenge.id,
            target=req.bundle_ref.get("target", ""),
            status="active",
        )
        program = ActionProgram(
            id="broker_stub",
            goal="broker stub execution",
            pattern_nodes=[],
            steps=[PrimitiveActionStep(
                primitive=req.step.get("primitive", req.primitive_name),
                instruction=req.step.get("instruction", ""),
                parameters=req.step.get("parameters", {}),
            )],
            allowed_primitives=req.bundle_ref.get("visible_primitives", [req.primitive_name]),
            verification_rules=[],
            required_profile=WorkerProfile.SOLVER,
        )
        return TaskBundle(
            project_id=req.project_id,
            run_id=req.request_id,
            action_program=program,
            stage=ProjectStage.EXPLORE,
            worker_profile=WorkerProfile.SOLVER,
            target=req.bundle_ref.get("target", ""),
            challenge=challenge,
            instance=instance,
            handoff_summary=req.bundle_ref.get("handoff_summary", "broker stub execution"),
            visible_primitives=req.bundle_ref.get("visible_primitives", [req.primitive_name]),
        )