from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from .platform_models import EpisodeEntry


@dataclass(slots=True)
class SemanticRetrievalHit:
    """语义检索命中"""
    episode_id: str
    summary: str
    pattern_families: list[str]
    stop_reason: str
    semantic_similarity: float
    lexical_overlap: float
    hybrid_score: float
    confidence: float
    relevance_explanation: str


class VectorStore(Protocol):
    """向量存储协议"""
    def add(self, id: str, vector: list[float], metadata: dict[str, Any]) -> None: ...
    def search(self, vector: list[float], limit: int) -> list[tuple[str, float]]: ...


class InMemoryVectorStore:
    """内存向量存储 — 支持真实 cosine similarity，空向量时回退 metadata score"""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def add(self, id: str, vector: list[float], metadata: dict[str, Any]) -> None:
        self._vectors[id] = vector
        self._metadata[id] = metadata

    def search(self, vector: list[float], limit: int) -> list[tuple[str, float]]:
        if not self._vectors:
            return []
        # If query vector is empty, fall back to metadata scores (backward compat)
        if not vector:
            results = [(id, meta.get("score", 0.0)) for id, meta in self._metadata.items()]
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:limit]
        # Compute cosine similarity against all stored vectors
        results: list[tuple[str, float]] = []
        for id, stored_vec in self._vectors.items():
            if not stored_vec:
                continue
            sim = _cosine_similarity(vector, stored_vec)
            results.append((id, sim))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


_CJK_RANGE = re.compile(r"[一-鿿㐀-䶿豈-﫿]+")
_ASCII_RANGE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """分词：CJK 整词 + ASCII token"""
    lowered = text.lower()
    cjk_tokens = _CJK_RANGE.findall(lowered)
    ascii_tokens = _ASCII_RANGE.findall(lowered)
    return cjk_tokens + ascii_tokens


def _compute_jaccard_similarity(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """Jaccard similarity on token sets (原 _compute_tfidf_similarity 实现)"""
    if not query_tokens or not doc_tokens:
        return 0.0
    query_set = set(query_tokens)
    doc_set = set(doc_tokens)
    intersection = query_set & doc_set
    union = query_set | doc_set
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _term_frequencies(tokens: list[str]) -> dict[str, float]:
    """Compute normalized term frequencies"""
    counts = Counter(tokens)
    total = len(tokens)
    if total == 0:
        return {}
    return {t: c / total for t, c in counts.items()}


def _compute_tfidf_similarity(query_tokens: list[str], doc_tokens: list[str], idf: dict[str, float] | None = None) -> float:
    """Cosine similarity on TF-IDF vectors"""
    if not query_tokens or not doc_tokens:
        return 0.0
    query_tf = _term_frequencies(query_tokens)
    doc_tf = _term_frequencies(doc_tokens)
    # Use provided IDF or flat 1.0 fallback
    if idf is None:
        all_tokens = set(query_tokens) | set(doc_tokens)
        idf = {t: 1.0 for t in all_tokens}
    # Compute TF-IDF dot product and norms
    all_terms = set(query_tf) | set(doc_tf)
    dot = 0.0
    norm_q = 0.0
    norm_d = 0.0
    for term in all_terms:
        q_val = query_tf.get(term, 0.0) * idf.get(term, 1.0)
        d_val = doc_tf.get(term, 0.0) * idf.get(term, 1.0)
        dot += q_val * d_val
        norm_q += q_val * q_val
        norm_d += d_val * d_val
    norm_q = math.sqrt(norm_q)
    norm_d = math.sqrt(norm_d)
    if norm_q == 0.0 or norm_d == 0.0:
        return 0.0
    return dot / (norm_q * norm_d)


def _compute_lexical_overlap(query: str, text: str) -> float:
    """计算词汇重叠度"""
    query_tokens = _tokenize(query)
    text_tokens = _tokenize(text)
    if not query_tokens or not text_tokens:
        return 0.0
    query_set = set(query_tokens)
    text_set = set(text_tokens)
    overlap = query_set & text_set
    return len(overlap) / len(query_set)


class HybridRetrievalStrategy:
    """混合检索策略：语义 + 词汇"""

    def __init__(self, alpha: float = 0.7, beta: float = 0.3) -> None:
        self.alpha = alpha
        self.beta = beta

    def search(self, query: str, episodes: list[EpisodeEntry], idf: dict[str, float] | None = None) -> list[SemanticRetrievalHit]:
        """混合检索"""
        hits: list[SemanticRetrievalHit] = []
        query_tokens = _tokenize(query)

        for episode in episodes:
            semantic_sim = _compute_tfidf_similarity(
                query_tokens, _tokenize(episode.feature_text), idf
            )
            lexical_overlap = _compute_lexical_overlap(query, episode.summary)
            hybrid_score = self.compute_hybrid_score(semantic_sim, lexical_overlap)
            confidence = (semantic_sim + lexical_overlap + hybrid_score) / 3.0

            explanation = ""
            if semantic_sim > 0.5:
                explanation += "语义高度相似"
            if lexical_overlap > 0.3:
                explanation += "; 词汇重叠"
            if not explanation:
                explanation = "低相关度"

            hits.append(SemanticRetrievalHit(
                episode_id=episode.id,
                summary=episode.summary,
                pattern_families=episode.pattern_families,
                stop_reason=episode.stop_reason,
                semantic_similarity=semantic_sim,
                lexical_overlap=lexical_overlap,
                hybrid_score=hybrid_score,
                confidence=confidence,
                relevance_explanation=explanation,
            ))

        return self.rank_hits(hits)

    def compute_hybrid_score(self, semantic_sim: float, lexical_overlap: float) -> float:
        """混合评分计算"""
        return self.alpha * semantic_sim + self.beta * lexical_overlap

    def rank_hits(self, hits: list[SemanticRetrievalHit]) -> list[SemanticRetrievalHit]:
        """重新排序检索结果"""
        return sorted(hits, key=lambda h: h.hybrid_score, reverse=True)


class SemanticRetrievalEngine:
    """语义检索引擎 — 支持向量检索 + 词汇检索混合"""

    def __init__(self,
                 vector_store: VectorStore | None = None,
                 hybrid_alpha: float = 0.7,
                 embedding_model: Any = None) -> None:
        self._vector_store = vector_store or InMemoryVectorStore()
        self._hybrid_strategy = HybridRetrievalStrategy(
            alpha=hybrid_alpha, beta=1.0 - hybrid_alpha
        )
        self._embedding_model = embedding_model or FallbackEmbeddingModel()
        self._episodes: list[EpisodeEntry] = []
        self._idf: dict[str, float] = {}

    def search(self, query: str, limit: int = 5) -> list[SemanticRetrievalHit]:
        """语义检索：向量 + 词汇混合"""
        if not self._episodes:
            return []

        # Embed query for vector search
        query_vectors = self._embedding_model.embed([query])
        query_vector = query_vectors[0] if query_vectors else []

        # Vector search (if vectors available)
        vector_hits: list[tuple[str, float]] = []
        if query_vector:
            vector_hits = self._vector_store.search(query_vector, limit=limit * 2)

        # Lexical search
        lexical_hits = self._hybrid_strategy.search(query, self._episodes, self._idf)

        # Merge results
        merged = self._merge_results(vector_hits, lexical_hits)
        return merged[:limit]

    def _merge_results(self,
                       vector_hits: list[tuple[str, float]],
                       lexical_hits: list[SemanticRetrievalHit]) -> list[SemanticRetrievalHit]:
        """合并向量 + 词汇检索结果"""
        vec_scores = {id: score for id, score in vector_hits}
        # Re-weight lexical hits that also have vector scores
        for hit in lexical_hits:
            vec_score = vec_scores.get(hit.episode_id, 0.0)
            if vec_score > 0.0:
                hit.semantic_similarity = max(hit.semantic_similarity, vec_score)
                hit.hybrid_score = self._hybrid_strategy.alpha * vec_score + \
                    (1.0 - self._hybrid_strategy.alpha) * hit.hybrid_score

        # Add vector-only hits not in lexical results
        existing_ids = {h.episode_id for h in lexical_hits}
        for id, score in vector_hits:
            if id not in existing_ids:
                ep = next((e for e in self._episodes if e.id == id), None)
                if ep:
                    lexical_hits.append(SemanticRetrievalHit(
                        episode_id=id, summary=ep.summary,
                        pattern_families=ep.pattern_families,
                        stop_reason=ep.stop_reason,
                        semantic_similarity=score,
                        lexical_overlap=0.0,
                        hybrid_score=self._hybrid_strategy.alpha * score,
                        confidence=score,
                        relevance_explanation="vector similarity only",
                    ))

        return sorted(lexical_hits, key=lambda h: h.hybrid_score, reverse=True)

    def index_episode(self, episode: EpisodeEntry) -> None:
        """索引新案例 — embed + store + update IDF"""
        self._episodes.append(episode)
        text = f"{episode.feature_text} {episode.summary}"
        vectors = self._embedding_model.embed([text])
        vector = vectors[0] if vectors else []
        metadata = {
            "feature_text": episode.feature_text,
            "summary": episode.summary,
        }
        self._vector_store.add(episode.id, vector, metadata)
        # Update IDF
        tokens = _tokenize(text)
        for token in tokens:
            self._idf[token] = self._idf.get(token, 0.0) + 1.0

    def update_index(self, episodes: list[EpisodeEntry]) -> None:
        """批量更新索引"""
        for episode in episodes:
            self.index_episode(episode)

    def compute_similarity(self, query: str, episode: EpisodeEntry) -> float:
        """计算语义相似度"""
        query_tokens = _tokenize(query)
        episode_tokens = _tokenize(episode.feature_text)
        return _compute_tfidf_similarity(query_tokens, episode_tokens, self._idf)


class FallbackEmbeddingModel:
    """无 embedding 包时返回空向量，引擎回退到词汇检索"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]