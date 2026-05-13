"""MemoryReducer — L4.

Extracts structured memory from raw Blackboard events after every tool
outcome. Returns ReducedMemory for the caller to persist selectively.
Does NOT store entries — that is MemoryService.store_entry's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardEvent
from attack_agent.team.context import SOLVER_CONTEXT_LIMITS
from attack_agent.team.protocol import (
    MemoryEntry,
    MemoryKind,
)


@dataclass
class ReducedMemory:
    """Result of running memory reducers over recent events."""

    facts: list[MemoryEntry] = field(default_factory=list)
    credentials: list[MemoryEntry] = field(default_factory=list)
    endpoints: list[MemoryEntry] = field(default_factory=list)
    failure_boundaries: list[MemoryEntry] = field(default_factory=list)
    scratchpad_summary: str = ""
    event_ids_seen: list[str] = field(default_factory=list)


class MemoryReducer:
    """Extract structured memory from Blackboard events.

    Runs over recent events and extracts:
    - facts from OBSERVATION payloads (kind=fact or unrecognized)
    - credentials from session_state payloads (cookies, auth_headers)
    - endpoints from OBSERVATION payloads (http-request, endpoint kinds)
    - failure boundaries from ACTION_OUTCOME (status != ok)
    """

    def reduce_observations(
        self,
        events: list[BlackboardEvent],
        project_id: str,
        limit: int = 20,
    ) -> ReducedMemory:
        """Process recent events and extract structured memory."""
        result = ReducedMemory()
        recent = events[-limit:] if len(events) > limit else events

        for ev in recent:
            result.event_ids_seen.append(ev.event_id)

            if ev.event_type == EventType.OBSERVATION.value:
                self._reduce_observation(ev, project_id, result)

            elif ev.event_type == EventType.ACTION_OUTCOME.value:
                self._reduce_action_outcome(ev, project_id, result)

        # Build scratchpad_summary from top items
        self._build_scratchpad(result)
        # Bound event_ids_seen
        max_ids = SOLVER_CONTEXT_LIMITS["max_recent_event_ids"]
        result.event_ids_seen = result.event_ids_seen[-max_ids:]
        return result

    def _reduce_observation(
        self,
        ev: BlackboardEvent,
        project_id: str,
        result: ReducedMemory,
    ) -> None:
        kind_str = ev.payload.get("kind", "")
        summary = ev.payload.get("summary", ev.payload.get("text", ""))
        confidence = ev.payload.get("confidence", 0.0)

        # Credential extraction from session_state
        if kind_str == "session_state":
            cookies = ev.payload.get("cookies_count", 0)
            auth_keys = ev.payload.get("auth_headers_keys", [])
            if cookies > 0 or auth_keys:
                result.credentials.append(MemoryEntry(
                    kind=MemoryKind.CREDENTIAL,
                    content=f"session: {cookies} cookies, {auth_keys}",
                    confidence=confidence,
                    project_id=project_id,
                ))

        # Endpoint extraction
        elif kind_str in ("http-request", "http-response", "endpoint"):
            result.endpoints.append(MemoryEntry(
                kind=MemoryKind.ENDPOINT,
                content=summary,
                confidence=confidence,
                project_id=project_id,
            ))

        # Explicit credential kind
        elif kind_str == MemoryKind.CREDENTIAL.value:
            result.credentials.append(MemoryEntry(
                kind=MemoryKind.CREDENTIAL,
                content=summary,
                confidence=confidence,
                project_id=project_id,
            ))

        # Explicit endpoint kind
        elif kind_str == MemoryKind.ENDPOINT.value:
            result.endpoints.append(MemoryEntry(
                kind=MemoryKind.ENDPOINT,
                content=summary,
                confidence=confidence,
                project_id=project_id,
            ))

        # Fact extraction (kind=fact or unrecognized primitive kinds)
        elif kind_str in (MemoryKind.FACT.value, "fact", "") or kind_str not in MemoryKind._value2member_map_:
            result.facts.append(MemoryEntry(
                kind=MemoryKind.FACT,
                content=summary,
                confidence=confidence,
                project_id=project_id,
            ))

    def _reduce_action_outcome(
        self,
        ev: BlackboardEvent,
        project_id: str,
        result: ReducedMemory,
    ) -> None:
        status = ev.payload.get("status", "")
        if status != "ok":
            error = ev.payload.get("error", ev.payload.get("failure_reason", ""))
            result.failure_boundaries.append(MemoryEntry(
                kind=MemoryKind.FAILURE_BOUNDARY,
                content=error or "action failed",
                confidence=0.0,
                project_id=project_id,
            ))

    def _build_scratchpad(self, result: ReducedMemory) -> None:
        max_chars = SOLVER_CONTEXT_LIMITS["max_scratchpad_summary_chars"]
        fact_summaries = [f.content for f in result.facts[:5]]
        credential_summaries = [c.content for c in result.credentials[:3]]
        boundary_summaries = [b.content for b in result.failure_boundaries[:3]]

        parts = []
        if fact_summaries:
            parts.append("Facts: " + "; ".join(fact_summaries))
        if credential_summaries:
            parts.append("Credentials: " + "; ".join(credential_summaries))
        if boundary_summaries:
            parts.append("Boundaries: " + "; ".join(boundary_summaries))

        result.scratchpad_summary = " | ".join(parts)
        if len(result.scratchpad_summary) > max_chars:
            result.scratchpad_summary = result.scratchpad_summary[:max_chars]