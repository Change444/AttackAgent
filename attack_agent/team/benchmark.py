"""Benchmark Runner — Phase I.

Evaluate team runtime runs against metrics, compare runs, and run
regression checks against baseline fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardEvent
from attack_agent.team.protocol import MemoryKind


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RunMetrics:
    solve_success: bool = False
    total_cycles: int = 0
    failed_attempts: int = 0
    review_count: int = 0
    policy_blocks: int = 0
    submission_attempts: int = 0
    repeated_failure_rate: float = 0.0
    stagnation_events: int = 0
    observation_severity_counts: dict[str, int] = field(default_factory=dict)
    budget_consumed: float = 0.0
    idea_claim_rate: float = 0.0


@dataclass
class MetricsComparison:
    deltas: dict[str, float | int | bool] = field(default_factory=dict)
    overall_score: float = 0.0


@dataclass
class RegressionReport:
    baseline_metrics: dict[str, RunMetrics] = field(default_factory=dict)
    current_metrics: dict[str, RunMetrics] = field(default_factory=dict)
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    overall_status: str = "pass"


# ---------------------------------------------------------------------------
# BenchmarkRunner
# ---------------------------------------------------------------------------

class BenchmarkRunner:

    def evaluate_project(self, project_id: str, blackboard: Any) -> RunMetrics:
        """Compute RunMetrics from a project's event journal."""
        events = blackboard.load_events(project_id)
        state = blackboard.rebuild_state(project_id)

        # solve_success: project status indicates solved
        solve_success = state.project is not None and state.project.status in ("solved", "flag_found")

        # total_cycles: count distinct cycle markers (action_outcome events)
        total_cycles = sum(1 for e in events if e.event_type == EventType.ACTION_OUTCOME.value)

        # failed_attempts: action_outcome events with status != "ok"
        failed_attempts = sum(
            1 for e in events
            if e.event_type == EventType.ACTION_OUTCOME.value and e.payload.get("status", "ok") != "ok"
        )

        # review_count: security_validation events that triggered review
        review_count = sum(
            1 for e in events
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("outcome") == "needs_review"
        )

        # policy_blocks: security_validation events that denied
        policy_blocks = sum(
            1 for e in events
            if e.event_type == EventType.SECURITY_VALIDATION.value
            and e.payload.get("outcome") in ("deny", "block", "budget_exceeded", "rate_limit")
        )

        # submission_attempts: submission events
        submission_attempts = sum(1 for e in events if e.event_type == EventType.SUBMISSION.value)

        # repeated_failure_rate: ratio of distinct failure descriptions to total failures
        failure_contents = [
            e.payload.get("error", e.payload.get("summary", ""))
            for e in events
            if e.event_type == EventType.ACTION_OUTCOME.value and e.payload.get("status", "ok") != "ok"
        ]
        if failed_attempts > 0:
            unique_failures = len(set(failure_contents)) if failure_contents else 0
            repeated_failure_rate = 1.0 - (unique_failures / failed_attempts)
        else:
            repeated_failure_rate = 0.0

        # stagnation_events: checkpoint events with stagnation observation
        stagnation_events = sum(
            1 for e in events
            if e.event_type == EventType.CHECKPOINT.value
            and any(
                obs.get("kind") == "stagnation"
                for obs in e.payload.get("observations", [])
            )
        )

        # observation_severity_counts: from checkpoint events
        severity_counts: dict[str, int] = {}
        for e in events:
            if e.event_type == EventType.CHECKPOINT.value:
                for obs in e.payload.get("observations", []):
                    sev = obs.get("severity", "info")
                    severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # budget_consumed: sum of budget_used from action_outcome payloads
        budget_consumed = sum(
            e.payload.get("budget_used", 0.0)
            for e in events
            if e.event_type == EventType.ACTION_OUTCOME.value
        )

        # idea_claim_rate: ratio of claimed/verified ideas to total ideas
        total_ideas = len(state.ideas)
        claimed_or_verified = sum(
            1 for idea in state.ideas
            if idea.status.value in ("claimed", "testing", "verified")
        )
        idea_claim_rate = (claimed_or_verified / total_ideas) if total_ideas > 0 else 0.0

        return RunMetrics(
            solve_success=solve_success,
            total_cycles=total_cycles,
            failed_attempts=failed_attempts,
            review_count=review_count,
            policy_blocks=policy_blocks,
            submission_attempts=submission_attempts,
            repeated_failure_rate=repeated_failure_rate,
            stagnation_events=stagnation_events,
            observation_severity_counts=severity_counts,
            budget_consumed=budget_consumed,
            idea_claim_rate=idea_claim_rate,
        )

    def compare_metrics(self, run_a: RunMetrics, run_b: RunMetrics) -> MetricsComparison:
        """Compare two RunMetrics, returning deltas and an overall score."""
        deltas: dict[str, float | int | bool] = {}
        numeric_fields = [
            "total_cycles", "failed_attempts", "review_count",
            "policy_blocks", "submission_attempts", "repeated_failure_rate",
            "stagnation_events", "budget_consumed", "idea_claim_rate",
        ]

        for f in numeric_fields:
            va = getattr(run_a, f)
            vb = getattr(run_b, f)
            deltas[f] = vb - va

        deltas["solve_success"] = run_b.solve_success and not run_a.solve_success

        # overall_score: weighted sum of improvements
        # Positive = improvement, negative = regression
        weights = {
            "solve_success": 10.0,
            "total_cycles": -0.5,       # fewer cycles = better
            "failed_attempts": -1.0,    # fewer failures = better
            "review_count": -0.3,
            "policy_blocks": -0.5,
            "submission_attempts": -0.5,
            "repeated_failure_rate": -2.0,
            "stagnation_events": -1.0,
            "budget_consumed": -0.1,
            "idea_claim_rate": 1.0,     # higher claim rate = better
        }
        overall_score = 0.0
        for f, w in weights.items():
            d = deltas.get(f, 0)
            if isinstance(d, bool):
                d = 1.0 if d else 0.0
            # For negative-weight fields, negative delta is actually improvement
            if w < 0:
                overall_score += w * d  # e.g. fewer cycles: d<0, w<0 → positive
            else:
                overall_score += w * d

        return MetricsComparison(deltas=deltas, overall_score=overall_score)

    def run_regression(self, challenge_ids: list[str],
                       current_blackboard: Any,
                       baseline_blackboard: Any) -> RegressionReport:
        """Compare current run metrics against baseline fixtures.

        Both blackboards must already contain completed runs for the
        challenge_ids. This method does NOT run challenges itself —
        it only reads and compares existing event journals.
        """
        baseline_metrics: dict[str, RunMetrics] = {}
        current_metrics: dict[str, RunMetrics] = {}
        regressions: list[str] = []
        improvements: list[str] = []

        for cid in challenge_ids:
            bm = self.evaluate_project(cid, baseline_blackboard)
            cm = self.evaluate_project(cid, current_blackboard)
            baseline_metrics[cid] = bm
            current_metrics[cid] = cm

            comp = self.compare_metrics(bm, cm)
            for field_name, delta in comp.deltas.items():
                if field_name == "solve_success":
                    if delta:
                        improvements.append(f"{cid}: newly solved")
                    elif not cm.solve_success and bm.solve_success:
                        regressions.append(f"{cid}: lost solve")
                elif isinstance(delta, (int, float)):
                    if delta < 0 and field_name in (
                        "total_cycles", "failed_attempts", "review_count",
                        "policy_blocks", "submission_attempts",
                        "repeated_failure_rate", "stagnation_events",
                        "budget_consumed",
                    ):
                        improvements.append(f"{cid}: {field_name} decreased by {abs(delta):.2f}")
                    elif delta > 0 and field_name in (
                        "total_cycles", "failed_attempts", "review_count",
                        "policy_blocks", "submission_attempts",
                        "repeated_failure_rate", "stagnation_events",
                        "budget_consumed",
                    ):
                        regressions.append(f"{cid}: {field_name} increased by {delta:.2f}")
                    elif delta > 0 and field_name == "idea_claim_rate":
                        improvements.append(f"{cid}: {field_name} increased by {delta:.2f}")
                    elif delta < 0 and field_name == "idea_claim_rate":
                        regressions.append(f"{cid}: {field_name} decreased by {abs(delta):.2f}")

        overall = "pass"
        if regressions and not improvements:
            overall = "fail"
        elif regressions and improvements:
            overall = "mixed"
        elif improvements:
            overall = "pass"

        return RegressionReport(
            baseline_metrics=baseline_metrics,
            current_metrics=current_metrics,
            regressions=regressions,
            improvements=improvements,
            overall_status=overall,
        )