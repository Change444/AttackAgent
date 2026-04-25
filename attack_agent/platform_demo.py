from __future__ import annotations

from .console import WebConsoleView
from .platform import CompetitionPlatform
from .platform_models import ChallengeDefinition
from .provider import InMemoryCompetitionProvider


def build_demo_platform() -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="web-1",
                name="Web Login Boundary",
                category="web",
                difficulty="easy",
                target="http://127.0.0.1:8080",
                description="A local web challenge with login, role checks, and a hidden admin path.",
                metadata={
                    "hint_budget": 2,
                    "hint": "Inspect auth boundaries, role checks, and hidden responses.",
                    "flag": "flag{local-ctf-demo}",
                    "signals": ["login", "token", "cookie", "admin", "role"],
                    "primitive_payloads": {
                        "http-request": [
                            {
                                "id": "obs-auth",
                                "type": "observation",
                                "kind": "http-surface",
                                "tags": ["identity-boundary", "observation_gate"],
                                "payload": {
                                    "services": [{"name": "http", "port": 8080}],
                                    "endpoints": [{"path": "/"}, {"path": "/login"}, {"path": "/admin"}],
                                    "findings": [{"title": "admin path exists behind role check", "severity": "medium", "status": "observed"}],
                                },
                            },
                            {
                                "id": "obs-admin",
                                "type": "observation",
                                "kind": "privileged-response",
                                "tags": ["identity-boundary", "verification_gate"],
                                "text": "admin response body includes flag{local-ctf-demo}",
                            },
                        ],
                        "structured-parse": [
                            {
                                "id": "hyp-token",
                                "type": "hypothesis",
                                "tags": ["identity-boundary", "observation_gate"],
                                "statement": "Session material carries authorization context",
                                "confidence": 0.82,
                            }
                        ],
                        "session-materialize": [
                            {
                                "id": "obs-session",
                                "type": "observation",
                                "kind": "session-state",
                                "tags": ["identity-boundary", "action_template"],
                                "payload": {"sessions": [{"username": "ctf-admin", "privilege": "admin", "secret_ref": "vault://demo/admin"}]},
                            }
                        ],
                        "extract-candidate": [
                            {
                                "type": "candidate_flag",
                                "tags": ["identity-boundary", "verification_gate"],
                                "value": "flag{local-ctf-demo}",
                                "confidence": 0.97,
                            }
                        ],
                    },
                    "sandbox_program": "texts = inputs.get('texts', []); result = {'texts': [text for text in texts if 'flag{' in text]}",
                    "sandbox_inputs": {"texts": ["admin response body includes flag{local-ctf-demo}"]},
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


def main() -> None:
    platform = build_demo_platform()
    platform.solve_all()
    console = WebConsoleView(platform.state_graph)
    print(console.render_text())


if __name__ == "__main__":
    main()
