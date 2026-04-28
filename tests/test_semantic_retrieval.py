import unittest

from attack_agent.semantic_retrieval import (
    SemanticRetrievalEngine,
    SemanticRetrievalHit,
    HybridRetrievalStrategy,
    InMemoryVectorStore,
    _tokenize,
    _compute_tfidf_similarity,
    _compute_jaccard_similarity,
    _compute_lexical_overlap,
    FallbackEmbeddingModel,
)
from attack_agent.platform_models import EpisodeEntry


class TestTokenize(unittest.TestCase):

    def test_tokenize_basic(self):
        tokens = _tokenize("SQL injection attack")
        self.assertEqual(tokens, ["sql", "injection", "attack"])

    def test_tokenize_empty(self):
        tokens = _tokenize("")
        self.assertEqual(tokens, [])

    def test_tokenize_mixed_case(self):
        tokens = _tokenize("Hello World 123")
        self.assertEqual(tokens, ["hello", "world", "123"])


class TestTfidfSimilarity(unittest.TestCase):

    def test_similar_texts(self):
        sim = _compute_tfidf_similarity(
            ["sql", "injection"], ["sql", "injection", "attack"]
        )
        self.assertGreater(sim, 0.3)

    def test_no_overlap(self):
        sim = _compute_tfidf_similarity(["abc"], ["xyz"])
        self.assertEqual(sim, 0.0)

    def test_empty_input(self):
        sim = _compute_tfidf_similarity([], ["test"])
        self.assertEqual(sim, 0.0)


class TestJaccardSimilarity(unittest.TestCase):

    def test_similar_sets(self):
        sim = _compute_jaccard_similarity(["sql", "injection"], ["sql", "injection", "attack"])
        self.assertAlmostEqual(sim, 2.0 / 3.0, places=3)

    def test_no_overlap(self):
        sim = _compute_jaccard_similarity(["abc"], ["xyz"])
        self.assertEqual(sim, 0.0)

    def test_identical_sets(self):
        sim = _compute_jaccard_similarity(["sql"], ["sql"])
        self.assertEqual(sim, 1.0)


class TestLexicalOverlap(unittest.TestCase):

    def test_overlap(self):
        overlap = _compute_lexical_overlap("sql injection", "sql injection attack")
        self.assertGreater(overlap, 0.5)

    def test_no_overlap(self):
        overlap = _compute_lexical_overlap("abc", "xyz")
        self.assertEqual(overlap, 0.0)


class TestHybridRetrievalStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = HybridRetrievalStrategy(alpha=0.7, beta=0.3)
        self.episodes = [
            EpisodeEntry(
                id="e1", feature_text="http request sql injection",
                pattern_families=["web"], summary="SQL注入攻击",
                success=True, stop_reason="candidate_found",
            ),
            EpisodeEntry(
                id="e2", feature_text="binary reverse engineering",
                pattern_families=["binary"], summary="二进制逆向",
                success=True, stop_reason="candidate_found",
            ),
        ]

    def test_search_returns_hits(self):
        """测试搜索返回命中"""
        hits = self.strategy.search("sql injection", self.episodes)
        self.assertEqual(len(hits), 2)
        # SQL episode should rank higher
        self.assertEqual(hits[0].episode_id, "e1")

    def test_compute_hybrid_score(self):
        """测试混合评分计算"""
        score = self.strategy.compute_hybrid_score(0.8, 0.5)
        expected = 0.7 * 0.8 + 0.3 * 0.5
        self.assertAlmostEqual(score, expected)

    def test_rank_hits_sorts_by_hybrid_score(self):
        """测试按混合评分排序"""
        hits = [
            SemanticRetrievalHit(
                episode_id="h1", summary="low", pattern_families=["x"],
                stop_reason="", semantic_similarity=0.2, lexical_overlap=0.1,
                hybrid_score=0.17, confidence=0.1, relevance_explanation="",
            ),
            SemanticRetrievalHit(
                episode_id="h2", summary="high", pattern_families=["x"],
                stop_reason="", semantic_similarity=0.8, lexical_overlap=0.7,
                hybrid_score=0.77, confidence=0.8, relevance_explanation="",
            ),
        ]
        ranked = self.strategy.rank_hits(hits)
        self.assertEqual(ranked[0].episode_id, "h2")


class TestSemanticRetrievalEngine(unittest.TestCase):

    def setUp(self):
        self.engine = SemanticRetrievalEngine(hybrid_alpha=0.7)
        self.episodes = [
            EpisodeEntry(
                id="e1", feature_text="http request sql injection",
                pattern_families=["web"], summary="SQL注入挑战",
                success=True,
            ),
            EpisodeEntry(
                id="e2", feature_text="browser inspect xss",
                pattern_families=["web"], summary="XSS攻击",
                success=True,
            ),
        ]
        for ep in self.episodes:
            self.engine.index_episode(ep)

    def test_index_episode(self):
        """测试索引新案例"""
        self.assertEqual(len(self.engine._episodes), 2)

    def test_search_returns_results(self):
        """测试搜索返回结果"""
        hits = self.engine.search("sql injection", limit=5)
        self.assertTrue(len(hits) > 0)
        self.assertIsInstance(hits[0], SemanticRetrievalHit)
        self.assertEqual(hits[0].episode_id, "e1")

    def test_search_empty_index(self):
        """测试空索引搜索"""
        empty_engine = SemanticRetrievalEngine()
        hits = empty_engine.search("test", limit=5)
        self.assertEqual(len(hits), 0)

    def test_compute_similarity(self):
        """测试计算相似度"""
        sim = self.engine.compute_similarity("sql injection", self.episodes[0])
        self.assertGreater(sim, 0.0)

    def test_update_index_batch(self):
        """测试批量更新索引"""
        new_episodes = [
            EpisodeEntry(id="e3", feature_text="code sandbox",
                         pattern_families=["binary"], summary="代码执行", success=True),
        ]
        self.engine.update_index(new_episodes)
        self.assertEqual(len(self.engine._episodes), 3)

    def test_search_limit(self):
        """测试搜索限制"""
        hits = self.engine.search("test", limit=1)
        self.assertLessEqual(len(hits), 1)


class TestInMemoryVectorStore(unittest.TestCase):

    def test_add_and_search(self):
        store = InMemoryVectorStore()
        store.add("e1", [], {"score": 0.9})
        store.add("e2", [], {"score": 0.5})
        results = store.search([], limit=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], "e1")


if __name__ == "__main__":
    unittest.main()