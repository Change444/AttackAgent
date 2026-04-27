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

    def test_session_materialize_fallback_to_metadata(self):
        metadata = {
            "primitive_payloads": {
                "session-materialize": [
                    {"type": "observation", "payload": {"session_type": "cookie"}, "confidence": 0.9}
                ]
            }
        }
        bundle = _make_bundle(metadata=metadata)
        step = PrimitiveActionStep(primitive="session-materialize", instruction="session", parameters={})
        from attack_agent.runtime import _execute_session_materialize
        outcome = _execute_session_materialize(step, bundle, None)
        self.assertEqual(outcome.status, "ok")
        self.assertTrue(len(outcome.observations) > 0)


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

    def test_structured_parse_fallback_to_metadata(self):
        metadata = {
            "primitive_payloads": {
                "structured-parse": [
                    {"type": "observation", "id": "sp-1", "payload": {"parsed": "data"}, "confidence": 0.9}
                ]
            }
        }
        bundle = _make_bundle(metadata=metadata)
        step = PrimitiveActionStep(primitive="structured-parse", instruction="parse",
                                    parameters={})
        from attack_agent.runtime import _execute_structured_parse
        outcome = _execute_structured_parse(step, bundle)
        self.assertEqual(outcome.status, "ok")

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

    def test_diff_compare_fallback_to_metadata(self):
        metadata = {
            "primitive_payloads": {
                "diff-compare": [
                    {"type": "observation", "payload": {"change_count": 3}, "confidence": 0.9}
                ]
            }
        }
        bundle = _make_bundle(metadata=metadata)
        step = PrimitiveActionStep(primitive="diff-compare", instruction="compare", parameters={})
        from attack_agent.runtime import _execute_diff_compare
        outcome = _execute_diff_compare(step, bundle)
        self.assertEqual(outcome.status, "ok")


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

    def test_disallowed_class_definition(self):
        sandbox = CodeSandbox()
        with self.assertRaises(RuntimeError):
            sandbox.execute("class Foo:\n    pass\nresult = {}", {})

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


if __name__ == "__main__":
    unittest.main()