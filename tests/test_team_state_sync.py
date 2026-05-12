"""Tests for StateSyncService — Phase K-3."""

import os
import tempfile
import unittest

from attack_agent.platform_models import (
    CandidateFlag,
    ChallengeDefinition,
    ChallengeInstance,
    EventType,
    Observation,
    PatternEdge,
    PatternGraph,
    PatternNode,
    PatternNodeKind,
    ProjectSnapshot,
    ProjectStage,
    WorkerProfile,
)
from attack_agent.state_graph import ProjectRecord, SessionState, StateGraphService
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.protocol import MemoryKind
from attack_agent.team.state_sync import StateSyncService, SyncConfig


def _make_project_record(pid: str = "p1") -> ProjectRecord:
    """Create a minimal ProjectRecord for testing."""
    challenge = ChallengeDefinition(
        id="c1", name="test", category="web", difficulty="easy",
        target="http://test", description="test challenge",
        flag_pattern="flag\\{[^}]+\\}",
    )
    instance = ChallengeInstance(
        instance_id="i1", challenge_id="c1", target="http://test",
        status="running",
    )
    snapshot = ProjectSnapshot(
        project_id=pid, challenge=challenge, priority=1,
        stage=ProjectStage.EXPLORE, status="running",
        worker_profile=WorkerProfile.NETWORK, instance=instance,
    )
    return ProjectRecord(snapshot=snapshot)


class TestStateSyncServiceSyncProject(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "bb.db"))
        self.bb = BlackboardService(self.config)
        self.state_sync = StateSyncService(SyncConfig())
        self.sg = StateGraphService()

    def tearDown(self):
        self.bb.close()
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_sync_project_writes_observations(self):
        """sync_project writes OBSERVATION events for each observation."""
        record = _make_project_record("p1")
        obs = Observation(
            id="obs1", kind="http-request", source="s1", target="http://test",
            payload={"summary": "found endpoint", "status_code": 200},
            confidence=0.8, novelty=0.5,
        )
        record.observations["obs1"] = obs
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        obs_events = [e for e in events if e.event_type == "observation"
                      and e.source == "state_sync"]
        self.assertEqual(len(obs_events), 1)
        self.assertEqual(obs_events[0].payload["kind"], "http-request")
        self.assertEqual(obs_events[0].payload["entry_id"], "obs1")
        self.assertEqual(obs_events[0].payload["confidence"], 0.8)
        self.assertEqual(obs_events[0].payload["payload"]["summary"], "found endpoint")

    def test_sync_project_writes_candidate_flags(self):
        """sync_project writes CANDIDATE_FLAG events for each flag."""
        record = _make_project_record("p1")
        flag = CandidateFlag(
            value="flag{abc}", source_chain=["s1"], confidence=0.9,
            format_match=True, dedupe_key="flag{abc}", evidence_refs=["e1"],
        )
        record.candidate_flags["flag{abc}"] = flag
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        flag_events = [e for e in events if e.event_type == "candidate_flag"
                       and e.source == "state_sync"]
        self.assertEqual(len(flag_events), 1)
        self.assertEqual(flag_events[0].payload["flag"], "flag{abc}")
        self.assertEqual(flag_events[0].payload["dedupe_key"], "flag{abc}")
        self.assertEqual(flag_events[0].payload["confidence"], 0.9)

    def test_sync_project_writes_project_upserted(self):
        """sync_project writes project_upserted with stage/status."""
        record = _make_project_record("p1")
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        upsert_events = [e for e in events if e.event_type == "project_upserted"
                         and e.source == "state_sync"]
        self.assertEqual(len(upsert_events), 1)
        self.assertEqual(upsert_events[0].payload["stage"], "explore")
        self.assertEqual(upsert_events[0].payload["status"], "running")

    def test_sync_project_writes_stagnation_checkpoint(self):
        """sync_project writes stagnation CHECKPOINT when stagnation_counter > 0."""
        record = _make_project_record("p1")
        record.stagnation_counter = 3
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        stagnation_events = [e for e in events if e.event_type == "checkpoint"
                             and e.payload.get("stagnation_update")]
        self.assertEqual(len(stagnation_events), 1)
        self.assertEqual(stagnation_events[0].payload["stagnation_counter"], 3)

    def test_sync_project_no_stagnation_when_zero(self):
        """sync_project does NOT write stagnation checkpoint when counter == 0."""
        record = _make_project_record("p1")
        record.stagnation_counter = 0
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        stagnation_events = [e for e in events if e.event_type == "checkpoint"
                             and e.payload.get("stagnation_update")]
        self.assertEqual(len(stagnation_events), 0)

    def test_sync_project_writes_session_state(self):
        """sync_project writes OBSERVATION event for session_state."""
        record = _make_project_record("p1")
        ss = SessionState(
            cookies=[{"name": "session", "value": "abc", "domain": "test", "path": "/"}],
            auth_headers={"Authorization": "Bearer xyz"},
            base_url="http://test",
        )
        record.session_state = ss
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        ss_events = [e for e in events if e.event_type == "observation"
                     and e.payload.get("kind") == "session_state"]
        self.assertEqual(len(ss_events), 1)
        self.assertEqual(ss_events[0].payload["cookies_count"], 1)
        self.assertEqual(ss_events[0].payload["auth_headers_keys"], ["Authorization"])

    def test_sync_project_writes_pattern_graph(self):
        """sync_project writes CHECKPOINT event for pattern_graph."""
        record = _make_project_record("p1")
        pg = PatternGraph(
            graph_id="pg1",
            nodes={
                "n1": PatternNode(
                    id="n1", family="identity", kind=PatternNodeKind.GOAL,
                    label="goal", keywords=["auth"], capability_hints=["http"],
                    status="active",
                ),
            },
            edges=[PatternEdge(source="n1", target="n2", condition="found")],
            family_priority=["identity"],
            active_family="identity",
        )
        record.pattern_graph = pg
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        pg_events = [e for e in events if e.event_type == "checkpoint"
                     and e.payload.get("pattern_graph_created")]
        self.assertEqual(len(pg_events), 1)
        nodes = pg_events[0].payload["nodes"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["node_id"], "n1")
        self.assertEqual(nodes[0]["kind"], "goal")
        self.assertEqual(nodes[0]["status"], "active")

    def test_sync_project_writes_sync_marker(self):
        """sync_project writes a sync_marker CHECKPOINT event."""
        record = _make_project_record("p1")
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        marker_events = [e for e in events if e.event_type == "checkpoint"
                         and e.payload.get("sync_marker")]
        self.assertEqual(len(marker_events), 1)
        self.assertEqual(marker_events[0].payload["sync_mode"], "full")

    def test_sync_project_no_record_returns_early(self):
        """sync_project returns None when project_id has no StateGraphService record."""
        self.state_sync.sync_project("nonexistent", self.sg, self.bb)
        # Should not crash, no events written
        events = self.bb.load_events("nonexistent")
        self.assertEqual(len(events), 0)


class TestStateSyncServiceSyncDelta(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "bb.db"))
        self.bb = BlackboardService(self.config)
        self.state_sync = StateSyncService(SyncConfig())
        self.sg = StateGraphService()

    def tearDown(self):
        self.bb.close()
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_sync_delta_only_writes_new_observations(self):
        """sync_delta only writes observations not already in sync_marker."""
        record = _make_project_record("p1")
        obs1 = Observation(
            id="obs1", kind="http-request", source="s1", target="http://test",
            payload={"summary": "found"}, confidence=0.8, novelty=0.5,
        )
        obs2 = Observation(
            id="obs2", kind="structured-parse", source="s1", target="http://test",
            payload={"summary": "parsed"}, confidence=0.7, novelty=0.4,
        )
        record.observations["obs1"] = obs1
        self.sg.projects["p1"] = record

        # Full sync first (writes obs1)
        self.state_sync.sync_project("p1", self.sg, self.bb)

        # Now add obs2 to StateGraphService
        record.observations["obs2"] = obs2

        # Delta sync should only write obs2
        self.state_sync.sync_delta("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        delta_obs = [e for e in events if e.event_type == "observation"
                     and e.source == "state_sync_delta"]
        self.assertEqual(len(delta_obs), 1)
        self.assertEqual(delta_obs[0].payload["entry_id"], "obs2")

    def test_sync_delta_only_writes_new_flags(self):
        """sync_delta only writes candidate_flags not already synced."""
        record = _make_project_record("p1")
        flag1 = CandidateFlag(
            value="flag{abc}", source_chain=["s1"], confidence=0.9,
            format_match=True, dedupe_key="flag{abc}", evidence_refs=["e1"],
        )
        flag2 = CandidateFlag(
            value="flag{xyz}", source_chain=["s1"], confidence=0.8,
            format_match=True, dedupe_key="flag{xyz}", evidence_refs=["e2"],
        )
        record.candidate_flags["flag{abc}"] = flag1
        self.sg.projects["p1"] = record

        # Full sync first (writes flag1)
        self.state_sync.sync_project("p1", self.sg, self.bb)

        # Add flag2
        record.candidate_flags["flag{xyz}"] = flag2

        # Delta sync should only write flag2
        self.state_sync.sync_delta("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        delta_flags = [e for e in events if e.event_type == "candidate_flag"
                       and e.source == "state_sync_delta"]
        self.assertEqual(len(delta_flags), 1)
        self.assertEqual(delta_flags[0].payload["flag"], "flag{xyz}")

    def test_sync_delta_writes_sync_marker(self):
        """sync_delta writes a delta sync_marker CHECKPOINT."""
        record = _make_project_record("p1")
        self.sg.projects["p1"] = record

        self.state_sync.sync_project("p1", self.sg, self.bb)
        result = self.state_sync.sync_delta("p1", self.sg, self.bb)

        # result should be a sync_marker event_id
        self.assertIsNotNone(result)

        events = self.bb.load_events("p1")
        delta_markers = [e for e in events if e.event_type == "checkpoint"
                         and e.payload.get("sync_marker")
                         and e.payload.get("sync_mode") == "delta"]
        self.assertEqual(len(delta_markers), 1)

    def test_sync_delta_no_record_returns_none(self):
        """sync_delta returns None when project_id has no record."""
        result = self.state_sync.sync_delta("nonexistent", self.sg, self.bb)
        self.assertIsNone(result)

    def test_sync_delta_with_no_prior_sync(self):
        """sync_delta without prior full sync writes all observations and flags."""
        record = _make_project_record("p1")
        obs = Observation(
            id="obs1", kind="http-request", source="s1", target="http://test",
            payload={"summary": "found"}, confidence=0.8, novelty=0.5,
        )
        record.observations["obs1"] = obs
        self.sg.projects["p1"] = record

        # Delta sync without prior full sync (no sync_marker exists)
        result = self.state_sync.sync_delta("p1", self.sg, self.bb)

        events = self.bb.load_events("p1")
        delta_obs = [e for e in events if e.event_type == "observation"
                     and e.source == "state_sync_delta"]
        self.assertEqual(len(delta_obs), 1)
        self.assertEqual(delta_obs[0].payload["entry_id"], "obs1")


class TestStateSyncServiceValidateConsistency(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "bb.db"))
        self.bb = BlackboardService(self.config)
        self.state_sync = StateSyncService(SyncConfig())
        self.sg = StateGraphService()

    def tearDown(self):
        self.bb.close()
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_validate_consistency_matches(self):
        """validate_consistency returns True when Blackboard matches StateGraphService."""
        record = _make_project_record("p1")
        record.snapshot.status = "running"
        self.sg.projects["p1"] = record

        # Seed matching Blackboard state
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "running"}, "system")

        result = self.state_sync.validate_consistency("p1", self.sg, self.bb)
        self.assertTrue(result)

    def test_validate_consistency_mismatch_writes_correction(self):
        """validate_consistency writes corrective event on mismatch."""
        record = _make_project_record("p1")
        record.snapshot.status = "running"
        self.sg.projects["p1"] = record

        # Seed Blackboard with different status
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "new"}, "system")

        result = self.state_sync.validate_consistency("p1", self.sg, self.bb)
        self.assertFalse(result)

        # Check corrective event was written
        events = self.bb.load_events("p1")
        correction_events = [e for e in events if e.source == "state_sync_validation"]
        self.assertEqual(len(correction_events), 1)
        self.assertEqual(correction_events[0].payload["status"], "running")

    def test_validate_consistency_no_bb_state_writes_correction(self):
        """validate_consistency writes corrective event when Blackboard has no state."""
        record = _make_project_record("p1")
        self.sg.projects["p1"] = record

        # No Blackboard events for this project
        result = self.state_sync.validate_consistency("p1", self.sg, self.bb)
        self.assertFalse(result)

        events = self.bb.load_events("p1")
        correction_events = [e for e in events if e.source == "state_sync_validation"]
        self.assertEqual(len(correction_events), 1)

    def test_validate_consistency_no_record_returns_true(self):
        """validate_consistency returns True when StateGraphService has no record."""
        result = self.state_sync.validate_consistency("nonexistent", self.sg, self.bb)
        self.assertTrue(result)


class TestObservationEventsInBlackboard(unittest.TestCase):
    """Verify that detailed observation events are accessible via rebuild_state."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = BlackboardConfig(db_path=os.path.join(self.tmpdir, "bb.db"))
        self.bb = BlackboardService(self.config)

    def tearDown(self):
        self.bb.close()
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_detailed_observation_creates_memory_entry(self):
        """Per-observation OBSERVATION events create MemoryEntry in rebuild_state."""
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "new"}, "system")
        self.bb.append_event("p1", "observation",
                             {"kind": "http-request", "summary": "found endpoint",
                              "confidence": 0.8, "entry_id": "obs1"}, "executor")
        self.bb.append_event("p1", "observation",
                             {"kind": "structured-parse", "summary": "parsed data",
                              "confidence": 0.7, "entry_id": "obs2"}, "executor")

        state = self.bb.rebuild_state("p1")
        facts = state.facts
        obs_facts = [f for f in facts if f.entry_id in ("obs1", "obs2")]
        self.assertEqual(len(obs_facts), 2)
        # Primitive kinds fall back to FACT, original kind preserved in content
        for f in obs_facts:
            self.assertEqual(f.kind, MemoryKind.FACT)
        # Content includes original kind prefix for primitive-type observations
        self.assertTrue(obs_facts[0].content.startswith("http-request:"))
        self.assertTrue(obs_facts[1].content.startswith("structured-parse:"))

    def test_session_state_observation_creates_memory_entry(self):
        """OBSERVATION event with kind=session_state creates MemoryEntry."""
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "new"}, "system")
        self.bb.append_event("p1", "observation",
                             {"kind": "session_state", "summary": "session_state: 2 cookies",
                              "cookies_count": 2, "auth_headers_keys": ["Authorization"],
                              "confidence": 0.5}, "executor")

        state = self.bb.rebuild_state("p1")
        ss_entries = [f for f in state.facts if f.kind == MemoryKind.SESSION_STATE]
        self.assertEqual(len(ss_entries), 1)
        self.assertEqual(ss_entries[0].content, "session_state: 2 cookies")

    def test_action_outcome_with_stagnation_counter(self):
        """ACTION_OUTCOME event preserves stagnation_counter in payload."""
        self.bb.append_event("p1", "project_upserted",
                             {"challenge_id": "c1", "status": "new"}, "system")
        self.bb.append_event("p1", "action_outcome",
                             {"status": "ok", "stagnation_counter": 3,
                              "broker_execution": True}, "executor")

        events = self.bb.load_events("p1")
        outcome_events = [e for e in events if e.event_type == "action_outcome"]
        self.assertEqual(outcome_events[0].payload["stagnation_counter"], 3)


if __name__ == "__main__":
    unittest.main()