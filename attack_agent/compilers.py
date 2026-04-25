from __future__ import annotations

from dataclasses import dataclass, field

from .world_state import WorldState


@dataclass(slots=True)
class HandoffMemory:
    target: str
    summary: str
    completed_steps: list[str] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    recommended_next: list[str] = field(default_factory=list)


class ProgressCompiler:
    def compile(self, state: WorldState, target: str) -> HandoffMemory:
        completed_steps = []
        dead_ends = []
        evidence_refs = []
        for action in state.actions:
            if action.target != target:
                continue
            label = f"{action.tool_name}:{action.status}"
            if action.status == "ok":
                completed_steps.append(label)
            else:
                dead_ends.append(f"{label}:{action.error_type or 'error'}")
        for evidence_id, evidence in state.evidence.items():
            evidence_target = str(evidence.data.get("target", ""))
            if evidence_target == target or target in evidence.description:
                evidence_refs.append(evidence_id)
        summary_bits = []
        if target in state.assets or f"asset:{target}" in state.assets:
            summary_bits.append("asset-known")
        if any(finding.asset_id == f"asset:{target}" for finding in state.findings.values()):
            summary_bits.append("finding-confirmed")
        if any(session.asset_id == f"asset:{target}" for session in state.sessions.values()):
            summary_bits.append("session-available")
        summary = ", ".join(summary_bits) if summary_bits else "limited progress"
        recommended_next = ["prefer validation"] if any(session.asset_id == f"asset:{target}" for session in state.sessions.values()) else ["continue analysis"]
        return HandoffMemory(
            target=target,
            summary=summary,
            completed_steps=completed_steps[-6:],
            dead_ends=dead_ends[-6:],
            evidence_refs=evidence_refs[-6:],
            recommended_next=recommended_next,
        )


class RetryHandoffCompiler:
    def compile(self, previous: HandoffMemory | None, current: HandoffMemory) -> HandoffMemory:
        if previous is None:
            return current
        combined_completed = list(dict.fromkeys(previous.completed_steps + current.completed_steps))
        combined_dead_ends = list(dict.fromkeys(previous.dead_ends + current.dead_ends))
        combined_evidence = list(dict.fromkeys(previous.evidence_refs + current.evidence_refs))
        combined_next = list(dict.fromkeys(previous.recommended_next + current.recommended_next))
        summary = current.summary
        if previous.summary != current.summary:
            summary = f"{previous.summary} -> {current.summary}"
        return HandoffMemory(
            target=current.target,
            summary=summary,
            completed_steps=combined_completed[-8:],
            dead_ends=combined_dead_ends[-8:],
            evidence_refs=combined_evidence[-8:],
            recommended_next=combined_next[:4],
        )
