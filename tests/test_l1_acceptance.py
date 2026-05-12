"""L1 Event Semantics Cleanup — Acceptance tests.

Verifies the 5 acceptance criteria from the Team Evolution Roadmap:
1. Proposing an idea does not increase candidate flag count.
2. Recording CONVERGE does not create an IdeaEntry.
3. A real extracted flag appears as candidate flag with evidence refs.
4. TeamManager.decide_submit() ignores non-flag ideas.
5. Legacy event logs can still be replayed.
"""

import os
import tempfile
import unittest

from attack_agent.platform_models import EventType
from attack_agent.team.apply_event import apply_event_to_state
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.ideas import IdeaService
from attack_agent.team.manager import ManagerConfig, TeamManager
from attack_agent.team.protocol import (
    ActionType,
    IdeaEntry,
    IdeaStatus,
    MemoryKind,
    StrategyAction,
    TeamProject,
)
from attack_agent.team.scheduler import SyncScheduler, _record_action


def _make_bb(test_name: str) -> BlackboardService:
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, f"bb_l1_{test_name}.db")
    return BlackboardService(BlackboardConfig(db_path=db_path))


class TestL1Acceptance1_IdeaDoesNotIncreaseCandidateFlagCount(unittest.TestCase):
    """Acceptance 1: Proposing an idea does not increase candidate flag count."""

    def setUp(self):
        self.bb = _make_bb("accept1")
        self.mgr = TeamManager()
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_idea_proposal_not_counted_as_candidate_flag(self):
        idea_svc = IdeaService(self.bb)
        idea_svc.propose("p1", "try SQL injection")
        events = self.bb.load_events("p1")
        stagnation = self.mgr._compute_stagnation("p1", events)
        self.assertEqual(stagnation.candidate_flag_count, 0)
        self.assertFalse(stagnation.has_candidate_flags)

    def test_idea_claim_not_counted_as_candidate_flag(self):
        idea_svc = IdeaService(self.bb)
        idea = idea_svc.propose("p1", "try XSS")
        idea_svc.claim("p1", idea.idea_id, "s1")
        events = self.bb.load_events("p1")
        stagnation = self.mgr._compute_stagnation("p1", events)
        self.assertEqual(stagnation.candidate_flag_count, 0)

    def test_idea_verified_not_counted_as_candidate_flag(self):
        idea_svc = IdeaService(self.bb)
        idea = idea_svc.propose("p1", "flag found")
        idea_svc.mark_verified("p1", idea.idea_id)
        events = self.bb.load_events("p1")
        stagnation = self.mgr._compute_stagnation("p1", events)
        self.assertEqual(stagnation.candidate_flag_count, 0)

    def test_genuine_flag_is_counted(self):
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{real}", "confidence": 0.9},
                             source="state_sync")
        events = self.bb.load_events("p1")
        stagnation = self.mgr._compute_stagnation("p1", events)
        self.assertEqual(stagnation.candidate_flag_count, 1)
        self.assertTrue(stagnation.has_candidate_flags)


class TestL1Acceptance2_ConvergeDoesNotCreateIdeaEntry(unittest.TestCase):
    """Acceptance 2: Recording CONVERGE does not create an IdeaEntry."""

    def setUp(self):
        self.bb = _make_bb("accept2")

    def tearDown(self):
        self.bb.close()

    def test_converge_action_no_idea_entry(self):
        action = StrategyAction(
            action_type=ActionType.CONVERGE,
            project_id="p1",
            reason="converge on candidates",
        )
        _record_action(self.bb, action)
        state = self.bb.rebuild_state("p1")
        # CONVERGE recorded as strategy_action, not as IdeaEntry
        self.assertEqual(len(state.ideas), 0)
        events = self.bb.load_events("p1")
        # The event type should be strategy_action, not candidate_flag
        self.assertEqual(events[0].event_type, EventType.STRATEGY_ACTION.value)


class TestL1Acceptance3_RealFlagHasEvidenceRefs(unittest.TestCase):
    """Acceptance 3: A real extracted flag appears as candidate flag with evidence refs."""

    def setUp(self):
        self.bb = _make_bb("accept3")
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_genuine_flag_appears_as_fact(self):
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{abc123}", "confidence": 0.95},
                             source="state_sync")
        state = self.bb.rebuild_state("p1")
        # genuine flag creates a fact, not an idea
        flag_facts = [f for f in state.facts
                      if f.kind == MemoryKind.FACT and f.content.startswith("candidate flag:")]
        self.assertEqual(len(flag_facts), 1)
        self.assertIn("flag{abc123}", flag_facts[0].content)
        self.assertEqual(len(state.ideas), 0)

    def test_genuine_flag_triggers_convergence_in_stage_inference(self):
        from attack_agent.team.scheduler import _infer_stage
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{abc}", "confidence": 0.9},
                             source="state_sync")
        events = self.bb.load_events("p1")
        stage = _infer_stage(events, "running")
        self.assertEqual(stage, "converge")


class TestL1Acceptance4_SubmitIgnoresNonFlagIdeas(unittest.TestCase):
    """Acceptance 4: TeamManager.decide_submit() ignores non-flag ideas."""

    def setUp(self):
        self.bb = _make_bb("accept4")
        self.mgr = TeamManager(ManagerConfig(confidence_threshold=0.6))
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})

    def tearDown(self):
        self.bb.close()

    def test_idea_proposal_not_treated_as_candidate(self):
        idea_svc = IdeaService(self.bb)
        idea_svc.propose("p1", "try SQL injection")
        events = self.bb.load_events("p1")
        action = self.mgr.decide_submit("p1", events)
        # no genuine candidates → abandon
        self.assertEqual(action.action_type, ActionType.ABANDON)

    def test_idea_claim_not_treated_as_candidate(self):
        idea_svc = IdeaService(self.bb)
        idea = idea_svc.propose("p1", "check cookies")
        idea_svc.claim("p1", idea.idea_id, "s1")
        events = self.bb.load_events("p1")
        action = self.mgr.decide_submit("p1", events)
        self.assertEqual(action.action_type, ActionType.ABANDON)

    def test_idea_verified_not_treated_as_candidate(self):
        idea_svc = IdeaService(self.bb)
        idea = idea_svc.propose("p1", "flag{maybe}")
        idea_svc.mark_verified("p1", idea.idea_id)
        events = self.bb.load_events("p1")
        action = self.mgr.decide_submit("p1", events)
        # verified idea is not a genuine flag → still no candidates
        self.assertEqual(action.action_type, ActionType.ABANDON)

    def test_genuine_flag_is_treated_as_candidate(self):
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{real}", "confidence": 0.9},
                             source="state_sync")
        events = self.bb.load_events("p1")
        action = self.mgr.decide_submit("p1", events)
        self.assertEqual(action.action_type, ActionType.SUBMIT_FLAG)


class TestL1Acceptance5_LegacyEventReplay(unittest.TestCase):
    """Acceptance 5: Legacy event logs can still be replayed."""

    def setUp(self):
        self.bb = _make_bb("accept5")

    def tearDown(self):
        self.bb.close()

    def test_old_idea_service_events_replay_as_ideas(self):
        # Simulate old-format IdeaService events (candidate_flag with status)
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "old idea", "idea_id": "i1", "status": "pending",
                              "confidence": 0.5, "priority": 100},
                             source="idea_service")
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "old idea", "idea_id": "i1", "status": "claimed",
                              "confidence": 0.5, "solver_id": "s1"},
                             source="idea_service")
        state = self.bb.rebuild_state("p1")
        # old idea lifecycle events replay correctly as idea, not as candidate flag fact
        self.assertEqual(len(state.ideas), 1)
        self.assertEqual(state.ideas[0].description, "old idea")
        self.assertEqual(state.ideas[0].status, IdeaStatus.CLAIMED)
        self.assertEqual(state.ideas[0].solver_id, "s1")
        # no false candidate flag fact
        flag_facts = [f for f in state.facts
                      if f.kind == MemoryKind.FACT and f.content.startswith("candidate flag:")]
        self.assertEqual(len(flag_facts), 0)

    def test_old_state_sync_events_replay_as_genuine_flags(self):
        # Old genuine flag events (no status) still replay correctly
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{legacy}", "confidence": 0.9},
                             source="state_sync")
        state = self.bb.rebuild_state("p1")
        # genuine flag creates fact, not idea
        flag_facts = [f for f in state.facts
                      if f.kind == MemoryKind.FACT and f.content.startswith("candidate flag:")]
        self.assertEqual(len(flag_facts), 1)
        self.assertIn("flag{legacy}", flag_facts[0].content)
        self.assertEqual(len(state.ideas), 0)

    def test_mixed_legacy_and_new_events_replay_correctly(self):
        self.bb.append_event("p1", EventType.PROJECT_UPSERTED.value, {"status": "new"})
        # legacy idea event
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "legacy idea", "idea_id": "i1", "status": "pending"},
                             source="idea_service")
        # new-style idea event
        self.bb.append_event("p1", EventType.IDEA_PROPOSED.value,
                             {"flag": "new idea", "idea_id": "i2", "status": "pending"},
                             source="idea_service")
        # genuine flag
        self.bb.append_event("p1", EventType.CANDIDATE_FLAG.value,
                             {"flag": "flag{genuine}", "confidence": 0.9},
                             source="state_sync")
        state = self.bb.rebuild_state("p1")
        # 2 ideas (one from legacy, one from new)
        self.assertEqual(len(state.ideas), 2)
        # 1 genuine flag fact
        flag_facts = [f for f in state.facts
                      if f.kind == MemoryKind.FACT and f.content.startswith("candidate flag:")]
        self.assertEqual(len(flag_facts), 1)
        # manager sees only genuine flag as candidate
        events = self.bb.load_events("p1")
        mgr = TeamManager()
        stagnation = mgr._compute_stagnation("p1", events)
        self.assertEqual(stagnation.candidate_flag_count, 1)


if __name__ == "__main__":
    unittest.main()