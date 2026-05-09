"""SyncScheduler — Phase C.

Synchronous single-thread scheduler that loops schedule_cycle until
projects reach done / abandoned. Keeps concurrency=1 by default.

Ported from CompetitionPlatform.solve_all() control flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.protocol import (
    ActionType,
    StrategyAction,
    TeamProject,
    to_dict,
)


@dataclass
class SchedulerConfig:
    max_cycles: int = 12
    max_project_solvers: int = 1


class SyncScheduler:
    """Synchronous scheduler: read events → Manager decisions → write events."""

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()

    def schedule_cycle(
        self,
        project_id: str,
        manager: TeamManager,
        blackboard: BlackboardService,
    ) -> list[StrategyAction]:
        """One scheduling cycle for a project.

        1. Read current state from Blackboard.
        2. Ask Manager for decisions.
        3. Record each decision as an event in the journal.
        4. Return the list of StrategyActions taken.
        """
        events = blackboard.load_events(project_id)
        state = blackboard.rebuild_state(project_id)

        if state.project is None:
            # project not yet admitted — nothing to do
            return []

        project = state.project

        # terminal states — no action needed
        if project.status in ("done", "abandoned"):
            return []

        # determine current stage from event history
        current_stage = _infer_stage(events, project.status)

        # ask manager for the primary decision
        action = manager.decide_stage_transition(
            project_id, current_stage, events
        )
        if action is None:
            return []

        # record the decision event
        _record_action(blackboard, action)

        # for converge stage, also check submit
        if action.action_type == ActionType.CONVERGE:
            submit_action = manager.decide_submit(project_id, events)
            _record_action(blackboard, submit_action)
            return [action, submit_action]

        return [action]

    def run_project(
        self,
        project_id: str,
        manager: TeamManager,
        blackboard: BlackboardService,
    ) -> TeamProject:
        """Run a project until done / abandoned.

        Loops schedule_cycle up to max_cycles times.
        """
        for _ in range(self.config.max_cycles):
            state = blackboard.rebuild_state(project_id)
            if state.project is None:
                # project hasn't been admitted yet — admit it first
                team_project = TeamProject(project_id=project_id)
                blackboard.append_event(
                    project_id,
                    EventType.PROJECT_UPSERTED.value,
                    {"challenge_id": "", "status": "new"},
                    source="scheduler",
                )
                # re-admit through manager
                action = manager.admit_project(team_project)
                _record_action(blackboard, action)

            state = blackboard.rebuild_state(project_id)
            if state.project is not None and state.project.status in ("done", "abandoned"):
                return state.project

            self.schedule_cycle(project_id, manager, blackboard)

        # max cycles reached — mark abandoned if not done
        state = blackboard.rebuild_state(project_id)
        if state.project is not None and state.project.status not in ("done", "abandoned"):
            blackboard.append_event(
                project_id,
                EventType.PROJECT_UPSERTED.value,
                {
                    "challenge_id": state.project.challenge_id,
                    "status": "abandoned",
                },
                source="scheduler",
            )
            state = blackboard.rebuild_state(project_id)

        return state.project or TeamProject(project_id=project_id, status="abandoned")

    def run_all(
        self,
        manager: TeamManager,
        blackboard: BlackboardService,
        project_ids: list[str],
    ) -> dict[str, TeamProject]:
        """Run all projects sequentially (concurrency=1)."""
        results: dict[str, TeamProject] = {}
        for pid in project_ids:
            results[pid] = self.run_project(pid, manager, blackboard)
        return results


# -- helpers --

def _infer_stage(events: list, project_status: str) -> str:
    """Infer current stage from event history and project status."""
    if project_status == "done":
        return "done"
    if project_status == "abandoned":
        return "abandoned"

    # look at the most recent stage-relevant events
    has_reason = False
    has_explore = False
    has_convergence_events = False

    for ev in events:
        et = ev.event_type
        if et == EventType.WORKER_ASSIGNED.value:
            has_reason = True
        if et in (EventType.OBSERVATION.value, EventType.ACTION_OUTCOME.value):
            has_explore = True
        if et == EventType.CANDIDATE_FLAG.value:
            has_convergence_events = True
        if et == EventType.PROJECT_ABANDONED.value:
            return "abandoned"
        if et == EventType.PROJECT_DONE.value:
            return "done"

    if has_convergence_events:
        return "converge"
    if has_explore:
        return "explore"
    if has_reason:
        return "reason"
    return "bootstrap"


def _record_action(
    blackboard: BlackboardService, action: StrategyAction
) -> None:
    """Write a StrategyAction decision to the Blackboard event journal."""
    payload = to_dict(action)
    event_type = _action_to_event_type(action.action_type)
    blackboard.append_event(
        action.project_id,
        event_type,
        payload,
        source="manager",
    )


def _action_to_event_type(action_type: ActionType) -> str:
    """Map StrategyAction action_type to a Blackboard EventType string."""
    mapping = {
        ActionType.LAUNCH_SOLVER: EventType.WORKER_ASSIGNED.value,
        ActionType.STEER_SOLVER: EventType.REQUEUE.value,
        ActionType.SUBMIT_FLAG: EventType.SUBMISSION.value,
        ActionType.CONVERGE: EventType.CANDIDATE_FLAG.value,
        ActionType.ABANDON: EventType.PROJECT_ABANDONED.value,
        ActionType.STOP_SOLVER: EventType.WORKER_TIMEOUT.value,
    }
    return mapping.get(action_type, EventType.REQUEUE.value)