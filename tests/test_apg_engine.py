from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from attack_agent.apg import APGPlanner, CodeSandbox, EpisodeMemory, PatternLibrary
from attack_agent.platform_models import ChallengeDefinition, EpisodeEntry, PrimitiveActionStep, ProjectSnapshot
from attack_agent.reasoning import HeuristicReasoner, LLMReasoner, PlanCandidate, ReasoningContext, StaticReasoningModel


class APGEngineTests(unittest.TestCase):
    def test_pattern_graph_prioritizes_identity_boundary(self) -> None:
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        snapshot = ProjectSnapshot(
            project_id="project:web-1",
            challenge=ChallengeDefinition(
                id="web-1",
                name="JWT Admin Panel",
                category="web",
                difficulty="medium",
                target="http://demo",
                description="A login page issues a token and the admin role unlocks the hidden admin endpoint.",
                metadata={"signals": ["login", "token", "admin", "role"]},
            ),
        )
        graph = planner.create_graph(snapshot)
        self.assertEqual("identity-boundary", graph.family_priority[0])

    def test_episode_memory_returns_relevant_hits(self) -> None:
        memory = EpisodeMemory()
        memory.add(EpisodeEntry(id="ep1", feature_text="jwt token role admin cookie", pattern_families=["identity-boundary"], summary="auth boundary", success=True))
        hits = memory.search("admin token cookie")
        self.assertTrue(hits)
        self.assertEqual("ep1", hits[0].episode_id)

    def test_episode_memory_ranks_stronger_match_ahead_of_partial_overlap(self) -> None:
        memory = EpisodeMemory()
        memory.add(
            EpisodeEntry(
                id="ep-strong",
                feature_text="admin token cookie role jwt session",
                pattern_families=["identity-boundary"],
                summary="strong auth match",
                success=True,
            )
        )
        memory.add(
            EpisodeEntry(
                id="ep-partial",
                feature_text="admin token cookie",
                pattern_families=["identity-boundary"],
                summary="partial auth overlap",
                success=True,
            )
        )

        hits = memory.search("admin token cookie role")

        self.assertGreaterEqual(len(hits), 2)
        self.assertEqual("ep-strong", hits[0].episode_id)
        self.assertEqual("ep-partial", hits[1].episode_id)

    def test_episode_memory_persists_entries_to_local_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "episodes.json"
            memory = EpisodeMemory(store_path)
            memory.add(
                EpisodeEntry(
                    id="ep-persisted",
                    feature_text="archive file extract note",
                    pattern_families=["file-archive-forensics"],
                    summary="artifact path",
                    success=True,
                )
            )

            reloaded = EpisodeMemory(store_path)
            hits = reloaded.search("extract archive note")
            self.assertTrue(hits)
            self.assertEqual("ep-persisted", hits[0].episode_id)

    def test_code_sandbox_blocks_imports(self) -> None:
        sandbox = CodeSandbox()
        with self.assertRaisesRegex(RuntimeError, "sandbox_disallowed"):
            sandbox.execute("import os\nresult = {}", {})

    def test_llm_reasoner_accepts_valid_candidate_index_selection(self) -> None:
        reasoner = LLMReasoner(
            StaticReasoningModel(
                {
                    "choose_program": {
                        "candidate_index": 1,
                        "rationale": "second candidate fits the current evidence better",
                    }
                }
            )
        )
        context = ReasoningContext(
            challenge_id="web-1",
            challenge_name="JWT Admin Panel",
            category="web",
            description="login token admin role",
            signals=["login", "token", "admin"],
            candidates=[
                PlanCandidate(
                    family="identity-boundary",
                    node_id="identity-boundary:observe",
                    node_kind="observation_gate",
                    steps=[PrimitiveActionStep("http-request", "inspect auth routes")],
                    score=3.0,
                ),
                PlanCandidate(
                    family="identity-boundary",
                    node_id="identity-boundary:act",
                    node_kind="action_template",
                    steps=[PrimitiveActionStep("diff-compare", "compare privilege-sensitive responses")],
                    score=2.0,
                ),
            ],
        )

        decision = reasoner.choose_program(context)

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual("identity-boundary", decision.family)
        self.assertEqual("identity-boundary:act", decision.node_id)
        self.assertEqual("llm", decision.source)

    def test_llm_reasoner_candidate_index_uses_heuristic_candidate_order(self) -> None:
        reasoner = LLMReasoner(
            StaticReasoningModel(
                {
                    "choose_program": {
                        "candidate_index": 0,
                        "rationale": "pick the top-ranked heuristic candidate",
                    }
                }
            )
        )
        context = ReasoningContext(
            challenge_id="web-1",
            challenge_name="JWT Admin Panel",
            category="web",
            description="login token admin role",
            signals=["login", "token", "admin"],
            candidates=[
                PlanCandidate(
                    family="identity-boundary",
                    node_id="identity-boundary:act",
                    node_kind="action_template",
                    steps=[PrimitiveActionStep("diff-compare", "compare privilege-sensitive responses")],
                    score=2.0,
                ),
                PlanCandidate(
                    family="identity-boundary",
                    node_id="identity-boundary:observe",
                    node_kind="observation_gate",
                    steps=[PrimitiveActionStep("http-request", "inspect auth routes")],
                    score=3.0,
                ),
            ],
        )

        decision = reasoner.choose_program(context)

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual("identity-boundary:observe", decision.node_id)
        self.assertEqual("llm", decision.source)

    def test_llm_reasoner_candidate_index_uses_deterministic_tie_break(self) -> None:
        reasoner = LLMReasoner(
            StaticReasoningModel(
                {
                    "choose_program": {
                        "candidate_index": 0,
                        "rationale": "pick the deterministically first equal-ranked candidate",
                    }
                }
            )
        )
        context = ReasoningContext(
            challenge_id="web-1",
            challenge_name="JWT Admin Panel",
            category="web",
            description="login token admin role",
            signals=["login", "token", "admin"],
            candidates=[
                PlanCandidate(
                    family="identity-boundary",
                    node_id="identity-boundary:zeta",
                    node_kind="action_template",
                    steps=[PrimitiveActionStep("diff-compare", "compare privilege-sensitive responses")],
                    score=3.0,
                ),
                PlanCandidate(
                    family="identity-boundary",
                    node_id="identity-boundary:alpha",
                    node_kind="observation_gate",
                    steps=[PrimitiveActionStep("http-request", "inspect auth routes")],
                    score=3.0,
                ),
            ],
        )

        decision = reasoner.choose_program(context)

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual("identity-boundary:alpha", decision.node_id)
        self.assertEqual("llm", decision.source)

    def test_llm_reasoner_candidate_index_matches_heuristic_fallback_choice(self) -> None:
        heuristic = HeuristicReasoner()
        llm_reasoner = LLMReasoner(
            StaticReasoningModel(
                {
                    "choose_program": {
                        "candidate_index": 0,
                        "rationale": "pick the top heuristic candidate",
                    }
                }
            ),
            fallback=heuristic,
        )
        context = ReasoningContext(
            challenge_id="web-1",
            challenge_name="JWT Admin Panel",
            category="web",
            description="login token admin role",
            signals=["login", "token", "admin"],
            candidates=[
                PlanCandidate(
                    family="identity-boundary",
                    node_id="identity-boundary:verify",
                    node_kind="verification_gate",
                    steps=[PrimitiveActionStep("extract-candidate", "extract candidate flag")],
                    score=2.0,
                ),
                PlanCandidate(
                    family="identity-boundary",
                    node_id="identity-boundary:observe",
                    node_kind="observation_gate",
                    steps=[PrimitiveActionStep("http-request", "inspect auth routes")],
                    score=3.0,
                ),
            ],
        )

        heuristic_decision = heuristic.choose_program(context)
        llm_decision = llm_reasoner.choose_program(context)

        self.assertIsNotNone(heuristic_decision)
        self.assertIsNotNone(llm_decision)
        assert heuristic_decision is not None
        assert llm_decision is not None
        self.assertEqual(heuristic_decision.node_id, llm_decision.node_id)
        self.assertEqual("llm", llm_decision.source)


if __name__ == "__main__":
    unittest.main()
