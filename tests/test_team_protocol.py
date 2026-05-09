"""Tests for attack_agent.team.protocol — Phase A protocol extraction."""

import unittest

from attack_agent.team.protocol import (
    ActionType,
    FailureBoundary,
    HumanDecision,
    HumanDecisionChoice,
    IdeaEntry,
    IdeaStatus,
    MemoryEntry,
    MemoryKind,
    PolicyDecision,
    PolicyOutcome,
    ReviewRequest,
    ReviewStatus,
    SolverSession,
    SolverStatus,
    StrategyAction,
    TeamProject,
    from_dict,
    legacy_bundle_to_solver_session,
    legacy_episode_to_memory_entry,
    legacy_project_to_team_project,
    legacy_submit_decision_to_policy,
    to_dict,
)
from attack_agent.platform_models import (
    EpisodeEntry,
    ProjectSnapshot,
    TaskBundle,
    WorkerProfile,
)
from attack_agent.strategy import SubmitDecision
from attack_agent.state_graph import ProjectRecord, WorldState


class TestDataclassInstantiation(unittest.TestCase):
    """All protocol dataclasses can be instantiated with defaults."""

    def test_team_project_defaults(self):
        p = TeamProject()
        self.assertTrue(p.project_id)
        self.assertEqual(p.status, "new")
        self.assertTrue(p.created_at)

    def test_strategy_action_defaults(self):
        a = StrategyAction()
        self.assertEqual(a.action_type, ActionType.LAUNCH_SOLVER)

    def test_solver_session_defaults(self):
        s = SolverSession()
        self.assertTrue(s.solver_id)
        self.assertEqual(s.status, SolverStatus.CREATED)

    def test_memory_entry_defaults(self):
        m = MemoryEntry()
        self.assertTrue(m.entry_id)
        self.assertEqual(m.kind, MemoryKind.FACT)

    def test_idea_entry_defaults(self):
        i = IdeaEntry()
        self.assertTrue(i.idea_id)
        self.assertEqual(i.status, IdeaStatus.PENDING)

    def test_failure_boundary_defaults(self):
        b = FailureBoundary()
        self.assertTrue(b.boundary_id)

    def test_policy_decision_defaults(self):
        d = PolicyDecision()
        self.assertEqual(d.decision, PolicyOutcome.ALLOW)

    def test_review_request_defaults(self):
        r = ReviewRequest()
        self.assertTrue(r.request_id)
        self.assertEqual(r.status, ReviewStatus.PENDING)

    def test_human_decision_defaults(self):
        h = HumanDecision()
        self.assertEqual(h.decision, HumanDecisionChoice.APPROVED)

    def test_explicit_values(self):
        p = TeamProject(project_id="p1", challenge_id="c1", status="running")
        self.assertEqual(p.project_id, "p1")
        self.assertEqual(p.challenge_id, "c1")
        self.assertEqual(p.status, "running")


class TestSerializationRoundtrip(unittest.TestCase):
    """to_dict → from_dict preserves all data for each dataclass."""

    def test_team_project_roundtrip(self):
        p = TeamProject(project_id="p1", challenge_id="c2")
        d = to_dict(p)
        p2 = from_dict(TeamProject, d)
        self.assertEqual(p.project_id, p2.project_id)
        self.assertEqual(p.challenge_id, p2.challenge_id)

    def test_strategy_action_roundtrip(self):
        a = StrategyAction(action_type=ActionType.SUBMIT_FLAG, priority=50)
        d = to_dict(a)
        a2 = from_dict(StrategyAction, d)
        self.assertEqual(a.action_type, a2.action_type)
        self.assertEqual(a.priority, a2.priority)

    def test_solver_session_roundtrip(self):
        s = SolverSession(status=SolverStatus.RUNNING, profile="browser")
        d = to_dict(s)
        s2 = from_dict(SolverSession, d)
        self.assertEqual(s.status, s2.status)
        self.assertEqual(s.profile, s2.profile)

    def test_memory_entry_roundtrip(self):
        m = MemoryEntry(kind=MemoryKind.CREDENTIAL, content="admin:pass")
        d = to_dict(m)
        m2 = from_dict(MemoryEntry, d)
        self.assertEqual(m.kind, m2.kind)
        self.assertEqual(m.content, m2.content)

    def test_idea_entry_roundtrip(self):
        i = IdeaEntry(status=IdeaStatus.TESTING, priority=75)
        d = to_dict(i)
        i2 = from_dict(IdeaEntry, d)
        self.assertEqual(i.status, i2.status)
        self.assertEqual(i.priority, i2.priority)

    def test_failure_boundary_roundtrip(self):
        b = FailureBoundary(description="path blocked")
        d = to_dict(b)
        b2 = from_dict(FailureBoundary, d)
        self.assertEqual(b.description, b2.description)

    def test_policy_decision_roundtrip(self):
        d_obj = PolicyDecision(decision=PolicyOutcome.DENY, reason="unsafe")
        d = to_dict(d_obj)
        d2 = from_dict(PolicyDecision, d)
        self.assertEqual(d_obj.decision, d2.decision)
        self.assertEqual(d_obj.reason, d2.reason)

    def test_review_request_roundtrip(self):
        r = ReviewRequest(risk_level="high", title="submit flag X")
        d = to_dict(r)
        r2 = from_dict(ReviewRequest, d)
        self.assertEqual(r.risk_level, r2.risk_level)
        self.assertEqual(r.title, r2.title)

    def test_human_decision_roundtrip(self):
        h = HumanDecision(decision=HumanDecisionChoice.REJECTED, reason="bad flag")
        d = to_dict(h)
        h2 = from_dict(HumanDecision, d)
        self.assertEqual(h.decision, h2.decision)
        self.assertEqual(h.reason, h2.reason)

    def test_enum_serialized_as_string(self):
        """Enums should serialize to their string values, not enum objects."""
        a = StrategyAction(action_type=ActionType.CONVERGE)
        d = to_dict(a)
        self.assertEqual(d["action_type"], "converge")
        self.assertIsInstance(d["action_type"], str)


class TestLegacyMappings(unittest.TestCase):
    """Legacy mapping functions return non-None vNext objects."""

    def test_project_record_to_team_project(self):
        from attack_agent.platform_models import ChallengeDefinition, ChallengeInstance
        challenge = ChallengeDefinition(id="c1", name="test", category="web", difficulty="easy", target="http://x")
        snap = ProjectSnapshot(project_id="p1", challenge=challenge)
        record = ProjectRecord(snapshot=snap, world_state=WorldState())
        tp = legacy_project_to_team_project(record)
        self.assertIsNotNone(tp)
        self.assertEqual(tp.project_id, "p1")
        self.assertEqual(tp.challenge_id, "c1")

    def test_task_bundle_to_solver_session(self):
        from attack_agent.platform_models import ActionProgram, ChallengeDefinition, ChallengeInstance, PrimitiveActionStep
        challenge = ChallengeDefinition(id="c1", name="test", category="web", difficulty="easy", target="http://x")
        instance = ChallengeInstance(instance_id="i1", challenge_id="c1", target="http://x", status="running")
        program = ActionProgram(
            id="prog1", goal="test", pattern_nodes=[], steps=[],
            allowed_primitives=[], verification_rules=[], required_profile=WorkerProfile.NETWORK,
        )
        bundle = TaskBundle(
            project_id="p1", run_id="r1", action_program=program,
            stage=ProjectSnapshot(project_id="p1", challenge=challenge).stage,
            worker_profile=WorkerProfile.NETWORK,
            target="http://x", challenge=challenge, instance=instance,
            handoff_summary="",
            visible_primitives=[],
        )
        ss = legacy_bundle_to_solver_session(bundle, "s1")
        self.assertIsNotNone(ss)
        self.assertEqual(ss.solver_id, "s1")
        self.assertEqual(ss.project_id, "p1")
        self.assertEqual(ss.profile, "network")

    def test_submit_decision_to_policy(self):
        dec_accepted = SubmitDecision(accepted=True, reason="flag looks valid")
        pd = legacy_submit_decision_to_policy(dec_accepted)
        self.assertIsNotNone(pd)
        self.assertEqual(pd.decision, PolicyOutcome.ALLOW)
        self.assertEqual(pd.action_type, "submit_flag")

        dec_denied = SubmitDecision(accepted=False, reason="format mismatch")
        pd2 = legacy_submit_decision_to_policy(dec_denied)
        self.assertEqual(pd2.decision, PolicyOutcome.DENY)

    def test_episode_to_memory_entry(self):
        ep_success = EpisodeEntry(id="e1", feature_text="f", pattern_families=["web"], summary="found endpoint", success=True)
        me = legacy_episode_to_memory_entry(ep_success)
        self.assertIsNotNone(me)
        self.assertEqual(me.kind, MemoryKind.FACT)
        self.assertEqual(me.content, "found endpoint")

        ep_fail = EpisodeEntry(id="e2", feature_text="f", pattern_families=["crypto"], summary="encryption blocked", success=False)
        me2 = legacy_episode_to_memory_entry(ep_fail)
        self.assertEqual(me2.kind, MemoryKind.FAILURE_BOUNDARY)


if __name__ == "__main__":
    unittest.main()