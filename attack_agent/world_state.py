from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import TypeVar

from .models import (
    ActionRecord,
    AgentStage,
    Asset,
    BaseEntity,
    Credential,
    Endpoint,
    Evidence,
    Finding,
    Service,
    Session,
    StageState,
)

T = TypeVar("T", bound=BaseEntity)


class WorldState:
    def __init__(self) -> None:
        self.assets: dict[str, Asset] = {}
        self.services: dict[str, Service] = {}
        self.endpoints: dict[str, Endpoint] = {}
        self.credentials: dict[str, Credential] = {}
        self.sessions: dict[str, Session] = {}
        self.findings: dict[str, Finding] = {}
        self.actions: list[ActionRecord] = []
        self.evidence: dict[str, Evidence] = {}
        self.stage_history: list[StageState] = [StageState(id="stage_initial", source="system", stage=AgentStage.RECON)]
        self.history_summary: list[str] = []
        self.denied_targets: set[str] = set()

    @property
    def stage(self) -> AgentStage:
        return self.stage_history[-1].stage

    def unlock_stage(self, stage: AgentStage, source: str, notes: str = "", capabilities: tuple[str, ...] = ()) -> None:
        if stage == self.stage:
            return
        self.stage_history.append(
            StageState(id=f"stage_{len(self.stage_history)}", source=source, stage=stage, notes=notes, unlocked_capabilities=capabilities)
        )
        self.history_summary.append(f"stage unlocked: {stage.value} via {source}")

    def add_evidence(self, evidence: Evidence) -> None:
        self.evidence[evidence.id] = evidence

    def _upsert(self, store: dict[str, T], entity: T) -> None:
        existing = store.get(entity.id)
        if existing is None:
            store[entity.id] = entity
            return
        if entity.evidence_ref and existing.evidence_ref and entity.evidence_ref in self.evidence and existing.evidence_ref in self.evidence:
            incoming_score = self.evidence[entity.evidence_ref].confidence
            current_score = self.evidence[existing.evidence_ref].confidence
            if incoming_score >= current_score:
                store[entity.id] = entity
                return
        if entity.confidence >= existing.confidence:
            store[entity.id] = entity

    def upsert_asset(self, entity: Asset) -> None:
        self._upsert(self.assets, entity)

    def upsert_service(self, entity: Service) -> None:
        self._upsert(self.services, entity)

    def upsert_endpoint(self, entity: Endpoint) -> None:
        self._upsert(self.endpoints, entity)

    def upsert_credential(self, entity: Credential) -> None:
        self._upsert(self.credentials, entity)

    def upsert_session(self, entity: Session) -> None:
        self._upsert(self.sessions, entity)

    def upsert_finding(self, entity: Finding) -> None:
        self._upsert(self.findings, entity)

    def record_action(self, action: ActionRecord) -> None:
        self.actions.append(action)

    def recent_failures(self, limit: int = 5) -> list[ActionRecord]:
        failures = [action for action in reversed(self.actions) if action.status == "failed"]
        return failures[:limit]

    def previously_failed(self, tool_name: str, target: str) -> bool:
        return any(action.tool_name == tool_name and action.target == target and action.status == "failed" for action in self.actions)

    def compact_view(self, limit: int = 15) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for store_name, store in (
            ("assets", self.assets),
            ("services", self.services),
            ("endpoints", self.endpoints),
            ("findings", self.findings),
            ("credentials", self.credentials),
            ("sessions", self.sessions),
        ):
            for entity in store.values():
                rows.append({"kind": store_name, **asdict(entity)})
        rows.sort(key=lambda item: (item.get("confidence", 0.0), str(item.get("timestamp"))), reverse=True)
        return rows[:limit]

    def expire_entities(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        for store in (self.assets, self.services, self.endpoints, self.credentials, self.sessions, self.findings):
            expired_ids = [entity_id for entity_id, entity in store.items() if entity.is_expired(now)]
            for entity_id in expired_ids:
                del store[entity_id]

    def candidate_targets(self) -> list[str]:
        targets = [asset.hostname for asset in self.assets.values()]
        targets.extend(endpoint.path for endpoint in self.endpoints.values())
        return list(dict.fromkeys(targets))
