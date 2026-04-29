from __future__ import annotations

import re
from urllib import error, parse, request
from typing import Any

from .config import BrowserConfig

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False
    _sync_playwright = None  # type: ignore[assignment]


def playwright_is_available() -> bool:
    """Check if Playwright Python SDK is installed."""
    return _HAS_PLAYWRIGHT


def build_browser_inspector_from_config(
    browser_config: BrowserConfig | None = None,
) -> StdlibBrowserInspector | PlaywrightBrowserInspector:
    """Factory: create browser inspector from config.

    engine="auto" → Playwright if available, stdlib otherwise.
    engine="stdlib" → always stdlib.
    engine="playwright" → Playwright; raises ImportError if not installed.
    """
    config = browser_config or BrowserConfig()
    if config.engine == "stdlib":
        return StdlibBrowserInspector(config)
    if config.engine == "playwright":
        if not _HAS_PLAYWRIGHT:
            raise ImportError(
                "playwright package not installed; run: pip install attack-agent[browser]"
            )
        return PlaywrightBrowserInspector(config)
    # engine == "auto"
    if _HAS_PLAYWRIGHT:
        return PlaywrightBrowserInspector(config)
    return StdlibBrowserInspector(config)


class StdlibBrowserInspector:
    """stdlib fallback: urllib GET + HTMLParser, no JS execution."""

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig(engine="stdlib")
        self._extract_scripts = self._config.extract_scripts

    def inspect_page(
        self,
        spec: dict[str, object],
        default_target: str,
        session_manager: Any | None = None,
    ) -> dict[str, object]:
        """Inspect a page via urllib — same as legacy _perform_browser_inspect."""
        from .runtime import _perform_browser_inspect as _stdlib_perform

        result = _stdlib_perform(spec, default_target, session_manager, extract_scripts=self._extract_scripts)
        # Ensure new fields are present (stdlib cannot fill them meaningfully)
        result.setdefault("scripts", [])
        result.setdefault("js_rendered_text", "")
        result.setdefault("console_messages", [])
        result.setdefault("cookies", [])
        return result

    def close(self) -> None:
        """No-op: stdlib has no persistent resources."""


class PlaywrightBrowserInspector:
    """Playwright-backed browser inspector with JS rendering + script extraction."""

    def __init__(self, config: BrowserConfig | None = None) -> None:
        assert _HAS_PLAYWRIGHT
        self._config = config or BrowserConfig()
        self._pw_manager: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._launch_failed: bool = False

    def _ensure_browser(self) -> None:
        """Lazy browser launch — called on first inspect_page."""
        if self._browser is not None:
            return
        if self._launch_failed:
            return
        try:
            self._pw_manager = _sync_playwright().start()
            launchers = {
                "chromium": self._pw_manager.chromium,
                "firefox": self._pw_manager.firefox,
                "webkit": self._pw_manager.webkit,
            }
            launcher = launchers.get(self._config.browser_type, self._pw_manager.chromium)
            self._browser = launcher.launch(headless=self._config.headless)
            self._context = self._browser.new_context()
        except Exception:
            self._launch_failed = True

    def inspect_page(
        self,
        spec: dict[str, object],
        default_target: str,
        session_manager: Any | None = None,
    ) -> dict[str, object]:
        """Inspect a page via Playwright — JS rendering + script extraction."""
        self._ensure_browser()
        if self._launch_failed or self._browser is None:
            # Browser launch failed — delegate to stdlib
            stdlib = StdlibBrowserInspector(self._config)
            return stdlib.inspect_page(spec, default_target, session_manager)

        base_url = str(spec.get("url") or default_target)
        path = str(spec.get("path", "") or "")
        if path:
            final_url = parse.urljoin(
                base_url if base_url.endswith("/") else f"{base_url}/",
                path.lstrip("/"),
            )
        else:
            final_url = base_url

        extra_headers = dict(spec.get("headers", {}) or {})
        if extra_headers:
            self._context.set_extra_http_headers(extra_headers)

        page = self._context.new_page()
        console_messages: list[str] = []
        page.on("console", lambda msg: console_messages.append(f"{msg.type}: {msg.text}"))

        try:
            response = page.goto(
                final_url,
                timeout=self._config.timeout_seconds * 1000,
                wait_until="domcontentloaded",
            )

            if self._config.wait_for_selector:
                page.wait_for_selector(
                    self._config.wait_for_selector,
                    timeout=self._config.timeout_seconds * 1000,
                )
            # Give JS a moment to finish rendering
            page.wait_for_timeout(500)
        except Exception as exc:
            page.close()
            # Re-raise as URLError for compatibility with _execute_browser_inspect
            raise error.URLError(str(exc))

        status_code = response.status if response else 0
        headers = response.headers if response else {}
        title = page.title()

        # JS-rendered text (text after JavaScript execution)
        js_rendered_text = ""
        try:
            js_rendered_text = page.evaluate("document.body?.innerText || ''") or ""
        except Exception:
            pass

        # Static rendered text (from raw HTML, for backward compat)
        raw_html = page.content()
        from .runtime import _parse_html_page
        parsed = _parse_html_page(
            raw_html, final_url, extract_scripts=self._config.extract_scripts
        )

        # Comments from rendered DOM (may differ from static HTML)
        comments_js: list[str] = []
        try:
            comments_js = page.evaluate(
                "() => Array.from(document.querySelectorAll('*'))"
                ".flatMap(el => Array.from(el.childNodes)"
                ".filter(n => n.nodeType === 8)"
                ".map(n => n.textContent))"
            )
        except Exception:
            comments_js = parsed["comments"]

        # Rendered nodes
        rendered_nodes: list[str] = []
        try:
            rendered_nodes = page.evaluate(
                "() => Array.from(document.querySelectorAll('main, section, article, div[id]'))"
                ".map(el => el.tagName.toLowerCase() + '#' + el.id)"
            )
        except Exception:
            rendered_nodes = parsed["nodes"]

        # Links (from rendered DOM)
        links: list[dict[str, str]] = []
        try:
            links = page.evaluate(
                "() => Array.from(document.querySelectorAll('a[href]'))"
                ".map(a => ({path: new URL(a.href).pathname || '/', "
                "url: a.href, text: (a.textContent || '').trim()}))"
            )
        except Exception:
            links = parsed["links"]

        # Forms (from rendered DOM)
        forms: list[dict[str, object]] = []
        try:
            forms = page.evaluate(
                "() => Array.from(document.querySelectorAll('form'))"
                ".map((f, i) => ({id: 'form-' + i, "
                "action: f.action, method: (f.method || 'GET').toUpperCase(), "
                "inputs: Array.from(f.querySelectorAll('input[name]')).map(i => i.name)}))"
            )
        except Exception:
            forms = parsed["forms"]

        # Scripts — the critical new extraction
        scripts: list[dict[str, str]] = []
        if self._config.extract_scripts:
            try:
                scripts = page.evaluate(
                    "() => Array.from(document.querySelectorAll('script'))"
                    ".map(s => ({src: s.src || '', inline: s.textContent || '', type: s.type || ''}))"
                )
            except Exception:
                scripts = parsed.get("scripts", [])

        # Cookies from browser context
        cookies: list[dict[str, str]] = []
        try:
            raw_cookies = self._context.cookies()
            for c in raw_cookies:
                cookies.append({
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ""),
                    "path": c.get("path", ""),
                })
        except Exception:
            pass

        page.close()

        return {
            "url": final_url,
            "status_code": status_code,
            "headers": headers,
            "title": title,
            "rendered_text": parsed["rendered_text"],
            "comments": comments_js if comments_js else parsed["comments"],
            "rendered_nodes": rendered_nodes if rendered_nodes else parsed["nodes"],
            "links": links if links else parsed["links"],
            "forms": forms if forms else parsed["forms"],
            "content_type": headers.get("content-type", ""),
            "response_bytes": len(raw_html.encode("utf-8", errors="replace")),
            "scripts": scripts,
            "js_rendered_text": js_rendered_text,
            "console_messages": console_messages,
            "cookies": cookies,
        }

    def close(self) -> None:
        """Close browser and stop Playwright manager."""
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw_manager is not None:
            try:
                self._pw_manager.stop()
            except Exception:
                pass
            self._pw_manager = None