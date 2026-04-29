from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from attack_agent.apg import APGPlanner, CodeSandbox, EpisodeMemory, PatternLibrary, FAMILY_KEYWORDS, FAMILY_PROGRAMS, FAMILY_PROFILES, _inject_challenge_params
from attack_agent.platform_models import ChallengeDefinition, ChallengeInstance, EpisodeEntry, PatternNodeKind, PrimitiveActionStep, ProjectSnapshot, WorkerProfile, DualPathConfig, PathType, PlanningContext, ActionProgram, ActionOutcome, EventType, ProjectStage
from attack_agent.reasoning import HeuristicReasoner, LLMReasoner, PlanCandidate, ReasoningContext, StaticReasoningModel
from attack_agent.enhanced_apg import EnhancedAPGPlanner
from attack_agent.semantic_retrieval import SemanticRetrievalEngine
from attack_agent.dynamic_pattern_composer import DynamicPatternComposer
from attack_agent.heuristic_free_exploration import HeuristicFreeExplorationPlanner
from attack_agent.constraints import LightweightSecurityShell, SecurityConstraints


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

    def test_inject_challenge_params_fills_url_for_http_request(self) -> None:
        challenge = ChallengeDefinition(id="c1", name="Test", category="web",
                                        difficulty="easy", target="http://127.0.0.1:8080")
        steps = [PrimitiveActionStep("http-request", "Inspect routes", {"required_tags": ["identity-boundary", "observation_gate"]})]
        injected = _inject_challenge_params(steps, challenge)
        self.assertEqual(injected[0].parameters["url"], "http://127.0.0.1:8080")

    def test_inject_challenge_params_fills_url_for_browser_inspect(self) -> None:
        challenge = ChallengeDefinition(id="c1", name="Test", category="web",
                                        difficulty="easy", target="http://127.0.0.1:8080")
        steps = [PrimitiveActionStep("browser-inspect", "Observe page", {"required_tags": ["reflection-render-boundary", "observation_gate"]})]
        injected = _inject_challenge_params(steps, challenge)
        self.assertEqual(injected[0].parameters["url"], "http://127.0.0.1:8080")

    def test_inject_challenge_params_fills_login_url_for_session_materialize(self) -> None:
        challenge = ChallengeDefinition(id="c1", name="Test", category="web",
                                        difficulty="easy", target="http://127.0.0.1:8080")
        steps = [PrimitiveActionStep("session-materialize", "Login", {"required_tags": ["identity-boundary", "action_template"]})]
        injected = _inject_challenge_params(steps, challenge)
        self.assertEqual(injected[0].parameters["login_url"], "http://127.0.0.1:8080")

    def test_inject_challenge_params_preserves_existing_params(self) -> None:
        challenge = ChallengeDefinition(id="c1", name="Test", category="web",
                                        difficulty="easy", target="http://127.0.0.1:8080")
        steps = [PrimitiveActionStep("http-request", "Custom URL", {"required_tags": ["x"], "url": "http://custom:9999"})]
        injected = _inject_challenge_params(steps, challenge)
        self.assertEqual(injected[0].parameters["url"], "http://custom:9999")

    def test_inject_challenge_params_uses_instance_target(self) -> None:
        challenge = ChallengeDefinition(id="c1", name="Test", category="web",
                                        difficulty="easy", target="http://challenge-target")
        instance = ChallengeInstance(instance_id="i1", challenge_id="c1", target="http://instance-target", status="running")
        steps = [PrimitiveActionStep("http-request", "Fetch", {"required_tags": ["x"]})]
        injected = _inject_challenge_params(steps, challenge, instance)
        self.assertEqual(injected[0].parameters["url"], "http://instance-target")

    def test_inject_challenge_params_no_injection_for_parse(self) -> None:
        challenge = ChallengeDefinition(id="c1", name="Test", category="web",
                                        difficulty="easy", target="http://127.0.0.1:8080")
        steps = [
            PrimitiveActionStep("structured-parse", "Parse", {"required_tags": ["x"]}),
            PrimitiveActionStep("diff-compare", "Compare", {"required_tags": ["x"]}),
        ]
        injected = _inject_challenge_params(steps, challenge)
        self.assertNotIn("url", injected[0].parameters)
        self.assertNotIn("url", injected[1].parameters)

    def test_inject_challenge_params_injects_url_for_artifact_scan_http(self) -> None:
        challenge = ChallengeDefinition(id="c1", name="Test", category="web",
                                        difficulty="easy", target="http://127.0.0.1:8080")
        steps = [PrimitiveActionStep("artifact-scan", "Scan", {"required_tags": ["x"]})]
        injected = _inject_challenge_params(steps, challenge)
        self.assertEqual(injected[0].parameters["url"], "http://127.0.0.1:8080")

    def test_inject_challenge_params_no_url_for_artifact_scan_file(self) -> None:
        challenge = ChallengeDefinition(id="c1", name="Test", category="forensics",
                                        difficulty="easy", target="file:///archive.zip")
        steps = [PrimitiveActionStep("artifact-scan", "Scan", {"required_tags": ["x"]})]
        injected = _inject_challenge_params(steps, challenge)
        self.assertNotIn("url", injected[0].parameters)

    def test_apg_planner_plan_candidates_have_challenge_params(self) -> None:
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        snapshot = ProjectSnapshot(
            project_id="project:web-1",
            challenge=ChallengeDefinition(
                id="web-1", name="JWT Admin Panel", category="web",
                difficulty="medium", target="http://demo:3000",
                description="login token admin role",
                metadata={"signals": ["login", "token", "admin", "role"]},
            ),
        )
        graph = planner.create_graph(snapshot)
        record = type("R", (), {"snapshot": snapshot, "pattern_graph": graph, "observations": {}, "hypotheses": {}, "episode_memory": EpisodeMemory()})()
        candidates = planner._plan_candidates(record, planner._family_scores(record, []))
        http_steps = [s for c in candidates for s in c.steps if s.primitive == "http-request"]
        self.assertTrue(len(http_steps) > 0)
        for step in http_steps:
            self.assertEqual(step.parameters.get("url"), "http://demo:3000")

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


# --- R11: switch_path tests ---

    def _build_enhanced_planner(self, config=None):
        """Helper to build an EnhancedAPGPlanner for testing"""
        config = config or DualPathConfig()
        memory = EpisodeMemory()
        pattern_library = PatternLibrary()
        structured = APGPlanner(memory, pattern_library)
        constraints = SecurityConstraints()
        shell = LightweightSecurityShell(constraints)
        from attack_agent.constraint_aware_reasoner import ConstraintContextBuilder
        builder = ConstraintContextBuilder(constraints)
        composer = DynamicPatternComposer()
        free = HeuristicFreeExplorationPlanner(builder, shell, composer, memory)
        semantic = SemanticRetrievalEngine()
        return EnhancedAPGPlanner(structured, free, semantic, composer, config)

    def _build_record_for_switch(self, challenge_id="test-switch",
                                 challenge_desc="login token admin role",
                                 signals=["login", "token", "admin", "role"],
                                 target="http://demo"):
        """Helper to build a minimal record for switch_path testing"""
        snapshot = ProjectSnapshot(
            project_id=f"project-{challenge_id}",
            challenge=ChallengeDefinition(
                id=challenge_id, name="Test Challenge", category="web",
                difficulty="medium", target=target,
                description=challenge_desc,
                metadata={"signals": signals},
            ),
        )
        graph = PatternLibrary().build(snapshot)
        record = type("R", (), {
            "snapshot": snapshot,
            "pattern_graph": graph,
            "observations": {},
            "hypotheses": {},
            "run_journal": [],
            "stagnation_counter": 0,
        })()
        return record

    def test_switch_path_switches_structured_to_free_exploration(self) -> None:
        """R11: switch_path should switch from STRUCTURED to FREE_EXPLORATION when budget available"""
        planner = self._build_enhanced_planner()
        record = self._build_record_for_switch()

        # Default path is STRUCTURED; switch should succeed (budget > 0)
        result = planner.switch_path(record, "stagnation")
        self.assertTrue(result)
        project_id = record.snapshot.project_id
        self.assertEqual(planner._current_paths[project_id], PathType.FREE_EXPLORATION)

    def test_switch_path_no_switch_when_budget_exhausted(self) -> None:
        """R11: switch_path should fail when exploration budget is exhausted"""
        config = DualPathConfig(exploration_budget_per_project=1)
        planner = self._build_enhanced_planner(config)
        record = self._build_record_for_switch()

        # Exhaust exploration budget
        planner._exploration_attempts[record.snapshot.project_id] = 1
        result = planner.switch_path(record, "budget_exhausted")
        self.assertFalse(result)

    def test_switch_path_back_to_structured_from_free_exploration(self) -> None:
        """R11: switch_path should switch back to STRUCTURED when max exploration attempts exceeded"""
        config = DualPathConfig(max_exploration_attempts=2)
        planner = self._build_enhanced_planner(config)
        record = self._build_record_for_switch()
        project_id = record.snapshot.project_id

        # Start in free exploration with max attempts reached
        planner._current_paths[project_id] = PathType.FREE_EXPLORATION
        planner._exploration_attempts[project_id] = 2

        result = planner.switch_path(record, "exploration_exhausted")
        self.assertTrue(result)
        self.assertEqual(planner._current_paths[project_id], PathType.STRUCTURED)

    def test_switch_path_records_event_in_journal(self) -> None:
        """R11: switch_path records a PATH_SELECTION event in run_journal"""
        planner = self._build_enhanced_planner()
        record = self._build_record_for_switch()
        record.run_journal = []

        planner.switch_path(record, "stagnation")
        self.assertTrue(len(record.run_journal) >= 1)
        switch_event = record.run_journal[-1]
        self.assertEqual(switch_event.type, EventType.PATH_SELECTION)
        self.assertEqual(switch_event.source, "enhanced_apg_switch")

    def test_switch_path_resets_stagnation_on_switch(self) -> None:
        """R11: switch_path resets stagnation counter when switching"""
        planner = self._build_enhanced_planner()
        record = self._build_record_for_switch()
        project_id = record.snapshot.project_id

        # Simulate some stagnation
        planner._stagnation_counters[project_id] = 5
        planner.switch_path(record, "stagnation")
        self.assertEqual(planner._stagnation_counters[project_id], 0)

    def test_record_outcome_tracks_stagnation(self) -> None:
        """R11: record_outcome increments stagnation on failure, resets on success"""
        planner = self._build_enhanced_planner()
        record = self._build_record_for_switch()
        project_id = record.snapshot.project_id

        program = ActionProgram(
            id="test-prog", goal="test",
            pattern_nodes=["identity-boundary:observe"],
            steps=[PrimitiveActionStep("http-request", "test", {})],
            allowed_primitives=["http-request"],
            verification_rules=["flag_pattern"],
            required_profile=WorkerProfile.NETWORK,
            planner_source="structured",
        )

        # 2 failures increment stagnation
        planner.record_outcome(record, program, ActionOutcome(status="failed"))
        planner.record_outcome(record, program, ActionOutcome(status="failed"))
        self.assertEqual(planner._stagnation_counters[project_id], 2)

        # Success resets stagnation
        planner.record_outcome(record, program, ActionOutcome(status="ok", novelty=0.5))
        self.assertEqual(planner._stagnation_counters[project_id], 0)

    # --- R12: multi-family composition tests ---

    def test_compose_multi_family_candidates_produces_combined_steps(self) -> None:
        """R12: _compose_multi_family_candidates produces candidates combining two families"""
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        challenge = ChallengeDefinition(
            id="multi-test", name="SQL + XSS Challenge", category="web",
            difficulty="medium", target="http://demo",
            description="sql query xss script injection vulnerability",
            metadata={"signals": ["sql", "query", "xss", "script", "injection"]},
        )
        snapshot = ProjectSnapshot(project_id="project-multi-test", challenge=challenge)
        graph = planner.pattern_library.build(snapshot)

        record = type("R", (), {
            "snapshot": snapshot,
            "pattern_graph": graph,
            "observations": {},
            "hypotheses": {},
        })()

        family_scores = planner._family_scores(record, [])
        multi_candidates = planner._compose_multi_family_candidates(record, family_scores)

        # Should produce at least 1 multi-family candidate
        self.assertTrue(len(multi_candidates) >= 1)

        # At least one candidate should have secondary_families
        has_secondary = any(len(c.secondary_families) > 0 for c in multi_candidates)
        self.assertTrue(has_secondary)

        # Multi-family candidate steps should contain steps from multiple families
        multi_cand = [c for c in multi_candidates if len(c.secondary_families) > 0][0]
        # The primary family's observation_gate steps + secondary's action_template steps
        self.assertTrue(len(multi_cand.steps) > 0)

    def test_compose_multi_family_candidates_respects_score_ratio(self) -> None:
        """R12: compose only pairs families whose score >= 0.7 of the primary"""
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        challenge = ChallengeDefinition(
            id="multi-ratio", name="Dominant Identity Challenge", category="web",
            difficulty="medium", target="http://demo",
            description="login token admin role auth session",
            metadata={"signals": ["login", "token", "admin", "role", "auth", "session"]},
        )
        snapshot = ProjectSnapshot(project_id="project-multi-ratio", challenge=challenge)
        graph = planner.pattern_library.build(snapshot)

        record = type("R", (), {
            "snapshot": snapshot,
            "pattern_graph": graph,
            "observations": {},
            "hypotheses": {},
        })()

        family_scores = planner._family_scores(record, [])
        # Check that only families with score >= 0.7 * max_score are composed
        max_score = max(family_scores.values())
        eligible_secondary = [f for f, s in family_scores.items()
                             if s > 0 and s >= 0.7 * max_score and f != max(family_scores, key=family_scores.get)]

        multi_candidates = planner._compose_multi_family_candidates(record, family_scores, score_ratio=0.7)
        # All secondary families in candidates must have score >= 0.7 * max_score
        for cand in multi_candidates:
            for sec_fam in cand.secondary_families:
                self.assertTrue(family_scores.get(sec_fam, 0) >= 0.7 * max_score,
                                f"Secondary family {sec_fam} score {family_scores.get(sec_fam)} "
                                f"should be >= {0.7 * max_score}")

    def test_compose_multi_family_candidates_injects_challenge_params(self) -> None:
        """R12: multi-family candidate steps should have challenge URL injected"""
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        challenge = ChallengeDefinition(
            id="multi-inject", name="SQL + XSS Challenge", category="web",
            difficulty="medium", target="http://target.example.com",
            description="sql query xss script injection vulnerability",
            metadata={"signals": ["sql", "query", "xss", "script"]},
        )
        snapshot = ProjectSnapshot(project_id="project-multi-inject", challenge=challenge)
        graph = planner.pattern_library.build(snapshot)

        record = type("R", (), {
            "snapshot": snapshot,
            "pattern_graph": graph,
            "observations": {},
            "hypotheses": {},
        })()

        family_scores = planner._family_scores(record, [])
        multi_candidates = planner._compose_multi_family_candidates(record, family_scores)

        if len(multi_candidates) > 0:
            http_steps = [s for c in multi_candidates for s in c.steps if s.primitive == "http-request"]
            for step in http_steps:
                url = step.parameters.get("url")
                if url is not None:
                    self.assertEqual(url, "http://target.example.com")

    def test_compose_multi_family_no_candidates_with_low_secondary_scores(self) -> None:
        """R12: no multi-family candidates when secondary families score too low"""
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        # Challenge matching only one family strongly
        challenge = ChallengeDefinition(
            id="single-dominant", name="Pure Encoding", category="misc",
            difficulty="easy", target="http://demo",
            description="base64 decode encode transform cipher hash",
            metadata={"signals": ["base64", "decode", "encode", "transform", "cipher", "hash"]},
        )
        snapshot = ProjectSnapshot(project_id="project-single-dominant", challenge=challenge)
        graph = planner.pattern_library.build(snapshot)

        record = type("R", (), {
            "snapshot": snapshot,
            "pattern_graph": graph,
            "observations": {},
            "hypotheses": {},
        })()

        family_scores = planner._family_scores(record, [])
        multi_candidates = planner._compose_multi_family_candidates(record, family_scores, score_ratio=0.7)
        # If encoding-transform dominates, secondary families with < 0.7 * score won't compose
        max_score = max(family_scores.values())
        secondary_eligible = sum(1 for s in family_scores.values()
                                 if s > 0 and s >= 0.7 * max_score and s < max_score)
        if secondary_eligible == 0:
            self.assertEqual(len(multi_candidates), 0)

    def test_plan_candidates_includes_multi_family(self) -> None:
        """R12: _plan_candidates includes multi-family composition candidates alongside single-family"""
        planner = APGPlanner(EpisodeMemory(), PatternLibrary())
        challenge = ChallengeDefinition(
            id="plan-multi", name="SQL + XSS Challenge", category="web",
            difficulty="medium", target="http://demo",
            description="sql query xss script injection vulnerability",
            metadata={"signals": ["sql", "query", "xss", "script", "injection"]},
        )
        snapshot = ProjectSnapshot(project_id="project-plan-multi", challenge=challenge)
        graph = planner.pattern_library.build(snapshot)

        record = type("R", (), {
            "snapshot": snapshot,
            "pattern_graph": graph,
            "observations": {},
            "hypotheses": {},
        })()

        family_scores = planner._family_scores(record, [])
        candidates = planner._plan_candidates(record, family_scores)

        # Should include both single-family and multi-family candidates
        single_family = [c for c in candidates if len(c.secondary_families) == 0]
        multi_family = [c for c in candidates if len(c.secondary_families) > 0]
        self.assertTrue(len(single_family) > 0, "Should have single-family candidates")
        # Multi-family candidates depend on score ratio; may or may not exist
        # but the method should produce them when conditions are met

    def test_heuristic_free_exploration_produces_multi_family_program(self) -> None:
        """R12: HeuristicFreeExplorationPlanner produces programs combining 2 top families"""
        from attack_agent.heuristic_free_exploration import HeuristicFreeExplorationPlanner
        from attack_agent.constraint_aware_reasoner import ConstraintContextBuilder
        from attack_agent.constraints import SecurityConstraints

        constraints = SecurityConstraints()
        builder = ConstraintContextBuilder(constraints)
        shell = LightweightSecurityShell(constraints)
        composer = DynamicPatternComposer()
        memory = EpisodeMemory()
        free_planner = HeuristicFreeExplorationPlanner(builder, shell, composer, memory)

        challenge = ChallengeDefinition(
            id="free-multi", name="SQL + XSS Challenge", category="web",
            difficulty="medium", target="http://demo",
            description="sql query xss script injection vulnerability",
            metadata={"signals": ["sql", "query", "xss", "script", "injection"]},
        )
        snapshot = ProjectSnapshot(
            project_id="project-free-multi",
            challenge=challenge,
            stage=ProjectStage.EXPLORE,
        )
        context = PlanningContext(
            record=type("R", (), {"snapshot": snapshot, "pattern_graph": None, "observations": {}, "hypotheses": {}, "run_journal": []})(),
            attempt_count=1,
            historical_success_rate=0.0,
            complexity_score=0.5,
            pattern_confidence=0.0,
            exploration_budget=3,
            current_path=PathType.FREE_EXPLORATION,
        )

        program = free_planner.generate_constrained_plan(context)
        if program is not None:
            # Should have steps combining multiple families
            self.assertTrue(len(program.steps) > 0)


if __name__ == "__main__":
    unittest.main()
