"""SyncScheduler — Phase C.

Synchronous single-thread scheduler that loops schedule_cycle until
projects reach done / abandoned. Keeps concurrency=1 by default.

Ported from CompetitionPlatform.solve_all() control flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.event_compat import is_genuine_candidate_flag
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.memory_reducer import MemoryReducer
from attack_agent.team.protocol import (
    ActionType,
    MemoryEntry,
    MemoryKind,
    ReviewRequest,
    SolverStatus,
    StrategyAction,
    TeamProject,
    to_dict,
)
from attack_agent.team.review import HumanReviewGate
from attack_agent.team.solver import SolverSessionManager

if TYPE_CHECKING:
    from attack_agent.team.context import ContextCompiler
    from attack_agent.team.policy import PolicyHarness
    from attack_agent.team.runtime import TeamRuntime


@dataclass
class SchedulerConfig:
    max_cycles: int = 12
    max_project_solvers: int = 1


class SyncScheduler:
    """Synchronous scheduler: read events → Manager decisions → write events."""

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()

    def execute_strategy_action(
        self,
        action: StrategyAction,
        project_id: str,
        blackboard: BlackboardService,
        runtime: TeamRuntime | None = None,
        policy_harness: PolicyHarness | None = None,
        review_gate: HumanReviewGate | None = None,
    ) -> list[StrategyAction]:
        """Execute a StrategyAction through the hard policy gate.

        L3 hard gate: every action passes PolicyHarness.validate_action().
        - deny/budget_exceeded/rate_limit → no record, no execution, return []
        - needs_review → record action, create ReviewRequest with full payload
          and causal_ref to action event, return without execution
        - allow → record and execute the action
        """
        if policy_harness is not None:
            policy_result = policy_harness.validate_action(action, project_id, blackboard)
            if policy_result.decision.value in ("deny", "budget_exceeded", "rate_limit"):
                return []
            if policy_result.decision.value == "needs_review":
                action.requires_review = True
                action.policy_tags = action.policy_tags + ["needs_review"]
                ev = _record_action(blackboard, action, return_event=True)
                request = ReviewRequest(
                    project_id=project_id,
                    action_type=action.action_type.value,
                    risk_level=action.risk_level,
                    title=f"Review required: {action.action_type.value}",
                    description=action.reason,
                    proposed_action=str(action.action_type.value),
                    proposed_action_payload=to_dict(action),
                )
                gate = review_gate or HumanReviewGate()
                causal_ref = ev.event_id if ev is not None else None
                gate.create_review(request, blackboard, causal_ref=causal_ref)
                return [action]

        # Policy allows (or no policy harness) — record only.
        # Actual execution is handled by schedule_cycle() or callers.
        _record_action(blackboard, action)
        return [action]

    def schedule_cycle(
        self,
        project_id: str,
        manager: TeamManager,
        blackboard: BlackboardService,
        runtime: TeamRuntime | None = None,
        context_compiler: ContextCompiler | None = None,
        policy_harness: PolicyHarness | None = None,
        solver_manager: SolverSessionManager | None = None,
    ) -> list[StrategyAction]:
        """One scheduling cycle for a project.

        1. Read current state from Blackboard.
        2. Ask Manager for decisions.
        3. Record each decision as an event in the journal.
        4. If runtime has real executor and action requires execution,
           call runtime._execute_solver_cycle() to run a real cycle.
           (One call now covers BOOTSTRAP→REASON→EXPLORE advancement
           + first EXPLORE execution, matching CompetitionPlatform.run_cycle.)
        5. After execution, re-evaluate for converge/submit.
        6. Return the list of StrategyActions taken.
        """
        events = blackboard.load_events(project_id)
        state = blackboard.rebuild_state(project_id)

        if state.project is None:
            return []

        project = state.project

        if project.status in ("done", "abandoned"):
            return []

        current_stage = _infer_stage(events, project.status)

        # -- L2: compile ManagerContext when compiler available --
        ctx = None
        if context_compiler is not None:
            ctx = context_compiler.compile_manager_context(project_id, blackboard)

        # -- L2: use context-aware method when context available --
        if ctx is not None:
            action = manager.decide_stage_transition_from_context(
                project_id, current_stage, ctx
            )
        else:
            action = manager.decide_stage_transition(
                project_id, current_stage, events
            )

        if action is None:
            return []

        # -- L3: hard policy gate via execute_strategy_action --
        gate_actions = self.execute_strategy_action(
            action, project_id, blackboard, runtime, policy_harness,
        )
        if not gate_actions:
            # policy denied/budget_exceeded/rate_limit — no action taken
            return []
        if action.requires_review:
            # L3 hard gate: needs_review recorded but NOT executed
            # Review approval will re-execute the action later
            return gate_actions

        # Action was allowed by policy — check for follow-up converge/submit

        # -- L5: create/claim/start SolverSession before execution --
        solver_id = ""
        if (
            solver_manager is not None
            and runtime is not None
            and runtime.use_real_executor
            and action.action_type in (ActionType.LAUNCH_SOLVER, ActionType.STEER_SOLVER)
        ):
            if action.action_type == ActionType.LAUNCH_SOLVER:
                session = solver_manager.create_and_persist(
                    project_id, blackboard, profile="network",
                )
                if session is None:
                    # Concurrency limit reached — cannot launch new solver
                    return [action]
                solver_id = session.solver_id
            elif action.action_type == ActionType.STEER_SOLVER and action.target_solver_id:
                # STEER_SOLVER: reuse existing session if still active
                existing = solver_manager.get_session(
                    project_id, action.target_solver_id, blackboard
                )
                if existing is not None and existing.status in (
                    SolverStatus.ASSIGNED, SolverStatus.RUNNING,
                    SolverStatus.WAITING_REVIEW,
                ):
                    solver_id = existing.solver_id
                else:
                    session = solver_manager.create_and_persist(
                        project_id, blackboard, profile="network",
                    )
                    if session is None:
                        return [action]
                    solver_id = session.solver_id
            else:
                # STEER_SOLVER without target_solver_id — create new
                session = solver_manager.create_and_persist(
                    project_id, blackboard, profile="network",
                )
                if session is None:
                    return [action]
                solver_id = session.solver_id

            # Claim session → ASSIGNED
            solver_manager.claim_session(project_id, solver_id, blackboard)

            # Claim idea lease: bind solver to best unclaimed idea
            if runtime.ideas is not None:
                best_idea = runtime.ideas.get_best_unclaimed(project_id)
                if best_idea is not None:
                    runtime.ideas.claim(project_id, best_idea.idea_id, solver_id)
                    blackboard.append_event(
                        project_id=project_id,
                        event_type=EventType.WORKER_ASSIGNED.value,
                        payload={
                            "solver_id": solver_id,
                            "status": SolverStatus.ASSIGNED.value,
                            "active_idea_id": best_idea.idea_id,
                        },
                        source="scheduler_l5",
                    )

            # Start session → RUNNING
            solver_manager.start_session(project_id, solver_id, blackboard)

        # Execute real solver cycle if runtime has executor capability
        if (
            runtime is not None
            and runtime.use_real_executor
            and action.action_type in (ActionType.LAUNCH_SOLVER, ActionType.STEER_SOLVER)
        ):
            result = runtime._execute_solver_cycle(project_id, solver_id)
            if result is not None:
                # Post-execution: sync delta from StateGraphService to Blackboard
                if runtime.state_sync is not None and runtime._state_graph is not None:
                    runtime.state_sync.sync_delta(
                        project_id, runtime._state_graph, blackboard
                    )

                # -- L4: compile solver context and update session binding --
                if context_compiler is not None:
                    solver_session = None
                    if solver_manager is not None and solver_id:
                        solver_session = solver_manager.get_session(
                            project_id, solver_id, blackboard
                        )
                    if solver_id:
                        solver_ctx = context_compiler.compile_solver_context(
                            project_id, solver_id, blackboard
                        )
                        # Run memory reducer over recent events
                        reducer = MemoryReducer()
                        recent_events = blackboard.load_events(project_id)
                        reduced = reducer.reduce_observations(recent_events, project_id)
                        # Persist extracted credentials and endpoints
                        for entry in reduced.credentials:
                            runtime.memory.store_entry(project_id, entry)
                        for entry in reduced.endpoints:
                            runtime.memory.store_entry(project_id, entry)
                        # Update SolverSession with L4 fields via WORKER_HEARTBEAT
                        local_mem_ids = [m.entry_id for m in solver_ctx.local_memory[:5]]
                        active_idea_id = solver_ctx.active_idea.idea_id if solver_ctx.active_idea else ""
                        cost = result.get("cost", 0.0) or 0.0
                        budget_remaining = max(0.0, solver_session.budget_remaining - cost) if solver_session else 0.0
                        blackboard.append_event(
                            project_id=project_id,
                            event_type=EventType.WORKER_HEARTBEAT.value,
                            payload={
                                "solver_id": solver_id,
                                "status": SolverStatus.RUNNING.value,
                                "budget_remaining": budget_remaining,
                                "active_idea_id": active_idea_id,
                                "local_memory_ids": local_mem_ids,
                                "scratchpad_summary": reduced.scratchpad_summary,
                                "recent_event_ids": reduced.event_ids_seen[-20:],
                            },
                            source="scheduler_l4",
                        )

                # -- L5: complete session after execution --
                if solver_manager is not None and solver_id:
                    outcome_str = "ok" if result.get("status") == "ok" else "error"
                    solver_manager.complete_session(
                        project_id, solver_id, outcome_str, blackboard
                    )

                # After execution, re-evaluate state for converge/submit
                events = blackboard.load_events(project_id)
                state = blackboard.rebuild_state(project_id)
                if state.project is not None and state.project.status not in ("done", "abandoned"):
                    # -- L2: compile context for follow-up if available --
                    follow_up_ctx = None
                    if context_compiler is not None:
                        follow_up_ctx = context_compiler.compile_manager_context(project_id, blackboard)

                    if follow_up_ctx is not None:
                        follow_up = manager.decide_stage_transition_from_context(
                            project_id, _infer_stage(events, state.project.status), follow_up_ctx
                        )
                    else:
                        follow_up = manager.decide_stage_transition(
                            project_id, _infer_stage(events, state.project.status), events
                        )
                    if follow_up is not None:
                        follow_up_gate = self.execute_strategy_action(
                            follow_up, project_id, blackboard, runtime,
                            policy_harness,
                        )
                        if not follow_up_gate:
                            return [action]
                        if follow_up.requires_review:
                            return [action, follow_up]
                        if follow_up.action_type == ActionType.CONVERGE:
                            if follow_up_ctx is not None:
                                submit_action = manager.decide_submit_from_context(follow_up_ctx)
                            else:
                                submit_action = manager.decide_submit(project_id, events)
                            submit_gate = self.execute_strategy_action(
                                submit_action, project_id, blackboard, runtime,
                                policy_harness,
                            )
                            if submit_gate and not submit_action.requires_review:
                                _execute_submit_if_possible(runtime, project_id, submit_action, blackboard)
                            return [action, follow_up, submit_action]
                        return [action, follow_up]
                return [action]
            else:
                # _execute_solver_cycle returned None — mark session failed
                if solver_manager is not None and solver_id:
                    solver_manager.complete_session(
                        project_id, solver_id, "error", blackboard
                    )
                return [action]

        # for converge stage, also check submit
        if action.action_type == ActionType.CONVERGE:
            if ctx is not None:
                submit_action = manager.decide_submit_from_context(ctx)
            else:
                submit_action = manager.decide_submit(project_id, events)
            submit_gate = self.execute_strategy_action(
                submit_action, project_id, blackboard, runtime, policy_harness,
            )
            if submit_gate and not submit_action.requires_review:
                _execute_submit_if_possible(runtime, project_id, submit_action, blackboard)
            return [action, submit_action]

        return [action]

    def run_project(
        self,
        project_id: str,
        manager: TeamManager,
        blackboard: BlackboardService,
        runtime: TeamRuntime | None = None,
        context_compiler: ContextCompiler | None = None,
        policy_harness: PolicyHarness | None = None,
        solver_manager: SolverSessionManager | None = None,
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

            self.schedule_cycle(
                project_id, manager, blackboard, runtime,
                context_compiler, policy_harness, solver_manager,
            )

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
        runtime: TeamRuntime | None = None,
        context_compiler: ContextCompiler | None = None,
        policy_harness: PolicyHarness | None = None,
        solver_manager: SolverSessionManager | None = None,
    ) -> dict[str, TeamProject]:
        """Run all projects sequentially (concurrency=1)."""
        results: dict[str, TeamProject] = {}
        for pid in project_ids:
            results[pid] = self.run_project(
                pid, manager, blackboard, runtime,
                context_compiler, policy_harness, solver_manager,
            )
        return results


# -- helpers --

def _infer_stage(events: list, project_status: str) -> str:
    """Infer current stage from event history and project status.

    When project_upserted events carry a 'stage' field (written by
    _execute_solver_cycle or solve_all), use the latest one as the
    authoritative stage. Otherwise fall back to event-type inference.
    """
    if project_status == "done":
        return "done"
    if project_status == "abandoned":
        return "abandoned"

    # Check latest project_upserted event for explicit stage
    for ev in reversed(events):
        if ev.event_type == EventType.PROJECT_UPSERTED.value:
            stage = ev.payload.get("stage", "")
            if stage in ("bootstrap", "reason", "explore", "converge", "done", "abandoned"):
                return stage

    # Fall back to event-type inference
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
            # Only genuine flags count as convergence events
            if is_genuine_candidate_flag(et, ev.payload, ev.source):
                has_convergence_events = True
        elif et == EventType.STRATEGY_ACTION.value:
            if ev.payload.get("action_type") == "converge":
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
    blackboard: BlackboardService, action: StrategyAction,
    return_event: bool = False,
) -> Any | None:
    """Write a StrategyAction decision to the Blackboard event journal.
    Returns the BlackboardEvent if return_event=True (for causal_ref extraction)."""
    payload = to_dict(action)
    event_type = _action_to_event_type(action.action_type)
    ev = blackboard.append_event(
        action.project_id,
        event_type,
        payload,
        source="manager",
    )
    if return_event:
        return ev
    return None


def _action_to_event_type(action_type: ActionType) -> str:
    """Map StrategyAction action_type to a Blackboard EventType string."""
    mapping = {
        ActionType.LAUNCH_SOLVER: EventType.WORKER_ASSIGNED.value,
        ActionType.STEER_SOLVER: EventType.REQUEUE.value,
        ActionType.SUBMIT_FLAG: EventType.SUBMISSION.value,
        ActionType.CONVERGE: EventType.STRATEGY_ACTION.value,
        ActionType.ABANDON: EventType.PROJECT_ABANDONED.value,
        ActionType.STOP_SOLVER: EventType.WORKER_TIMEOUT.value,
    }
    return mapping.get(action_type, EventType.REQUEUE.value)


def _execute_submit_if_possible(
    runtime: TeamRuntime | None,
    project_id: str,
    submit_action: StrategyAction,
    blackboard: BlackboardService,
) -> None:
    """Execute real flag submission via runtime.submit_flag() if possible.
    L3 hard gate: do NOT execute if action requires_review."""
    if runtime is None or not runtime.use_real_executor:
        return
    if submit_action.action_type != ActionType.SUBMIT_FLAG:
        return
    # L3: requires_review means submission is waiting for review approval
    if submit_action.requires_review:
        return

    state_graph = runtime._state_graph
    if state_graph is None:
        return
    record = state_graph.projects.get(project_id)
    if record is None or not record.candidate_flags:
        return

    # Extract first available flag from StateGraphService
    dk, candidate = next(iter(record.candidate_flags.items()))
    runtime.submit_flag(project_id, candidate.value, idea_id=dk)

    # After submission, sync DONE state to Blackboard if flag was accepted
    record = state_graph.projects.get(project_id)
    if record is not None and record.snapshot.stage.value == "done":
        blackboard.append_event(
            project_id=project_id,
            event_type=EventType.PROJECT_UPSERTED.value,
            payload={
                "challenge_id": record.snapshot.challenge.id,
                "status": "done",
                "stage": "done",
            },
            source="scheduler",
        )