from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from attack_agent.apg import APGPlanner, CodeSandbox, EpisodeMemory, PatternLibrary, FAMILY_KEYWORDS, FAMILY_PROGRAMS, FAMILY_PROFILES
from attack_agent.platform_models import ChallengeDefinition, EpisodeEntry, PatternNodeKind, PrimitiveActionStep, ProjectSnapshot, WorkerProfile
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

    def test_pattern_graph_prioritizes_ssrf_family(self) -> None:
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        snapshot = ProjectSnapshot(
            project_id="project:ssrf-1",
            challenge=ChallengeDefinition(
                id="ssrf-1",
                name="Internal Proxy",
                category="web",
                difficulty="medium",
                target="http://demo",
                description="A fetch endpoint proxies requests to internal services and cloud metadata.",
                metadata={"signals": ["ssrf", "internal", "metadata", "cloud"]},
            ),
        )
        graph = planner.create_graph(snapshot)
        self.assertEqual("ssrf-server-boundary", graph.family_priority[0])

    def test_pattern_graph_prioritizes_ssti_family(self) -> None:
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        snapshot = ProjectSnapshot(
            project_id="project:ssti-1",
            challenge=ChallengeDefinition(
                id="ssti-1",
                name="Jinja Injection",
                category="web",
                difficulty="medium",
                target="http://demo",
                description="A jinja template engine evaluates user expressions and renders output.",
                metadata={"signals": ["ssti", "jinja", "expression"]},
            ),
        )
        graph = planner.create_graph(snapshot)
        self.assertEqual("ssti-template-boundary", graph.family_priority[0])

    def test_pattern_graph_prioritizes_crypto_family(self) -> None:
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        snapshot = ProjectSnapshot(
            project_id="project:crypto-1",
            challenge=ChallengeDefinition(
                id="crypto-1",
                name="RSA Padding Oracle",
                category="crypto",
                difficulty="hard",
                target="http://demo",
                description="An RSA padding oracle leaks ciphertext plaintext information through differential responses.",
                metadata={"signals": ["rsa", "padding", "oracle"]},
            ),
        )
        graph = planner.create_graph(snapshot)
        self.assertEqual("crypto-math-boundary", graph.family_priority[0])

    def test_pattern_graph_prioritizes_pwn_family(self) -> None:
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        snapshot = ProjectSnapshot(
            project_id="project:pwn-1",
            challenge=ChallengeDefinition(
                id="pwn-1",
                name="Buffer Overflow ROP",
                category="pwn",
                difficulty="hard",
                target="http://demo",
                description="A buffer overflow with ROP gadgets allows shellcode execution bypassing NX.",
                metadata={"signals": ["pwn", "overflow", "rop", "gadget"]},
            ),
        )
        graph = planner.create_graph(snapshot)
        self.assertEqual("pwn-memory-boundary", graph.family_priority[0])

    def test_all_14_families_have_keywords_profiles_and_programs(self) -> None:
        """All 14 families must have keywords, profiles, and 4-node programs"""
        for family in FAMILY_KEYWORDS:
            self.assertIn(family, FAMILY_PROFILES, f"{family} missing from FAMILY_PROFILES")
            self.assertIn(family, FAMILY_PROGRAMS, f"{family} missing from FAMILY_PROGRAMS")
            programs = FAMILY_PROGRAMS[family]
            for kind in (PatternNodeKind.OBSERVATION_GATE, PatternNodeKind.ACTION_TEMPLATE, PatternNodeKind.VERIFICATION_GATE, PatternNodeKind.FALLBACK):
                self.assertIn(kind, programs, f"{family} missing {kind} in FAMILY_PROGRAMS")
                self.assertTrue(len(programs[kind]) > 0, f"{family} has empty {kind} steps")
        self.assertEqual(len(FAMILY_KEYWORDS), 14, "Expected 14 families")

    def test_new_family_keywords_have_low_overlap_with_core(self) -> None:
        """New 8 families should not heavily overlap keywords with original 6 families"""
        core_families = {"identity-boundary", "input-interpreter-boundary", "reflection-render-boundary",
                         "file-archive-forensics", "encoding-transform", "binary-string-extraction"}
        new_families = set(FAMILY_KEYWORDS.keys()) - core_families
        for new_fam in new_families:
            new_kws = set(FAMILY_KEYWORDS[new_fam])
            for core_fam in core_families:
                core_kws = set(FAMILY_KEYWORDS[core_fam])
                overlap = new_kws & core_kws
                self.assertLessEqual(len(overlap), 1,
                                     f"{new_fam} overlaps {core_fam} by {overlap} (>1 keyword)")

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
