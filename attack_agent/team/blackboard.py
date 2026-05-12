"""Blackboard Event Journal — Phase B.

Append-only SQLite event store with materialized state rebuild.
Each event is immutable; no update/delete operations exist.
Event schema supports replay: causal_ref links to a prior event_id for causality tracking.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.protocol import (
    IdeaEntry,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    TeamProject,
    to_dict,
)
from attack_agent.team.apply_event import apply_event_to_state


# ---------------------------------------------------------------------------
# Event record
# ---------------------------------------------------------------------------

@dataclass
class BlackboardEvent:
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    project_id: str = ""
    event_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    causal_ref: str | None = None


# ---------------------------------------------------------------------------
# Rebuild result
# ---------------------------------------------------------------------------

@dataclass
class MaterializedState:
    project: TeamProject | None = None
    facts: list[MemoryEntry] = field(default_factory=list)
    ideas: list[IdeaEntry] = field(default_factory=list)
    sessions: list[SolverSession] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BlackboardService:
    """Append-only event journal backed by SQLite."""

    def __init__(self, config: BlackboardConfig | None = None) -> None:
        self.config = config or BlackboardConfig()
        self._db: sqlite3.Connection | None = None
        self._ensure_db()

    # -- lifecycle --

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def _ensure_db(self) -> None:
        Path(self.config.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.config.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id    TEXT PRIMARY KEY,
                project_id  TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                payload     TEXT NOT NULL,
                source      TEXT NOT NULL DEFAULT 'system',
                timestamp   TEXT NOT NULL,
                causal_ref  TEXT
            )
            """
        )
        self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_events_project
            ON events (project_id, timestamp)
            """
        )
        self._db.commit()

    def clear_project_events(self, project_id: str) -> None:
        """Remove all events for a project — used before fresh run."""
        if self._db is None:
            return
        self._db.execute("DELETE FROM events WHERE project_id = ?", (project_id,))
        self._db.commit()

    # -- write --

    def append_event(
        self,
        project_id: str,
        event_type: str,
        payload: dict[str, Any],
        source: str = "system",
        causal_ref: str | None = None,
    ) -> BlackboardEvent:
        ev = BlackboardEvent(
            project_id=project_id,
            event_type=event_type,
            payload=payload,
            source=source,
            causal_ref=causal_ref,
        )
        self._db.execute(
            """
            INSERT INTO events (event_id, project_id, event_type, payload, source, timestamp, causal_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ev.event_id,
                ev.project_id,
                ev.event_type,
                json.dumps(ev.payload, ensure_ascii=False),
                ev.source,
                ev.timestamp,
                ev.causal_ref,
            ),
        )
        self._db.commit()
        return ev

    # -- read --

    def load_events(self, project_id: str) -> list[BlackboardEvent]:
        rows = self._db.execute(
            """
            SELECT event_id, project_id, event_type, payload, source, timestamp, causal_ref
            FROM events WHERE project_id = ? ORDER BY timestamp
            """,
            (project_id,),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    # -- rebuild --

    def rebuild_state(self, project_id: str) -> MaterializedState:
        events = self.load_events(project_id)
        state = MaterializedState()
        # Track latest idea state per idea_id — later events override earlier ones.
        idea_index: dict[str, IdeaEntry] = {}
        # Track latest session state per solver_id — later events override earlier ones.
        session_index: dict[str, SolverSession] = {}
        for ev in events:
            self._apply_event(state, ev, idea_index, session_index)
        # Collapse ideas to latest state per idea_id
        state.ideas = list(idea_index.values())
        # Collapse sessions to latest state per solver_id
        state.sessions = list(session_index.values())
        return state

    def list_facts(self, project_id: str) -> list[MemoryEntry]:
        state = self.rebuild_state(project_id)
        return [m for m in state.facts if m.kind == MemoryKind.FACT]

    def list_ideas(self, project_id: str) -> list[IdeaEntry]:
        return self.rebuild_state(project_id).ideas

    def list_sessions(self, project_id: str) -> list[SolverSession]:
        return self.rebuild_state(project_id).sessions

    # -- export --

    def export_run_log(self, project_id: str) -> list[dict[str, Any]]:
        events = self.load_events(project_id)
        return [self._event_to_dict(ev) for ev in events]

    # -- internals --

    def _new_materialized_state(self) -> MaterializedState:
        """Create a fresh MaterializedState. Used by ReplayEngine to avoid circular import."""
        return MaterializedState()

    def _row_to_event(self, row: sqlite3.Row) -> BlackboardEvent:
        return BlackboardEvent(
            event_id=row["event_id"],
            project_id=row["project_id"],
            event_type=row["event_type"],
            payload=json.loads(row["payload"]),
            source=row["source"],
            timestamp=row["timestamp"],
            causal_ref=row["causal_ref"],
        )

    def _event_to_dict(self, ev: BlackboardEvent) -> dict[str, Any]:
        return {
            "event_id": ev.event_id,
            "project_id": ev.project_id,
            "event_type": ev.event_type,
            "payload": ev.payload,
            "source": ev.source,
            "timestamp": ev.timestamp,
            "causal_ref": ev.causal_ref,
        }

    def _apply_event(self, state: MaterializedState, ev: BlackboardEvent,
                      idea_index: dict[str, IdeaEntry] | None = None,
                      session_index: dict[str, SolverSession] | None = None) -> None:
        idx = idea_index if idea_index is not None else {}
        sidx = session_index if session_index is not None else {}
        state.project = apply_event_to_state(
            project_id=ev.project_id,
            event_type=ev.event_type,
            payload=ev.payload,
            timestamp=ev.timestamp,
            event_id=ev.event_id,
            state_project=state.project,
            state_facts=state.facts,
            idea_index=idx,
            session_index=sidx,
            source=ev.source,
        )
        # If caller didn't provide indexes, merge temp indexes into state lists
        if idea_index is None:
            state.ideas.extend(idx.values())
        if session_index is None:
            state.sessions.extend(sidx.values())