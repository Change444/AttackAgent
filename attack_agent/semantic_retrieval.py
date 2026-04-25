from __future__ import annotations

import math
import re
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
    """内存向量存储（TF-IDF/词袋相似度）"""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
        self._tfidf: dict[str, dict[str, float]] = {}

    def add(self, id: str, vector: list[float], metadata: dict[str, Any]) -> None:
        self._entries[id] = metadata

    def search(self, vector: list[float], limit: int) -> list[tuple[str, float]]:
        if not self._entries:
            return []
        results: list[tuple[str, float]] = []
        for id, meta in self._entries.items():
            score = meta.get("score", 0.0)
            results.append((id, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]


def _tokenize(text: str) -> list[str]:
    """简单分词"""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return words


def _compute_tfidf_similarity(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """计算基于词袋的相似度"""
    if not query_tokens or not doc_tokens:
        return 0.0

    query_set = set(query_tokens)
    doc_set = set(doc_tokens)
    intersection = query_set & doc_set
    union = query_set | doc_set

    if not union:
        return 0.0

    return len(intersection) / len(union)


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

    def search(self, query: str, episodes: list[EpisodeEntry]) -> list[SemanticRetrievalHit]:
        """混合检索"""
        hits: list[SemanticRetrievalHit] = []
        query_tokens = _tokenize(query)

        for episode in episodes:
            semantic_sim = _compute_tfidf_similarity(
                query_tokens, _tokenize(episode.feature_text)
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
    """语义检索引擎"""

    def __init__(self,
                 vector_store: VectorStore | None = None,
                 hybrid_alpha: float = 0.7) -> None:
        self._vector_store = vector_store or InMemoryVectorStore()
        self._hybrid_strategy = HybridRetrievalStrategy(
            alpha=hybrid_alpha, beta=1.0 - hybrid_alpha
        )
        self._episodes: list[EpisodeEntry] = []

    def search(self, query: str, limit: int = 5) -> list[SemanticRetrievalHit]:
        """语义检索"""
        if not self._episodes:
            return []

        hits = self._hybrid_strategy.search(query, self._episodes)
        return hits[:limit]

    def index_episode(self, episode: EpisodeEntry) -> None:
        """索引新案例"""
        self._episodes.append(episode)
        metadata = {
            "feature_text": episode.feature_text,
            "summary": episode.summary,
            "score": 1.0,
        }
        self._vector_store.add(episode.id, [], metadata)

    def update_index(self, episodes: list[EpisodeEntry]) -> None:
        """批量更新索引"""
        for episode in episodes:
            self.index_episode(episode)

    def compute_similarity(self, query: str, episode: EpisodeEntry) -> float:
        """计算语义相似度"""
        query_tokens = _tokenize(query)
        episode_tokens = _tokenize(episode.feature_text)
        return _compute_tfidf_similarity(query_tokens, episode_tokens)