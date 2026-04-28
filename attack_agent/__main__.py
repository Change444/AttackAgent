"""CLI entry point for AttackAgent: python -m attack_agent [options]

Usage examples:
  python -m attack_agent --config config/settings.json
  python -m attack_agent --provider-url http://127.0.0.1:8080
  python -m attack_agent --ctfd-url http://ctfd.example.com --ctfd-token <api_token>
  python -m attack_agent --ctfd-url http://ctfd.example.com --ctfd-username admin --ctfd-password pass
  python -m attack_agent  # heuristic mode, InMemoryCompetitionProvider demo
"""
from __future__ import annotations

import argparse
import sys
import logging
from pathlib import Path

from .config import AttackAgentConfig
from .console import WebConsoleView
from .model_adapter import build_model_from_config, is_available
from .platform import CompetitionPlatform
from .platform_models import ChallengeDefinition
from .provider import InMemoryCompetitionProvider, LocalHTTPCompetitionProvider
from .ctfd_provider import CTFdCompetitionProvider
from .ctfd_provider import CTFdCompetitionProvider


def _build_provider(provider_url: str | None, challenges_file: str | None,
                    ctfd_url: str | None, ctfd_username: str | None,
                    ctfd_password: str | None, ctfd_token: str | None) -> object:
    """Construct a CompetitionProvider from CLI options."""
    if ctfd_url:
        return CTFdCompetitionProvider(
            base_url=ctfd_url,
            username=ctfd_username,
            password=ctfd_password,
            api_token=ctfd_token,
        )

    if provider_url:
        return LocalHTTPCompetitionProvider(provider_url)

    if challenges_file:
        import json
        with open(challenges_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        challenges = [ChallengeDefinition(**item) for item in data]
        return InMemoryCompetitionProvider(challenges)

    # Default: demo provider with a single local challenge
    return InMemoryCompetitionProvider([
        ChallengeDefinition(
            id="demo-1",
            name="Demo Challenge",
            category="web",
            difficulty="easy",
            target="http://127.0.0.1:8000",
            description="Default demo challenge for heuristic mode.",
            metadata={"hint_budget": 1, "hint": "Try the identity-boundary path.", "flag": "flag{demo}"},
        ),
    ])


def _build_model(agent_config: AttackAgentConfig) -> object | None:
    """Build a ReasoningModel from config, or None for heuristic mode."""
    model_config = agent_config.model
    if model_config.provider == "heuristic":
        return None

    if not is_available(model_config.provider):
        available = {"openai": "pip install attack-agent[openai]", "anthropic": "pip install attack-agent[anthropic]"}
        hint = available.get(model_config.provider, f"install the {model_config.provider} SDK")
        print(f"Error: {model_config.provider} SDK not installed. Run: {hint}", file=sys.stderr)
        sys.exit(1)

    return build_model_from_config(model_config)


def _setup_logging(agent_config: AttackAgentConfig) -> None:
    """Configure logging from AttackAgentConfig.logging."""
    log_config = agent_config.logging
    level = getattr(logging, log_config.level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="attack_agent",
        description="AttackAgent — authorized-lab / CTF pentest agent",
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=Path("config/settings.json"),
        help="Path to AttackAgentConfig JSON file (default: config/settings.json)",
    )
    parser.add_argument(
        "--provider-url",
        type=str,
        default=None,
        help="Base URL for LocalHTTPCompetitionProvider (e.g. http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--challenges-file",
        type=str,
        default=None,
        help="Path to JSON file with challenge definitions (for InMemoryCompetitionProvider)",
    )
    parser.add_argument(
        "--ctfd-url",
        type=str,
        default=None,
        help="CTFd platform base URL (e.g. http://ctfd.example.com)",
    )
    parser.add_argument(
        "--ctfd-username",
        type=str,
        default=None,
        help="CTFd username for session auth (requires --ctfd-password)",
    )
    parser.add_argument(
        "--ctfd-password",
        type=str,
        default=None,
        help="CTFd password for session auth",
    )
    parser.add_argument(
        "--ctfd-token",
        type=str,
        default=None,
        help="CTFd API token for Bearer auth",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        choices=["heuristic", "openai", "anthropic"],
        help="Model provider override (overrides config file model.provider)",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Override max solve cycles (overrides config file platform.max_cycles)",
    )
    parser.add_argument(
        "--stagnation-threshold",
        type=int,
        default=None,
        help="Override stagnation abandon threshold (overrides config file platform.stagnation_threshold)",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=None,
        help="Override flag submission confidence threshold (overrides config file platform.flag_confidence_threshold)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print detailed run journal after solve",
    )

    args = parser.parse_args(argv)

    # Load config
    if args.config.exists():
        agent_config = AttackAgentConfig.from_file(args.config)
    else:
        agent_config = AttackAgentConfig.from_defaults()

    # Apply CLI overrides
    if args.model:
        agent_config.model.provider = args.model
    if args.max_cycles is not None:
        agent_config.platform.max_cycles = args.max_cycles
    if args.stagnation_threshold is not None:
        agent_config.platform.stagnation_threshold = args.stagnation_threshold
    if args.confidence_threshold is not None:
        agent_config.platform.flag_confidence_threshold = args.confidence_threshold

    _setup_logging(agent_config)

    provider = _build_provider(
        args.provider_url, args.challenges_file,
        args.ctfd_url, args.ctfd_username, args.ctfd_password, args.ctfd_token,
    )
    model = _build_model(agent_config)

    platform = CompetitionPlatform(provider, model=model, agent_config=agent_config)

    print("AttackAgent starting...", file=sys.stderr)
    platform.solve_all(max_cycles=agent_config.platform.max_cycles)

    # Print summary
    view = WebConsoleView(platform.state_graph)
    print(view.render_text())

    if args.verbose:
        for project_id in platform.state_graph.projects:
            print(f"\n--- Run journal: {project_id} ---")
            print(view.render_run_journal_text(project_id))
            print(f"\n--- Pattern graph: {project_id} ---")
            print(view.render_pattern_graph_text(project_id))

    # Summary stats
    solved = sum(
        1 for r in platform.state_graph.projects.values()
        if r.snapshot.stage.value == "done"
    )
    total = len(platform.state_graph.projects)
    print(f"\nResult: {solved}/{total} challenges solved.", file=sys.stderr)


if __name__ == "__main__":
    main()