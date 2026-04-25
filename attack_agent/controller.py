from __future__ import annotations

from .platform_models import Event, EventType, ProjectSnapshot, ProjectStage
from .provider import CompetitionProvider
from .state_graph import StateGraphService


class Controller:
    def __init__(self, provider: CompetitionProvider, state_graph: StateGraphService) -> None:
        self.provider = provider
        self.state_graph = state_graph
        self.instance_quota = 3

    def sync_challenges(self) -> list[str]:
        project_ids: list[str] = []
        for challenge in self.provider.list_challenges():
            project_id = f"project:{challenge.id}"
            snapshot = ProjectSnapshot(project_id=project_id, challenge=challenge, stage=ProjectStage.BOOTSTRAP)
            self.state_graph.upsert_project(snapshot)
            project_ids.append(project_id)
        return project_ids

    def ensure_instance(self, project_id: str) -> None:
        record = self.state_graph.projects[project_id]
        if record.snapshot.instance is not None:
            return
        instance = self.provider.start_challenge(record.snapshot.challenge.id)
        record.snapshot.status = "running"
        self.state_graph.record_instance(project_id, instance)

    def maybe_request_hint(self, project_id: str) -> bool:
        record = self.state_graph.projects[project_id]
        if record.candidate_flags or record.snapshot.stage == ProjectStage.DONE:
            return False
        failures = len(record.world_state.recent_failures(limit=4))
        if failures < 2:
            return False
        hint = self.provider.request_hint(instance_id=record.snapshot.instance.instance_id)
        self.state_graph.append_event(
            Event(
                type=EventType.HINT,
                project_id=project_id,
                run_id=f"hint-{project_id}",
                payload={"hint": hint.hint, "remaining": hint.remaining},
                source="controller",
            )
        )
        return True

    def submit_candidate(self, project_id: str, dedupe_key: str) -> dict[str, str | bool]:
        record = self.state_graph.projects[project_id]
        candidate = record.candidate_flags[dedupe_key]
        result = self.provider.submit_flag(record.snapshot.instance.instance_id, candidate.value)
        candidate.submitted = True
        payload = {"dedupe_key": dedupe_key, "accepted": result.accepted, "message": result.message, "status": result.status}
        self.state_graph.append_event(
            Event(
                type=EventType.SUBMISSION,
                project_id=project_id,
                run_id=f"submit-{project_id}",
                payload=payload,
                source="controller",
            )
        )
        if result.accepted:
            record.snapshot.stage = ProjectStage.DONE
            record.snapshot.status = "solved"
            self.state_graph.append_event(
                Event(
                    type=EventType.PROJECT_DONE,
                    project_id=project_id,
                    run_id=f"done-{project_id}",
                    payload={"accepted_flag": candidate.value},
                    source="controller",
                )
            )
            self.provider.stop_challenge(record.snapshot.instance.instance_id)
        return payload
