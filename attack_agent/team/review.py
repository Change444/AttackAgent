"""HumanReviewGate — Phase E.

Review request lifecycle management: create, resolve, list pending, auto-expire.
All state changes are recorded in Blackboard event journal.

HumanReviewGate is a pure logic service — no CLI blocking or Web UI required.
Review resolution is driven by external callers invoking resolve_review().
"""

from __future__ import annotations

from datetime import datetime, timezone

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import (
    HumanDecision,
    HumanDecisionChoice,
    MemoryKind,
    PolicyOutcome,
    ReviewRequest,
    ReviewStatus,
    to_dict,
)


class HumanReviewGate:
    """Review request lifecycle: create → pending → resolved / expired."""

    def create_review(
        self,
        request: ReviewRequest,
        blackboard: BlackboardService,
        causal_ref: str | None = None,
    ) -> ReviewRequest:
        """Create a ReviewRequest and write it to Blackboard."""
        # L7: enrich observer review descriptions with intervention context
        if request.proposed_action_payload:
            tags = request.proposed_action_payload.get("policy_tags", [])
            if any(t.startswith("observer_") for t in tags):
                intervention = request.proposed_action_payload.get("intervention_level", "")
                rec_action = request.proposed_action_payload.get("recommended_action", "")
                if intervention or rec_action:
                    observer_note = f" [observer: level={intervention}, recommended={rec_action}]"
                    request.description = request.description + observer_note
        blackboard.append_event(
            project_id=request.project_id,
            event_type=EventType.SECURITY_VALIDATION.value,
            payload={
                "review_id": request.request_id,
                "action_type": request.action_type,
                "risk_level": request.risk_level,
                "title": request.title,
                "description": request.description,
                "proposed_action": request.proposed_action,
                "proposed_action_payload": request.proposed_action_payload,
                "alternatives": request.alternatives,
                "timeout_policy": request.timeout_policy,
                "status": ReviewStatus.PENDING.value,
                "outcome": "needs_review",
            },
            source="human_review_gate",
            causal_ref=causal_ref,
        )
        return request

    def resolve_review(
        self,
        request_id: str,
        decision: HumanDecision,
        blackboard: BlackboardService,
        project_id: str = "",
    ) -> ReviewRequest | None:
        """Resolve a pending ReviewRequest with a HumanDecision.

        Updates status to approved/rejected/modified per decision choice.
        Writes resolution event to Blackboard. On reject, records a failure
        boundary MemoryEntry via ACTION_OUTCOME event.

        project_id is required to locate the review in the event journal.
        """
        # find the request by scanning SECURITY_VALIDATION events
        review = self._find_review(request_id, project_id, blackboard)
        if review is None:
            return None

        if review.status != ReviewStatus.PENDING:
            return review  # already resolved

        new_status = self._decision_to_status(decision.decision)
        review.status = new_status
        review.decision = decision.decision.value
        review.decided_by = decision.decided_by
        review.decided_at = decision.decided_at or datetime.now(timezone.utc).isoformat()

        # write resolution event
        resolution_payload = {
            "review_id": request_id,
            "outcome": "review_" + new_status.value,
            "decision": decision.decision.value,
            "decided_by": decision.decided_by,
            "decided_at": review.decided_at,
            "reason": decision.reason,
            "status": new_status.value,
        }

        # L11: MODIFIED — build delta and modified_action_payload
        if decision.decision == HumanDecisionChoice.MODIFIED and decision.modified_params:
            original_payload = review.proposed_action_payload or {}
            modified_payload = {**original_payload, **decision.modified_params}
            delta_lines = []
            for key, new_val in decision.modified_params.items():
                old_val = original_payload.get(key, "<absent>")
                delta_lines.append(f"{key}: {old_val} → {new_val}")
            resolution_payload["original_action_payload"] = original_payload
            resolution_payload["modified_params"] = decision.modified_params
            resolution_payload["modified_action_payload"] = modified_payload
            resolution_payload["delta"] = delta_lines
            review.proposed_action_payload = modified_payload

        blackboard.append_event(
            project_id=review.project_id,
            event_type=EventType.SECURITY_VALIDATION.value,
            payload=resolution_payload,
            source="human_review_gate",
            causal_ref=request_id,
        )

        # on reject: record failure boundary
        if decision.decision == HumanDecisionChoice.REJECTED:
            blackboard.append_event(
                project_id=review.project_id,
                event_type=EventType.ACTION_OUTCOME.value,
                payload={
                    "status": "blocked",
                    "entry_id": request_id + "_reject",
                    "kind": MemoryKind.FAILURE_BOUNDARY.value,
                    "error": f"review rejected: {review.action_type} — {decision.reason}",
                    "summary": f"review rejected: {review.action_type}",
                },
                source="human_review_gate",
                causal_ref=request_id,
            )

        return review

    def list_pending_reviews(
        self,
        project_id: str,
        blackboard: BlackboardService,
    ) -> list[ReviewRequest]:
        """List pending ReviewRequests from Blackboard event journal."""
        reviews = self._build_review_index(project_id, blackboard)
        return [r for r in reviews.values() if r.status == ReviewStatus.PENDING]

    def auto_expire_reviews(
        self,
        project_id: str,
        timeout_seconds: int,
        blackboard: BlackboardService,
    ) -> list[ReviewRequest]:
        """Auto-expire pending reviews older than timeout_seconds.

        Default timeout_policy is auto_reject — expired reviews are treated
        as rejected with decided_by="auto_expire".
        """
        now = datetime.now(timezone.utc)
        pending = self.list_pending_reviews(project_id, blackboard)
        expired: list[ReviewRequest] = []

        # find creation timestamps from events
        review_created_at: dict[str, str] = {}
        events = blackboard.load_events(project_id)
        for ev in events:
            if ev.event_type == EventType.SECURITY_VALIDATION.value:
                rid = ev.payload.get("review_id")
                if rid and ev.payload.get("status") == ReviewStatus.PENDING.value:
                    review_created_at[rid] = ev.timestamp

        for review in pending:
            created_ts = review_created_at.get(review.request_id)
            if not created_ts:
                continue
            try:
                created_dt = datetime.fromisoformat(created_ts)
                age = (now - created_dt).total_seconds()
            except (ValueError, TypeError):
                continue

            if age > timeout_seconds:
                expire_decision = HumanDecision(
                    request_id=review.request_id,
                    decision=HumanDecisionChoice.REJECTED,
                    decided_by="auto_expire",
                    reason=f"review expired after {timeout_seconds}s",
                )
                self.resolve_review(review.request_id, expire_decision, blackboard, project_id=project_id)
                expired.append(review)

        return expired

    # -- internal helpers --

    def _find_review(
        self, request_id: str, project_id: str, blackboard: BlackboardService,
    ) -> ReviewRequest | None:
        """Rebuild a specific ReviewRequest from event journal."""
        reviews = self._build_review_index(project_id, blackboard)
        return reviews.get(request_id)

    def _build_review_index(
        self, project_id: str, blackboard: BlackboardService,
    ) -> dict[str, ReviewRequest]:
        """Build review_id → ReviewRequest from SECURITY_VALIDATION events.
        Latest event per review_id wins (append-only → last status is current).
        """
        reviews: dict[str, ReviewRequest] = {}
        events = blackboard.load_events(project_id)
        for ev in events:
            if ev.event_type != EventType.SECURITY_VALIDATION.value:
                continue
            p = ev.payload
            review_id = p.get("review_id")
            if not review_id:
                continue
            status_str = p.get("status", "")
            if not status_str:
                continue
            try:
                status = ReviewStatus(status_str)
            except ValueError:
                continue
            reviews[review_id] = ReviewRequest(
                request_id=review_id,
                project_id=project_id,
                action_type=p.get("action_type", ""),
                risk_level=p.get("risk_level", "low"),
                title=p.get("title", ""),
                description=p.get("description", ""),
                proposed_action=p.get("proposed_action", ""),
                proposed_action_payload=p.get("proposed_action_payload", {}),
                alternatives=p.get("alternatives", []),
                timeout_policy=p.get("timeout_policy", "auto_reject"),
                status=status,
                decided_by=p.get("decided_by", ""),
                decided_at=p.get("decided_at", ""),
            )
        return reviews

    def _decision_to_status(self, choice: HumanDecisionChoice) -> ReviewStatus:
        mapping = {
            HumanDecisionChoice.APPROVED: ReviewStatus.APPROVED,
            HumanDecisionChoice.REJECTED: ReviewStatus.REJECTED,
            HumanDecisionChoice.MODIFIED: ReviewStatus.MODIFIED,
        }
        return mapping.get(choice, ReviewStatus.PENDING)