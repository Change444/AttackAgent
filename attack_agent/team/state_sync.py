"""StateSyncService — Phase K-3.

Reconciles StateGraphService state into Blackboard event journal.
Two modes:
- sync_project: full sync of all StateGraphService data → Blackboard events
- sync_delta: incremental sync (only new data not already in Blackboard)

Does NOT modify Dispatcher / WorkerRuntime / StateGraphService core logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from attack_agent.state_graph import StateGraphService
from attack_agent.team.blackboard import BlackboardService


@dataclass
class SyncConfig:
    max_sync_retries: int = 3


class StateSyncService:
    """Sync StateGraphService state into Blackboard event journal."""

    def __init__(self, config: SyncConfig | None = None) -> None:
        self.config = config or SyncConfig()

    def sync_project(
        self,
        project_id: str,
        state_graph: StateGraphService,
        blackboard: BlackboardService,
    ) -> None:
        """Full sync: write all StateGraphService data to Blackboard.

        Writes events for:
        - record.observations → OBSERVATION events
        - record.candidate_flags → CANDIDATE_FLAG events
        - record.snapshot.stage/status → project_upserted event
        - record.stagnation_counter → CHECKPOINT event
        - record.session_state → OBSERVATION event (kind=session_state)
        - record.pattern_graph → CHECKPOINT event
        """
        record = state_graph.projects.get(project_id)
        if record is None:
            return

        # project stage/status
        blackboard.append_event(
            project_id=project_id,
            event_type="project_upserted",
            payload={
                "challenge_id": record.snapshot.challenge.id,
                "status": record.snapshot.status,
                "stage": record.snapshot.stage.value,
            },
            source="state_sync",
        )

        # observations
        for obs_id, obs in record.observations.items():
            blackboard.append_event(
                project_id=project_id,
                event_type="observation",
                payload={
                    "kind": obs.kind,
                    "source": obs.source,
                    "target": obs.target,
                    "payload": obs.payload,
                    "confidence": obs.confidence,
                    "novelty": obs.novelty,
                    "entry_id": obs.id,
                    "summary": obs.payload.get("summary", obs.kind),
                },
                source="state_sync",
            )

        # candidate_flags
        for dedupe_key, flag in record.candidate_flags.items():
            blackboard.append_event(
                project_id=project_id,
                event_type="candidate_flag",
                payload={
                    "flag": flag.value,
                    "confidence": flag.confidence,
                    "format_match": flag.format_match,
                    "dedupe_key": flag.dedupe_key,
                    "source_chain": flag.source_chain,
                    "evidence_refs": flag.evidence_refs,
                    "submitted": flag.submitted,
                },
                source="state_sync",
            )

        # stagnation_counter
        if record.stagnation_counter > 0:
            blackboard.append_event(
                project_id=project_id,
                event_type="checkpoint",
                payload={
                    "stagnation_update": True,
                    "stagnation_counter": record.stagnation_counter,
                },
                source="state_sync",
            )

        # session_state
        if record.session_state is not None:
            ss = record.session_state
            blackboard.append_event(
                project_id=project_id,
                event_type="observation",
                payload={
                    "kind": "session_state",
                    "cookies_count": len(ss.cookies),
                    "auth_headers_keys": list(ss.auth_headers.keys()),
                    "base_url": ss.base_url,
                    "summary": f"session_state: {len(ss.cookies)} cookies, {len(ss.auth_headers)} auth headers",
                },
                source="state_sync",
            )

        # pattern_graph
        if record.pattern_graph is not None:
            pg = record.pattern_graph
            blackboard.append_event(
                project_id=project_id,
                event_type="checkpoint",
                payload={
                    "pattern_graph_created": True,
                    "nodes": [
                        {
                            "node_id": n.id,
                            "kind": n.kind.value,
                            "status": n.status,
                            "family": n.family,
                        }
                        for n in pg.nodes.values()
                    ],
                    "active_family": pg.active_family,
                    "family_priority": pg.family_priority,
                },
                source="state_sync",
            )

        # Write sync marker
        blackboard.append_event(
            project_id=project_id,
            event_type="checkpoint",
            payload={
                "sync_marker": True,
                "synced_observation_ids": list(record.observations.keys()),
                "synced_flag_keys": list(record.candidate_flags.keys()),
                "sync_mode": "full",
            },
            source="state_sync",
        )

    def sync_delta(
        self,
        project_id: str,
        state_graph: StateGraphService,
        blackboard: BlackboardService,
        last_sync_event_id: str | None = None,
    ) -> str | None:
        """Incremental sync: only write data not already in Blackboard.

        Reads the latest sync_marker CHECKPOINT event to determine what
        has already been synced. If last_sync_event_id is provided, only
        considers events after that ID.

        Returns the event_id of the new sync_marker CHECKPOINT event,
        or None if no record exists.
        """
        record = state_graph.projects.get(project_id)
        if record is None:
            return None

        # Find already-synced items from the latest sync_marker event
        synced_obs_ids: set[str] = set()
        synced_flag_keys: set[str] = set()

        events = blackboard.load_events(project_id)
        for ev in events:
            if last_sync_event_id is not None and ev.event_id == last_sync_event_id:
                break  # stop at boundary — older events already accounted for
            if ev.event_type == "checkpoint":
                payload = ev.payload
                if payload.get("sync_marker"):
                    synced_obs_ids = set(payload.get("synced_observation_ids", []))
                    synced_flag_keys = set(payload.get("synced_flag_keys", []))
                    break  # latest sync_marker wins (events are time-ordered, reversed scan)

        # Scan in reverse to find latest sync_marker
        for ev in reversed(events):
            if ev.event_type == "checkpoint" and ev.payload.get("sync_marker"):
                synced_obs_ids = set(ev.payload.get("synced_observation_ids", []))
                synced_flag_keys = set(ev.payload.get("synced_flag_keys", []))
                break

        # Write new observations not yet synced
        new_obs_ids = set(record.observations.keys()) - synced_obs_ids
        for obs_id in new_obs_ids:
            obs = record.observations[obs_id]
            blackboard.append_event(
                project_id=project_id,
                event_type="observation",
                payload={
                    "kind": obs.kind,
                    "source": obs.source,
                    "target": obs.target,
                    "payload": obs.payload,
                    "confidence": obs.confidence,
                    "novelty": obs.novelty,
                    "entry_id": obs.id,
                    "summary": obs.payload.get("summary", obs.kind),
                },
                source="state_sync_delta",
            )

        # Write new candidate_flags not yet synced
        new_flag_keys = set(record.candidate_flags.keys()) - synced_flag_keys
        for dedupe_key in new_flag_keys:
            flag = record.candidate_flags[dedupe_key]
            blackboard.append_event(
                project_id=project_id,
                event_type="candidate_flag",
                payload={
                    "flag": flag.value,
                    "confidence": flag.confidence,
                    "format_match": flag.format_match,
                    "dedupe_key": flag.dedupe_key,
                    "source_chain": flag.source_chain,
                    "evidence_refs": flag.evidence_refs,
                    "submitted": flag.submitted,
                },
                source="state_sync_delta",
            )

        # Write new sync marker
        all_obs_ids = set(record.observations.keys())
        all_flag_keys = set(record.candidate_flags.keys())

        # Get the event_id of the sync marker we just wrote
        sync_events = blackboard.load_events(project_id)
        marker_event_id: str | None = None

        blackboard.append_event(
            project_id=project_id,
            event_type="checkpoint",
            payload={
                "sync_marker": True,
                "synced_observation_ids": list(all_obs_ids),
                "synced_flag_keys": list(all_flag_keys),
                "sync_mode": "delta",
                "new_observation_ids": list(new_obs_ids),
                "new_flag_keys": list(new_flag_keys),
            },
            source="state_sync_delta",
        )

        # Return the event_id of the sync marker (last event written)
        sync_events = blackboard.load_events(project_id)
        for ev in reversed(sync_events):
            if ev.event_type == "checkpoint" and ev.payload.get("sync_marker") and ev.source == "state_sync_delta":
                marker_event_id = ev.event_id
                break

        return marker_event_id

    def validate_consistency(
        self,
        project_id: str,
        state_graph: StateGraphService,
        blackboard: BlackboardService,
    ) -> bool:
        """Validate Blackboard rebuild_state matches StateGraphService project state.

        If mismatch detected, write corrective project_upserted event.
        Returns True if consistent, False if correction was needed.
        """
        record = state_graph.projects.get(project_id)
        if record is None:
            return True

        bb_state = blackboard.rebuild_state(project_id)
        if bb_state.project is None:
            # No Blackboard state — write corrective event
            blackboard.append_event(
                project_id=project_id,
                event_type="project_upserted",
                payload={
                    "challenge_id": record.snapshot.challenge.id,
                    "status": record.snapshot.status,
                    "stage": record.snapshot.stage.value,
                },
                source="state_sync_validation",
            )
            return False

        consistent = True

        # Check challenge_id
        if bb_state.project.challenge_id != record.snapshot.challenge.id:
            consistent = False

        # Check status alignment
        sg_status = record.snapshot.status
        bb_status = bb_state.project.status
        # Map StateGraphService stages to Blackboard status conventions
        sg_stage = record.snapshot.stage.value
        if sg_stage in ("done", "abandoned"):
            sg_status = sg_stage
        if bb_status != sg_status:
            consistent = False

        if not consistent:
            blackboard.append_event(
                project_id=project_id,
                event_type="project_upserted",
                payload={
                    "challenge_id": record.snapshot.challenge.id,
                    "status": sg_status or record.snapshot.status,
                    "stage": sg_stage,
                },
                source="state_sync_validation",
            )

        return consistent