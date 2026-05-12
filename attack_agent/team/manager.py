"""TeamManager — Phase C.

Translates Dispatcher / CompetitionPlatform decision logic into StrategyAction
protocol objects. All decisions are recorded via Blackboard event journal.

Decision thresholds are ported from Dispatcher defaults:
- stagnation_threshold = 8
- confidence_threshold = 0.6
- recent_failures_limit = 4
- tombstone_threshold = 2
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.team.blackboard import BlackboardEvent
from attack_agent.team.event_compat import is_genuine_candidate_flag
from attack_agent.team.protocol import (
    ActionType,
    StrategyAction,
    TeamProject,
)


@dataclass
class ManagerConfig:
    stagnation_threshold: int = 8
    confidence_threshold: float = 0.6
    recent_failures_limit: int = 4
    tombstone_threshold: int = 2
    max_cycles: int = 12


class TeamManager:
    """Pure decision function: reads events, returns StrategyAction.

    No direct state mutation — all side effects go through Blackboard.
    """

    def __init__(self, config: ManagerConfig | None = None) -> None:
        self.config = config or ManagerConfig()

    # -- project admission --

    def admit_project(self, team_project: TeamProject) -> StrategyAction:
        """New project → launch a solver."""
        return StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id=team_project.project_id,
            reason="project admitted",
            priority=100,
        )

    # -- stage transition --

    def decide_stage_transition(
        self,
        project_id: str,
        current_stage: str,
        events: list[BlackboardEvent],
    ) -> StrategyAction | None:
        """Decide next stage based on current stage and event history.

        Stage machine (ported from Dispatcher):
        bootstrap → reason → explore → converge / abandon
        """
        if current_stage == "bootstrap":
            return StrategyAction(
                action_type=ActionType.LAUNCH_SOLVER,
                project_id=project_id,
                reason="bootstrap → reason: assign solver profile",
            )
        if current_stage == "reason":
            return StrategyAction(
                action_type=ActionType.STEER_SOLVER,
                project_id=project_id,
                reason="reason → explore: pattern graph ready",
            )
        # explore stage — check for convergence or abandon
        state = self._compute_stagnation(project_id, events)
        if state.should_abandon:
            return StrategyAction(
                action_type=ActionType.ABANDON,
                project_id=project_id,
                reason=f"abandon: stagnation={state.stagnation_counter}, "
                        f"dead_ends={state.dead_end_count}, low_novelty={state.low_novelty}",
            )
        # candidate flags present → converge
        if state.has_candidate_flags:
            return StrategyAction(
                action_type=ActionType.CONVERGE,
                project_id=project_id,
                reason=f"converge: {state.candidate_flag_count} candidate flags",
            )
        # still exploring — steer solver
        return StrategyAction(
            action_type=ActionType.STEER_SOLVER,
            project_id=project_id,
            reason="continue explore",
        )

    # -- solver assignment --

    def assign_solver(
        self, project_id: str, profile: str = "network"
    ) -> StrategyAction:
        """Assign a solver with the given profile."""
        return StrategyAction(
            action_type=ActionType.LAUNCH_SOLVER,
            project_id=project_id,
            reason=f"assign solver: profile={profile}",
            risk_level="low",
        )

    # -- heartbeat --

    def handle_solver_heartbeat(
        self, project_id: str, solver_id: str
    ) -> StrategyAction:
        """Acknowledge heartbeat — solver is alive."""
        return StrategyAction(
            action_type=ActionType.STEER_SOLVER,
            project_id=project_id,
            target_solver_id=solver_id,
            reason="heartbeat acknowledged",
            priority=50,
        )

    # -- timeout / requeue --

    def handle_solver_timeout(
        self,
        project_id: str,
        solver_id: str,
        events: list[BlackboardEvent],
    ) -> StrategyAction:
        """Decide requeue vs abandon after solver timeout.

        Ported from Dispatcher.should_abandon + requeue logic.
        """
        state = self._compute_stagnation(project_id, events)
        if state.should_abandon:
            return StrategyAction(
                action_type=ActionType.ABANDON,
                project_id=project_id,
                target_solver_id=solver_id,
                reason=f"abandon after timeout: stagnation={state.stagnation_counter}",
            )
        # requeue — back to explore
        return StrategyAction(
            action_type=ActionType.STEER_SOLVER,
            project_id=project_id,
            target_solver_id=solver_id,
            reason="requeue after timeout",
        )

    # -- convergence --

    def decide_convergence(
        self, project_id: str, events: list[BlackboardEvent]
    ) -> StrategyAction:
        """Decide whether to converge, abandon, or keep exploring."""
        state = self._compute_stagnation(project_id, events)
        if state.should_abandon:
            return StrategyAction(
                action_type=ActionType.ABANDON,
                project_id=project_id,
                reason=f"abandon: stagnation={state.stagnation_counter}",
            )
        if state.has_candidate_flags:
            return StrategyAction(
                action_type=ActionType.CONVERGE,
                project_id=project_id,
                reason=f"converge: {state.candidate_flag_count} candidate flags",
            )
        return StrategyAction(
            action_type=ActionType.STEER_SOLVER,
            project_id=project_id,
            reason="keep exploring",
        )

    # -- submit --

    def decide_submit(
        self, project_id: str, events: list[BlackboardEvent]
    ) -> StrategyAction:
        """Decide whether to submit a candidate flag.

        Ported from SubmitClassifier logic:
        - confidence >= threshold → submit
        - confidence < threshold → converge (wait)
        - no candidates → abandon
        """
        candidates = self._extract_candidates(events)
        if not candidates:
            return StrategyAction(
                action_type=ActionType.ABANDON,
                project_id=project_id,
                reason="no candidate flags to submit",
            )
        best = max(candidates, key=lambda c: c.confidence)
        if best.confidence >= self.config.confidence_threshold:
            return StrategyAction(
                action_type=ActionType.SUBMIT_FLAG,
                project_id=project_id,
                target_idea_id=best.idea_id,
                reason=f"submit: confidence={best.confidence:.2f} >= "
                        f"{self.config.confidence_threshold:.2f}",
                risk_level="high",
                requires_review=True,
            )
        return StrategyAction(
            action_type=ActionType.CONVERGE,
            project_id=project_id,
            reason=f"wait: best confidence={best.confidence:.2f} < "
                   f"{self.config.confidence_threshold:.2f}",
        )

    # -- internal helpers --

    @dataclass
    class _StagnationState:
        stagnation_counter: int = 0
        should_abandon: bool = False
        has_candidate_flags: bool = False
        candidate_flag_count: int = 0
        dead_end_count: int = 0
        low_novelty: bool = False

    @dataclass
    class _CandidateInfo:
        idea_id: str = ""
        confidence: float = 0.0

    def _compute_stagnation(
        self, project_id: str, events: list[BlackboardEvent]
    ) -> _StagnationState:
        """Compute stagnation state from event journal.

        Ported from Dispatcher._update_after_outcome + should_abandon.
        Candidate flags override abandon — same as Dispatcher which
        sets CONVERGE when candidate_flags exist before checking abandon.
        """
        result = TeamManager._StagnationState()
        candidate_count = 0
        failure_count = 0
        novelty_reset = False
        tombstones = 0

        for ev in events:
            p = ev.payload
            et = ev.event_type

            # candidate flags — only genuine extracted flags
            if et == "candidate_flag":
                if is_genuine_candidate_flag(et, p, ev.source):
                    candidate_count += 1
            # action outcomes
            elif et == "action_outcome":
                status = p.get("status", "")
                novelty = p.get("novelty", 0.0)
                if status == "ok" and novelty > 0.0:
                    novelty_reset = True
                if status != "ok":
                    failure_count += 1
            # tombstones / security blocks count as dead ends
            elif et in ("project_abandoned", "security_validation"):
                outcome = p.get("outcome", "")
                if outcome in ("deny", "block", "critical"):
                    tombstones += 1

        result.candidate_flag_count = candidate_count
        result.has_candidate_flags = candidate_count > 0
        result.dead_end_count = tombstones

        # stagnation counter: reset if any novelty, else count failures
        if novelty_reset:
            result.stagnation_counter = 0
        else:
            result.stagnation_counter = failure_count

        # candidate flags present → never abandon (same as Dispatcher:
        # candidate_flags set stage to CONVERGE before abandon check)
        if result.has_candidate_flags:
            result.should_abandon = False
        elif result.stagnation_counter >= self.config.stagnation_threshold:
            repeated_dead_ends = result.dead_end_count >= self.config.tombstone_threshold
            result.low_novelty = failure_count > 0
            result.should_abandon = repeated_dead_ends or result.low_novelty

        return result

    def _extract_candidates(
        self, events: list[BlackboardEvent]
    ) -> list[_CandidateInfo]:
        """Extract candidate flag info from event journal — only genuine flags."""
        candidates: list[TeamManager._CandidateInfo] = []
        for ev in events:
            if ev.event_type == "candidate_flag":
                if is_genuine_candidate_flag(ev.event_type, ev.payload, ev.source):
                    p = ev.payload
                    candidates.append(
                        TeamManager._CandidateInfo(
                            idea_id=ev.event_id,
                            confidence=p.get("confidence", 0.5),
                        )
                    )
        return candidates