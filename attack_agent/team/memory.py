"""MemoryService — Phase D.

Structured memory operations over Blackboard event journal.
Stores MemoryEntries via events, queries materialized state,
deduplicates entries, and extracts FailureBoundary objects.
"""

from __future__ import annotations

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import (
    FailureBoundary,
    MemoryEntry,
    MemoryKind,
    to_dict,
)


class MemoryService:
    """Read/write structured memory backed by Blackboard event journal."""

    def __init__(self, blackboard: BlackboardService) -> None:
        self.blackboard = blackboard

    def store_entry(self, project_id: str, entry: MemoryEntry) -> MemoryEntry:
        """Store a MemoryEntry into Blackboard as an event.

        Uses EventType.OBSERVATION for fact/credential/endpoint/hint,
        EventType.ACTION_OUTCOME for failure_boundary.
        """
        entry.project_id = project_id
        if entry.kind == MemoryKind.FAILURE_BOUNDARY:
            event_type = EventType.ACTION_OUTCOME.value
            payload = {
                "status": "error",
                "error": entry.content,
                "summary": entry.content,
                "entry_id": entry.entry_id,
                "kind": entry.kind.value,
                "confidence": entry.confidence,
                "evidence_refs": entry.evidence_refs,
            }
        else:
            event_type = EventType.OBSERVATION.value
            payload = {
                "summary": entry.content,
                "text": entry.content,
                "entry_id": entry.entry_id,
                "kind": entry.kind.value,
                "confidence": entry.confidence,
                "evidence_refs": entry.evidence_refs,
            }
        self.blackboard.append_event(
            project_id, event_type, payload, source="memory_service"
        )
        return entry

    def query_by_kind(
        self, project_id: str, kind: MemoryKind, limit: int = 20
    ) -> list[MemoryEntry]:
        """Query materialized state for entries of a given kind."""
        state = self.blackboard.rebuild_state(project_id)
        matching = [m for m in state.facts if m.kind == kind]
        # return most recent first
        matching.reverse()
        return matching[:limit]

    def query_by_confidence(
        self, project_id: str, min_confidence: float, limit: int = 10
    ) -> list[MemoryEntry]:
        """Query entries with confidence >= threshold, highest first."""
        state = self.blackboard.rebuild_state(project_id)
        matching = [
            m for m in state.facts if m.confidence >= min_confidence
        ]
        matching.sort(key=lambda m: m.confidence, reverse=True)
        return matching[:limit]

    def dedupe(self, project_id: str) -> int:
        """Deduplicate entries with identical content, keeping the highest-confidence one.

        Returns the number of duplicates removed. This is a read-only analysis —
        actual deduplication would require rewriting events, which violates the
        append-only journal principle. Instead, consumers should use this method
        to identify duplicates and skip them at query time.
        """
        state = self.blackboard.rebuild_state(project_id)
        seen: dict[str, MemoryEntry] = {}
        duplicates = 0
        for m in state.facts:
            key = f"{m.kind.value}:{m.content}"
            if key in seen:
                # keep the one with higher confidence
                if m.confidence > seen[key].confidence:
                    seen[key] = m
                duplicates += 1
            else:
                seen[key] = m
        return duplicates

    def get_failure_boundaries(
        self, project_id: str
    ) -> list[FailureBoundary]:
        """Extract all failure_boundary MemoryEntries as FailureBoundary objects."""
        entries = self.query_by_kind(project_id, MemoryKind.FAILURE_BOUNDARY)
        return [
            FailureBoundary(
                boundary_id=m.entry_id,
                project_id=m.project_id,
                description=m.content,
                evidence_refs=m.evidence_refs,
                created_at=m.created_at,
            )
            for m in entries
        ]

    def get_deduped_entries(
        self, project_id: str, kind: MemoryKind | None = None, limit: int = 20
    ) -> list[MemoryEntry]:
        """Return entries after deduplication, optionally filtered by kind.

        Keeps highest-confidence entry per unique (kind, content) pair.
        """
        state = self.blackboard.rebuild_state(project_id)
        pool = state.facts if kind is None else [
            m for m in state.facts if m.kind == kind
        ]
        seen: dict[str, MemoryEntry] = {}
        for m in pool:
            key = f"{m.kind.value}:{m.content}"
            if key not in seen or m.confidence > seen[key].confidence:
                seen[key] = m
        result = list(seen.values())
        result.sort(key=lambda m: m.confidence, reverse=True)
        return result[:limit]