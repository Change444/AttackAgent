from __future__ import annotations

import io
import json
from pathlib import Path
from urllib import error, parse, request
from typing import Any

from .config import HttpConfig

try:
    import requests as _requests_module
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False
    _requests_module = None  # type: ignore[assignment]


def requests_is_available() -> bool:
    """Check if requests package is installed."""
    return _HAS_REQUESTS


def build_http_client_from_config(
    http_config: HttpConfig | None = None,
) -> StdlibHttpClient | RequestsHttpClient:
    """Factory: create HTTP client from config.

    engine="auto" -> Requests if available, stdlib otherwise.
    engine="stdlib" -> always stdlib.
    engine="requests" -> Requests; raises ImportError if not installed.
    """
    config = http_config or HttpConfig()
    if config.engine == "stdlib":
        return StdlibHttpClient(config)
    if config.engine == "requests":
        if not _HAS_REQUESTS:
            raise ImportError(
                "requests package not installed; run: pip install attack-agent[http]"
            )
        return RequestsHttpClient(config)
    # engine == "auto"
    if _HAS_REQUESTS:
        return RequestsHttpClient(config)
    return StdlibHttpClient(config)


class StdlibHttpClient:
    """stdlib fallback: urllib.request, no multipart/Basic Auth/SSL bypass."""

    def __init__(self, config: HttpConfig | None = None) -> None:
        self._config = config or HttpConfig(engine="stdlib")

    def perform_request(
        self,
        spec: dict[str, object],
        default_target: str,
        session_manager: Any | None = None,
    ) -> dict[str, object]:
        """Execute HTTP request via urllib — same logic as legacy _perform_http_request."""
        from .runtime import (
            _encode_http_request_body,
            _extract_auth_clues,
            _extract_cookies,
            _extract_endpoints,
            _extract_forms,
            _infer_http_encoding,
        )

        base_url = str(spec.get("url") or default_target)
        path = str(spec.get("path", "") or "")
        final_url = parse.urljoin(
            base_url if base_url.endswith("/") else f"{base_url}/",
            path.lstrip("/"),
        ) if path else base_url
        query = spec.get("query")
        if isinstance(query, dict) and query:
            encoded_query = parse.urlencode({str(key): str(value) for key, value in query.items()})
            separator = "&" if parse.urlparse(final_url).query else "?"
            final_url = f"{final_url}{separator}{encoded_query}"
        method = str(spec.get("method", "GET")).upper()
        body = _encode_http_request_body(spec)
        req = request.Request(final_url, data=body, method=method)
        for key, value in dict(spec.get("headers", {}) or {}).items():
            req.add_header(str(key), str(value))
        # Inject auth headers from session_manager
        if session_manager is not None and hasattr(session_manager, "get_auth_headers"):
            for name, value in session_manager.get_auth_headers().items():
                if not req.has_header(name):
                    req.add_header(name, value)
        if body is not None:
            if "json" in spec and not req.has_header("Content-Type"):
                req.add_header("Content-Type", "application/json")
            if "form" in spec and not req.has_header("Content-Type"):
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
        timeout = float(spec.get("timeout") or self._config.timeout_seconds)
        opener = session_manager.build_opener() if session_manager else request.build_opener(request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            with opener.open(req, timeout=timeout) as response:
                status_code = int(response.status)
                raw_body = response.read()
                headers = dict(response.headers.items())
        except error.HTTPError as exc:
            status_code = int(exc.code)
            raw_body = exc.read()
            headers = dict(exc.headers.items())
        encoding = _infer_http_encoding(headers, raw_body)
        text = raw_body.decode(encoding, errors="replace")
        cookies = _extract_cookies(headers)
        if session_manager:
            jar_cookies = session_manager.get_cookies_text()
            seen = set(cookies)
            for jc in jar_cookies:
                if jc not in seen:
                    cookies.append(jc)
                    seen.add(jc)
        parsed_url = parse.urlparse(final_url)
        return {
            "url": final_url,
            "method": method,
            "status_code": status_code,
            "headers": headers,
            "text": text,
            "cookies": cookies,
            "endpoints": _extract_endpoints(text, final_url),
            "forms": _extract_forms(text, final_url),
            "auth_clues": _extract_auth_clues(text, headers, final_url),
            "services": [{"name": parsed_url.scheme or "http", "port": parsed_url.port or (443 if parsed_url.scheme == "https" else 80)}],
            "content_type": headers.get("Content-Type", ""),
            "response_bytes": len(raw_body),
            "auth_used": "none",
            "ssl_verified": True,
            "uploaded_files": [],
        }

    def close(self) -> None:
        """No-op: stdlib has no persistent resources."""


class RequestsHttpClient:
    """requests-backed HTTP client: multipart, Basic Auth, Bearer Auth, SSL bypass."""

    def __init__(self, config: HttpConfig | None = None) -> None:
        assert _HAS_REQUESTS
        self._config = config or HttpConfig()
        self._session: Any = None

    def _ensure_session(self, session_manager: Any | None = None) -> Any:
        """Lazy-init requests.Session, seeded from HttpSessionManager."""
        if self._session is not None:
            return self._session
        import requests
        self._session = requests.Session()
        self._session.max_redirects = self._config.max_redirects
        if session_manager is not None:
            for cookie in session_manager.cookie_jar:
                self._session.cookies.set(cookie.name, cookie.value, domain=cookie.domain)
            if hasattr(session_manager, "get_auth_headers"):
                for name, value in session_manager.get_auth_headers().items():
                    self._session.headers[name] = value
        return self._session

    def perform_request(
        self,
        spec: dict[str, object],
        default_target: str,
        session_manager: Any | None = None,
    ) -> dict[str, object]:
        """Execute HTTP request via requests library with full capability."""
        import requests as req_lib

        sess = self._ensure_session(session_manager)

        base_url = str(spec.get("url") or default_target)
        path = str(spec.get("path", "") or "")
        final_url = parse.urljoin(
            base_url if base_url.endswith("/") else f"{base_url}/",
            path.lstrip("/"),
        ) if path else base_url
        query = spec.get("query")
        params = {str(k): str(v) for k, v in query.items()} if isinstance(query, dict) and query else {}
        method = str(spec.get("method", "GET")).upper()

        # Auth handling
        auth_used = "none"
        auth_tuple = None
        auth_info = spec.get("auth")
        auth_type = str(spec.get("auth_type", "basic")).lower()
        auth_token = spec.get("auth_token")
        if isinstance(auth_info, dict) and auth_info:
            username = str(auth_info.get("username", ""))
            password = str(auth_info.get("password", ""))
            if username and password and auth_type == "basic":
                auth_tuple = (username, password)
                auth_used = "basic"
            elif auth_type == "bearer":
                token = username if username else str(auth_info.get("token", ""))
                if token:
                    sess.headers["Authorization"] = f"Bearer {token}"
                    auth_used = "bearer"
        elif auth_token:
            sess.headers["Authorization"] = f"Bearer {str(auth_token)}"
            auth_used = "bearer"

        # Inject persisted auth headers from session_manager
        if session_manager is not None and hasattr(session_manager, "get_auth_headers"):
            for name, value in session_manager.get_auth_headers().items():
                if name not in sess.headers:
                    sess.headers[name] = value

        # Headers from spec — skip values that can't be encoded as latin-1
        # (HTTP headers must be latin-1 per RFC 7230; LLM may generate non-ASCII)
        extra_headers = dict(spec.get("headers", {}) or {})
        for k, v in extra_headers.items():
            try:
                str(v).encode("latin-1")
                sess.headers[str(k)] = str(v)
            except UnicodeEncodeError:
                pass

        # Body handling
        json_payload = spec.get("json")
        form_payload = spec.get("form")
        raw_body = spec.get("body")
        files_payload = spec.get("files")

        verify_ssl = self._config.verify_ssl
        if "verify_ssl" in spec:
            verify_ssl = bool(spec["verify_ssl"])

        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": final_url,
            "params": params,
            "timeout": float(spec.get("timeout") or self._config.timeout_seconds),
            "auth": auth_tuple,
            "verify": verify_ssl,
            "allow_redirects": True,
        }

        uploaded_files: list[str] = []

        # Multipart file upload
        if isinstance(files_payload, dict) and files_payload:
            prepared_files: dict[str, Any] = {}
            for field_name, file_spec in files_payload.items():
                if isinstance(file_spec, str):
                    file_path = Path(file_spec)
                    if file_path.exists():
                        prepared_files[field_name] = (
                            file_path.name,
                            file_path.open("rb"),
                            "application/octet-stream",
                        )
                    else:
                        prepared_files[field_name] = (
                            field_name,
                            io.BytesIO(file_spec.encode("utf-8")),
                            "application/octet-stream",
                        )
                elif isinstance(file_spec, dict):
                    filename = str(file_spec.get("filename", field_name))
                    content = file_spec.get("content", "")
                    if isinstance(content, str):
                        content = content.encode("utf-8")
                    content_type = str(file_spec.get("content_type", "application/octet-stream"))
                    prepared_files[field_name] = (filename, io.BytesIO(content), content_type)
                elif isinstance(file_spec, bytes):
                    prepared_files[field_name] = (field_name, io.BytesIO(file_spec), "application/octet-stream")
                uploaded_files.append(str(field_name))
            request_kwargs["files"] = prepared_files
            if isinstance(form_payload, dict) and form_payload:
                request_kwargs["data"] = {str(k): str(v) for k, v in form_payload.items()}
        elif json_payload is not None:
            request_kwargs["json"] = json_payload
        elif isinstance(form_payload, dict) and form_payload:
            request_kwargs["data"] = {str(k): str(v) for k, v in form_payload.items()}
        elif raw_body is not None:
            if isinstance(raw_body, bytes):
                request_kwargs["data"] = raw_body
            elif isinstance(raw_body, str):
                request_kwargs["data"] = raw_body.encode("utf-8")
            else:
                request_kwargs["data"] = json.dumps(raw_body, ensure_ascii=True, default=str).encode("utf-8")

        # Suppress InsecureRequestWarning when verify=False
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        try:
            response = sess.request(**request_kwargs)
        except req_lib.exceptions.SSLError as exc:
            raise error.URLError(str(exc))
        except req_lib.exceptions.ConnectionError as exc:
            raise error.URLError(str(exc))
        except req_lib.exceptions.Timeout as exc:
            raise error.URLError(str(exc))
        except req_lib.exceptions.RequestException as exc:
            raise error.URLError(str(exc))

        status_code = response.status_code
        response_headers = dict(response.headers)
        text = response.text
        raw_content = response.content

        # Collect cookies from both session jar and response
        cookies = [f"{c.name}={c.value}" for c in sess.cookies]
        from .runtime import _extract_cookies as _extract_resp_cookies
        resp_cookies = _extract_resp_cookies(response_headers)
        seen = set(cookies)
        for rc in resp_cookies:
            if rc not in seen:
                cookies.append(rc)
                seen.add(rc)

        # Persist cookies back to HttpSessionManager
        if session_manager is not None:
            import http.cookiejar
            for cookie in sess.cookies:
                cj_cookie = http.cookiejar.Cookie(
                    version=0, name=cookie.name, value=cookie.value,
                    port=None, port_specified=False,
                    domain=cookie.domain, domain_specified=True,
                    domain_initial_dot=cookie.domain.startswith("."),
                    path=cookie.path, path_specified=True,
                    secure=cookie.secure, expires=None,
                    discard=True, comment=None, comment_url=None,
                    rest={}, rfc2109=False,
                )
                session_manager.cookie_jar.set_cookie(cj_cookie)

        # Persist auth headers to HttpSessionManager
        if session_manager is not None and hasattr(session_manager, "add_auth_header"):
            if "Authorization" in sess.headers:
                session_manager.add_auth_header("Authorization", sess.headers["Authorization"])

        parsed_url = parse.urlparse(final_url)
        from .runtime import _extract_endpoints, _extract_forms, _extract_auth_clues

        return {
            "url": final_url,
            "method": method,
            "status_code": status_code,
            "headers": response_headers,
            "text": text,
            "cookies": cookies,
            "endpoints": _extract_endpoints(text, final_url),
            "forms": _extract_forms(text, final_url),
            "auth_clues": _extract_auth_clues(text, response_headers, final_url),
            "services": [{"name": parsed_url.scheme or "http", "port": parsed_url.port or (443 if parsed_url.scheme == "https" else 80)}],
            "content_type": response_headers.get("Content-Type", ""),
            "response_bytes": len(raw_content),
            "auth_used": auth_used,
            "ssl_verified": verify_ssl,
            "uploaded_files": uploaded_files,
        }

    def close(self) -> None:
        """Close requests.Session."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None