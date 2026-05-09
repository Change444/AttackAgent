"""SolverSession lifecycle manager — Phase F.

Manages SolverSession state machine transitions via Blackboard event journal.
Each transition writes an event; materialized state is rebuilt by latest-wins
per solver_id (similar to idea_index in BlackboardService._apply_event).

State machine:
  created → assigned → running → waiting_review
  running → completed / failed
  created / assigned / running → expired
  created / assigned / running → cancelled
  Illegal transitions return None (no event written).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import (
    SolverSession,
    SolverStatus,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class SolverSessionConfig:
    max_project_solvers: int = 1
    session_timeout_seconds: int = 300
    heartbeat_interval_seconds: int = 60
    budget_per_session: float = 20.0


# ---------------------------------------------------------------------------
# Active statuses — used for concurrency check
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = frozenset({
    SolverStatus.CREATED,
    SolverStatus.ASSIGNED,
    SolverStatus.RUNNING,
    SolverStatus.WAITING_REVIEW,
})

_TERMINAL_STATUSES = frozenset({
    SolverStatus.COMPLETED,
    SolverStatus.FAILED,
    SolverStatus.EXPIRED,
    SolverStatus.CANCELLED,
})

# Legal transitions: current_status → set of allowed next statuses
_TRANSITIONS: dict[SolverStatus, frozenset[SolverStatus]] = {
    SolverStatus.CREATED: frozenset({SolverStatus.ASSIGNED, SolverStatus.EXPIRED, SolverStatus.CANCELLED}),
    SolverStatus.ASSIGNED: frozenset({SolverStatus.RUNNING, SolverStatus.EXPIRED, SolverStatus.CANCELLED}),
    SolverStatus.RUNNING: frozenset({
        SolverStatus.WAITING_REVIEW,
        SolverStatus.COMPLETED,
        SolverStatus.FAILED,
        SolverStatus.EXPIRED,
        SolverStatus.CANCELLED,
    }),
    SolverStatus.WAITING_REVIEW: frozenset({
        SolverStatus.RUNNING,
        SolverStatus.EXPIRED,
        SolverStatus.CANCELLED,
    }),
}


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SolverSessionManager:
    """CRUD + lifecycle for SolverSession via Blackboard event journal."""

    def __init__(self, config: SolverSessionConfig | None = None) -> None:
        self.config = config or SolverSessionConfig()

    # -- create --

    def create_session(
        self,
        project_id: str,
        profile: str = "network",
        solver_id: str = "",
    ) -> SolverSession | None:
        """Create a new SolverSession (status=created).

        Rejects if project already has max_project_solvers active sessions.
        Writes WORKER_ASSIGNED event with session_id / solver_id / profile / status / budget_remaining.
        """
        # Concurrency gate: we need a blackboard to check, but create_session
        # is called *before* we have one attached. The caller must check
        # concurrency externally via list_sessions + count active.
        # For now, we just create and let concurrency enforcement happen
        # at claim time or via the scheduler.
        session = SolverSession(
            solver_id=solver_id or _gen_session_id(),
            project_id=project_id,
            profile=profile,
            status=SolverStatus.CREATED,
            budget_remaining=self.config.budget_per_session,
        )
        return session

    def create_and_persist(
        self,
        project_id: str,
        blackboard: BlackboardService,
        profile: str = "network",
        solver_id: str = "",
    ) -> SolverSession | None:
        """Create session AND persist to Blackboard. Rejects if concurrency limit reached."""
        state = blackboard.rebuild_state(project_id)
        active_count = sum(1 for s in state.sessions if s.status in _ACTIVE_STATUSES)
        if active_count >= self.config.max_project_solvers:
            return None

        session = self.create_session(project_id, profile, solver_id)
        if session is None:
            return None

        blackboard.append_event(
            project_id=project_id,
            event_type=EventType.WORKER_ASSIGNED.value,
            payload={
                "solver_id": session.solver_id,
                "profile": session.profile,
                "status": SolverStatus.CREATED.value,
                "budget_remaining": session.budget_remaining,
                "session_id": session.solver_id,
            },
        )
        return session

    # -- claim --

    def claim_session(
        self,
        project_id: str,
        solver_id: str,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        """Find a created/assigned session and mark it assigned.

        Illegal if session is not in created/assigned status.
        """
        session = self._find_session(project_id, solver_id, blackboard)
        if session is None or session.status not in {SolverStatus.CREATED, SolverStatus.ASSIGNED}:
            return None

        self._transition(
            project_id, solver_id, SolverStatus.ASSIGNED, blackboard,
            event_type=EventType.WORKER_ASSIGNED.value,
            payload={"solver_id": solver_id, "status": SolverStatus.ASSIGNED.value},
        )
        return self._find_session(project_id, solver_id, blackboard)

    # -- start --

    def start_session(
        self,
        project_id: str,
        solver_id: str,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        """Mark session as running. Illegal unless current status is assigned."""
        session = self._find_session(project_id, solver_id, blackboard)
        if session is None or session.status != SolverStatus.ASSIGNED:
            return None

        self._transition(
            project_id, solver_id, SolverStatus.RUNNING, blackboard,
            event_type=EventType.WORKER_HEARTBEAT.value,
            payload={"solver_id": solver_id, "status": SolverStatus.RUNNING.value},
        )
        return self._find_session(project_id, solver_id, blackboard)

    # -- heartbeat --

    def heartbeat(
        self,
        project_id: str,
        solver_id: str,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        """Write heartbeat event for a running session."""
        session = self._find_session(project_id, solver_id, blackboard)
        if session is None or session.status != SolverStatus.RUNNING:
            return None

        blackboard.append_event(
            project_id=project_id,
            event_type=EventType.WORKER_HEARTBEAT.value,
            payload={"solver_id": solver_id, "status": SolverStatus.RUNNING.value},
        )
        return session

    # -- complete --

    def complete_session(
        self,
        project_id: str,
        solver_id: str,
        outcome: str,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        """Mark session completed (outcome=ok) or failed (outcome!=ok).

        Rejects duplicate completion on terminal statuses.
        """
        session = self._find_session(project_id, solver_id, blackboard)
        if session is None:
            return None
        if session.status in _TERMINAL_STATUSES:
            return None  # duplicate completion rejection
        if session.status != SolverStatus.RUNNING:
            return None  # illegal transition

        new_status = SolverStatus.COMPLETED if outcome == "ok" else SolverStatus.FAILED
        self._transition(
            project_id, solver_id, new_status, blackboard,
            event_type=EventType.ACTION_OUTCOME.value,
            payload={
                "solver_id": solver_id,
                "status": new_status.value,
                "outcome": outcome,
            },
        )
        return self._find_session(project_id, solver_id, blackboard)

    # -- expire --

    def expire_session(
        self,
        project_id: str,
        solver_id: str,
        timeout_seconds: int,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        """Expire a timed-out session. Illegal on terminal statuses."""
        session = self._find_session(project_id, solver_id, blackboard)
        if session is None or session.status in _TERMINAL_STATUSES:
            return None
        # Only expire if status allows the transition
        if SolverStatus.EXPIRED not in _TRANSITIONS.get(session.status, frozenset()):
            return None

        self._transition(
            project_id, solver_id, SolverStatus.EXPIRED, blackboard,
            event_type=EventType.WORKER_TIMEOUT.value,
            payload={"solver_id": solver_id, "status": SolverStatus.EXPIRED.value, "timeout_seconds": timeout_seconds},
        )
        return self._find_session(project_id, solver_id, blackboard)

    # -- cancel --

    def cancel_session(
        self,
        project_id: str,
        solver_id: str,
        reason: str,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        """Cancel a session. Illegal on terminal statuses."""
        session = self._find_session(project_id, solver_id, blackboard)
        if session is None or session.status in _TERMINAL_STATUSES:
            return None
        if SolverStatus.CANCELLED not in _TRANSITIONS.get(session.status, frozenset()):
            return None

        self._transition(
            project_id, solver_id, SolverStatus.CANCELLED, blackboard,
            event_type=EventType.ACTION_OUTCOME.value,
            payload={"solver_id": solver_id, "status": SolverStatus.CANCELLED.value, "error": reason},
        )
        return self._find_session(project_id, solver_id, blackboard)

    # -- query --

    def get_session(
        self,
        project_id: str,
        solver_id: str,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        return self._find_session(project_id, solver_id, blackboard)

    def list_sessions(
        self,
        project_id: str,
        blackboard: BlackboardService,
    ) -> list[SolverSession]:
        return blackboard.list_sessions(project_id)

    # -- TaskBundle bridge --

    def create_session_from_bundle(
        self,
        bundle,
        project_id: str,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        """Create a SolverSession from a TaskBundle (legacy → vNext mapping extension).

        profile comes from bundle.worker_profile.value,
        budget_remaining from SolverSessionConfig.budget_per_session.
        """
        return self.create_and_persist(
            project_id=project_id,
            profile=bundle.worker_profile.value,
            blackboard=blackboard,
        )

    # -- internals --

    def _find_session(
        self,
        project_id: str,
        solver_id: str,
        blackboard: BlackboardService,
    ) -> SolverSession | None:
        state = blackboard.rebuild_state(project_id)
        for s in state.sessions:
            if s.solver_id == solver_id:
                return s
        return None

    def _transition(
        self,
        project_id: str,
        solver_id: str,
        new_status: SolverStatus,
        blackboard: BlackboardService,
        event_type: str,
        payload: dict,
    ) -> None:
        """Write transition event to Blackboard. The _apply_event in BlackboardService
        will pick it up during rebuild and apply latest-wins per solver_id."""
        blackboard.append_event(
            project_id=project_id,
            event_type=event_type,
            payload=payload,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gen_session_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]