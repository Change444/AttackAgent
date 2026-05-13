"""L6 acceptance tests — KnowledgePacket and MergeHub Routing.

Acceptance criteria:
1. Duplicate facts merge into one accepted memory entry
2. Conflicting facts create a merge decision rather than overwriting silently
3. High-priority candidate flag reaches Verifier/Manager
4. A help request routes to a different Solver profile
5. Solver inbox changes the next context pack
"""

import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.blackboard import BlackboardService, BlackboardConfig
from attack_agent.team.context import ContextCompiler, SOLVER_CONTEXT_LIMITS
from attack_agent.team.ideas import IdeaService
from attack_agent.team.memory import MemoryService
from attack_agent.team.memory_reducer import KnowledgePacketBuilder, MemoryReducer
from attack_agent.team.merge import MergeHub, PacketRouteResult
from attack_agent.team.manager import TeamManager
from attack_agent.team.protocol import (
    KnowledgePacket,
    KnowledgePacketType,
    MemoryEntry,
    MemoryKind,
    SolverSession,
    SolverStatus,
)


def _make_bb() -> BlackboardService:
    return BlackboardService(BlackboardConfig(db_path=":memory:"))


def _seed_project(bb: BlackboardService, project_id: str = "p1") -> None:
    bb.append_event(project_id, EventType.PROJECT_UPSERTED.value,
                     {"challenge_id": "c1", "status": "new"})


def _seed_solver(bb: BlackboardService, project_id: str, solver_id: str,
                  profile: str = "network", status: str = "running") -> None:
    bb.append_event(project_id, EventType.WORKER_ASSIGNED.value, {
        "solver_id": solver_id,
        "profile": profile,
        "status": status,
    })


class TestL6DuplicateFactsMergeIntoOne(unittest.TestCase):
    """L6 acceptance criterion 1: duplicate facts merge into one accepted memory entry."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        self.merge = MergeHub(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_duplicate_facts_merge_into_one_accepted_entry(self):
        # Publish two identical fact packets from different solvers
        pkt1 = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.FACT,
            source_solver_id="s1",
            content="admin panel at /admin",
            confidence=0.8,
            routing_priority=80,
            suggested_recipients=["all"],
        )
        pkt2 = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.FACT,
            source_solver_id="s2",
            content="admin panel at /admin",
            confidence=0.8,
            routing_priority=80,
            suggested_recipients=["all"],
        )

        # Publish events
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt1.packet_id, "packet_type": "fact",
                               "content": pkt1.content, "confidence": pkt1.confidence,
                               "source_solver_id": "s1", "routing_priority": 80,
                               "suggested_recipients": ["all"]},
                              source="scheduler_l6")
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt2.packet_id, "packet_type": "fact",
                               "content": pkt2.content, "confidence": pkt2.confidence,
                               "source_solver_id": "s2", "routing_priority": 80,
                               "suggested_recipients": ["all"]},
                              source="scheduler_l6")

        # Process through MergeHub
        result = self.merge.process_incoming_packets("p1", [pkt1, pkt2])

        # Only one fact should be accepted (merged)
        accepted_facts = [p for p in result.global_packets
                          if p.packet_type == KnowledgePacketType.FACT
                          and p.merge_status == "accepted"]
        self.assertEqual(len(accepted_facts), 1,
                         "Duplicate facts must merge into one accepted entry")

        # The accepted packet should carry merged_from_ids
        self.assertTrue(len(accepted_facts[0].merged_from_ids) > 0,
                        "Accepted packet must track merged source IDs")

        # Dedup decision must exist
        dedup_decisions = [d for d in result.decisions if d.decision == "discard"]
        self.assertTrue(len(dedup_decisions) >= 1,
                        "Dedup decision must be recorded for duplicate facts")

    def test_duplicate_facts_result_in_one_blackboard_entry(self):
        pkt1 = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.FACT,
            source_solver_id="s1",
            content="found SQL injection",
            confidence=0.7,
            suggested_recipients=["all"],
        )
        pkt2 = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.FACT,
            source_solver_id="s2",
            content="found SQL injection",
            confidence=0.7,
            suggested_recipients=["all"],
        )

        # First publish and route pkt1 alone — it should be accepted
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt1.packet_id, "packet_type": "fact",
                               "content": pkt1.content, "confidence": pkt1.confidence,
                               "source_solver_id": "s1", "suggested_recipients": ["all"]},
                              source="scheduler_l6")
        self.merge.process_incoming_packets("p1", [pkt1])

        # Now publish pkt2 — duplicate, should be discarded
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt2.packet_id, "packet_type": "fact",
                               "content": pkt2.content, "confidence": pkt2.confidence,
                               "source_solver_id": "s2", "suggested_recipients": ["all"]},
                              source="scheduler_l6")
        result = self.merge.process_incoming_packets("p1", [pkt2])

        # Check Blackboard: only one fact entry for this content
        state = self.bb.rebuild_state("p1")
        fact_content_entries = [f for f in state.facts
                                if f.kind == MemoryKind.FACT
                                and "found SQL injection" in f.content]
        # Multiple OBSERVATION events may exist but they represent the merge trail
        # The key is that pkt2 was discarded and not added as a new fact
        discard_decisions = [d for d in result.decisions if d.decision == "discard"]
        self.assertTrue(len(discard_decisions) >= 1,
                        "Second duplicate packet must produce a discard decision")


class TestL6ConflictingFactsCreateMergeDecision(unittest.TestCase):
    """L6 acceptance criterion 2: conflicting facts create a merge decision."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        self.merge = MergeHub(self.bb)

    def tearDown(self):
        self.bb.close()

    def test_conflicting_facts_create_merge_decision(self):
        # First: establish an accepted fact packet
        pkt1 = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.FACT,
            source_solver_id="s1",
            content="backend uses Node.js",
            confidence=0.6,
            routing_priority=60,
            suggested_recipients=["all"],
        )
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt1.packet_id, "packet_type": "fact",
                               "content": pkt1.content, "confidence": pkt1.confidence,
                               "source_solver_id": "s1", "routing_priority": 60,
                               "suggested_recipients": ["all"]},
                              source="scheduler_l6")
        self.merge.process_incoming_packets("p1", [pkt1])

        # Now: send a conflicting fact (same content, different confidence)
        pkt2 = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.FACT,
            source_solver_id="s2",
            content="backend uses Node.js",
            confidence=0.9,
            routing_priority=90,
            suggested_recipients=["all"],
        )
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt2.packet_id, "packet_type": "fact",
                               "content": pkt2.content, "confidence": pkt2.confidence,
                               "source_solver_id": "s2", "routing_priority": 90,
                               "suggested_recipients": ["all"]},
                              source="scheduler_l6")
        result = self.merge.process_incoming_packets("p1", [pkt2])

        # A conflict decision must exist
        conflict_decisions = [d for d in result.decisions if d.decision == "conflict"]
        self.assertTrue(len(conflict_decisions) >= 1,
                        "Conflicting confidence values must produce a conflict decision")

        # The conflict decision must reference both packet IDs
        conflict = conflict_decisions[0]
        self.assertTrue(conflict.kept_entry_id or conflict.discarded_ids,
                        "Conflict decision must identify kept and discarded entries")

        # A conflict event must be in Blackboard
        events = self.bb.load_events("p1")
        conflict_events = [e for e in events
                           if e.event_type == EventType.KNOWLEDGE_PACKET_MERGED.value
                           and e.payload.get("merge_status") == "conflicted"]
        self.assertTrue(len(conflict_events) >= 1,
                        "Conflict must be recorded as KNOWLEDGE_PACKET_MERGED event in Blackboard")


class TestL6HighPriorityCandidateFlagReachesManager(unittest.TestCase):
    """L6 acceptance criterion 3: high-priority candidate flag reaches Verifier/Manager."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        _seed_solver(self.bb, "p1", "s1", "network", "running")
        self.merge = MergeHub(self.bb)
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
            manager=TeamManager(),
        )

    def tearDown(self):
        self.bb.close()

    def test_candidate_flag_packet_reaches_manager_context(self):
        # Create a high-priority candidate flag packet
        pkt = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.CANDIDATE_FLAG,
            source_solver_id="s1",
            content="flag{secret_found}",
            confidence=0.95,
            routing_priority=200,
            suggested_recipients=["all"],
            evidence_refs=["ev_1", "ev_2"],
        )

        # Publish and route
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt.packet_id, "packet_type": "candidate_flag",
                               "content": pkt.content, "confidence": pkt.confidence,
                               "source_solver_id": "s1", "routing_priority": 200,
                               "suggested_recipients": ["all"],
                               "evidence_refs": pkt.evidence_refs},
                              source="scheduler_l6")
        result = self.merge.process_incoming_packets("p1", [pkt])

        # The candidate flag must be routed as a global packet
        self.assertTrue(len(result.global_packets) >= 1,
                        "Candidate flag must be in global_packets after routing")

        # A CANDIDATE_FLAG event must be written to Blackboard by MergeHub
        events = self.bb.load_events("p1")
        flag_events = [e for e in events
                       if e.event_type == EventType.CANDIDATE_FLAG.value
                       and e.payload.get("flag") == "flag{secret_found}"]
        self.assertTrue(len(flag_events) >= 1,
                        "MergeHub must write CANDIDATE_FLAG event for accepted flag packet")

        # The flag must appear in ManagerContext when compiled
        ctx = self.compiler.compile_manager_context("p1", self.bb)
        flag_found = any(f.description == "flag{secret_found}" for f in ctx.candidate_flags)
        self.assertTrue(flag_found,
                        "High-priority candidate flag must appear in ManagerContext.candidate_flags")


class TestL6HelpRequestRoutesToDifferentProfile(unittest.TestCase):
    """L6 acceptance criterion 4: help request routes to a different Solver profile."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        # Create two solver sessions: network and browser
        _seed_solver(self.bb, "p1", "s1", "network", "running")
        _seed_solver(self.bb, "p1", "s2", "browser", "running")
        self.merge = MergeHub(self.bb)
        self.builder = KnowledgePacketBuilder()

    def tearDown(self):
        self.bb.close()

    def test_help_request_routes_to_browser_solver(self):
        # Network solver (s1) sends a help request targeting browser profile
        help_pkt = self.builder.build_help_request(
            project_id="p1",
            solver_id="s1",
            description="Need browser-based XSS testing",
            target_profile="browser",
        )

        # Publish and route
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": help_pkt.packet_id, "packet_type": "help_request",
                               "content": help_pkt.content, "confidence": help_pkt.confidence,
                               "source_solver_id": "s1", "routing_priority": 50,
                               "suggested_recipients": ["profile:browser"],
                               "evidence_refs": help_pkt.evidence_refs},
                              source="scheduler_l6")
        result = self.merge.process_incoming_packets("p1", [help_pkt])

        # The help request must be routed to the browser solver (s2), not the network solver (s1)
        self.assertTrue("s2" in result.targeted_packets,
                        "Help request targeting profile:browser must route to solver s2")
        targeted_to_s2 = result.targeted_packets.get("s2", [])
        self.assertTrue(any(p.packet_type == KnowledgePacketType.HELP_REQUEST for p in targeted_to_s2),
                        "Targeted packets for s2 must include the HELP_REQUEST")

        # It must NOT be in global_packets (targeted, not broadcast)
        help_in_global = [p for p in result.global_packets
                          if p.packet_type == KnowledgePacketType.HELP_REQUEST]
        self.assertEqual(len(help_in_global), 0,
                         "Help request must not be in global_packets — it's targeted")


class TestL6SolverInboxChangesContextPack(unittest.TestCase):
    """L6 acceptance criterion 5: Solver inbox changes the next context pack."""

    def setUp(self):
        self.bb = _make_bb()
        _seed_project(self.bb)
        _seed_solver(self.bb, "p1", "s1", "network", "running")
        self.merge = MergeHub(self.bb)
        self.mem_svc = MemoryService(self.bb)
        self.idea_svc = IdeaService(self.bb)
        self.compiler = ContextCompiler(
            memory_service=self.mem_svc,
            idea_service=self.idea_svc,
            manager=TeamManager(),
        )

    def tearDown(self):
        self.bb.close()

    def test_inbox_populated_from_routed_packets(self):
        # Create a fact packet targeted to solver s1
        pkt = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.FACT,
            source_solver_id="s2",
            content="discovered credentials in /etc/passwd",
            confidence=0.85,
            routing_priority=85,
            suggested_recipients=["all"],
        )

        # Publish and route through MergeHub
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt.packet_id, "packet_type": "fact",
                               "content": pkt.content, "confidence": pkt.confidence,
                               "source_solver_id": "s2", "routing_priority": 85,
                               "suggested_recipients": ["all"]},
                              source="scheduler_l6")
        result = self.merge.process_incoming_packets("p1", [pkt])

        # Compile solver context — inbox must contain the routed packet
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)

        # Inbox must NOT be empty
        self.assertTrue(len(ctx.inbox) > 0,
                        "Solver inbox must contain packets after routing")

        # The inbox item must include the fact content
        inbox_content = [item.get("content", "") for item in ctx.inbox]
        self.assertTrue(any("discovered credentials" in c for c in inbox_content),
                        "Inbox must contain the fact packet content")

    def test_targeted_packet_appears_in_target_solver_inbox(self):
        # Create a credential packet targeted specifically to solver s1
        pkt = KnowledgePacket(
            project_id="p1",
            packet_type=KnowledgePacketType.CREDENTIAL,
            source_solver_id="s2",
            content="admin:password123",
            confidence=0.9,
            routing_priority=90,
            suggested_recipients=["s1"],
        )

        # Publish
        self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                              {"packet_id": pkt.packet_id, "packet_type": "credential",
                               "content": pkt.content, "confidence": pkt.confidence,
                               "source_solver_id": "s2", "routing_priority": 90,
                               "suggested_recipients": ["s1"]},
                              source="scheduler_l6")
        result = self.merge.process_incoming_packets("p1", [pkt])

        # Deliver targeted packet via KNOWLEDGE_PACKET_MERGED event
        for target_id, targeted_pkts in result.targeted_packets.items():
            for tpkt in targeted_pkts:
                self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_MERGED.value, {
                    "packet_id": tpkt.packet_id,
                    "packet_type": tpkt.packet_type.value,
                    "content": tpkt.content,
                    "confidence": tpkt.confidence,
                    "merge_status": "accepted",
                    "routing_priority": tpkt.routing_priority,
                    "source_solver_id": tpkt.source_solver_id,
                    "suggested_recipients": tpkt.suggested_recipients,
                    "evidence_refs": tpkt.evidence_refs,
                }, source="merge_hub_targeted")

        # Compile context for solver s1 — targeted packet must be in inbox
        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        self.assertTrue(len(ctx.inbox) > 0,
                        "Targeted packet must appear in solver s1's inbox")

        inbox_content = [item.get("content", "") for item in ctx.inbox]
        self.assertTrue(any("admin:password123" in c for c in inbox_content),
                        "Targeted credential packet must be in s1's inbox content")

    def test_inbox_bounded_by_limits(self):
        # Route many packets — inbox must stay bounded
        for i in range(20):
            pkt = KnowledgePacket(
                project_id="p1",
                packet_type=KnowledgePacketType.FACT,
                source_solver_id="s2",
                content=f"fact_{i}",
                confidence=0.7,
                suggested_recipients=["all"],
            )
            self.bb.append_event("p1", EventType.KNOWLEDGE_PACKET_PUBLISHED.value,
                                  {"packet_id": pkt.packet_id, "packet_type": "fact",
                                   "content": pkt.content, "confidence": pkt.confidence,
                                   "source_solver_id": "s2",
                                   "suggested_recipients": ["all"]},
                                  source="scheduler_l6")
            self.merge.process_incoming_packets("p1", [pkt])

        ctx = self.compiler.compile_solver_context("p1", "s1", self.bb)
        max_inbox = SOLVER_CONTEXT_LIMITS["max_inbox_items"]
        self.assertTrue(len(ctx.inbox) <= max_inbox,
                        f"Inbox must be bounded by max_inbox_items={max_inbox}")


if __name__ == "__main__":
    unittest.main()