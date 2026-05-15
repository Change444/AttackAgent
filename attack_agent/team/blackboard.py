"""Blackboard Event Journal — Phase B.

Append-only SQLite event store with materialized state rebuild.
Each event is immutable; no update/delete operations exist.
Event schema supports replay: causal_ref links to a prior event_id for causality tracking.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.protocol import (
    IdeaEntry,
    KnowledgePacket,
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
    packets: list[KnowledgePacket] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BlackboardService:
    """Append-only event journal backed by SQLite.

    L11: events are isolated by run_id. start_run() creates a new run
    context; load_events/rebuild_state filter by the latest run_id by
    default. Historical runs remain queryable via explicit run_id.
    """

    def __init__(self, config: BlackboardConfig | None = None) -> None:
        self.config = config or BlackboardConfig()
        self._db: sqlite3.Connection | None = None
        self._ensure_db()
        self._lock = threading.Lock()
        self._current_runs: dict[str, str] = {}  # project_id → run_id

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
                causal_ref  TEXT,
                run_id      TEXT DEFAULT NULL
            )
            """
        )
        # L11: schema migration — add run_id column to pre-L11 databases
        # Must happen before creating the run_id index
        self._migrate_add_run_id()
        # L11: run_id isolation index (only after column exists)
        self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_events_run
            ON events (project_id, run_id)
            """
        )
        self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_events_project
            ON events (project_id, timestamp)
            """
        )
        self._db.commit()

    def _migrate_add_run_id(self) -> None:
        """Add run_id column to existing events table if it doesn't exist."""
        try:
            self._db.execute("SELECT run_id FROM events LIMIT 1")
        except sqlite3.OperationalError:
            self._db.execute("ALTER TABLE events ADD COLUMN run_id TEXT DEFAULT NULL")

    def clear_project_events(self, project_id: str) -> None:
        """Remove all events for a project — used before fresh run."""
        if self._db is None:
            return
        with self._lock:
            self._db.execute("DELETE FROM events WHERE project_id = ?", (project_id,))
            self._db.commit()

    # -- L11: run isolation --

    def start_run(self, project_id: str) -> str:
        """Start a new run for a project, returning the run_id.

        All subsequent append_event calls for this project will
        carry this run_id. load_events/rebuild_state default to
        filtering by the latest run_id.
        """
        run_id = uuid.uuid4().hex[:12]
        self._current_runs[project_id] = run_id
        return run_id

    def get_current_run_id(self, project_id: str) -> str | None:
        """Return the current run_id for a project, if set."""
        return self._current_runs.get(project_id)

    def list_runs(self, project_id: str) -> list[str]:
        """List all run_ids for a project, ordered by first event timestamp."""
        if self._db is None:
            return []
        with self._lock:
            rows = self._db.execute(
                """
                SELECT DISTINCT run_id FROM events
                WHERE project_id = ? AND run_id IS NOT NULL
                ORDER BY run_id
                """,
                (project_id,),
            ).fetchall()
            return [r["run_id"] for r in rows]

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
        run_id = self._current_runs.get(project_id)
        with self._lock:
            self._db.execute(
                """
                INSERT INTO events (event_id, project_id, event_type, payload, source, timestamp, causal_ref, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev.event_id,
                    ev.project_id,
                    ev.event_type,
                    json.dumps(ev.payload, ensure_ascii=False),
                    ev.source,
                    ev.timestamp,
                    ev.causal_ref,
                    run_id,
                ),
            )
            self._db.commit()
        return ev

    # -- read --

    def load_events(self, project_id: str, run_id: str | None = None) -> list[BlackboardEvent]:
        """Load events for a project, filtered by run_id.

        If run_id is None, uses the current run_id for the project
        from _current_runs. If that is also None, loads all events
        (backward compatibility with pre-L11 data).
        """
        effective_run_id = run_id or self._current_runs.get(project_id)
        with self._lock:
            if effective_run_id is not None:
                rows = self._db.execute(
                    """
                    SELECT event_id, project_id, event_type, payload, source, timestamp, causal_ref
                    FROM events WHERE project_id = ? AND run_id = ? ORDER BY timestamp
                    """,
                    (project_id, effective_run_id),
                ).fetchall()
            else:
                rows = self._db.execute(
                    """
                    SELECT event_id, project_id, event_type, payload, source, timestamp, causal_ref
                    FROM events WHERE project_id = ? ORDER BY timestamp
                    """,
                    (project_id,),
                ).fetchall()
            return [self._row_to_event(r) for r in rows]

    def load_events_after(self, project_id: str, after_event_id: str = "") -> list[BlackboardEvent]:
        """Load events for a project newer than the given event_id.

        If after_event_id is empty, returns all events.
        Used for SSE streaming: client sends Last-Event-ID, server returns newer events.
        """
        if not after_event_id:
            return self.load_events(project_id)
        with self._lock:
            row = self._db.execute(
                "SELECT timestamp FROM events WHERE event_id = ?",
                (after_event_id,),
            ).fetchone()
            if row is None:
                return self.load_events(project_id)
            rows = self._db.execute(
                """
                SELECT event_id, project_id, event_type, payload, source, timestamp, causal_ref
                FROM events WHERE project_id = ? AND timestamp > ? ORDER BY timestamp
                """,
                (project_id, row["timestamp"]),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]

    def load_all_events_after(self, after_event_id: str = "") -> list[BlackboardEvent]:
        """Load events across ALL projects newer than the given event_id.

        Used for global SSE stream (no project filter).
        """
        with self._lock:
            if not after_event_id:
                rows = self._db.execute(
                    """
                    SELECT event_id, project_id, event_type, payload, source, timestamp, causal_ref
                    FROM events ORDER BY timestamp
                    """,
                ).fetchall()
                return [self._row_to_event(r) for r in rows]
            row = self._db.execute(
                "SELECT timestamp FROM events WHERE event_id = ?",
                (after_event_id,),
            ).fetchone()
            if row is None:
                rows = self._db.execute(
                    """
                    SELECT event_id, project_id, event_type, payload, source, timestamp, causal_ref
                    FROM events ORDER BY timestamp
                    """,
                ).fetchall()
                return [self._row_to_event(r) for r in rows]
            rows = self._db.execute(
                """
                SELECT event_id, project_id, event_type, payload, source, timestamp, causal_ref
                FROM events WHERE timestamp > ? ORDER BY timestamp
                """,
                (row["timestamp"],),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]

    # -- rebuild --

    def rebuild_state(self, project_id: str, run_id: str | None = None) -> MaterializedState:
        events = self.load_events(project_id, run_id)
        state = MaterializedState()
        # Track latest idea state per idea_id — later events override earlier ones.
        idea_index: dict[str, IdeaEntry] = {}
        # Track latest session state per solver_id — later events override earlier ones.
        session_index: dict[str, SolverSession] = {}
        # L6: Track latest packet state per packet_id
        packet_index: dict[str, KnowledgePacket] = {}
        for ev in events:
            self._apply_event(state, ev, idea_index, session_index, packet_index)
        # Collapse ideas to latest state per idea_id
        state.ideas = list(idea_index.values())
        # Collapse sessions to latest state per solver_id
        state.sessions = list(session_index.values())
        # L6: Collapse packets
        state.packets = list(packet_index.values())
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
                      session_index: dict[str, SolverSession] | None = None,
                      packet_index: dict[str, KnowledgePacket] | None = None) -> None:
        idx = idea_index if idea_index is not None else {}
        sidx = session_index if session_index is not None else {}
        pidx = packet_index if packet_index is not None else {}
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
            packet_index=pidx,
            source=ev.source,
        )
        # If caller didn't provide indexes, merge temp indexes into state lists
        if idea_index is None:
            state.ideas.extend(idx.values())
        if session_index is None:
            state.sessions.extend(sidx.values())
        if packet_index is None:
            state.packets.extend(pidx.values())