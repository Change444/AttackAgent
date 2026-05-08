from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .apg import EpisodeMemory, build_episode_entry
from .compilers import HandoffMemory, ProgressCompiler, RetryHandoffCompiler
from .models import Asset, Credential, Endpoint, Evidence, Finding, Service, Session, new_id
from .platform_models import Artifact, CandidateFlag, ChallengeInstance, Event, EventType, Hypothesis, Observation, PatternGraph, ProjectSnapshot
from .world_state import WorldState
from .observation_summarizer import ObservationSummarizer


@dataclass(slots=True)
class SessionState:
    """Persistent session state across planning cycles."""
    cookies: list[dict] = field(default_factory=list)  # [{name, value, domain, path}]
    auth_headers: dict[str, str] = field(default_factory=dict)  # Authorization headers
    base_url: str = ""
    created_at: str = ""


@dataclass(slots=True)
class ProjectRecord:
    snapshot: ProjectSnapshot
    world_state: WorldState = field(default_factory=WorldState)
    run_journal: list[Event] = field(default_factory=list)
    candidate_flags: dict[str, CandidateFlag] = field(default_factory=dict)
    handoff: HandoffMemory | None = None
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    submission_history: list[dict[str, Any]] = field(default_factory=list)
    observations: dict[str, Observation] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    hypotheses: dict[str, Hypothesis] = field(default_factory=dict)
    pattern_graph: PatternGraph | None = None
    session_state: SessionState | None = None
    stagnation_counter: int = 0
    tombstones: list[str] = field(default_factory=list)


class StateGraphService:
    def __init__(self) -> None:
        self.projects: dict[str, ProjectRecord] = {}
        self.progress_compiler = ProgressCompiler()
        self.retry_compiler = RetryHandoffCompiler()
        self.episode_memory = EpisodeMemory()
        self.observation_summarizer = ObservationSummarizer()

    def upsert_project(self, project_snapshot: ProjectSnapshot) -> None:
        existing = self.projects.get(project_snapshot.project_id)
        if existing is None:
            self.projects[project_snapshot.project_id] = ProjectRecord(snapshot=project_snapshot)
            self.append_event(
                Event(
                    type=EventType.PROJECT_UPSERTED,
                    project_id=project_snapshot.project_id,
                    run_id=new_id("run"),
                    payload={"challenge_id": project_snapshot.challenge.id, "stage": project_snapshot.stage.value},
                    source="controller",
                )
            )
            return
        existing.snapshot = project_snapshot

    def append_event(self, event: Event) -> None:
        record = self.projects[event.project_id]
        record.run_journal.append(event)
        if event.type == EventType.OBSERVATION:
            self._apply_observation(record, event.payload)
        elif event.type == EventType.CANDIDATE_FLAG:
            self._apply_candidate_flag(record, event.payload)
        elif event.type == EventType.CHECKPOINT:
            record.checkpoints.append(dict(event.payload))
        elif event.type == EventType.SUBMISSION:
            record.submission_history.append(dict(event.payload))
        elif event.type == EventType.HINT:
            self._apply_hint(record, event.payload, event.source)
        elif event.type == EventType.ARTIFACT_ADDED:
            self._apply_artifact(record, event.payload)
        elif event.type == EventType.HYPOTHESIS_ADDED:
            self._apply_hypothesis(record, event.payload)
        elif event.type == EventType.ACTION_OUTCOME and event.payload.get("status") != "ok":
            record.tombstones.append(str(event.payload.get("failure_reason", "failed")))
        record.handoff = self.export_handoff(event.project_id)

    def record_program(self, project_id: str, program, outcome) -> None:
        self.append_event(
            Event(
                type=EventType.PROGRAM_COMPILED,
                project_id=project_id,
                run_id=program.id,
                payload={
                    "program_id": program.id,
                    "goal": program.goal,
                    "pattern_nodes": program.pattern_nodes,
                    "allowed_primitives": program.allowed_primitives,
                    "memory_refs": program.memory_refs,
                    "rationale": program.rationale,
                    "planner_source": program.planner_source,
                },
                source="dispatcher",
            )
        )
        record = self.projects[project_id]
        entry = build_episode_entry(record, program, outcome, self.observation_summarizer)
        self.episode_memory.add(entry)
        self.append_event(
            Event(
                type=EventType.MEMORY_STORED,
                project_id=project_id,
                run_id=program.id,
                payload={"episode_id": entry.id, "summary": entry.summary, "stop_reason": entry.stop_reason},
                source="state_graph",
            )
        )

    def query_graph(self, project_id: str, view: str = "summary") -> dict[str, Any]:
        record = self.projects[project_id]
        if view == "summary":
            return {
                "project_id": project_id,
                "stage": record.snapshot.stage.value,
                "status": record.snapshot.status,
                "worker_profile": record.snapshot.worker_profile.value,
                "instance": None if record.snapshot.instance is None else asdict(record.snapshot.instance),
                "candidate_flags": [asdict(candidate) for candidate in record.candidate_flags.values()],
                "observations": [observation.kind for observation in record.observations.values()],
                "artifacts": [artifact.kind for artifact in record.artifacts.values()],
                "hypotheses": [hypothesis.statement for hypothesis in record.hypotheses.values()],
                "pattern_graph": None
                if record.pattern_graph is None
                else {
                    "active_family": record.pattern_graph.active_family,
                    "resolved_nodes": [node.id for node in record.pattern_graph.nodes.values() if node.status == "resolved"],
                },
                "run_events": len(record.run_journal),
            }
        if view == "pattern":
            return {
                "active_family": None if record.pattern_graph is None else record.pattern_graph.active_family,
                "nodes": [] if record.pattern_graph is None else [asdict(node) for node in record.pattern_graph.nodes.values()],
            }
        return {
            "events": [
                {
                    **asdict(event),
                    "type": event.type.value,
                }
                for event in record.run_journal
            ]
        }

    def export_handoff(self, project_id: str) -> HandoffMemory:
        record = self.projects[project_id]
        current = self.progress_compiler.compile(record.world_state, record.snapshot.challenge.target)
        previous = record.handoff
        return self.retry_compiler.compile(previous, current)

    def reopen_project(self, project_id: str) -> None:
        record = self.projects[project_id]
        record.snapshot.stage = record.snapshot.stage.BOOTSTRAP
        record.snapshot.status = "reopened"
        record.handoff = self.export_handoff(project_id)
        self.append_event(
            Event(
                type=EventType.REQUEUE,
                project_id=project_id,
                run_id=new_id("run"),
                payload={"reason": "reopen"},
                source="controller",
            )
        )

    def record_instance(self, project_id: str, instance: ChallengeInstance) -> None:
        record = self.projects[project_id]
        record.snapshot.instance = instance
        self.append_event(
            Event(
                type=EventType.INSTANCE_STARTED,
                project_id=project_id,
                run_id=new_id("run"),
                payload={"instance_id": instance.instance_id, "target": instance.target},
                source="controller",
            )
        )

    def get_session_state(self, project_id: str) -> SessionState | None:
        """Get persistent session state for a project."""
        record = self.projects.get(project_id)
        if record is None:
            return None
        return record.session_state

    def set_session_state(self, project_id: str, session_state: SessionState) -> None:
        """Set persistent session state for a project."""
        record = self.projects.get(project_id)
        if record is None:
            return
        record.session_state = session_state

    def _apply_observation(self, record: ProjectRecord, payload: dict[str, Any]) -> None:
        target = record.snapshot.challenge.target
        obs_id = str(payload.get("id", new_id("observation")))
        observation_payload = dict(payload.get("payload", {}))
        if payload.get("text"):
            observation_payload["text"] = str(payload["text"])
        observation = Observation(
            id=obs_id,
            kind=str(payload.get("kind", "observation")),
            source=str(payload.get("source", "worker")),
            target=target,
            payload=observation_payload,
            confidence=float(payload.get("confidence", 0.75)),
            novelty=float(payload.get("novelty", 0.5)),
        )
        record.observations[observation.id] = observation
        evidence = Evidence(
            id=new_id("evidence"),
            description=str(payload.get("description", observation.kind)),
            source=observation.source,
            confidence=observation.confidence,
            data={"target": target, **observation.payload},
        )
        record.world_state.add_evidence(evidence)
        asset_id = f"asset:{target}"
        record.world_state.upsert_asset(Asset(id=asset_id, hostname=target, source=evidence.source, confidence=evidence.confidence, evidence_ref=evidence.id))
        for service in payload.get("services", []):
            record.world_state.upsert_service(
                Service(
                    id=f"service:{target}:{service['port']}",
                    asset_id=asset_id,
                    name=str(service["name"]),
                    port=int(service["port"]),
                    source=evidence.source,
                    confidence=evidence.confidence,
                    evidence_ref=evidence.id,
                )
            )
        for endpoint in payload.get("endpoints", []):
            record.world_state.upsert_endpoint(
                Endpoint(
                    id=f"endpoint:{target}:{endpoint['path']}",
                    asset_id=asset_id,
                    path=str(endpoint["path"]),
                    method=str(endpoint.get("method", "GET")),
                    source=evidence.source,
                    confidence=evidence.confidence,
                    evidence_ref=evidence.id,
                )
            )
        for finding in payload.get("findings", []):
            record.world_state.upsert_finding(
                Finding(
                    id=f"finding:{record.snapshot.challenge.id}:{finding['title']}",
                    asset_id=asset_id,
                    title=str(finding["title"]),
                    severity=str(finding.get("severity", "info")),
                    structured_details=dict(finding),
                    source=evidence.source,
                    confidence=evidence.confidence,
                    evidence_ref=evidence.id,
                    hypothesis_status=str(finding.get("status", "observed")),
                )
            )
        for session in payload.get("sessions", []):
            credential_id = f"credential:{target}:{session['username']}"
            record.world_state.upsert_credential(
                Credential(
                    id=credential_id,
                    asset_id=asset_id,
                    username=str(session["username"]),
                    secret_ref=str(session.get("secret_ref", "masked")),
                    privilege=str(session.get("privilege", "user")),
                    source=evidence.source,
                    confidence=evidence.confidence,
                    evidence_ref=evidence.id,
                )
            )
            record.world_state.upsert_session(
                Session(
                    id=f"session:{target}:{session['username']}",
                    asset_id=asset_id,
                    credential_id=credential_id,
                    session_type=str(session.get("session_type", "web")),
                    source=evidence.source,
                    confidence=evidence.confidence,
                    evidence_ref=evidence.id,
                )
            )

    def _apply_hint(self, record: ProjectRecord, payload: dict[str, Any], source: str) -> None:
        hint = payload.get("hint", "")
        if not hint:
            return
        evidence = Evidence(id=new_id("evidence"), description=f"hint: {hint}", source=source, confidence=0.9, data={"target": record.snapshot.challenge.target})
        record.world_state.add_evidence(evidence)
        record.world_state.upsert_finding(
            Finding(
                id=f"hint:{record.snapshot.challenge.id}:{len(record.submission_history)}",
                asset_id=f"asset:{record.snapshot.challenge.target}",
                title="competition hint",
                severity="info",
                structured_details={"hint": hint},
                source=source,
                confidence=0.9,
                evidence_ref=evidence.id,
                hypothesis_status="hint",
            )
        )

    def _apply_candidate_flag(self, record: ProjectRecord, payload: dict[str, Any]) -> None:
        candidate = CandidateFlag(**payload)
        existing = record.candidate_flags.get(candidate.dedupe_key)
        if existing is None or candidate.confidence >= existing.confidence:
            record.candidate_flags[candidate.dedupe_key] = candidate

    def _apply_artifact(self, record: ProjectRecord, payload: dict[str, Any]) -> None:
        artifact = Artifact(
            id=str(payload["id"]),
            kind=str(payload["kind"]),
            location=str(payload["location"]),
            fingerprint=str(payload["fingerprint"]),
            metadata=dict(payload.get("metadata", {})),
            evidence_refs=list(payload.get("evidence_refs", [])),
        )
        record.artifacts[artifact.id] = artifact

    def _apply_hypothesis(self, record: ProjectRecord, payload: dict[str, Any]) -> None:
        hypothesis = Hypothesis(
            id=str(payload["id"]),
            statement=str(payload["statement"]),
            preconditions=list(payload.get("preconditions", [])),
            supporting_observations=list(payload.get("supporting_observations", [])),
            confidence=float(payload.get("confidence", 0.7)),
        )
        record.hypotheses[hypothesis.id] = hypothesis
