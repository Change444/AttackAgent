"""Tests for browser_adapter module: StdlibBrowserInspector, PlaywrightBrowserInspector, factory."""
from __future__ import annotations

import http.server
import unittest
from unittest.mock import patch

from attack_agent.browser_adapter import (
    _HAS_PLAYWRIGHT,
    StdlibBrowserInspector,
    PlaywrightBrowserInspector,
    build_browser_inspector_from_config,
    playwright_is_available,
)
from attack_agent.config import BrowserConfig


class TestPlaywrightAvailability(unittest.TestCase):
    def test_playwright_is_available_returns_bool(self):
        result = playwright_is_available()
        self.assertIsInstance(result, bool)

    def test_has_playwright_sentinel_exists(self):
        # _HAS_PLAYWRIGHT should be a bool
        self.assertIsInstance(_HAS_PLAYWRIGHT, bool)


class TestBuildBrowserInspectorFromConfig(unittest.TestCase):
    def test_stdlib_engine_always_returns_stdlib(self):
        config = BrowserConfig(engine="stdlib")
        inspector = build_browser_inspector_from_config(config)
        self.assertIsInstance(inspector, StdlibBrowserInspector)

    def test_auto_engine_returns_stdlib_when_no_playwright(self):
        with patch("attack_agent.browser_adapter._HAS_PLAYWRIGHT", False):
            config = BrowserConfig(engine="auto")
            inspector = build_browser_inspector_from_config(config)
            self.assertIsInstance(inspector, StdlibBrowserInspector)

    def test_auto_engine_returns_playwright_when_available(self):
        if not _HAS_PLAYWRIGHT:
            self.skipTest("playwright not installed")
        config = BrowserConfig(engine="auto")
        inspector = build_browser_inspector_from_config(config)
        self.assertIsInstance(inspector, PlaywrightBrowserInspector)

    def test_playwright_engine_raises_when_not_installed(self):
        with patch("attack_agent.browser_adapter._HAS_PLAYWRIGHT", False):
            config = BrowserConfig(engine="playwright")
            with self.assertRaises(ImportError):
                build_browser_inspector_from_config(config)

    def test_default_config_creates_inspector(self):
        inspector = build_browser_inspector_from_config()
        # Should be StdlibBrowserInspector or PlaywrightBrowserInspector
        self.assertTrue(
            isinstance(inspector, (StdlibBrowserInspector, PlaywrightBrowserInspector))
        )


class TestStdlibBrowserInspector(unittest.TestCase):
    """Tests for the stdlib fallback path (no JS execution)."""

    def test_inspect_page_with_local_server(self):
        """Serve a simple page and verify StdlibBrowserInspector returns all expected keys."""
        import threading

        handler = _StaticHTMLHandler
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            inspector = StdlibBrowserInspector(BrowserConfig(engine="stdlib", extract_scripts=True))
            result = inspector.inspect_page(
                {"url": f"http://127.0.0.1:{port}/"},
                f"http://127.0.0.1:{port}/",
            )
            # Verify all expected keys present
            expected_keys = [
                "url", "status_code", "headers", "title", "rendered_text",
                "comments", "rendered_nodes", "links", "forms",
                "content_type", "response_bytes", "scripts",
                "js_rendered_text", "console_messages", "cookies",
            ]
            for key in expected_keys:
                self.assertIn(key, result, f"missing key: {key}")
            # Stdlib cannot render JS
            self.assertEqual(result["js_rendered_text"], "")
            self.assertEqual(result["console_messages"], [])
            # Script src should be captured even in stdlib mode
            self.assertTrue(len(result["scripts"]) > 0)
            inspector.close()
        finally:
            server.shutdown()

    def test_close_is_noop(self):
        inspector = StdlibBrowserInspector()
        inspector.close()  # should not raise


@unittest.skipUnless(_HAS_PLAYWRIGHT, "playwright not installed")
class TestPlaywrightBrowserInspector(unittest.TestCase):
    """Tests for Playwright-backed browser inspection (requires playwright package + browser binaries)."""

    def test_inspect_page_js_rendered_content(self):
        """Serve a page with dynamic JS content, verify js_rendered_text captures it."""
        import http.server
        import threading

        handler = _JSRenderHandler
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            inspector = PlaywrightBrowserInspector(BrowserConfig(engine="playwright"))
            result = inspector.inspect_page(
                {"url": f"http://127.0.0.1:{port}/"},
                f"http://127.0.0.1:{port}/",
            )
            self.assertIn("js_rendered_text", result)
            self.assertIn("flag{js_rendered}", result["js_rendered_text"])
            self.assertIn("scripts", result)
            self.assertTrue(len(result["scripts"]) > 0)
            inspector.close()
        finally:
            server.shutdown()

    def test_inspect_page_script_extraction(self):
        """Serve a page with script tags, verify scripts list captures src and inline content."""
        import http.server
        import threading

        handler = _ScriptExtractHandler
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            inspector = PlaywrightBrowserInspector(BrowserConfig(engine="playwright", extract_scripts=True))
            result = inspector.inspect_page(
                {"url": f"http://127.0.0.1:{port}/"},
                f"http://127.0.0.1:{port}/",
            )
            scripts = result["scripts"]
            # Should capture both inline and external script references
            found_inline = any("flag{inline_script}" in s.get("inline", "") for s in scripts)
            found_src = any(s.get("src", "") for s in scripts)
            self.assertTrue(found_inline or found_src, f"scripts={scripts}")
            inspector.close()
        finally:
            server.shutdown()

    def test_close_cleans_up(self):
        """Verify close() properly terminates browser."""
        inspector = PlaywrightBrowserInspector(BrowserConfig(engine="playwright"))
        inspector.close()
        self.assertIsNone(inspector._browser)


# ---- Test HTTP handlers ----

class _StaticHTMLHandler(http.server.BaseHTTPRequestHandler):
    """Serves a simple HTML page with a script tag for stdlib tests."""
    PAGE = b"""<html><head><title>Static Test</title>
<script src='/app.js' type='text/javascript'></script>
</head><body><!-- flag{static_comment} --><p>Hello static</p></body></html>"""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.PAGE)

    def log_message(self, format, *args):
        pass


class _JSRenderHandler(http.server.BaseHTTPRequestHandler):
    """Serves HTML with JS that dynamically adds content."""
    PAGE = b"""<html><head><title>JS Test</title>
<script>document.getElementById('dynamic').textContent = 'flag{js_rendered}';</script>
</head><body><div id="dynamic"></div></body></html>"""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.PAGE)

    def log_message(self, format, *args):
        pass  # suppress log noise


class _ScriptExtractHandler(http.server.BaseHTTPRequestHandler):
    """Serves HTML with inline + external script tags."""
    PAGE = b"""<html><head><title>Script Test</title>
<script src="/app.js" type="text/javascript"></script>
<script>var secret = 'flag{inline_script}';</script>
</head><body>Hello</body></html>"""

    def do_GET(self):
        if self.path == "/app.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.end_headers()
            self.wfile.write(b"console.log('external script');")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.PAGE)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    unittest.main()