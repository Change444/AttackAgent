"""Blackboard configuration — Phase B."""

from dataclasses import dataclass


@dataclass
class BlackboardConfig:
    db_path: str = "data/blackboard.db"