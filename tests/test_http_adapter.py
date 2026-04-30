"""Tests for http_adapter module: StdlibHttpClient, RequestsHttpClient, factory, HttpSessionManager auth."""
from __future__ import annotations

import base64
import http.server
import json
import threading
import unittest
from unittest.mock import patch
from urllib import parse

from attack_agent.http_adapter import (
    _HAS_REQUESTS,
    StdlibHttpClient,
    RequestsHttpClient,
    build_http_client_from_config,
    requests_is_available,
)
from attack_agent.config import HttpConfig
from attack_agent.runtime import HttpSessionManager


class TestRequestsAvailability(unittest.TestCase):
    def test_requests_is_available_returns_bool(self):
        result = requests_is_available()
        self.assertIsInstance(result, bool)

    def test_has_requests_sentinel_exists(self):
        self.assertIsInstance(_HAS_REQUESTS, bool)


class TestBuildHttpClientFromConfig(unittest.TestCase):
    def test_stdlib_engine_always_returns_stdlib(self):
        config = HttpConfig(engine="stdlib")
        client = build_http_client_from_config(config)
        self.assertIsInstance(client, StdlibHttpClient)

    def test_auto_engine_returns_stdlib_when_no_requests(self):
        with patch("attack_agent.http_adapter._HAS_REQUESTS", False):
            config = HttpConfig(engine="auto")
            client = build_http_client_from_config(config)
            self.assertIsInstance(client, StdlibHttpClient)

    def test_auto_engine_returns_requests_when_available(self):
        if not _HAS_REQUESTS:
            self.skipTest("requests not installed")
        config = HttpConfig(engine="auto")
        client = build_http_client_from_config(config)
        self.assertIsInstance(client, RequestsHttpClient)

    def test_requests_engine_raises_when_not_installed(self):
        with patch("attack_agent.http_adapter._HAS_REQUESTS", False):
            config = HttpConfig(engine="requests")
            with self.assertRaises(ImportError):
                build_http_client_from_config(config)

    def test_default_config_creates_client(self):
        client = build_http_client_from_config()
        self.assertTrue(
            isinstance(client, (StdlibHttpClient, RequestsHttpClient))
        )


class TestStdlibHttpClient(unittest.TestCase):
    """Tests for the stdlib fallback path."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TestHTTPHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_get_request_returns_all_keys(self):
        session_mgr = HttpSessionManager()
        client = StdlibHttpClient(HttpConfig(engine="stdlib"))
        spec = {"url": f"{self.base_url}/"}
        result = client.perform_request(spec, self.base_url, session_mgr)
        expected_keys = [
            "url", "method", "status_code", "headers", "text", "cookies",
            "endpoints", "forms", "auth_clues", "services",
            "content_type", "response_bytes",
            "auth_used", "ssl_verified", "uploaded_files",
        ]
        for key in expected_keys:
            self.assertIn(key, result, f"missing key: {key}")
        self.assertEqual(result["auth_used"], "none")
        self.assertEqual(result["ssl_verified"], True)
        self.assertEqual(result["uploaded_files"], [])
        client.close()

    def test_post_form_data(self):
        session_mgr = HttpSessionManager()
        client = StdlibHttpClient(HttpConfig(engine="stdlib"))
        spec = {
            "url": f"{self.base_url}/login",
            "method": "POST",
            "form": {"username": "admin", "password": "pass"},
        }
        result = client.perform_request(spec, self.base_url, session_mgr)
        self.assertEqual(result["status_code"], 200)
        client.close()

    def test_auth_headers_injection_from_session_manager(self):
        session_mgr = HttpSessionManager()
        session_mgr.add_auth_header("Authorization", "Bearer test-token")
        client = StdlibHttpClient(HttpConfig(engine="stdlib"))
        spec = {"url": f"{self.base_url}/secret"}
        result = client.perform_request(spec, self.base_url, session_mgr)
        # Stdlib injects auth headers into urllib Request — no way to verify server received them
        # with this simple handler, but the key point is that no error occurs
        self.assertIn("auth_used", result)
        client.close()

    def test_close_is_noop(self):
        client = StdlibHttpClient()
        client.close()  # should not raise


class TestHttpSessionManagerAuth(unittest.TestCase):
    def test_add_and_get_auth_headers(self):
        mgr = HttpSessionManager()
        mgr.add_auth_header("Authorization", "Bearer abc123")
        headers = mgr.get_auth_headers()
        self.assertEqual(headers["Authorization"], "Bearer abc123")

    def test_auth_headers_default_empty(self):
        mgr = HttpSessionManager()
        self.assertEqual(mgr.get_auth_headers(), {})

    def test_auth_headers_overwrite(self):
        mgr = HttpSessionManager()
        mgr.add_auth_header("Authorization", "Bearer old")
        mgr.add_auth_header("Authorization", "Bearer new")
        self.assertEqual(mgr.get_auth_headers()["Authorization"], "Bearer new")


@unittest.skipUnless(_HAS_REQUESTS, "requests not installed")
class TestRequestsHttpClient(unittest.TestCase):
    """Tests for the requests-backed HTTP client."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TestHTTPHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_get_request(self):
        client = RequestsHttpClient(HttpConfig(engine="requests"))
        spec = {"url": f"{self.base_url}/"}
        result = client.perform_request(spec, self.base_url)
        self.assertEqual(result["status_code"], 200)
        self.assertIn("auth_used", result)
        self.assertEqual(result["auth_used"], "none")
        client.close()

    def test_post_form_data(self):
        client = RequestsHttpClient(HttpConfig(engine="requests"))
        spec = {
            "url": f"{self.base_url}/login",
            "method": "POST",
            "form": {"username": "admin", "password": "pass"},
        }
        result = client.perform_request(spec, self.base_url)
        self.assertEqual(result["status_code"], 200)
        client.close()

    def test_basic_auth(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BasicAuthHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            client = RequestsHttpClient(HttpConfig(engine="requests"))
            spec = {
                "url": f"http://127.0.0.1:{port}/",
                "auth": {"username": "admin", "password": "pass"},
                "auth_type": "basic",
            }
            result = client.perform_request(spec, f"http://127.0.0.1:{port}/")
            self.assertEqual(result["auth_used"], "basic")
            self.assertEqual(result["status_code"], 200)
            self.assertIn("flag{basic_auth}", result["text"])
            client.close()
        finally:
            server.shutdown()

    def test_bearer_auth(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BearerAuthHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            client = RequestsHttpClient(HttpConfig(engine="requests"))
            spec = {
                "url": f"http://127.0.0.1:{port}/",
                "auth_token": "test-bearer-token",
            }
            result = client.perform_request(spec, f"http://127.0.0.1:{port}/")
            self.assertEqual(result["auth_used"], "bearer")
            self.assertEqual(result["status_code"], 200)
            client.close()
        finally:
            server.shutdown()

    def test_multipart_file_upload(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _UploadHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            client = RequestsHttpClient(HttpConfig(engine="requests"))
            spec = {
                "url": f"http://127.0.0.1:{port}/upload",
                "method": "POST",
                "files": {"upload": {"filename": "test.txt", "content": "flag{upload_content}", "content_type": "text/plain"}},
            }
            result = client.perform_request(spec, f"http://127.0.0.1:{port}/")
            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["uploaded_files"], ["upload"])
            client.close()
        finally:
            server.shutdown()

    def test_close_cleans_up(self):
        client = RequestsHttpClient(HttpConfig(engine="requests"))
        client.close()
        self.assertIsNone(client._session)


# ---- Test HTTP handlers ----

class _TestHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Serves pages for general HTTP tests: GET, POST form, JSON."""
    pages = {
        "/": "<html><head><title>Test Page</title></head><body><h1>Hello</h1>"
             "<a href='/secret'>Secret</a></body></html>",
        "/login": "<html><body>Login success</body></html>",
        "/secret": "<html><body>flag{secret_page}</body></html>",
        "/json": json.dumps({"users": [{"name": "admin"}]}),
    }

    def do_GET(self):
        path = self.path if self.path == "/" else self.path.rstrip("/")
        if path in self.pages:
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
        path = self.path if self.path == "/" else self.path.rstrip("/")
        if path == "/login":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = dict(parse.parse_qs(body).items())
            if params.get("username") == ["admin"] and params.get("password") == ["pass"]:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>Login OK</body></html>")
            else:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Login failed")
        elif path == "/json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "posted"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class _BasicAuthHandler(http.server.BaseHTTPRequestHandler):
    """Requires Basic Auth with admin:pass."""

    def do_GET(self):
        auth_header = self.headers.get("Authorization", "")
        expected = "Basic " + base64.b64encode(b"admin:pass").decode()
        if auth_header == expected:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"flag{basic_auth}")
        else:
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Basic realm=\"test\"")
            self.end_headers()

    def log_message(self, format, *args):
        pass


class _BearerAuthHandler(http.server.BaseHTTPRequestHandler):
    """Requires Bearer token 'test-bearer-token'."""

    def do_GET(self):
        auth_header = self.headers.get("Authorization", "")
        if auth_header == "Bearer test-bearer-token":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"flag{bearer_auth}")
        else:
            self.send_response(401)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class _UploadHandler(http.server.BaseHTTPRequestHandler):
    """Accepts multipart file upload."""

    def do_POST(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" in content_type:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"uploaded": True, "size": length}).encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    unittest.main()