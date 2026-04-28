from __future__ import annotations

import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from attack_agent.console import WebConsoleView
from attack_agent.platform import CompetitionPlatform
from attack_agent.platform_models import ChallengeDefinition, ProjectStage, WorkerProfile
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.reasoning import LLMReasoner, StaticReasoningModel


def build_identity_platform(flag_confidence: float = 0.97) -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="web-auth",
                name="JWT Role Boundary",
                category="web",
                difficulty="medium",
                target="http://127.0.0.1:8080",
                description="A local challenge with login, cookie-based auth, role checks, and an admin page.",
                metadata={
                    "hint_budget": 1,
                    "hint": "Look at the session material and compare user/admin responses.",
                    "flag": "flag{integration}",
                    "signals": ["login", "cookie", "token", "admin", "role"],
                    "primitive_payloads": {
                        "http-request": [
                            {
                                "id": "obs-auth-surface",
                                "type": "observation",
                                "kind": "http-surface",
                                "tags": ["identity-boundary", "observation_gate"],
                                "payload": {
                                    "services": [{"name": "http", "port": 8080}],
                                    "endpoints": [{"path": "/"}, {"path": "/login"}, {"path": "/profile"}, {"path": "/admin"}],
                                },
                            },
                            {
                                "id": "obs-admin-response",
                                "type": "observation",
                                "kind": "admin-response",
                                "tags": ["identity-boundary", "verification_gate"],
                                "text": "admin panel reveals privileged data",
                            },
                        ],
                        "structured-parse": [
                            {
                                "id": "hyp-auth",
                                "type": "hypothesis",
                                "tags": ["identity-boundary", "observation_gate"],
                                "statement": "Authorization depends on reusable session material",
                                "confidence": 0.8,
                            }
                        ],
                        "session-materialize": [
                            {
                                "id": "obs-session-state",
                                "type": "observation",
                                "kind": "session-state",
                                "tags": ["identity-boundary", "action_template"],
                                "payload": {"sessions": [{"username": "admin", "privilege": "admin", "secret_ref": "vault://admin"}]},
                            }
                        ],
                        "extract-candidate": [
                            {
                                "type": "candidate_flag",
                                "tags": ["identity-boundary", "verification_gate"],
                                "value": "flag{integration}",
                                "confidence": flag_confidence,
                            }
                        ],
                    },
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


def build_browser_platform() -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="web-render",
                name="Rendered Comment Trail",
                category="web",
                difficulty="easy",
                target="http://127.0.0.1:9090",
                description="A rendered front-end challenge with hidden comments and browser-only clues.",
                metadata={
                    "hint_budget": 1,
                    "hint": "Use the browser path and inspect rendered output.",
                    "flag": "flag{browser}",
                    "signals": ["render", "comment", "browser", "html"],
                    "requires_browser": True,
                    "primitive_payloads": {
                        "http-request": [
                            {
                                "id": "obs-render-surface",
                                "type": "observation",
                                "kind": "render-surface",
                                "tags": ["reflection-render-boundary", "observation_gate"],
                                "payload": {"endpoints": [{"path": "/"}, {"path": "/comments"}]},
                            }
                        ],
                        "browser-inspect": [
                            {
                                "id": "obs-browser",
                                "type": "observation",
                                "kind": "browser-comment",
                                "tags": ["reflection-render-boundary", "observation_gate", "reflection-render-boundary", "action_template"],
                                "text": "hidden comment says flag{browser}",
                            }
                        ],
                    },
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


def build_artifact_platform() -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="misc-file",
                name="Archive Forensics",
                category="misc",
                difficulty="easy",
                target="file://archive.zip",
                description="An archive-based challenge where extracted text reveals the flag.",
                metadata={
                    "hint_budget": 1,
                    "hint": "Inspect the archive contents and decoded payloads.",
                    "flag": "flag{archive}",
                    "signals": ["archive", "zip", "file", "extract"],
                    "primitive_payloads": {
                        "artifact-scan": [
                            {
                                "id": "artifact-1",
                                "type": "artifact",
                                "kind": "archive-member",
                                "tags": ["file-archive-forensics", "observation_gate"],
                                "location": "archive://note.txt",
                                "metadata": {"content": "remember this: flag{archive}"},
                            }
                        ]
                    },
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


def build_binary_platform() -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="rev-1",
                name="Binary Strings",
                category="rev",
                difficulty="easy",
                target="file://challenge.bin",
                description="A binary challenge where extracted strings expose the flag.",
                metadata={
                    "hint_budget": 1,
                    "hint": "Inspect printable strings and transformed output.",
                    "flag": "flag{binary}",
                    "signals": ["binary", "strings", "elf", "reverse"],
                    "primitive_payloads": {
                        "binary-inspect": [
                            {
                                "id": "artifact-binary",
                                "type": "artifact",
                                "kind": "binary-strings",
                                "tags": ["binary-string-extraction", "observation_gate"],
                                "location": "binary://strings.txt",
                                "metadata": {"content": "welcome flag{binary}"},
                            }
                        ]
                    },
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


def build_real_http_platform(target: str) -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="web-live",
                name="Live HTTP Observe",
                category="web",
                difficulty="easy",
                target=target,
                description="A local HTTP challenge used to verify the runtime real request branch.",
                metadata={
                    "hint_budget": 1,
                    "hint": "Observe the live HTTP response.",
                    "flag": "flag{live}",
                    "signals": ["login", "cookie", "admin", "auth"],
                    "http_request": {
                        "requests": [
                            {
                                "id": "obs-live-http",
                                "kind": "http-live",
                                "tags": ["identity-boundary", "observation_gate"],
                                "method": "GET",
                                "path": "/login?mode=live",
                                "headers": {"X-Test-Header": "attack-agent"},
                                "timeout": 2.0,
                            }
                        ]
                    },
                    "extract-candidate": [
                        {
                            "type": "candidate_flag",
                            "tags": ["identity-boundary", "verification_gate"],
                            "value": "flag{live}",
                            "confidence": 0.97,
                        }
                    ],
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


def build_real_browser_platform(target: str) -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="web-browser-live",
                name="Live Browser Inspect",
                category="web",
                difficulty="easy",
                target=target,
                description="A local rendered challenge used to verify the runtime browser inspect branch.",
                metadata={
                    "hint_budget": 1,
                    "hint": "Inspect the rendered page and hidden comments.",
                    "flag": "flag{browser-live}",
                    "signals": ["render", "browser", "comment", "html"],
                    "requires_browser": True,
                    "browser_inspect": {
                        "pages": [
                            {
                                "id": "obs-live-browser",
                                "kind": "browser-live",
                                "tags": ["reflection-render-boundary", "observation_gate"],
                                "path": "/rendered",
                                "headers": {"X-Browser-Test": "attack-agent"},
                                "timeout": 2.0,
                            }
                        ]
                    },
                    "extract-candidate": [
                        {
                            "type": "candidate_flag",
                            "tags": ["reflection-render-boundary", "verification_gate"],
                            "value": "flag{browser-live}",
                            "confidence": 0.97,
                        }
                    ],
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


def build_real_binary_platform(target: str) -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="rev-live",
                name="Live Binary Inspect",
                category="rev",
                difficulty="easy",
                target=target,
                description="A local binary challenge used to verify the runtime binary inspect branch.",
                metadata={
                    "hint_budget": 1,
                    "hint": "Inspect printable strings from the local binary.",
                    "flag": "flag{binary-live}",
                    "signals": ["binary", "strings", "reverse"],
                    "binary_inspect": {
                        "files": [
                            {
                                "id": "obs-live-binary",
                                "kind": "binary-live",
                                "tags": ["binary-string-extraction", "observation_gate"],
                                "min_length": 5,
                                "max_strings": 8,
                            }
                        ]
                    },
                    "extract-candidate": [
                        {
                            "type": "candidate_flag",
                            "tags": ["binary-string-extraction", "verification_gate"],
                            "value": "flag{binary-live}",
                            "confidence": 0.97,
                        }
                    ],
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


def build_real_artifact_platform(target: str) -> CompetitionPlatform:
    provider = InMemoryCompetitionProvider(
        [
            ChallengeDefinition(
                id="misc-live",
                name="Live Artifact Scan",
                category="misc",
                difficulty="easy",
                target=target,
                description="A local file challenge used to verify the runtime artifact scan branch.",
                metadata={
                    "hint_budget": 1,
                    "hint": "Inspect the local file as a single artifact.",
                    "flag": "flag{artifact-live}",
                    "signals": ["file", "artifact", "note", "extract"],
                    "artifact_scan": {
                        "files": [
                            {
                                "id": "obs-live-artifact",
                                "kind": "artifact-live",
                                "tags": ["file-archive-forensics", "observation_gate"],
                                "preview_bytes": 48,
                            }
                        ]
                    },
                    "extract-candidate": [
                        {
                            "type": "candidate_flag",
                            "tags": ["file-archive-forensics", "verification_gate"],
                            "value": "flag{artifact-live}",
                            "confidence": 0.97,
                        }
                    ],
                },
            )
        ]
    )
    return CompetitionPlatform(provider)


class PlatformFlowTests(unittest.TestCase):
    def test_artifact_scan_with_artifact_scan_config_uses_real_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "note.txt"
            artifact_path.write_text("remember this: flag{artifact-live}\n", encoding="utf-8")
            platform = build_real_artifact_platform(artifact_path.resolve().as_uri())
            platform.solve_all(max_cycles=12)
            record = platform.state_graph.projects["project:misc-live"]
            observation = record.observations["obs-live-artifact"]
            self.assertEqual("artifact-live", observation.kind)
            self.assertEqual(artifact_path.resolve().as_uri(), observation.payload["uri"])
            self.assertEqual("note.txt", observation.payload["name"])
            self.assertEqual(".txt", observation.payload["suffix"])
            self.assertEqual(artifact_path.stat().st_size, observation.payload["size_bytes"])
            self.assertIn("sha1", observation.payload)
            self.assertIn("remember this: flag{artifact-live}", observation.payload["text_preview"])

    def test_binary_inspect_with_binary_inspect_config_uses_real_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            binary_path = Path(tmpdir) / "challenge.bin"
            binary_path.write_bytes(
                b"\x00\x01lead\x00"
                b"FLAG=flag{binary-live}\x00"
                b"admin-panel\x00"
                b"\xff\x10"
                b"strings-here\x00"
            )
            platform = build_real_binary_platform(binary_path.resolve().as_uri())
            platform.solve_all(max_cycles=12)
            record = platform.state_graph.projects["project:rev-live"]
            observation = record.observations["obs-live-binary"]
            self.assertEqual("binary-live", observation.kind)
            self.assertEqual(binary_path.resolve().as_uri(), observation.payload["path"])
            self.assertEqual(binary_path.stat().st_size, observation.payload["size_bytes"])
            self.assertIn("FLAG=flag{binary-live}", observation.payload["strings"])
            self.assertIn("admin-panel", observation.payload["strings"])
            self.assertEqual("file", observation.payload["scheme"])
            self.assertGreaterEqual(observation.payload["string_count"], 3)

    def test_browser_inspect_with_browser_inspect_config_uses_real_branch(self) -> None:
        requests_seen: list[dict[str, object]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                requests_seen.append(
                    {
                        "path": self.path,
                        "header": self.headers.get("X-Browser-Test"),
                    }
                )
                body = (
                    "<html><head><title>Rendered Notes</title></head><body>"
                    "<main id='app'>client rendered comment board</main>"
                    "<!-- hidden comment says browser path works -->"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            platform = build_real_browser_platform(f"http://127.0.0.1:{server.server_port}")
            platform.solve_all(max_cycles=12)
            record = platform.state_graph.projects["project:web-browser-live"]
            observation = record.observations["obs-live-browser"]
            self.assertEqual("browser-live", observation.kind)
            self.assertEqual("/rendered", requests_seen[0]["path"])
            self.assertEqual("attack-agent", requests_seen[0]["header"])
            self.assertEqual(f"http://127.0.0.1:{server.server_port}/rendered", observation.payload["url"])
            self.assertEqual("Rendered Notes", observation.payload["title"])
            self.assertIn("hidden comment says browser path works", observation.payload["comments"])
            self.assertIn("client rendered comment board", observation.payload["rendered_text"])
            self.assertEqual(["main#app"], observation.payload["rendered_nodes"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_request_with_http_request_config_uses_real_http_branch(self) -> None:
        requests_seen: list[dict[str, object]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                requests_seen.append(
                    {
                        "path": self.path,
                        "header": self.headers.get("X-Test-Header"),
                    }
                )
                body = (
                    "<html><body>"
                    "<h1>login portal</h1>"
                    "<form action='/session' method='post'>"
                    "<input name='username' />"
                    "<input type='password' name='password' />"
                    "</form>"
                    "<a href='/admin'>admin</a>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Set-Cookie", "session=live")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            platform = build_real_http_platform(f"http://127.0.0.1:{server.server_port}")
            platform.solve_all(max_cycles=12)
            record = platform.state_graph.projects["project:web-live"]
            observation = record.observations["obs-live-http"]
            self.assertEqual("http-live", observation.kind)
            self.assertEqual(200, observation.payload["status_code"])
            self.assertEqual("attack-agent", requests_seen[0]["header"])
            self.assertEqual("/login?mode=live", requests_seen[0]["path"])
            self.assertEqual(["session=live"], observation.payload["cookies"])
            self.assertEqual("/admin", observation.payload["endpoints"][0]["path"])
            self.assertEqual(
                [{"id": "form-0", "action": f"http://127.0.0.1:{server.server_port}/session", "method": "POST", "inputs": ["username", "password"]}],
                observation.payload["forms"],
            )
            self.assertIn("login_form", observation.payload["auth_clues"])
            self.assertIn("password_field", observation.payload["auth_clues"])
            self.assertIn("username_field", observation.payload["auth_clues"])
            self.assertIn("session_cookie", observation.payload["auth_clues"])
            self.assertIn("auth_path", observation.payload["auth_clues"])
            self.assertIn("auth_keywords", observation.payload["auth_clues"])
            self.assertIn("login portal", observation.payload["text"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_request_without_http_request_config_falls_back_to_metadata(self) -> None:
        platform = build_identity_platform()
        platform.solve_all(max_cycles=12)
        record = platform.state_graph.projects["project:web-auth"]
        observation = record.observations["obs-auth-surface"]
        self.assertEqual("http-surface", observation.kind)
        self.assertEqual([{"name": "http", "port": 8080}], observation.payload["services"])
        self.assertEqual(
            [{"path": "/"}, {"path": "/login"}, {"path": "/profile"}, {"path": "/admin"}],
            observation.payload["endpoints"],
        )
        self.assertNotIn("status_code", observation.payload)

    def test_unseen_web_auth_flow_uses_identity_pattern_and_solves(self) -> None:
        platform = build_identity_platform()
        platform.solve_all(max_cycles=12)
        record = platform.state_graph.projects["project:web-auth"]
        self.assertEqual(ProjectStage.DONE, record.snapshot.stage)
        self.assertEqual("identity-boundary", record.pattern_graph.active_family)
        self.assertTrue(record.submission_history)

    def test_browser_pattern_selects_browser_profile(self) -> None:
        platform = build_browser_platform()
        platform.solve_all(max_cycles=12)
        record = platform.state_graph.projects["project:web-render"]
        self.assertEqual(WorkerProfile.BROWSER, record.snapshot.worker_profile)
        self.assertTrue(record.candidate_flags)

    def test_artifact_pattern_solves_without_new_plugin_code(self) -> None:
        platform = build_artifact_platform()
        platform.solve_all(max_cycles=12)
        record = platform.state_graph.projects["project:misc-file"]
        self.assertEqual(ProjectStage.DONE, record.snapshot.stage)

    def test_binary_pattern_solves_without_new_plugin_code(self) -> None:
        platform = build_binary_platform()
        platform.solve_all(max_cycles=12)
        record = platform.state_graph.projects["project:rev-1"]
        self.assertEqual(ProjectStage.DONE, record.snapshot.stage)

    def test_low_confidence_flag_is_blocked(self) -> None:
        platform = build_identity_platform(flag_confidence=0.5)
        platform.solve_all(max_cycles=12)
        record = platform.state_graph.projects["project:web-auth"]
        self.assertNotEqual(ProjectStage.DONE, record.snapshot.stage)
        self.assertFalse(record.submission_history)

    def test_timeout_and_requeue_are_recorded(self) -> None:
        platform = build_identity_platform()
        platform.bootstrap()
        platform.dispatcher.mark_timeout("run-timeout")
        platform.dispatcher.requeue("project:web-auth", "hint")
        events = platform.state_graph.query_graph("project:web-auth", view="events")["events"]
        event_types = [event["type"] for event in events]
        self.assertIn("worker_timeout", event_types)
        self.assertIn("requeue", event_types)

    def test_console_view_renders_project_summary(self) -> None:
        platform = build_identity_platform()
        platform.solve_all(max_cycles=12)
        view = WebConsoleView(platform.state_graph).render_text()
        self.assertIn("project:web-auth", view)

    def test_console_view_renders_single_project_pattern_graph(self) -> None:
        platform = build_identity_platform()
        platform.solve_all(max_cycles=12)
        view = WebConsoleView(platform.state_graph).render_pattern_graph_text("project:web-auth")
        self.assertIn("project:web-auth", view)
        self.assertIn("active_family=identity-boundary", view)
        self.assertIn("identity-boundary:observe", view)
        self.assertIn("family=identity-boundary", view)
        self.assertIn("status=resolved", view)

    def test_console_view_renders_single_project_run_journal(self) -> None:
        platform = build_identity_platform()
        platform.solve_all(max_cycles=12)
        view = WebConsoleView(platform.state_graph).render_run_journal_text("project:web-auth")
        self.assertIn("project:web-auth", view)
        self.assertIn("events=", view)
        self.assertIn("project_upserted | controller |", view)
        self.assertIn("instance_started | controller |", view)
        self.assertIn("program_compiled | dispatcher |", view)
        self.assertLess(view.index("project_upserted | controller |"), view.index("instance_started | controller |"))
        self.assertLess(view.index("instance_started | controller |"), view.index("program_compiled | dispatcher |"))

    def test_llm_reasoner_can_override_worker_profile(self) -> None:
        reasoner = LLMReasoner(
            StaticReasoningModel(
                {
                    "select_worker_profile": {
                        "profile": "browser",
                        "reason": "ui-heavy challenge should start with browser workflow",
                    }
                }
            )
        )
        platform = build_identity_platform()
        platform = CompetitionPlatform(platform.provider, reasoner=reasoner)
        platform.bootstrap()
        platform.dispatcher.schedule("project:web-auth")
        record = platform.state_graph.projects["project:web-auth"]
        self.assertEqual(WorkerProfile.BROWSER, record.snapshot.worker_profile)

    def test_llm_reasoner_records_planner_source_and_rationale(self) -> None:
        reasoner = LLMReasoner(
            StaticReasoningModel(
                {
                    "choose_program": {
                        "family": "identity-boundary",
                        "node_id": "identity-boundary:observe",
                        "step_primitives": ["structured-parse", "http-request"],
                        "rationale": "normalize auth clues before hitting deeper endpoints",
                    }
                }
            )
        )
        platform = build_identity_platform()
        platform = CompetitionPlatform(platform.provider, reasoner=reasoner)
        platform.bootstrap()
        platform.dispatcher.schedule("project:web-auth")
        platform.dispatcher.schedule("project:web-auth")
        platform.dispatcher.schedule("project:web-auth")
        events = platform.state_graph.query_graph("project:web-auth", view="events")["events"]
        compiled = [event for event in events if event["type"] == "program_compiled"]
        self.assertTrue(compiled)
        payload = compiled[-1]["payload"]
        # planner_source may be "llm" (structured path) or "free_exploration_heuristic" (heuristic path)
        self.assertIn(payload["planner_source"], {"llm", "free_exploration_heuristic"})
        # rationale varies by path — structured gives LLM rationale, heuristic gives family info
        self.assertTrue(len(payload["rationale"]) > 0)


if __name__ == "__main__":
    unittest.main()
