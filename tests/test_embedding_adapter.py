import math
import unittest

from attack_agent.embedding_adapter import (
    FallbackEmbeddingModel,
    SentenceTransformerEmbeddingModel,
    OpenAIEmbeddingModel,
    build_embedding_from_config,
)
from attack_agent.config import AttackAgentConfig, ModelConfig, SemanticRetrievalConfig
from attack_agent.semantic_retrieval import (
    InMemoryVectorStore,
    _tokenize,
    _compute_jaccard_similarity,
    _compute_tfidf_similarity,
    _compute_lexical_overlap,
    _cosine_similarity,
)


class TestFallbackEmbeddingModel(unittest.TestCase):

    def test_returns_empty_vectors(self):
        model = FallbackEmbeddingModel()
        result = model.embed(["hello", "world"])
        self.assertEqual(result, [[] for _ in range(2)])


class TestSentenceTransformerModel(unittest.TestCase):

    def test_class_is_importable_without_package(self):
        """SentenceTransformerEmbeddingModel should be importable even without sentence_transformers installed"""
        # Just verify the class exists and can be instantiated
        model = SentenceTransformerEmbeddingModel("test-model")
        self.assertEqual(model._model_name, "test-model")
        self.assertIsNone(model._model)


class TestOpenAIEmbeddingModel(unittest.TestCase):

    def test_class_is_importable(self):
        """OpenAIEmbeddingModel should be importable"""
        config = ModelConfig(provider="openai", model_name="text-embedding-3-small")
        model = OpenAIEmbeddingModel(config)
        self.assertEqual(model._config.model_name, "text-embedding-3-small")


class TestBuildEmbeddingFromConfig(unittest.TestCase):

    def test_heuristic_returns_fallback(self):
        """heuristic provider should return FallbackEmbeddingModel"""
        config = ModelConfig(provider="heuristic")
        model = build_embedding_from_config(config)
        self.assertIsInstance(model, FallbackEmbeddingModel)


class TestInMemoryVectorStoreWithRealVectors(unittest.TestCase):

    def test_add_and_search_with_vectors(self):
        """Store vectors and search with cosine similarity"""
        store = InMemoryVectorStore()
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        vec_c = [0.9, 0.1, 0.0]  # close to vec_a

        store.add("a", vec_a, {"text": "hello"})
        store.add("b", vec_b, {"text": "world"})
        store.add("c", vec_c, {"text": "hi"})

        results = store.search([1.0, 0.0, 0.0], limit=3)
        self.assertTrue(len(results) >= 2)
        # "a" should be top result (cosine similarity = 1.0)
        self.assertEqual(results[0][0], "a")
        self.assertAlmostEqual(results[0][1], 1.0, places=5)

    def test_backward_compat_empty_vectors(self):
        """Empty vectors fall back to metadata score"""
        store = InMemoryVectorStore()
        store.add("e1", [], {"text": "test", "score": 0.8})
        store.add("e2", [], {"text": "test2", "score": 0.5})

        results = store.search([], limit=2)
        self.assertTrue(len(results) >= 2)
        # Should be sorted by metadata score
        self.assertEqual(results[0][0], "e1")


class TestTokenizeCJK(unittest.TestCase):

    def test_cjk_mixed_text(self):
        """CJK characters should be tokenized as whole phrases"""
        tokens = _tokenize("SQL注入攻击")
        self.assertIn("sql", tokens)
        # CJK characters appear as whole phrases
        cjk_tokens = [t for t in tokens if t != "sql"]
        self.assertTrue(len(cjk_tokens) >= 1)

    def test_cjk_only(self):
        """Pure CJK text should produce tokens"""
        tokens = _tokenize("渗透测试")
        self.assertTrue(len(tokens) >= 1)

    def test_ascii_only(self):
        """Pure ASCII text works as before"""
        tokens = _tokenize("sql injection attack")
        self.assertIn("sql", tokens)
        self.assertIn("injection", tokens)
        self.assertIn("attack", tokens)

    def test_empty_input(self):
        tokens = _tokenize("")
        self.assertEqual(tokens, [])


class TestJaccardSimilarity(unittest.TestCase):

    def test_similar_sets(self):
        score = _compute_jaccard_similarity(["sql", "inject"], ["sql", "query"])
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_no_overlap(self):
        score = _compute_jaccard_similarity(["a"], ["b"])
        self.assertEqual(score, 0.0)


class TestTfidfSimilarity(unittest.TestCase):

    def test_produces_different_result_from_jaccard(self):
        """Real TF-IDF should differ from Jaccard for same input"""
        query = ["sql", "sql", "inject"]
        doc = ["sql", "query", "inject"]
        jaccard = _compute_jaccard_similarity(query, doc)
        tfidf = _compute_tfidf_similarity(query, doc)
        # They should be different (TF-IDF weights "sql" higher since it appears twice in query)
        self.assertNotAlmostEqual(jaccard, tfidf, places=2)

    def test_empty_input(self):
        score = _compute_tfidf_similarity([], ["sql"])
        self.assertEqual(score, 0.0)

    def test_with_idf(self):
        """TF-IDF with provided IDF should produce non-zero result"""
        query = ["sql", "inject"]
        doc = ["sql", "inject", "query"]
        idf = {"sql": 1.5, "inject": 1.2, "query": 0.8}
        score = _compute_tfidf_similarity(query, doc, idf=idf)
        self.assertGreater(score, 0.0)


class TestCosineSimilarity(unittest.TestCase):

    def test_identical_vectors(self):
        sim = _cosine_similarity([1.0, 0.0], [1.0, 0.0])
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_orthogonal_vectors(self):
        sim = _cosine_similarity([1.0, 0.0], [0.0, 1.0])
        self.assertAlmostEqual(sim, 0.0, places=5)

    def test_zero_vector(self):
        sim = _cosine_similarity([0.0, 0.0], [1.0, 0.0])
        self.assertEqual(sim, 0.0)


if __name__ == "__main__":
    unittest.main()