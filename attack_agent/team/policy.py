"""PolicyHarness — Phase E.

Unified security, budget, submit-governance, and review decision point.
Converges logic from LightweightSecurityShell, SubmitClassifier, primitive
visibility, and budget/rate limits into a single PolicyDecision output.

PolicyHarness is a NEW entry point — it calls existing module outputs for
decision mapping, NOT replacing them. No existing files are modified.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import (
    ActionType,
    PolicyDecision,
    PolicyOutcome,
    StrategyAction,
)


@dataclass
class RiskThresholds:
    """Risk level → policy outcome mapping."""
    critical: str = "deny"
    high: str = "needs_review"
    medium: str = "allow"
    low: str = "allow"


@dataclass
class PolicyConfig:
    """PolicyHarness configuration."""
    risk_thresholds: RiskThresholds = field(default_factory=RiskThresholds)
    budget_limit: float = 100.0
    rate_limit_window: int = 60  # seconds
    rate_limit_max: int = 30  # max actions within window
    submit_confidence_threshold: float = 0.6
    allowed_primitives: list[str] = field(default_factory=lambda: [
        "http-request", "browser-inspect", "artifact-scan", "binary-inspect",
        "code-sandbox", "extract-candidate", "structured-parse", "diff-compare",
        "session-materialize",
    ])
    forbidden_primitives: list[str] = field(default_factory=list)


class PolicyHarness:
    """Unified policy decision engine.

    validate_action reads a StrategyAction + Blackboard state, applies risk
    thresholds, budget checks, rate limits, primitive visibility, and submit
    governance. Returns a PolicyDecision and writes it to the event journal.
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def validate_action(
        self,
        action: StrategyAction,
        project_id: str,
        blackboard: BlackboardService,
    ) -> PolicyDecision:
        """Evaluate a StrategyAction and return a PolicyDecision.

        Decision flow:
        1. primitive visibility check → deny if forbidden
        2. budget check → budget_exceeded
        3. rate limit check → rate_limit
        4. risk threshold mapping (critical→deny, high→needs_review, etc.)
        5. submit_flag special: high risk + requires_review → needs_review
        6. default → allow

        Each decision is recorded in Blackboard as SECURITY_VALIDATION event.
        """
        # 1. primitive visibility
        # L7: THROTTLE_SOLVER/REASSIGN_SOLVER are scheduling actions, not primitive executions
        if action.action_type not in (ActionType.THROTTLE_SOLVER, ActionType.REASSIGN_SOLVER):
            if action.action_type == ActionType.LAUNCH_SOLVER:
                primitives_used = self._extract_primitives_from_reason(action.reason)
                for p in primitives_used:
                    if p in self.config.forbidden_primitives:
                        decision = self._make_decision(
                            PolicyOutcome.DENY, action, "forbidden primitive: " + p,
                        )
                        self._record(blackboard, project_id, decision)
                        return decision

        # 2. budget check
        state = blackboard.rebuild_state(project_id)
        total_cost = self._estimate_project_cost(state)
        if total_cost + action.budget_request > self.config.budget_limit:
            decision = self._make_decision(
                PolicyOutcome.BUDGET_EXCEEDED, action,
                f"budget exhausted: {total_cost:.1f} + {action.budget_request:.1f} > {self.config.budget_limit:.1f}",
            )
            self._record(blackboard, project_id, decision)
            return decision

        # 3. rate limit check
        events = blackboard.load_events(project_id)
        recent_count = self._count_recent_actions(events)
        if recent_count >= self.config.rate_limit_max:
            decision = self._make_decision(
                PolicyOutcome.RATE_LIMIT, action,
                f"rate limit: {recent_count} actions in {self.config.rate_limit_window}s window",
            )
            self._record(blackboard, project_id, decision)
            return decision

        # -- L7: observer-initiated safety blocks bypass critical deny --
        # Observer safety-block actions carry "observer_" policy tags.
        # They must reach human review, not be auto-denied by policy.
        if action.policy_tags and any(t.startswith("observer_") for t in action.policy_tags):
            if action.risk_level == "critical":
                outcome = PolicyOutcome.NEEDS_REVIEW
                reason = f"observer safety block: risk_level={action.risk_level} → needs_review (observer override)"
                decision = self._make_decision(outcome, action, reason)
                self._record(blackboard, project_id, decision)
                return decision

        # 4. risk threshold mapping
        outcome = self._map_risk(action.risk_level)
        reason = f"risk_level={action.risk_level} → {outcome.value}"

        # 5. submit_flag special: force needs_review
        if action.action_type == ActionType.SUBMIT_FLAG:
            if action.requires_review or action.risk_level in ("high", "critical"):
                outcome = PolicyOutcome.NEEDS_REVIEW
                reason = "flag submit requires review"

        decision = self._make_decision(outcome, action, reason)
        self._record(blackboard, project_id, decision)
        return decision

    # -- helpers --

    def _make_decision(
        self, outcome: PolicyOutcome, action: StrategyAction, reason: str,
    ) -> PolicyDecision:
        return PolicyDecision(
            decision=outcome,
            action_type=action.action_type.value,
            risk_level=action.risk_level,
            reason=reason,
            constraints=[c for c in self._risk_constraints(outcome)],
        )

    def _map_risk(self, risk_level: str) -> PolicyOutcome:
        thresholds = self.config.risk_thresholds
        mapping = {
            "critical": thresholds.critical,
            "high": thresholds.high,
            "medium": thresholds.medium,
            "low": thresholds.low,
        }
        mapped = mapping.get(risk_level, "allow")
        return PolicyOutcome(mapped)

    def _risk_constraints(self, outcome: PolicyOutcome) -> list[str]:
        if outcome == PolicyOutcome.DENY:
            return ["action blocked by policy"]
        if outcome == PolicyOutcome.NEEDS_REVIEW:
            return ["requires human review before execution"]
        if outcome == PolicyOutcome.BUDGET_EXCEEDED:
            return ["budget limit reached"]
        if outcome == PolicyOutcome.RATE_LIMIT:
            return ["rate limit exceeded"]
        return []

    def _record(
        self, blackboard: BlackboardService, project_id: str,
        decision: PolicyDecision,
    ) -> None:
        from attack_agent.team.protocol import to_dict
        blackboard.append_event(
            project_id=project_id,
            event_type=EventType.SECURITY_VALIDATION.value,
            payload=to_dict(decision),
            source="policy_harness",
        )

    def _extract_primitives_from_reason(self, reason: str) -> list[str]:
        """Heuristic: primitive names mentioned in reason text."""
        known = set(self.config.allowed_primitives) | set(self.config.forbidden_primitives)
        found = [p for p in known if p in reason]
        return found

    def _estimate_project_cost(self, state: Any) -> float:
        """Rough cost estimate from materialized state facts + sessions."""
        cost_map = {
            "http-request": 1.0, "browser-inspect": 1.4,
            "artifact-scan": 1.2, "binary-inspect": 1.2,
            "code-sandbox": 1.5, "extract-candidate": 0.4,
            "structured-parse": 0.8, "diff-compare": 0.7,
        }
        total = len(state.sessions) * 5.0  # baseline per session
        for f in state.facts:
            for p, c in cost_map.items():
                if p in f.content:
                    total += c
        return total

    def _count_recent_actions(self, events: list[Any]) -> int:
        """Count SECURITY_VALIDATION + WORKER_ASSIGNED events in rate window."""
        now = datetime.now(timezone.utc)
        window_start = now.timestamp() - self.config.rate_limit_window
        count = 0
        for ev in events:
            if ev.event_type in (
                EventType.SECURITY_VALIDATION.value,
                EventType.WORKER_ASSIGNED.value,
            ):
                try:
                    ts = datetime.fromisoformat(ev.timestamp).timestamp()
                    if ts >= window_start:
                        count += 1
                except (ValueError, TypeError):
                    count += 1  # count unparseable timestamps
        return count