"""Tests for real primitive execution capabilities."""

import hashlib
import http.server
import json
import os
import re
import struct
import tempfile
import threading
import time
import unittest
import zipfile
import tarfile
from pathlib import Path
from urllib import parse, request

from attack_agent.apg import CodeSandbox, _SafeAstValidator
from attack_agent.platform_models import (
    ActionProgram,
    ActionOutcome,
    CandidateFlag,
    ChallengeDefinition,
    ChallengeInstance,
    Observation,
    PrimitiveActionStep,
    ProjectStage,
    TaskBundle,
    WorkerProfile,
)
from attack_agent.runtime import (
    HttpSessionManager,
    PrimitiveRegistry,
    WorkerRuntime,
    _extract_candidates,
    _extract_utf8_strings,
    _extract_wide_strings,
    _parse_binary_headers,
    _parse_html_page,
    _perform_diff_compare,
    _perform_structured_parse,
)


def _make_bundle(target="http://127.0.0.1:9999", metadata=None, challenge_flag_pattern=r"flag\{[^}]+\}",
                 step_parameters=None, completed_observations=None):
    metadata = metadata or {}
    step_params = step_parameters or {}
    challenge = ChallengeDefinition(
        id="test-challenge", name="Test", category="web",
        difficulty="easy", target=target, description="test",
        flag_pattern=challenge_flag_pattern,
    )
    instance = ChallengeInstance(
        instance_id="inst-1", challenge_id="test-challenge",
        target=target, status="running", metadata=metadata,
    )
    program = ActionProgram(
        id="prog-1", goal="test", pattern_nodes=["test:goal"],
        steps=[PrimitiveActionStep(primitive="http-request", instruction="test", parameters=step_params)],
        allowed_primitives=["http-request"], verification_rules=[],
        required_profile=WorkerProfile.NETWORK,
    )
    bundle = TaskBundle(
        project_id="proj-1", run_id="run-1", action_program=program,
        stage=ProjectStage.EXPLORE, worker_profile=WorkerProfile.NETWORK,
        target=target, challenge=challenge, instance=instance,
        handoff_summary="", visible_primitives=["http-request", "browser-inspect", "session-materialize",
                                                  "structured-parse", "diff-compare", "extract-candidate",
                                                  "artifact-scan", "binary-inspect", "code-sandbox"],
    )
    if completed_observations:
        bundle.completed_observations = completed_observations
    return bundle


class _TestHTTPHandler(http.server.BaseHTTPRequestHandler):
    pages = {
        "/": "<html><head><title>Test Page</title></head><body><h1>Hello</h1>"
             "<form action='/login' method='POST'><input name='username'/><input name='password' type='password'/>"
             "<input type='submit'/></form><a href='/secret'>Secret</a>"
             "<!-- hidden: flag{html_comment} --></body></html>",
        "/login": "<html><body>Login success</body></html>",
        "/secret": "<html><body>flag{secret_page}</body></html>",
        "/json": json.dumps({"users": [{"name": "admin", "password": "flag{json_secret"}]}),
        "/set-cookie": "",
        "/redirect": "",
    }

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/set-cookie":
            self.send_response(200)
            self.send_header("Set-Cookie", "session=abc123")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Cookie set</body></html>")
        elif path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/secret")
            self.end_headers()
        elif path in self.pages:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            content = self.pages[path]
            if isinstance(content, str):
                self.wfile.write(content.encode("utf-8"))
            else:
                self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/login":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = dict(parse.parse_qs(body).items())
            if params.get("username") == ["admin"] and params.get("password") == ["pass"]:
                self.send_response(200)
                self.send_header("Set-Cookie", "auth=token123")
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>Login OK</body></html>")
            else:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Login failed")
        elif path == "/json":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "posted"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class HttpSessionManagerTests(unittest.TestCase):
    def test_build_opener_returns_opener_director(self):
        mgr = HttpSessionManager()
        opener = mgr.build_opener()
        self.assertIsInstance(opener, request.OpenerDirector)

    def test_cookie_jar_persistence(self):
        mgr = HttpSessionManager()
        jar = mgr.cookie_jar
        self.assertEqual(len(list(jar)), 0)

    def test_auth_headers_default_empty(self):
        mgr = HttpSessionManager()
        self.assertEqual(mgr.get_auth_headers(), {})

    def test_add_and_get_auth_headers(self):
        mgr = HttpSessionManager()
        mgr.add_auth_header("Authorization", "Bearer abc123")
        headers = mgr.get_auth_headers()
        self.assertEqual(headers["Authorization"], "Bearer abc123")


class HTTPRequestEnhancedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _TestHTTPHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_http_post_with_form_data(self):
        session_mgr = HttpSessionManager()
        spec = {
            "url": f"{self.base_url}/login",
            "method": "POST",
            "form": {"username": "admin", "password": "pass"},
        }
        from attack_agent.runtime import _perform_http_request
        result = _perform_http_request(spec, self.base_url, session_mgr)
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["method"], "POST")

    def test_http_cookie_persistence_across_requests(self):
        session_mgr = HttpSessionManager()
        spec1 = {"url": f"{self.base_url}/set-cookie"}
        from attack_agent.runtime import _perform_http_request
        result1 = _perform_http_request(spec1, self.base_url, session_mgr)
        self.assertIn("session=abc123", result1["cookies"])
        spec2 = {"url": f"{self.base_url}/secret"}
        result2 = _perform_http_request(spec2, self.base_url, session_mgr)
        jar_cookies = session_mgr.get_cookies_text()
        self.assertTrue(any("session" in c for c in jar_cookies))

    def test_http_redirect_following(self):
        session_mgr = HttpSessionManager()
        spec = {"url": f"{self.base_url}/redirect"}
        from attack_agent.runtime import _perform_http_request
        result = _perform_http_request(spec, self.base_url, session_mgr)
        self.assertEqual(result["status_code"], 200)
        self.assertIn("flag{secret_page}", result["text"])

    def test_http_request_post_json_body(self):
        session_mgr = HttpSessionManager()
        spec = {
            "url": f"{self.base_url}/json",
            "method": "POST",
            "json": {"data": "test"},
        }
        from attack_agent.runtime import _perform_http_request
        result = _perform_http_request(spec, self.base_url, session_mgr)
        self.assertEqual(result["status_code"], 200)

    def test_perform_http_request_has_r5_fields(self):
        session_mgr = HttpSessionManager()
        spec = {"url": f"{self.base_url}/"}
        from attack_agent.runtime import _perform_http_request
        result = _perform_http_request(spec, self.base_url, session_mgr)
        self.assertIn("auth_used", result)
        self.assertEqual(result["auth_used"], "none")
        self.assertIn("ssl_verified", result)
        self.assertEqual(result["ssl_verified"], True)
        self.assertIn("uploaded_files", result)
        self.assertEqual(result["uploaded_files"], [])

    def test_resolve_http_request_specs_includes_auth_fields(self):
        from attack_agent.runtime import _resolve_http_request_specs, PrimitiveActionStep
        metadata = {
            "http_request": {
                "url": "http://test/",
                "auth": {"username": "admin", "password": "pass"},
                "auth_type": "basic",
            }
        }
        bundle = _make_bundle(target="http://test/", metadata=metadata)
        step = PrimitiveActionStep(primitive="http-request", instruction="test", parameters={})
        specs = _resolve_http_request_specs(step, bundle)
        self.assertTrue(len(specs) > 0)
        self.assertIn("auth", specs[0])
        self.assertEqual(specs[0]["auth_type"], "basic")


class SessionMaterializeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _TestHTTPHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_session_materialize_real_login(self):
        from attack_agent.runtime import _execute_session_materialize, PrimitiveAdapter, PrimitiveActionSpec
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/login",
                "username": "admin",
                "password": "pass",
                "method": "POST",
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        adapter = PrimitiveAdapter(PrimitiveActionSpec("session-materialize", "session/state", {}, {}, 1.1, "medium"))
        outcome = adapter.execute(step, bundle, CodeSandbox(), session_mgr)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(len(outcome.observations) > 0)
        obs = outcome.observations[0]
        self.assertEqual(obs.kind, "session-materialized")
        self.assertEqual(obs.payload["status_code"], 200)
        self.assertIn("auth=token123", obs.payload["cookies_obtained"])

    def test_session_materialize_no_config_cleanly_fails(self):
        """Without session_materialize config, primitive returns clean failure."""
        bundle = _make_bundle(metadata={})
        step = PrimitiveActionStep(primitive="session-materialize", instruction="session", parameters={})
        from attack_agent.runtime import _execute_session_materialize
        outcome = _execute_session_materialize(step, bundle, None)
        self.assertEqual(outcome.status, "failed")
        self.assertIn("no_config_available", outcome.failure_reason)
        self.assertEqual(outcome.novelty, 0.0)
        self.assertEqual(len(outcome.observations), 0)


class StructuredParseTests(unittest.TestCase):
    def test_structured_parse_json_from_completed_observations(self):
        obs_payload = {"text": json.dumps({"secret_key": "flag{parsed}", "users": ["admin"]})}
        source_obs = Observation(id="obs-1", kind="http-response", source="http-request",
                                 target="http://test", payload=obs_payload, confidence=0.85, novelty=0.7)
        bundle = _make_bundle(step_parameters={"parse_source": "obs-1", "format": "json", "extract_fields": ["secret_key"]},
                              completed_observations={"obs-1": source_obs})
        step = PrimitiveActionStep(primitive="structured-parse", instruction="parse json",
                                    parameters={"parse_source": "obs-1", "format": "json", "extract_fields": ["secret_key"]})
        from attack_agent.runtime import _execute_structured_parse
        outcome = _execute_structured_parse(step, bundle)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(len(outcome.observations) > 0)
        obs = outcome.observations[0]
        self.assertIn("parsed_data", obs.payload)
        self.assertEqual(obs.payload["extracted"]["secret_key"], "flag{parsed}")

    def test_structured_parse_html_extracts_forms_and_links(self):
        html = "<html><head><title>Test</title></head><body>"
        html += "<form action='/login' method='POST'><input name='user'/></form>"
        html += "<a href='/page'>Link</a></body></html>"
        obs_payload = {"text": html}
        source_obs = Observation(id="obs-2", kind="browser-page", source="browser-inspect",
                                 target="http://test", payload=obs_payload, confidence=0.8, novelty=0.6)
        bundle = _make_bundle(step_parameters={"parse_source": "obs-2", "format": "html"},
                              completed_observations={"obs-2": source_obs})
        step = PrimitiveActionStep(primitive="structured-parse", instruction="parse html",
                                    parameters={"parse_source": "obs-2", "format": "html"})
        from attack_agent.runtime import _execute_structured_parse
        outcome = _execute_structured_parse(step, bundle)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(len(outcome.observations) > 0)
        obs = outcome.observations[0]
        self.assertIn("forms", obs.payload)
        self.assertEqual(len(obs.payload["forms"]), 1)
        self.assertEqual(obs.payload["forms"][0]["method"], "POST")

    def test_structured_parse_no_config_cleanly_fails(self):
        """Without parse_source/format parameters, structured-parse returns clean failure."""
        bundle = _make_bundle(metadata={})
        step = PrimitiveActionStep(primitive="structured-parse", instruction="parse",
                                    parameters={})
        from attack_agent.runtime import _execute_structured_parse
        outcome = _execute_structured_parse(step, bundle)
        self.assertEqual(outcome.status, "failed")
        self.assertIn("no_config_available", outcome.failure_reason)
        self.assertEqual(outcome.novelty, 0.0)
        self.assertEqual(len(outcome.observations), 0)

    def test_perform_structured_parse_headers(self):
        payload = {"headers": {"X-Secret": "flag{header}", "Authorization": "Bearer abc", "Content-Type": "text/html"}}
        result = _perform_structured_parse(payload, "headers", [])
        self.assertIn("interesting_headers", result)
        self.assertIn("X-Secret", result["interesting_headers"])


class DiffCompareTests(unittest.TestCase):
    def test_diff_compare_two_texts(self):
        result = _perform_diff_compare("line1\nline2\nline3", "line1\nline_changed\nline3\nline4",
                                        "baseline-1", "variant-1")
        self.assertIn("diff_lines", result)
        self.assertTrue(result["change_count"] > 0)
        self.assertIn("summary", result)
        self.assertIn("additions", result["summary"])

    def test_diff_compare_no_changes(self):
        result = _perform_diff_compare("same text", "same text", "b-1", "v-1")
        self.assertEqual(result["change_count"], 0)

    def test_diff_compare_from_completed_observations(self):
        obs1 = Observation(id="obs-a", kind="http-response", source="http-request",
                          target="http://test",
                          payload={"text": "Response version 1", "status_code": 200},
                          confidence=0.85, novelty=0.7)
        obs2 = Observation(id="obs-b", kind="http-response", source="http-request",
                          target="http://test",
                          payload={"text": "Response version 2 modified", "status_code": 200},
                          confidence=0.85, novelty=0.7)
        bundle = _make_bundle(
            step_parameters={"baseline_observation_id": "obs-a", "variant_observation_id": "obs-b"},
            completed_observations={"obs-a": obs1, "obs-b": obs2}
        )
        step = PrimitiveActionStep(primitive="diff-compare", instruction="compare",
                                    parameters={"baseline_observation_id": "obs-a", "variant_observation_id": "obs-b"})
        from attack_agent.runtime import _execute_diff_compare
        outcome = _execute_diff_compare(step, bundle)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(len(outcome.observations) > 0)
        obs = outcome.observations[0]
        self.assertEqual(obs.kind, "diff-result")
        self.assertIn("diff_lines", obs.payload)

    def test_diff_compare_no_config_cleanly_fails(self):
        """Without baseline/variant IDs, diff-compare returns clean failure."""
        bundle = _make_bundle(metadata={})
        step = PrimitiveActionStep(primitive="diff-compare", instruction="compare", parameters={})
        from attack_agent.runtime import _execute_diff_compare
        outcome = _execute_diff_compare(step, bundle)
        self.assertEqual(outcome.status, "failed")
        self.assertIn("no_config_available", outcome.failure_reason)
        self.assertEqual(outcome.novelty, 0.0)
        self.assertEqual(len(outcome.observations), 0)


class ExtractCandidateEnhancedTests(unittest.TestCase):
    def test_extract_candidate_from_completed_observations(self):
        obs = Observation(id="obs-1", kind="http-response", source="http-request",
                         target="http://test",
                         payload={"text": "The flag is flag{from_observation}"},
                         confidence=0.85, novelty=0.7)
        metadata = {"primitive_payloads": {}}
        bundle = _make_bundle(metadata=metadata, challenge_flag_pattern=r"flag\{[^}]+\}",
                              completed_observations={"obs-1": obs})
        step = PrimitiveActionStep(primitive="extract-candidate", instruction="extract", parameters={})
        outcome = _extract_candidates(step, bundle)
        self.assertTrue(len(outcome.candidate_flags) > 0)
        found = any(c.value == "flag{from_observation}" for c in outcome.candidate_flags)
        self.assertTrue(found)

    def test_extract_candidate_multi_pattern(self):
        obs = Observation(id="obs-1", kind="http-response", source="http-request",
                         target="http://test",
                         payload={"text": "Email: admin@ctf.com and flag{multi_pattern}"},
                         confidence=0.85, novelty=0.7)
        metadata = {"primitive_payloads": {}}
        bundle = _make_bundle(metadata=metadata, challenge_flag_pattern=r"flag\{[^}]+\}",
                              step_parameters={"patterns": [r"[a-z]+@[a-z]+\.[a-z]+"]},
                              completed_observations={"obs-1": obs})
        step = PrimitiveActionStep(primitive="extract-candidate", instruction="extract",
                                    parameters={"patterns": [r"[a-z]+@[a-z]+\.[a-z]+"]})
        outcome = _extract_candidates(step, bundle)
        flag_found = any(c.value == "flag{multi_pattern}" for c in outcome.candidate_flags)
        email_found = any(c.value == "admin@ctf.com" for c in outcome.candidate_flags)
        self.assertTrue(flag_found)
        self.assertTrue(email_found)


class CodeSandboxRelaxedTests(unittest.TestCase):
    def test_safe_import_hashlib(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("import hashlib\nresult = {'hash': hashlib.sha256(b'test').hexdigest()}", {})
        self.assertIn("hash", result)
        self.assertEqual(result["hash"], hashlib.sha256(b"test").hexdigest())

    def test_safe_import_base64(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("import base64\nresult = {'encoded': base64.b64encode(b'hello').decode()}", {})
        self.assertEqual(result["encoded"], "aGVsbG8=")

    def test_function_definition_allowed(self):
        sandbox = CodeSandbox()
        result = sandbox.execute(
            "def transform(s):\n    return s.upper()\nresult = {'text': transform('hello')}", {}
        )
        self.assertEqual(result["text"], "HELLO")

    def test_try_except_allowed(self):
        sandbox = CodeSandbox()
        result = sandbox.execute(
            "try:\n    x = int('abc')\nexcept ValueError:\n    result = {'error': 'caught'}", {}
        )
        self.assertEqual(result["error"], "caught")

    def test_disallowed_import_os(self):
        sandbox = CodeSandbox()
        with self.assertRaises(RuntimeError):
            sandbox.execute("import os\nresult = {}", {})

    def test_class_definition_allowed(self):
        sandbox = CodeSandbox()
        result = sandbox.execute(
            "class Decoder:\n    def __init__(self, data):\n        self.data = data\n    def decode(self):\n        return self.data[::-1]\nresult = {'decoded': Decoder('hello').decode()}", {}
        )
        self.assertEqual(result["decoded"], "olleh")

    def test_with_statement_allowed(self):
        sandbox = CodeSandbox()
        result = sandbox.execute(
            "class CM:\n    def __enter__(self):\n        return 'entered'\n    def __exit__(self, *args):\n        pass\nwith CM() as val:\n    result = {'context': val}", {}
        )
        self.assertEqual(result["context"], "entered")

    def test_raise_statement_allowed(self):
        sandbox = CodeSandbox()
        result = sandbox.execute(
            "try:\n    raise ValueError('test error')\nexcept ValueError as e:\n    result = {'error': str(e)}", {}
        )
        self.assertEqual(result["error"], "test error")

    def test_safe_import_zlib(self):
        sandbox = CodeSandbox()
        result = sandbox.execute(
            "import zlib\ndata = b'CTF data payload'\ncompressed = zlib.compress(data)\nresult = {'decompressed': zlib.decompress(compressed).decode()}", {}
        )
        self.assertEqual(result["decompressed"], "CTF data payload")

    def test_safe_import_csv(self):
        sandbox = CodeSandbox()
        result = sandbox.execute(
            "import csv\nrows = list(csv.reader(['a,b,c', '1,2,3']))\nresult = {'rows': rows}", {}
        )
        self.assertEqual(result["rows"], [["a", "b", "c"], ["1", "2", "3"]])

    def test_safe_ast_validator_safe_imports(self):
        validator = _SafeAstValidator(set(CodeSandbox.SAFE_BUILTINS), CodeSandbox.SAFE_IMPORTS)
        import ast
        tree = ast.parse("import hashlib\nresult = {}")
        validator.visit(tree)

    def test_safe_ast_validator_disallowed_import(self):
        validator = _SafeAstValidator(set(CodeSandbox.SAFE_BUILTINS), CodeSandbox.SAFE_IMPORTS)
        import ast
        tree = ast.parse("import os\nresult = {}")
        with self.assertRaises(RuntimeError):
            validator.visit(tree)


class BrowserInspectNonLocalhostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _TestHTTPHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_browser_inspect_non_localhost_url_accepted(self):
        from attack_agent.runtime import _resolve_browser_inspect_specs, PrimitiveAdapter, PrimitiveActionSpec
        metadata = {"browser_inspect": {"enabled": True}}
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="browser-inspect", instruction="inspect", parameters={})
        specs = _resolve_browser_inspect_specs(step, bundle)
        self.assertTrue(len(specs) > 0)

    def test_browser_inspect_improved_html_parser(self):
        html = "<html><head><title>Test</title></head><body>"
        html += "<form action='/login' method='POST'><input name='user'/><input name='pass' type='password'/></form>"
        html += "<a href='/page1'>Link1</a><a href='/page2'>Link2</a>"
        html += "<!-- flag{hidden_comment} --></body></html>"
        result = _parse_html_page(html, "http://test.com")
        self.assertEqual(result["title"], "Test")
        self.assertEqual(len(result["forms"]), 1)
        self.assertEqual(result["forms"][0]["method"], "POST")
        self.assertIn("user", result["forms"][0]["inputs"])
        self.assertEqual(len(result["links"]), 2)
        self.assertTrue(len(result["comments"]) > 0)


class BrowserInspectScriptsTests(unittest.TestCase):
    """Test _HTMLPageParser script extraction when extract_scripts=True."""

    def test_parse_html_page_extracts_script_src_when_enabled(self):
        html = "<html><head><script src='/app.js' type='text/javascript'></script></head><body>Hello</body></html>"
        result = _parse_html_page(html, "http://test.com", extract_scripts=True)
        self.assertEqual(len(result["scripts"]), 1)
        self.assertEqual(result["scripts"][0]["src"], "/app.js")
        self.assertEqual(result["scripts"][0]["type"], "text/javascript")

    def test_parse_html_page_extracts_inline_script_when_enabled(self):
        html = "<html><head><script>var x = 'flag{inline}';</script></head><body>Hello</body></html>"
        result = _parse_html_page(html, "http://test.com", extract_scripts=True)
        self.assertEqual(len(result["scripts"]), 1)
        self.assertIn("flag{inline}", result["scripts"][0]["inline"])

    def test_parse_html_page_no_scripts_by_default(self):
        html = "<html><head><script src='/app.js'></script></head><body>Hello</body></html>"
        result = _parse_html_page(html, "http://test.com")
        self.assertEqual(result["scripts"], [])

    def test_parse_html_page_scripts_do_not_pollute_rendered_text(self):
        html = "<html><head><script>alert('nope');</script></head><body>Visible text</body></html>"
        result = _parse_html_page(html, "http://test.com", extract_scripts=True)
        self.assertNotIn("nope", result["rendered_text"])
        self.assertIn("Visible text", result["rendered_text"])


class ArtifactScanHTTPDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_artifact_scan_zip_extraction(self):
        zip_path = Path(self.tmpdir.name) / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "flag{zip_content}")
            zf.writestr("config.json", json.dumps({"secret": "flag{zip_config}"}))
        metadata = {
            "artifact_scan": {
                "url": zip_path.as_uri(),
                "max_members": 20,
                "max_depth": 1,
            }
        }
        bundle = _make_bundle(target=zip_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(len(outcome.observations) > 0)
        payload = outcome.observations[0].payload
        self.assertIn("archive_members", payload)
        members = payload["archive_members"]
        self.assertTrue(len(members) >= 2)

    def test_artifact_scan_local_file(self):
        file_path = Path(self.tmpdir.name) / "test.txt"
        file_path.write_text("Hello flag{artifact_test}", encoding="utf-8")
        metadata = {
            "artifact_scan": {
                "url": file_path.as_uri(),
            }
        }
        bundle = _make_bundle(target=file_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        self.assertIn("text_preview", outcome.observations[0].payload)


class ArtifactScanEnhancedTests(unittest.TestCase):
    """Tests for R7: ZIP/tar content extraction, increased preview, content_type, deferred cleanup."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    # -- ZIP content extraction --

    def test_zip_content_preview(self):
        zip_path = Path(self.tmpdir.name) / "content.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "flag{zip_content_preview}")
            zf.writestr("config.json", '{"secret": "flag{zip_json_config}"}')
        metadata = {"artifact_scan": {"url": zip_path.as_uri()}}
        bundle = _make_bundle(target=zip_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        payload = outcome.observations[0].payload
        members = payload["archive_members"]
        readme_member = next(m for m in members if m["name"] == "readme.txt")
        self.assertIn("content_preview", readme_member)
        self.assertIn("flag{zip_content_preview}", readme_member["content_preview"])
        config_member = next(m for m in members if m["name"] == "config.json")
        self.assertIn("content_preview", config_member)
        self.assertIn("flag{zip_json_config}", config_member["content_preview"])

    def test_zip_content_type_guessing(self):
        zip_path = Path(self.tmpdir.name) / "types.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.json", '{"key": "value"}')
            zf.writestr("page.html", '<html><body>test</body></html>')
            zf.writestr("script.py", 'print("hello")')
        metadata = {"artifact_scan": {"url": zip_path.as_uri()}}
        bundle = _make_bundle(target=zip_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        payload = outcome.observations[0].payload
        members = payload["archive_members"]
        json_m = next(m for m in members if m["name"] == "data.json")
        self.assertEqual(json_m["content_type"], "application/json")
        html_m = next(m for m in members if m["name"] == "page.html")
        self.assertEqual(html_m["content_type"], "text/html")
        py_m = next(m for m in members if m["name"] == "script.py")
        self.assertEqual(py_m["content_type"], "text/x-python")

    def test_zip_binary_member_no_preview(self):
        zip_path = Path(self.tmpdir.name) / "mixed.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "plain text flag{mixed_zip}")
            # Write binary data (null bytes → no text preview)
            zf.writestr("binary.bin", b"\x00\x01\x02\x03flag\xff\xfe")
        metadata = {"artifact_scan": {"url": zip_path.as_uri()}}
        bundle = _make_bundle(target=zip_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        payload = outcome.observations[0].payload
        members = payload["archive_members"]
        text_m = next(m for m in members if m["name"] == "readme.txt")
        self.assertIn("content_preview", text_m)
        bin_m = next(m for m in members if m["name"] == "binary.bin")
        self.assertNotIn("content_preview", bin_m)

    # -- tar content extraction --

    def test_tar_content_preview(self):
        tar_path = Path(self.tmpdir.name) / "content.tar"
        with tarfile.open(tar_path, "w") as tf:
            info = tarfile.TarInfo(name="notes.txt")
            data = b"flag{tar_content_preview}"
            info.size = len(data)
            tf.addfile(info, __import__("io").BytesIO(data))
        metadata = {"artifact_scan": {"url": tar_path.as_uri()}}
        bundle = _make_bundle(target=tar_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        payload = outcome.observations[0].payload
        members = payload["archive_members"]
        notes_m = next(m for m in members if m["name"] == "notes.txt")
        self.assertIn("content_preview", notes_m)
        self.assertIn("flag{tar_content_preview}", notes_m["content_preview"])

    def test_targz_content_preview(self):
        targz_path = Path(self.tmpdir.name) / "content.tar.gz"
        with tarfile.open(targz_path, "w:gz") as tf:
            info = tarfile.TarInfo(name="secret.txt")
            data = b"flag{targz_content}"
            info.size = len(data)
            tf.addfile(info, __import__("io").BytesIO(data))
        metadata = {"artifact_scan": {"url": targz_path.as_uri()}}
        bundle = _make_bundle(target=targz_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        payload = outcome.observations[0].payload
        members = payload["archive_members"]
        secret_m = next(m for m in members if m["name"] == "secret.txt")
        self.assertIn("content_preview", secret_m)
        self.assertIn("flag{targz_content}", secret_m["content_preview"])

    # -- Increased preview size --

    def test_increased_preview_default_512(self):
        # Create a file longer than old 64-byte default but shorter than 512
        long_text = "A" * 300 + " flag{long_preview} " + "B" * 200
        file_path = Path(self.tmpdir.name) / "long.txt"
        file_path.write_text(long_text, encoding="utf-8")
        metadata = {"artifact_scan": {"url": file_path.as_uri()}}
        bundle = _make_bundle(target=file_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        preview = outcome.observations[0].payload["text_preview"]
        # Should contain flag that's at position ~300, well past old 64-byte limit
        self.assertIn("flag{long_preview}", preview)

    def test_preview_bytes_override(self):
        # Override preview_bytes to a specific value via step.parameters
        file_path = Path(self.tmpdir.name) / "override.txt"
        file_path.write_text("flag{short} " + "X" * 200, encoding="utf-8")
        metadata = {"artifact_scan": {"url": file_path.as_uri()}}
        bundle = _make_bundle(target=file_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={"preview_bytes": 15})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        preview = outcome.observations[0].payload["text_preview"]
        # With preview_bytes=15, "flag{short}" (10 chars) fits
        self.assertIn("flag{short}", preview)
        self.assertTrue(len(preview) <= 15)

    # -- content_type on main payload --

    def test_payload_content_type(self):
        file_path = Path(self.tmpdir.name) / "data.json"
        file_path.write_text('{"flag": "flag{json_file}"}', encoding="utf-8")
        metadata = {"artifact_scan": {"url": file_path.as_uri()}}
        bundle = _make_bundle(target=file_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        payload = outcome.observations[0].payload
        self.assertEqual(payload["content_type"], "application/json")

    # -- Backward compat: old tests still work --

    def test_backward_compat_zip_member_list(self):
        zip_path = Path(self.tmpdir.name) / "compat.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("a.txt", "hello")
            zf.writestr("b.txt", "world")
        metadata = {"artifact_scan": {"url": zip_path.as_uri()}}
        bundle = _make_bundle(target=zip_path.as_uri(), metadata=metadata)
        step = PrimitiveActionStep(primitive="artifact-scan", instruction="scan", parameters={})
        from attack_agent.runtime import _execute_artifact_scan
        outcome = _execute_artifact_scan(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        payload = outcome.observations[0].payload
        # Old keys still present
        for member in payload["archive_members"]:
            self.assertIn("name", member)
            self.assertIn("size_bytes", member)
            self.assertIn("content_type", member)  # new key


class BinaryInspectEnhancedTests(unittest.TestCase):
    def test_binary_inspect_utf8_strings(self):
        utf8_text = "Hello UTF8 \xe4\xb8\xad\xe6\x96\x87"
        raw = utf8_text.encode("utf-8") + b"\x00\x00\x00"
        strings = _extract_utf8_strings(raw, 4, 20)
        self.assertTrue(len(strings) > 0)

    def test_binary_inspect_wide_strings(self):
        wide_text = "Hello"
        raw = wide_text.encode("utf-16-le") + b"\x00\x00"
        strings = _extract_wide_strings(raw, 4, 20)
        self.assertTrue(len(strings) > 0)
        self.assertIn("Hello", strings)

    def test_binary_inspect_elf_header(self):
        elf_header = b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + b"\x02\x00" + b"\x00" * 20
        result = _parse_binary_headers(elf_header)
        self.assertIsNotNone(result)
        self.assertEqual(result["format"], "ELF")
        self.assertEqual(result["class"], "64-bit")

    def test_binary_inspect_pe_header(self):
        pe_data = bytearray(128)
        pe_data[0:2] = b"MZ"
        pe_offset = 64
        struct.pack_into("<I", pe_data, 60, pe_offset)
        pe_data[pe_offset:pe_offset+4] = b"PE\x00\x00"
        struct.pack_into("<H", pe_data, pe_offset+4, 0x8664)
        result = _parse_binary_headers(bytes(pe_data))
        self.assertIsNotNone(result)
        self.assertEqual(result["format"], "PE")
        self.assertEqual(result["machine"], "x86_64")

    def test_binary_inspect_not_a_binary(self):
        result = _parse_binary_headers(b"plain text data")
        self.assertIsNone(result)

    def test_binary_inspect_full_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.bin"
            content = b"\x7fELF\x01\x01\x01" + b"\x00" * 9 + b"\x03\x00" + b"\x00" * 20
            content += b"flag{binary_test}" + b"\x00\x00"
            content += "Hello Wide".encode("utf-16-le") + b"\x00\x00"
            file_path.write_bytes(content)
            metadata = {
                "binary_inspect": {
                    "url": file_path.as_uri(),
                    "min_length": 4,
                    "max_strings": 20,
                }
            }
            bundle = _make_bundle(target=file_path.as_uri(), metadata=metadata)
            step = PrimitiveActionStep(primitive="binary-inspect", instruction="inspect", parameters={})
            from attack_agent.runtime import _execute_binary_inspect
            outcome = _execute_binary_inspect(step, bundle)
            self.assertEqual(outcome.status, "ok")
            obs = outcome.observations[0]
            self.assertIn("encoding_types", obs.payload)
            self.assertIn("headers", obs.payload)
            self.assertEqual(obs.payload["headers"]["format"], "ELF")


class WorkerRuntimeSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _TestHTTPHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_run_task_creates_session_manager_and_populates_completed_observations(self):
        metadata = {
            "http_request": {"url": f"{self.base_url}/"},
            "primitive_payloads": {},
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        bundle.action_program.steps = [
            PrimitiveActionStep(primitive="http-request", instruction="get homepage",
                                parameters={"required_tags": []}),
        ]
        runtime = WorkerRuntime()
        events, outcome = runtime.run_task(bundle)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(len(bundle.completed_observations) > 0)

    def test_run_task_session_persistence_across_steps(self):
        metadata = {
            "http_request": [
                {"url": f"{self.base_url}/set-cookie"},
                {"url": f"{self.base_url}/secret"},
            ],
            "primitive_payloads": {},
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        bundle.action_program.steps = [
            PrimitiveActionStep(primitive="http-request", instruction="get cookie",
                                parameters={"required_tags": []}),
            PrimitiveActionStep(primitive="http-request", instruction="get secret",
                                parameters={"required_tags": []}),
        ]
        runtime = WorkerRuntime()
        events, outcome = runtime.run_task(bundle)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(len(outcome.observations) >= 2)


# ---- R6: session-materialize CSRF + JSON body test handlers ----

class _SessionTestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for session-materialize enhanced tests."""

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/csrf-login":
            self.send_response(200)
            self.send_header("Set-Cookie", "csrftoken=testcsrf123")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = (
                "<html><body>"
                "<form action='/csrf-login' method='POST'>"
                "<input type='hidden' name='csrfmiddlewaretoken' value='testcsrf123'/>"
                "<input name='username'/><input name='password' type='password'/>"
                "<input type='submit'/></form></body></html>"
            )
            self.wfile.write(html.encode("utf-8"))
        elif path == "/csrf-meta-login":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = (
                "<html><head><meta name='csrf-token' content='metatoken456'/></head>"
                "<body><form action='/csrf-meta-login' method='POST'>"
                "<input name='username'/><input name='password' type='password'/>"
                "<input type='submit'/></form></body></html>"
            )
            self.wfile.write(html.encode("utf-8"))
        elif path == "/csrf-header-login":
            self.send_response(200)
            self.send_header("X-CSRFToken", "headertoken789")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = "<html><body><form action='/csrf-header-login' method='POST'>"
            html += "<input name='username'/><input name='password' type='password'/>"
            html += "<input type='submit'/></form></body></html>"
            self.wfile.write(html.encode("utf-8"))
        elif path == "/api/login":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>API login endpoint</body></html>")
        elif path == "/auth-login":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Login form</body></html>")
        elif path == "/no-csrf-page":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>No CSRF here</body></html>")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/csrf-login":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = dict(parse.parse_qs(body).items())
            csrf_token = params.get("csrfmiddlewaretoken")
            username = params.get("username")
            password = params.get("password")
            if csrf_token == ["testcsrf123"] and username == ["admin"] and password == ["pass"]:
                self.send_response(200)
                self.send_header("Set-Cookie", "session=csrf_session_ok")
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>CSRF Login OK</body></html>")
            else:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"CSRF token missing or wrong")
        elif path == "/csrf-meta-login":
            csrf_header = self.headers.get("X-CSRFToken", "")
            if csrf_header == "metatoken456":
                self.send_response(200)
                self.send_header("Set-Cookie", "session=meta_session_ok")
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>Meta CSRF Login OK</body></html>")
            else:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"CSRF header missing")
        elif path == "/csrf-header-login":
            csrf_header = self.headers.get("X-CSRFToken", "")
            if csrf_header == "headertoken789":
                self.send_response(200)
                self.send_header("Set-Cookie", "session=header_session_ok")
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>Header CSRF Login OK</body></html>")
            else:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"CSRF header missing")
        elif path == "/api/login":
            content_type = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if "application/json" in content_type:
                try:
                    data = json.loads(body)
                    if data.get("username") == "admin" and data.get("password") == "pass":
                        self.send_response(200)
                        self.send_header("Authorization", "Bearer jwt_abc123")
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"token": "jwt_abc123", "user": "admin"}).encode())
                    else:
                        self.send_response(401)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "invalid credentials"}).encode())
                except json.JSONDecodeError:
                    self.send_response(400)
                    self.end_headers()
            else:
                self.send_response(400)
                self.end_headers()
        elif path == "/auth-login":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = dict(parse.parse_qs(body).items())
            if params.get("username") == ["admin"] and params.get("password") == ["pass"]:
                self.send_response(200)
                self.send_header("Authorization", "Bearer auth_test_token")
                self.send_header("Set-Cookie", "session=auth_ok")
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>Auth Login OK</body></html>")
            else:
                self.send_response(403)
                self.end_headers()
        elif path == "/json-form-login":
            content_type = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if "application/json" in content_type:
                try:
                    data = json.loads(body)
                    if data.get("username") == "admin" and data.get("password") == "pass":
                        self.send_response(200)
                        self.send_header("Set-Cookie", "session=json_form_ok")
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "ok"}).encode())
                    else:
                        self.send_response(403)
                        self.end_headers()
                except json.JSONDecodeError:
                    self.send_response(400)
                    self.end_headers()
            else:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class SessionMaterializeEnhancedTests(unittest.TestCase):
    """Tests for R6: CSRF prefetch + JSON body + auth token persistence."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _SessionTestHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_csrf_form_hidden(self):
        """CSRF token extracted from hidden input and injected into form POST."""
        from attack_agent.runtime import _execute_session_materialize, PrimitiveAdapter, PrimitiveActionSpec
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/csrf-login",
                "username": "admin",
                "password": "pass",
                "method": "POST",
                "csrf_token": True,
                "csrf_field": "csrfmiddlewaretoken",
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        outcome = _execute_session_materialize(step, bundle, session_mgr)
        self.assertEqual(outcome.status, "ok")
        obs = outcome.observations[0]
        self.assertEqual(obs.payload["status_code"], 200)
        self.assertTrue(obs.payload["csrf_prefetched"])
        self.assertEqual(obs.payload["csrf_token_value"], "testcsrf123")
        self.assertEqual(obs.payload["body_type"], "form")
        self.assertTrue(any("csrf_session_ok" in c for c in obs.payload["cookies_obtained"]))

    def test_csrf_meta_tag(self):
        """CSRF token extracted from <meta> tag and injected as X-CSRFToken header."""
        from attack_agent.runtime import _execute_session_materialize
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/csrf-meta-login",
                "username": "admin",
                "password": "pass",
                "method": "POST",
                "csrf_token": True,
                "csrf_source": "meta",
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        outcome = _execute_session_materialize(step, bundle, session_mgr)
        self.assertEqual(outcome.status, "ok")
        obs = outcome.observations[0]
        self.assertEqual(obs.payload["status_code"], 200)
        self.assertTrue(obs.payload["csrf_prefetched"])
        self.assertEqual(obs.payload["csrf_token_value"], "metatoken456")

    def test_csrf_response_header(self):
        """CSRF token extracted from GET response header."""
        from attack_agent.runtime import _execute_session_materialize
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/csrf-header-login",
                "username": "admin",
                "password": "pass",
                "method": "POST",
                "csrf_token": True,
                "csrf_source": "header",
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        outcome = _execute_session_materialize(step, bundle, session_mgr)
        self.assertEqual(outcome.status, "ok")
        obs = outcome.observations[0]
        self.assertEqual(obs.payload["status_code"], 200)
        self.assertTrue(obs.payload["csrf_prefetched"])
        self.assertEqual(obs.payload["csrf_token_value"], "headertoken789")

    def test_json_body_login(self):
        """JSON body login with token persistence."""
        from attack_agent.runtime import _execute_session_materialize
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/api/login",
                "method": "POST",
                "json": {"username": "admin", "password": "pass"},
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        outcome = _execute_session_materialize(step, bundle, session_mgr)
        self.assertEqual(outcome.status, "ok")
        obs = outcome.observations[0]
        self.assertEqual(obs.payload["status_code"], 200)
        self.assertEqual(obs.payload["body_type"], "json")
        # Token should be persisted in session_manager
        auth_headers = session_mgr.get_auth_headers()
        self.assertIn("Authorization", auth_headers)
        self.assertEqual(auth_headers["Authorization"], "Bearer jwt_abc123")

    def test_content_type_json_override(self):
        """form_fields serialized as JSON when content_type='application/json'."""
        from attack_agent.runtime import _execute_session_materialize
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/json-form-login",
                "method": "POST",
                "username": "admin",
                "password": "pass",
                "content_type": "application/json",
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        outcome = _execute_session_materialize(step, bundle, session_mgr)
        self.assertEqual(outcome.status, "ok")
        obs = outcome.observations[0]
        self.assertEqual(obs.payload["status_code"], 200)
        self.assertEqual(obs.payload["body_type"], "json")

    def test_auth_token_persistence(self):
        """Authorization header from response persisted to session_manager."""
        from attack_agent.runtime import _execute_session_materialize
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/auth-login",
                "username": "admin",
                "password": "pass",
                "method": "POST",
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        outcome = _execute_session_materialize(step, bundle, session_mgr)
        self.assertEqual(outcome.status, "ok")
        auth_headers = session_mgr.get_auth_headers()
        self.assertIn("Authorization", auth_headers)
        self.assertEqual(auth_headers["Authorization"], "Bearer auth_test_token")

    def test_csrf_not_found_proceeds(self):
        """CSRF prefetch on page with no CSRF token still proceeds."""
        from attack_agent.runtime import _execute_session_materialize
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/no-csrf-page",
                "username": "admin",
                "password": "pass",
                "method": "POST",
                "csrf_token": True,
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        outcome = _execute_session_materialize(step, bundle, session_mgr)
        # Should not crash — POST will likely 404 but the point is no crash
        self.assertNotEqual(outcome.status, None)
        obs = outcome.observations[0] if outcome.observations else None
        if obs:
            self.assertFalse(obs.payload["csrf_prefetched"])
            self.assertEqual(obs.payload["csrf_token_value"], "")

    def test_backward_compat_form_only(self):
        """Original form-only login still works unchanged."""
        from attack_agent.runtime import _execute_session_materialize, PrimitiveAdapter, PrimitiveActionSpec
        metadata = {
            "session_materialize": {
                "login_url": f"{self.base_url}/auth-login",
                "username": "admin",
                "password": "pass",
                "method": "POST",
            }
        }
        bundle = _make_bundle(target=self.base_url, metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="login",
                                    parameters={"required_tags": []})
        session_mgr = HttpSessionManager()
        outcome = _execute_session_materialize(step, bundle, session_mgr)
        self.assertEqual(outcome.status, "ok")
        obs = outcome.observations[0]
        self.assertEqual(obs.payload["status_code"], 200)
        self.assertEqual(obs.payload["body_type"], "form")
        self.assertFalse(obs.payload["csrf_prefetched"])


if __name__ == "__main__":
    unittest.main()