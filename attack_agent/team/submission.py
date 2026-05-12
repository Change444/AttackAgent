"""Phase G — SubmissionVerifier: internal verification passes before flag submission."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.protocol import MemoryKind, _gen_id
from attack_agent.platform_models import EventType


@dataclass
class CheckResult:
    check_name: str = ""
    passed: bool = False
    detail: str = ""


@dataclass
class VerificationResult:
    status: str = "passed"       # passed / failed / warning
    checks: list[CheckResult] = field(default_factory=list)
    reason: str = ""


@dataclass
class SubmissionConfig:
    max_submissions: int = 3
    flag_pattern: str = r"flag\{[^}]+\}"


class SubmissionVerifier:
    """Run verification passes before submitting a candidate flag."""

    def __init__(self, blackboard: BlackboardService) -> None:
        self._bb = blackboard

    def verify_flag_format(self, project_id: str, flag_value: str,
                           config: SubmissionConfig | None = None) -> VerificationResult:
        config = config or SubmissionConfig()
        pattern = config.flag_pattern
        match = re.search(pattern, flag_value)
        passed = match is not None

        result = VerificationResult(
            status="passed" if passed else "failed",
            checks=[CheckResult(
                check_name="flag_format",
                passed=passed,
                detail=f"pattern={pattern}, match={match.group(0) if match else 'none'}",
            )],
            reason="" if passed else f"flag '{flag_value}' does not match pattern '{pattern}'",
        )
        self._bb.append_event(
            project_id=project_id,
            event_type=EventType.SECURITY_VALIDATION.value,
            payload={
                "outcome": "pass" if passed else "deny",
                "reason": result.reason or "flag format verified",
                "check": "flag_format",
                "flag_value": flag_value,
                "format_match": passed,
            },
            source="submission_verifier",
        )
        return result

    def verify_evidence_chain(self, project_id: str, idea_id: str) -> VerificationResult:
        ideas = self._bb.list_ideas(project_id)
        target = None
        for i in ideas:
            if i.idea_id == idea_id:
                target = i
                break

        if target is None:
            # idea_id may be a CandidateFlag dedupe_key from StateGraphService
            # that isn't registered in IdeaService — this is expected when
            # flags are found via the real executor path. Treat as advisory.
            result = VerificationResult(
                status="warning",
                checks=[CheckResult(check_name="evidence_chain", passed=False,
                                    detail=f"idea {idea_id} not found in blackboard")],
                reason="idea not found in blackboard (advisory, not blocking)",
            )
        else:
            refs = target.failure_boundary_refs if hasattr(target, "failure_boundary_refs") else []
            # check that referenced evidence entries exist in facts
            state = self._bb.rebuild_state(project_id)
            all_ids = {f.entry_id for f in state.facts}
            missing = [r for r in refs if r not in all_ids]
            passed = len(missing) == 0

            result = VerificationResult(
                status="passed" if passed else "failed",
                checks=[CheckResult(
                    check_name="evidence_chain",
                    passed=passed,
                    detail=f"refs={len(refs)}, missing={len(missing)}"
                    + (f", missing_ids={missing}" if missing else ""),
                )],
                reason="" if passed else "evidence chain incomplete",
            )

        self._bb.append_event(
            project_id=project_id,
            event_type=EventType.SECURITY_VALIDATION.value,
            payload={
                "outcome": "pass" if result.status in ("passed", "warning") else "deny",
                "reason": result.reason or "evidence chain verified",
                "check": "evidence_chain",
                "idea_id": idea_id,
            },
            source="submission_verifier",
        )
        return result

    def verify_submission_budget(self, project_id: str,
                                 config: SubmissionConfig | None = None) -> VerificationResult:
        config = config or SubmissionConfig()
        events = self._bb.load_events(project_id)
        submission_count = sum(
            1 for e in events if e.event_type == EventType.SUBMISSION.value
        )
        passed = submission_count < config.max_submissions

        result = VerificationResult(
            status="passed" if passed else "failed",
            checks=[CheckResult(
                check_name="submission_budget",
                passed=passed,
                detail=f"submissions={submission_count}, max={config.max_submissions}",
            )],
            reason="" if passed else f"submission budget exceeded ({submission_count}/{config.max_submissions})",
        )
        self._bb.append_event(
            project_id=project_id,
            event_type=EventType.SECURITY_VALIDATION.value,
            payload={
                "outcome": "pass" if passed else "deny",
                "reason": result.reason or "submission budget ok",
                "check": "submission_budget",
                "submission_count": submission_count,
                "max_submissions": config.max_submissions,
            },
            source="submission_verifier",
        )
        return result

    def verify_completeness(self, project_id: str) -> VerificationResult:
        state = self._bb.rebuild_state(project_id)
        already_solved = state.project is not None and state.project.status == "solved"
        passed = not already_solved

        result = VerificationResult(
            status="passed" if passed else "failed",
            checks=[CheckResult(
                check_name="completeness",
                passed=passed,
                detail=f"project_status={state.project.status if state.project else 'none'}",
            )],
            reason="" if passed else "project already solved, no further submission needed",
        )
        self._bb.append_event(
            project_id=project_id,
            event_type=EventType.SECURITY_VALIDATION.value,
            payload={
                "outcome": "pass" if passed else "deny",
                "reason": result.reason or "project not yet solved",
                "check": "completeness",
                "project_status": state.project.status if state.project else "none",
            },
            source="submission_verifier",
        )
        return result

    def run_all_passes(self, project_id: str, flag_value: str, idea_id: str,
                       config: SubmissionConfig | None = None) -> VerificationResult:
        config = config or SubmissionConfig()
        checks: list[CheckResult] = []

        r1 = self.verify_flag_format(project_id, flag_value, config)
        checks.extend(r1.checks)
        if r1.status == "failed":
            return VerificationResult(status="failed", checks=checks, reason=r1.reason)

        r2 = self.verify_evidence_chain(project_id, idea_id)
        checks.extend(r2.checks)
        # evidence_chain "warning" (idea not found) is advisory, not blocking
        if r2.status == "failed":
            return VerificationResult(status="failed", checks=checks, reason=r2.reason)

        r3 = self.verify_submission_budget(project_id, config)
        checks.extend(r3.checks)
        if r3.status == "failed":
            return VerificationResult(status="failed", checks=checks, reason=r3.reason)

        r4 = self.verify_completeness(project_id)
        checks.extend(r4.checks)
        if r4.status == "failed":
            return VerificationResult(status="failed", checks=checks, reason=r4.reason)

        return VerificationResult(status="passed", checks=checks, reason="all passes succeeded")