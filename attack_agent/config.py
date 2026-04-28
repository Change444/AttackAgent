from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .platform_models import DualPathConfig


@dataclass(slots=True)
class PlatformConfig:
    max_cycles: int = 50
    timeout_seconds: int = 300
    enable_auto_submit: bool = True


@dataclass(slots=True)
class PatternDiscoveryConfig:
    enable: bool = True
    threshold: int = 3
    auto_apply: bool = False


@dataclass(slots=True)
class SemanticRetrievalConfig:
    enable: bool = True
    limit: int = 5
    hybrid_alpha: float = 0.7
    hybrid_beta: float = 0.3
    vector_store_type: str = "memory"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(slots=True)
class SecurityConfig:
    allowed_hostpatterns: list[str] | None = None
    max_http_requests: int = 30
    max_sandbox_executions: int = 5
    max_program_steps: int = 15
    require_observation_before_action: bool = True
    max_estimated_cost: float = 50.0

    def __post_init__(self) -> None:
        if self.allowed_hostpatterns is None:
            self.allowed_hostpatterns = ["127.0.0.1", "localhost"]


@dataclass(slots=True)
class MemoryConfig:
    persistence_enabled: bool = True
    store_path: str = "data/episodes.json"
    max_entries: int = 10000


@dataclass(slots=True)
class ModelConfig:
    provider: str = "heuristic"
    model_name: str = ""
    api_key: str = ""
    api_key_env: str = ""
    base_url: str = ""
    temperature: float = 0.3
    max_tokens: int = 1024
    timeout_seconds: int = 30
    max_retries: int = 2
    observation_summary_budget_chars: int = 2000


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    enable_event_logging: bool = True
    enable_performance_logging: bool = False


@dataclass(slots=True)
class AttackAgentConfig:
    platform: PlatformConfig
    dual_path: DualPathConfig
    pattern_discovery: PatternDiscoveryConfig
    semantic_retrieval: SemanticRetrievalConfig
    security: SecurityConfig
    memory: MemoryConfig
    logging: LoggingConfig
    model: ModelConfig = field(default_factory=ModelConfig)

    @classmethod
    def from_defaults(cls) -> AttackAgentConfig:
        """Create config with all defaults — no file needed."""
        return cls(
            platform=PlatformConfig(),
            dual_path=DualPathConfig(),
            pattern_discovery=PatternDiscoveryConfig(),
            semantic_retrieval=SemanticRetrievalConfig(),
            security=SecurityConfig(),
            memory=MemoryConfig(),
            logging=LoggingConfig(),
            model=ModelConfig(),
        )

    @classmethod
    def from_file(cls, config_path: Path) -> AttackAgentConfig:
        """从配置文件加载"""
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        semantic_data = data.get("semantic_retrieval", {})
        # Remove nested dict that doesn't map to flat config fields
        if "vector_store" in semantic_data:
            vs = semantic_data.pop("vector_store")
            semantic_data.setdefault("vector_store_type", vs.get("type", "memory"))
            semantic_data.setdefault("embedding_model", vs.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"))

        return cls(
            platform=PlatformConfig(**data.get("platform", {})),
            dual_path=DualPathConfig(**data.get("dual_path", {})),
            pattern_discovery=PatternDiscoveryConfig(**data.get("pattern_discovery", {})),
            semantic_retrieval=SemanticRetrievalConfig(**semantic_data),
            security=SecurityConfig(**data.get("security", {})),
            memory=MemoryConfig(**data.get("memory", {})),
            logging=LoggingConfig(**data.get("logging", {})),
            model=ModelConfig(**data.get("model", {})),
        )