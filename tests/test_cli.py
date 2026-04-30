"""Tests for the CLI entry point (__main__.py) and integration with real HTTP targets."""
from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from attack_agent.__main__ import main, _build_provider, _build_model
from attack_agent.config import AttackAgentConfig, SecurityConfig, ModelConfig
from attack_agent.platform_models import ChallengeDefinition
from attack_agent.provider import InMemoryCompetitionProvider, LocalHTTPCompetitionProvider


# ── CLI Tests ──


class TestCLIBuildProvider(unittest.TestCase):
    def test_build_provider_from_url(self):
        provider = _build_provider("http://127.0.0.1:9999", None, None, None, None, None)
        self.assertIsInstance(provider, LocalHTTPCompetitionProvider)
        self.assertEqual(provider.base_url, "http://127.0.0.1:9999")

    def test_build_provider_from_challenges_file(self):
        challenges = [
            {"id": "c1", "name": "Test", "category": "web", "difficulty": "easy",
             "target": "http://127.0.0.1:8000", "description": "test challenge"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(challenges, f)
            f.flush()
            provider = _build_provider(None, f.name, None, None, None, None)
        self.assertIsInstance(provider, InMemoryCompetitionProvider)
        self.assertEqual(len(provider.challenges), 1)
        Path(f.name).unlink(missing_ok=True)

    def test_build_provider_default_demo(self):
        provider = _build_provider(None, None, None, None, None, None)
        self.assertIsInstance(provider, InMemoryCompetitionProvider)
        self.assertEqual(len(provider.challenges), 1)
        self.assertEqual("demo-1", list(provider.challenges.keys())[0])


class TestCLIBuildModel(unittest.TestCase):
    def test_build_model_heuristic(self):
        config = AttackAgentConfig.from_defaults()
        config.model.provider = "heuristic"
        model = _build_model(config)
        self.assertIsNone(model)

    def test_build_model_openai_not_available(self):
        config = AttackAgentConfig.from_defaults()
        config.model.provider = "openai"
        # Will exit(1) if openai not installed — test the error path
        from attack_agent.model_adapter import is_available
        if not is_available("openai"):
            with self.assertRaises(SystemExit):
                _build_model(config)


class TestCLIMainRun(unittest.TestCase):
    def test_main_with_challenges_file_runs(self):
        """CLI with a challenges JSON file runs and produces output (no longer fakes solving via metadata)."""
        challenges = [
            {"id": "web-auth", "name": "JWT Role Boundary", "category": "web",
             "difficulty": "medium", "target": "http://127.0.0.1:8080",
             "description": "Local challenge with login and admin.",
             "metadata": {
                 "hint_budget": 1, "hint": "identity-boundary",
                 "signals": ["login", "cookie", "admin", "role"],
             }},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(challenges, f)
            f.flush()
            challenges_file = f.name

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            main(["--challenges-file", challenges_file, "--max-cycles", "3"])

        output = captured.getvalue()
        self.assertIn("project:web-auth", output)

        Path(challenges_file).unlink(missing_ok=True)

    def test_main_with_config_file(self):
        """CLI with config/settings.json should load and run (demo provider)."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            main(["--config", str(Path("config/settings.json")), "--max-cycles", "3"])

    def test_main_verbose_output(self):
        """CLI --verbose should print run journal and pattern graph."""
        challenges = [
            {"id": "c-verbose", "name": "Verbose Test", "category": "web",
             "difficulty": "easy", "target": "http://127.0.0.1:8080",
             "description": "test",
             "metadata": {
                 "hint_budget": 1, "signals": ["login", "admin"],
             }},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(challenges, f)
            f.flush()
            challenges_file = f.name

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            main(["--challenges-file", challenges_file, "--max-cycles", "3", "--verbose"])

        output = captured.getvalue()
        self.assertIn("Run journal", output)
        self.assertIn("Pattern graph", output)

        Path(challenges_file).unlink(missing_ok=True)

    def test_main_model_override(self):
        """CLI --model heuristic should override config even if config says openai."""
        config_path = Path("config/settings.json")
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            main(["--config", str(config_path), "--model", "heuristic", "--max-cycles", "3"])

        # Should not crash (heuristic mode always works)


# ── Real HTTP Integration Tests ──


class TestRealHTTPIntegration(unittest.TestCase):
    """Integration tests using a real local HTTP server."""

    def _make_server(self, handler_class) -> ThreadingHTTPServer:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_local_http_provider_list_challenges(self):
        """LocalHTTPCompetitionProvider can list challenges from a real server."""

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/challenges":
                    body = json.dumps({"items": [
                        {"id": "c1", "name": "Test", "category": "web",
                         "difficulty": "easy", "target": f"http://127.0.0.1:{self.server.server_port}",
                         "description": "test"},
                    ]}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, fmt, *args):  # noqa: A003
                return

        server, thread = self._make_server(Handler)
        try:
            provider = LocalHTTPCompetitionProvider(f"http://127.0.0.1:{server.server_port}")
            challenges = provider.list_challenges()
            self.assertEqual(len(challenges), 1)
            self.assertEqual("c1", challenges[0].id)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_local_http_provider_submit_flag(self):
        """LocalHTTPCompetitionProvider can submit a flag to a real server."""

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length))
                if self.path == "/submit":
                    accepted = data.get("flag") == "flag{test}"
                    body = json.dumps({
                        "accepted": accepted,
                        "message": "accepted" if accepted else "wrong",
                        "status": "accepted" if accepted else "rejected",
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/start_challenge":
                    body = json.dumps({
                        "instance": {"instance_id": "i1", "challenge_id": data.get("challenge_id"),
                                     "target": f"http://127.0.0.1:{self.server.server_port}",
                                     "status": "running"},
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_GET(self):  # noqa: N802
                if self.path == "/challenges":
                    body = json.dumps({"items": [
                        {"id": "c1", "name": "Test", "category": "web",
                         "difficulty": "easy",
                         "target": f"http://127.0.0.1:{self.server.server_port}",
                         "description": "test",
                         "metadata": {"flag": "flag{test}"}},
                    ]}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, fmt, *args):  # noqa: A003
                return

        server, thread = self._make_server(Handler)
        try:
            provider = LocalHTTPCompetitionProvider(f"http://127.0.0.1:{server.server_port}")
            instance = provider.start_challenge("c1")
            result = provider.submit_flag(instance.instance_id, "flag{test}")
            self.assertTrue(result.accepted)
            result2 = provider.submit_flag(instance.instance_id, "wrong")
            self.assertFalse(result2.accepted)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_cli_with_provider_url(self):
        """CLI --provider-url against a real HTTP server that provides challenges."""

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/challenges":
                    body = json.dumps({"items": [
                        {"id": "c1", "name": "ServerTest", "category": "web",
                         "difficulty": "easy",
                         "target": f"http://127.0.0.1:{self.server.server_port}",
                         "description": "test from server",
                         "metadata": {"flag": "flag{server}"}},
                    ]}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/status/"):
                    body = json.dumps({"status": "running"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length))
                if self.path == "/start_challenge":
                    body = json.dumps({
                        "instance": {"instance_id": "i1", "challenge_id": "c1",
                                     "target": f"http://127.0.0.1:{self.server.server_port}",
                                     "status": "running"},
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/submit":
                    accepted = data.get("flag") == "flag{server}"
                    body = json.dumps({
                        "accepted": accepted,
                        "message": "accepted" if accepted else "wrong",
                        "status": "accepted" if accepted else "rejected",
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/hint":
                    body = json.dumps({"hint": "no hint", "remaining": 0}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/stop_challenge":
                    body = json.dumps({"stopped": True}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, fmt, *args):  # noqa: A003
                return

        server, thread = self._make_server(Handler)
        try:
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                main(["--provider-url", f"http://127.0.0.1:{server.server_port}",
                      "--max-cycles", "5"])

            output = captured.getvalue()
            self.assertIn("project:c1", output)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class TestConfigFromDefaults(unittest.TestCase):
    def test_from_defaults_creates_valid_config(self):
        config = AttackAgentConfig.from_defaults()
        self.assertIsInstance(config.security, SecurityConfig)
        self.assertEqual(config.model.provider, "heuristic")
        self.assertEqual(config.platform.max_cycles, 50)
        self.assertEqual(config.platform.stagnation_threshold, 8)
        self.assertEqual(config.platform.flag_confidence_threshold, 0.6)

    def test_from_defaults_security_values(self):
        """from_defaults() security values should be usable directly."""
        config = AttackAgentConfig.from_defaults()
        from attack_agent.constraints import LightweightSecurityShell
        shell = LightweightSecurityShell(config.security)
        self.assertEqual(shell.security_config.max_http_requests, 30)
        self.assertEqual(shell.security_config.max_program_steps, 15)


if __name__ == "__main__":
    unittest.main()