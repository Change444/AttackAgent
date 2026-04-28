from __future__ import annotations

from typing import Any

from .config import ModelConfig


class FallbackEmbeddingModel:
    """无 embedding 包时返回空向量，引擎回退到词汇检索"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class SentenceTransformerEmbeddingModel:
    """sentence-transformers embedding adapter，惰性导入"""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer
        if self._model is None:
            self._model = SentenceTransformer(self._model_name)
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [list(e) for e in embeddings]


class OpenAIEmbeddingModel:
    """OpenAI embedding adapter，惰性导入"""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config
        self._client: Any = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        import openai
        if self._client is None:
            api_key = _resolve_api_key(self._config)
            kwargs: dict[str, Any] = {"api_key": api_key}
            if self._config.base_url:
                kwargs["base_url"] = self._config.base_url
            self._client = openai.OpenAI(**kwargs)
        response = self._client.embeddings.create(
            model=self._config.model_name or "text-embedding-3-small",
            input=texts,
        )
        return [list(d.embedding) for d in response.data]


def _resolve_api_key(config: ModelConfig) -> str:
    """Resolve API key from env var or literal"""
    if config.api_key_env:
        import os
        key = os.environ.get(config.api_key_env)
        if key:
            return key
    if config.api_key:
        return config.api_key
    raise ValueError("No API key configured for embedding model")


def build_embedding_from_config(model_config: ModelConfig, embedding_model_name: str = "") -> FallbackEmbeddingModel | OpenAIEmbeddingModel | SentenceTransformerEmbeddingModel:
    """构建 embedding 模型：优先 OpenAI，其次 sentence-transformers，最后 Fallback"""
    if model_config.provider == "openai":
        try:
            import openai  # noqa: F401
            return OpenAIEmbeddingModel(model_config)
        except ImportError:
            pass

    if embedding_model_name:
        try:
            import sentence_transformers  # noqa: F401
            return SentenceTransformerEmbeddingModel(embedding_model_name)
        except ImportError:
            pass

    return FallbackEmbeddingModel()