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
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    SolverStatus,
    TeamProject,
    to_dict,
)


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
        p = ev.payload
        et = ev.event_type

        if et == EventType.PROJECT_UPSERTED.value:
            state.project = TeamProject(
                project_id=ev.project_id,
                challenge_id=p.get("challenge_id", ""),
                status=p.get("status", "new"),
                created_at=ev.timestamp,
                updated_at=ev.timestamp,
            )
        elif et == EventType.OBSERVATION.value:
            kind = MemoryKind(p.get("kind", MemoryKind.FACT.value))
            entry_id = p.get("entry_id", ev.event_id)
            state.facts.append(
                MemoryEntry(
                    entry_id=entry_id,
                    project_id=ev.project_id,
                    kind=kind,
                    content=p.get("summary", p.get("text", "")),
                    confidence=p.get("confidence", 0.0),
                    created_at=ev.timestamp,
                )
            )
        elif et == EventType.CANDIDATE_FLAG.value:
            flag_text = p.get("flag", "")
            idea_id = p.get("idea_id", ev.event_id)
            idea_status = IdeaStatus(p.get("status", IdeaStatus.PENDING.value))
            solver_id = p.get("solver_id", "")
            idea = IdeaEntry(
                idea_id=idea_id,
                project_id=ev.project_id,
                description=flag_text,
                status=idea_status,
                priority=p.get("priority", 100),
                solver_id=solver_id,
            )
            if idea_index is not None:
                # latest event wins — same idea_id overwrites earlier state
                idea_index[idea_id] = idea
            else:
                state.ideas.append(idea)
            state.facts.append(
                MemoryEntry(
                    entry_id=ev.event_id + "_flag",
                    project_id=ev.project_id,
                    kind=MemoryKind.FACT,
                    content=f"candidate flag: {flag_text}",
                    confidence=p.get("confidence", 0.5),
                    created_at=ev.timestamp,
                )
            )
        elif et == EventType.WORKER_ASSIGNED.value:
            solver_id = p.get("solver_id", ev.event_id)
            # status from payload: Phase F sessions may start as "created"
            status_val = p.get("status", SolverStatus.ASSIGNED.value)
            session = SolverSession(
                solver_id=solver_id,
                project_id=ev.project_id,
                profile=p.get("profile", "network"),
                status=SolverStatus(status_val),
                budget_remaining=p.get("budget_remaining", 0.0),
            )
            if session_index is not None:
                # If solver_id already exists, merge: preserve budget/idea_id unless overridden
                existing = session_index.get(solver_id)
                if existing is not None:
                    session = SolverSession(
                        solver_id=solver_id,
                        project_id=ev.project_id,
                        profile=p.get("profile", existing.profile),
                        status=SolverStatus(status_val),
                        active_idea_id=existing.active_idea_id,
                        local_memory_ids=existing.local_memory_ids,
                        budget_remaining=p.get("budget_remaining", existing.budget_remaining),
                    )
                session_index[solver_id] = session
            else:
                state.sessions.append(session)
        elif et == EventType.WORKER_HEARTBEAT.value:
            # Session status update via heartbeat event (e.g. assigned→running)
            solver_id = p.get("solver_id", "")
            status_val = p.get("status", "")
            if session_index is not None and solver_id and status_val:
                existing = session_index.get(solver_id)
                if existing is not None:
                    session_index[solver_id] = SolverSession(
                        solver_id=solver_id,
                        project_id=existing.project_id,
                        profile=existing.profile,
                        status=SolverStatus(status_val),
                        active_idea_id=existing.active_idea_id,
                        local_memory_ids=existing.local_memory_ids,
                        budget_remaining=existing.budget_remaining,
                    )
        elif et == EventType.WORKER_TIMEOUT.value:
            # Session expiry
            solver_id = p.get("solver_id", "")
            status_val = p.get("status", SolverStatus.EXPIRED.value)
            if session_index is not None and solver_id:
                existing = session_index.get(solver_id)
                if existing is not None:
                    session_index[solver_id] = SolverSession(
                        solver_id=solver_id,
                        project_id=existing.project_id,
                        profile=existing.profile,
                        status=SolverStatus(status_val),
                        active_idea_id=existing.active_idea_id,
                        local_memory_ids=existing.local_memory_ids,
                        budget_remaining=existing.budget_remaining,
                    )
        elif et == EventType.ACTION_OUTCOME.value:
            # Session completion/failure/cancellation (if payload has solver_id + status)
            solver_id = p.get("solver_id", "")
            outcome_status = p.get("status", "")
            if session_index is not None and solver_id and outcome_status:
                existing = session_index.get(solver_id)
                if existing is not None:
                    session_index[solver_id] = SolverSession(
                        solver_id=solver_id,
                        project_id=existing.project_id,
                        profile=existing.profile,
                        status=SolverStatus(outcome_status),
                        active_idea_id=existing.active_idea_id,
                        local_memory_ids=existing.local_memory_ids,
                        budget_remaining=existing.budget_remaining,
                    )
            # Failure boundary fact — original behavior preserved:
            # any ACTION_OUTCOME with status != "ok" produces a failure boundary
            raw_status = p.get("status", "")
            if raw_status != "ok":
                entry_id = p.get("entry_id", ev.event_id)
                state.facts.append(
                    MemoryEntry(
                        entry_id=entry_id,
                        project_id=ev.project_id,
                        kind=MemoryKind.FAILURE_BOUNDARY,
                        content=p.get("error", p.get("summary", "action failed")),
                        confidence=0.0,
                        created_at=ev.timestamp,
                    )
                )
        elif et == EventType.SUBMISSION.value:
            if state.project is not None:
                state.project.status = p.get("result", "submitted")
                state.project.updated_at = ev.timestamp
        elif et == EventType.SECURITY_VALIDATION.value:
            outcome = p.get("outcome", "unknown")
            if outcome in ("deny", "block", "critical"):
                state.facts.append(
                    MemoryEntry(
                        entry_id=ev.event_id,
                        project_id=ev.project_id,
                        kind=MemoryKind.FAILURE_BOUNDARY,
                        content=f"security validation: {outcome} — {p.get('reason', '')}",
                        confidence=0.0,
                        created_at=ev.timestamp,
                    )
                )