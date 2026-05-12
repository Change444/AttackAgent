"""Event compatibility adapter — routes old candidate_flag events to correct semantic handlers.

L1 event semantics cleanup: candidate_flag was overloaded for ideas, flags,
convergence, and merge arbitration. This module provides classification helpers
so legacy event logs replay correctly and downstream consumers can distinguish
genuine flags from idea lifecycle events.
"""

from __future__ import annotations

from attack_agent.team.protocol import IdeaStatus

_IDEA_STATUS_VALUES = frozenset(s.value for s in IdeaStatus)

# Map IdeaStatus values to the new event type string
_STATUS_TO_CLASSIFIED = {
    IdeaStatus.PENDING.value: "idea_proposed",
    IdeaStatus.CLAIMED.value: "idea_claimed",
    IdeaStatus.VERIFIED.value: "idea_verified",
    IdeaStatus.FAILED.value: "idea_failed",
    IdeaStatus.shelved.value: "idea_proposed",
}


def classify_candidate_flag_event(payload: dict, source: str) -> str:
    """Classify an old-format candidate_flag event into its true semantic role.

    Returns one of: "idea_proposed", "idea_claimed", "idea_verified",
    "idea_failed", or "candidate_flag" (genuine flag).
    """
    status = payload.get("status", "")
    if status in _IDEA_STATUS_VALUES:
        return _STATUS_TO_CLASSIFIED.get(status, "idea_proposed")

    # MergeHub events carry idea_id or arbitration markers
    if source == "merge_hub" and (payload.get("idea_id") or payload.get("arbitration") or payload.get("merged_from_ids")):
        return "idea_proposed"

    # IdeaService events that somehow lack status — route by idea_id + source
    if source == "idea_service" and payload.get("idea_id"):
        return "idea_proposed"

    return "candidate_flag"


def is_genuine_candidate_flag(event_type: str, payload: dict, source: str) -> bool:
    """Return True only if this event represents a real extracted flag."""
    if event_type != "candidate_flag":
        return False
    return classify_candidate_flag_event(payload, source) == "candidate_flag"