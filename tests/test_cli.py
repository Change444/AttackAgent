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
from attack_agent.config import (
    AttackAgentConfig,
    BrowserConfig,
    HttpConfig,
    LoggingConfig,
    MemoryConfig,
    ModelConfig,
    PatternDiscoveryConfig,
    PlatformConfig,
    SecurityConfig,
    SemanticRetrievalConfig,
    DualPathConfig,
)
from attack_agent.platform_models import ChallengeDefinition
from attack_agent.provider import InMemoryCompetitionProvider, LocalHTTPCompetitionProvider


def _fast_test_config_dict() -> dict:
    """Minimal config dict with stdlib engine and short timeouts for fast tests."""
    return {
        "model": {"provider": "heuristic"},
        "platform": {"max_cycles": 2, "stagnation_threshold": 2, "flag_confidence_threshold": 0.6},
        "dual_path": {"path_switch_stagnation_threshold": 2},
        "pattern_discovery": {"enable": False},
        "semantic_retrieval": {"enable": False},
        "security": {"allowed_hostpatterns": ["127.0.0.1", "localhost"], "max_http_requests": 5},
        "memory": {"persistence_enabled": False},
        "logging": {"level": "WARNING"},
        "browser": {"engine": "stdlib", "timeout_seconds": 0.5},
        "http": {"engine": "stdlib", "timeout_seconds": 0.5},
    }


def _write_fast_config() -> str:
    """Write a fast test config to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(_fast_test_config_dict(), f)
    f.flush()
    f.close()
    return f.name


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
        from attack_agent.model_adapter import is_available
        if not is_available("openai"):
            with self.assertRaises(SystemExit):
                _build_model(config)


class TestCLIMainRun(unittest.TestCase):
    def test_main_with_config_file_runs(self):
        """CLI with a fast test config file runs quickly (no 30s timeouts)."""
        config_path = _write_fast_config()
        captured = io.StringIO()
        try:
            with patch("sys.stdout", captured):
                main(["--config", config_path, "--max-cycles", "2"])
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_main_with_challenges_file_runs(self):
        """CLI with a challenges JSON file runs and produces output."""
        challenges = [
            {"id": "web-auth", "name": "JWT Role Boundary", "category": "web",
             "difficulty": "medium", "target": "http://127.0.0.1:8080",
             "description": "Local challenge with login and admin.",
             "metadata": {
                 "hint_budget": 1, "hint": "identity-boundary",
                 "signals": ["login", "cookie", "admin", "role"],
             }},
        ]
        config_path = _write_fast_config()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(challenges, f)
            f.flush()
            challenges_file = f.name

        captured = io.StringIO()
        try:
            with patch("sys.stdout", captured):
                main(["--config", config_path, "--challenges-file", challenges_file, "--max-cycles", "2"])
        finally:
            Path(challenges_file).unlink(missing_ok=True)
            Path(config_path).unlink(missing_ok=True)

        output = captured.getvalue()
        self.assertIn("project:web-auth", output)

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
        config_path = _write_fast_config()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(challenges, f)
            f.flush()
            challenges_file = f.name

        captured = io.StringIO()
        try:
            with patch("sys.stdout", captured):
                main(["--config", config_path, "--challenges-file", challenges_file, "--max-cycles", "2", "--verbose"])
        finally:
            Path(challenges_file).unlink(missing_ok=True)
            Path(config_path).unlink(missing_ok=True)

        output = captured.getvalue()
        self.assertIn("Run journal", output)
        self.assertIn("Pattern graph", output)

    def test_main_model_override(self):
        """CLI --model heuristic should override config even if config says openai."""
        config_path = _write_fast_config()
        captured = io.StringIO()
        try:
            with patch("sys.stdout", captured):
                main(["--config", config_path, "--model", "heuristic", "--max-cycles", "2"])
        finally:
            Path(config_path).unlink(missing_ok=True)


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
        """CLI --provider-url against a real HTTP server (2 cycles only)."""

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
        config_path = _write_fast_config()
        try:
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                main(["--config", config_path,
                      "--provider-url", f"http://127.0.0.1:{server.server_port}",
                      "--max-cycles", "2"])

            output = captured.getvalue()
            self.assertIn("project:c1", output)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            Path(config_path).unlink(missing_ok=True)


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