from __future__ import annotations

import base64
import difflib
import hashlib
import http.cookiejar
import html.parser
import json
import re
import tempfile
import zipfile
import tarfile
from pathlib import Path
from urllib import error, parse, request
from dataclasses import dataclass, field
from typing import Any

from .apg import CodeSandbox
from .models import new_id
from .platform_models import (
    ActionOutcome,
    Artifact,
    CandidateFlag,
    Event,
    EventType,
    Hypothesis,
    Observation,
    PrimitiveActionSpec,
    PrimitiveActionStep,
    TaskBundle,
    WorkerLease,
    WorkerProfile,
)


def _match_tags(item: dict[str, object], required_tags: list[str]) -> bool:
    if not required_tags:
        return True
    tags = set(item.get("tags", []))
    return bool(tags.intersection(required_tags))


def _clean_fail(primitive_name: str) -> ActionOutcome:
    """Return a clean failure for primitives without config or real execution capability."""
    return ActionOutcome(
        status="failed",
        cost=0.0,
        novelty=0.0,
        failure_reason=f"no_config_available: {primitive_name} requires step.parameters or instance metadata configuration",
    )


def _make_cookie_from_header(cookie_header: str, target_url: str) -> http.cookiejar.Cookie:
    """Create a Cookie object from a Set-Cookie header string."""
    from urllib.parse import urlparse
    parsed = urlparse(target_url)
    parts = cookie_header.split(";")
    name_value = parts[0].strip()
    name, _, value = name_value.partition("=")
    cookie = http.cookiejar.Cookie(
        version=0, name=name.strip(), value=value.strip(),
        port=None, port_specified=False,
        domain=parsed.hostname or "", domain_specified=True, domain_initial_dot=False,
        path="/", path_specified=True,
        secure=False, expires=None, discard=True, comment=None, comment_url=None,
        rest={}, rfc2109=False,
    )
    for part in parts[1:]:
        part = part.strip()
        if "=" in part:
            attr_name, _, attr_val = part.partition("=")
            attr_name = attr_name.strip().lower()
            if attr_name == "path":
                cookie = http.cookiejar.Cookie(
                    version=0, name=name.strip(), value=value.strip(),
                    port=None, port_specified=False,
                    domain=cookie.domain, domain_specified=cookie.domain_specified, domain_initial_dot=cookie.domain_initial_dot,
                    path=attr_val.strip(), path_specified=True,
                    secure=cookie.secure, expires=cookie.expires, discard=cookie.discard,
                    comment=None, comment_url=None, rest={}, rfc2109=False,
                )
    return cookie


@dataclass
class HttpSessionManager:
    cookie_jar: http.cookiejar.CookieJar = field(default_factory=http.cookiejar.CookieJar)
    max_redirects: int = 5
    auth_headers: dict[str, str] = field(default_factory=dict)

    def build_opener(self) -> request.OpenerDirector:
        return request.build_opener(
            request.HTTPCookieProcessor(self.cookie_jar),
            request.HTTPRedirectHandler,
        )

    def get_cookies_text(self) -> list[str]:
        return [f"{c.name}={c.value}" for c in self.cookie_jar]

    def add_auth_header(self, name: str, value: str) -> None:
        self.auth_headers[name] = value

    def get_auth_headers(self) -> dict[str, str]:
        return dict(self.auth_headers)


@dataclass(slots=True)
class PrimitiveAdapter:
    spec: PrimitiveActionSpec

    def execute(self, step: PrimitiveActionStep, bundle: TaskBundle, sandbox: CodeSandbox, session_manager: HttpSessionManager | None = None, browser_inspector: Any | None = None, http_client: Any | None = None) -> ActionOutcome:
        if step.primitive == "http-request":
            return _execute_http_request(step, bundle, session_manager, http_client)
        if step.primitive == "browser-inspect":
            return _execute_browser_inspect(step, bundle, session_manager, browser_inspector)
        if step.primitive == "session-materialize":
            return _execute_session_materialize(step, bundle, session_manager)
        if step.primitive == "structured-parse":
            return _execute_structured_parse(step, bundle)
        if step.primitive == "diff-compare":
            return _execute_diff_compare(step, bundle)
        if step.primitive == "artifact-scan":
            return _execute_artifact_scan(step, bundle, session_manager)
        if step.primitive == "binary-inspect":
            return _execute_binary_inspect(step, bundle)
        if step.primitive == "code-sandbox":
            return _execute_code_sandbox(step, bundle, sandbox)
        if step.primitive == "extract-candidate":
            return _extract_candidates(step, bundle)
        return _clean_fail(self.spec.name)




def _substitute_observe_templates(spec: dict[str, object], completed_observations: dict[str, Any]) -> dict[str, object]:
    """Replace {observe.field} placeholders in spec values with data from recent observations."""
    if not completed_observations:
        return spec
    # Find the most recent http-request observation
    recent_obs = None
    for obs in reversed(list(completed_observations.values())):
        if obs.source == "http-request":
            recent_obs = obs
            break
    if recent_obs is None:
        return spec
    # Try to parse the observation text as JSON
    obs_data: dict[str, Any] = {}
    text = recent_obs.payload.get("text", "")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            obs_data = parsed
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    if not obs_data:
        return spec
    # Substitute {observe.*} placeholders in string values
    def _sub_value(val: object) -> object:
        if not isinstance(val, str):
            return val
        import re as _re
        def _replace(m: _re.Match) -> str:
            field = m.group(1)
            return str(obs_data.get(field, m.group(0)))
        return _re.sub(r"\{observe\.(\w+)\}", _replace, val)
    result: dict[str, object] = {}
    for k, v in spec.items():
        if isinstance(v, dict):
            result[k] = {sk: _sub_value(sv) for sk, sv in v.items()}
        elif isinstance(v, list):
            result[k] = [_sub_value(item) for item in v]
        else:
            result[k] = _sub_value(v)
    return result


def _execute_http_request(step: PrimitiveActionStep, bundle: TaskBundle, session_manager: HttpSessionManager | None = None, http_client: Any | None = None) -> ActionOutcome:
    request_specs = _resolve_http_request_specs(step, bundle)
    if not request_specs:
        return _clean_fail("http-request")
    # Recover session cookies from previous session-materialize observations
    if session_manager is not None:
        for obs in bundle.completed_observations.values():
            if obs.source == "session-materialize":
                for cookie_str in obs.payload.get("cookies_obtained", []):
                    session_manager.cookie_jar.set_cookie(
                        _make_cookie_from_header(cookie_str, bundle.target)
                    ) if "=" in cookie_str else None
                auth_token = obs.payload.get("auth_token", "")
                if auth_token and "Authorization" not in session_manager.auth_headers:
                    session_manager.add_auth_header("Authorization", auth_token)
    observations: list[Observation] = []
    artifacts: list[Artifact] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("http-request", 1.0))
    for index, spec in enumerate(request_specs):
        spec = _substitute_observe_templates(spec, bundle.completed_observations)
        try:
            response_data = _perform_http_request(spec, bundle.target, session_manager, http_client)
        except error.URLError as exc:
            return ActionOutcome(
                status="failed",
                cost=total_cost,
                novelty=0.0,
                failure_reason=f"http_request_unavailable:{getattr(exc.reason, 'strerror', exc.reason) or 'unavailable'}",
            )
        observation_id = str(spec.get("id") or f"http-request-{bundle.action_program.id}-{index}")
        if observation_id in bundle.known_observation_ids:
            continue
        payload = {
            "url": response_data["url"],
            "method": response_data["method"],
            "status_code": response_data["status_code"],
            "headers": response_data["headers"],
            "text": response_data["text"],
            "cookies": response_data["cookies"],
            "endpoints": response_data["endpoints"],
            "forms": response_data["forms"],
            "auth_clues": response_data["auth_clues"],
            "services": response_data["services"],
            "content_type": response_data["content_type"],
            "response_bytes": response_data["response_bytes"],
            "auth_used": response_data.get("auth_used", "none"),
            "ssl_verified": response_data.get("ssl_verified", True),
            "uploaded_files": response_data.get("uploaded_files", []),
        }
        observations.append(
            Observation(
                id=observation_id,
                kind=str(spec.get("kind", "http-response")),
                source="http-request",
                target=bundle.target,
                payload=payload,
                confidence=float(spec.get("confidence", 0.85)),
                novelty=float(spec.get("novelty", 0.7)),
            )
        )
    novelty = sum(observation.novelty for observation in observations) + (0.4 * len(artifacts))
    return ActionOutcome(
        status="ok" if observations else "failed",
        observations=observations,
        artifacts=artifacts,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if observations else "http_request_no_new_outputs",
    )


def _execute_browser_inspect(step: PrimitiveActionStep, bundle: TaskBundle, session_manager: HttpSessionManager | None = None, browser_inspector: Any | None = None) -> ActionOutcome:
    inspect_specs = _resolve_browser_inspect_specs(step, bundle)
    if not inspect_specs:
        return _clean_fail("browser-inspect")
    observations: list[Observation] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("browser-inspect", 1.4))
    for index, spec in enumerate(inspect_specs):
        try:
            if browser_inspector is not None:
                page_data = browser_inspector.inspect_page(spec, bundle.target, session_manager)
            else:
                page_data = _perform_browser_inspect(spec, bundle.target, session_manager)
        except error.URLError as exc:
            return ActionOutcome(
                status="failed",
                cost=total_cost,
                novelty=0.0,
                failure_reason=f"browser_inspect_unavailable:{getattr(exc.reason, 'strerror', exc.reason) or 'unavailable'}",
            )
        observation_id = str(spec.get("id") or f"browser-inspect-{bundle.action_program.id}-{index}")
        if observation_id in bundle.known_observation_ids:
            continue
        observations.append(
            Observation(
                id=observation_id,
                kind=str(spec.get("kind", "browser-page")),
                source="browser-inspect",
                target=bundle.target,
                payload={
                    "url": page_data["url"],
                    "status_code": page_data["status_code"],
                    "headers": page_data["headers"],
                    "title": page_data["title"],
                    "rendered_text": page_data["rendered_text"],
                    "comments": page_data["comments"],
                    "rendered_nodes": page_data["rendered_nodes"],
                    "links": page_data.get("links", []),
                    "forms": page_data.get("forms", []),
                    "content_type": page_data["content_type"],
                    "response_bytes": page_data["response_bytes"],
                    "scripts": page_data.get("scripts", []),
                    "js_rendered_text": page_data.get("js_rendered_text", ""),
                    "console_messages": page_data.get("console_messages", []),
                    "cookies": page_data.get("cookies", []),
                },
                confidence=float(spec.get("confidence", 0.82)),
                novelty=float(spec.get("novelty", 0.68)),
            )
        )
    novelty = sum(observation.novelty for observation in observations)
    return ActionOutcome(
        status="ok" if observations else "failed",
        observations=observations,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if observations else "browser_inspect_no_new_outputs",
    )


def _execute_binary_inspect(step: PrimitiveActionStep, bundle: TaskBundle) -> ActionOutcome:
    inspect_specs = _resolve_binary_inspect_specs(step, bundle)
    if not inspect_specs:
        return _clean_fail("binary-inspect")
    observations: list[Observation] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("binary-inspect", 1.2))
    for index, spec in enumerate(inspect_specs):
        binary_data = _perform_binary_inspect(spec, bundle.target)
        observation_id = str(spec.get("id") or f"binary-inspect-{bundle.action_program.id}-{index}")
        if observation_id in bundle.known_observation_ids:
            continue
        observations.append(
            Observation(
                id=observation_id,
                kind=str(spec.get("kind", "binary-strings")),
                source="binary-inspect",
                target=bundle.target,
                payload=binary_data,
                confidence=float(spec.get("confidence", 0.84)),
                novelty=float(spec.get("novelty", 0.66)),
            )
        )
    novelty = sum(observation.novelty for observation in observations)
    return ActionOutcome(
        status="ok" if observations else "failed",
        observations=observations,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if observations else "binary_inspect_no_new_outputs",
    )


def _execute_artifact_scan(step: PrimitiveActionStep, bundle: TaskBundle, session_manager: HttpSessionManager | None = None) -> ActionOutcome:
    inspect_specs = _resolve_artifact_scan_specs(step, bundle)
    if not inspect_specs:
        return _clean_fail("artifact-scan")
    observations: list[Observation] = []
    artifacts: list[Artifact] = []
    temp_dirs: list[tempfile.TemporaryDirectory] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("artifact-scan", 1.2))
    for index, spec in enumerate(inspect_specs):
        try:
            artifact_data, td = _perform_artifact_scan(spec, bundle.target, session_manager)
        except (ValueError, OSError):
            continue
        if td is not None:
            temp_dirs.append(td)
        observation_id = str(spec.get("id") or f"artifact-scan-{bundle.action_program.id}-{index}")
        if observation_id in bundle.known_observation_ids:
            continue
        observations.append(
            Observation(
                id=observation_id,
                kind=str(spec.get("kind", "artifact-file")),
                source="artifact-scan",
                target=bundle.target,
                payload=artifact_data,
                confidence=float(spec.get("confidence", 0.83)),
                novelty=float(spec.get("novelty", 0.64)),
            )
        )
    # Cleanup temp dirs after all specs are processed
    for td in temp_dirs:
        try:
            td.cleanup()
        except OSError:
            pass
    novelty = sum(observation.novelty for observation in observations)
    return ActionOutcome(
        status="ok" if observations else "failed",
        observations=observations,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if observations else "artifact_scan_no_new_outputs",
    )


def _step_param_overrides(step: PrimitiveActionStep) -> dict[str, object]:
    """Extract step.parameters excluding required_tags — these override metadata defaults."""
    return {k: v for k, v in step.parameters.items() if k != "required_tags" and v is not None}


def _resolve_http_request_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    parsed_target = parse.urlparse(bundle.target)
    if parsed_target.scheme not in {"http", "https"}:
        return []
    param_overrides = _step_param_overrides(step)
    metadata = bundle.instance.metadata
    raw_config = metadata.get("http_request")
    # When metadata absent but step.parameters has enough info, construct spec from parameters
    if raw_config is None:
        # Only construct from step.parameters when url or path is present — method alone is insufficient
        if param_overrides.get("url") or param_overrides.get("path"):
            spec = dict(param_overrides)
            if "method" not in spec:
                spec["method"] = "GET"
            return [spec]
        # Fallback: use bundle.target as URL
        spec = {"url": bundle.target, "method": "GET"}
        spec.update(param_overrides)
        return [spec]
    required_tags = list(step.parameters.get("required_tags", []))
    if isinstance(raw_config, list):
        candidates = [item for item in raw_config if isinstance(item, dict)]
        defaults: dict[str, object] = {}
    elif isinstance(raw_config, dict):
        if raw_config.get("enabled", True) is False:
            return []
        defaults = {key: value for key, value in {
            "method": raw_config.get("method"),
            "path": raw_config.get("path"),
            "url": raw_config.get("url"),
            "headers": raw_config.get("headers"),
            "query": raw_config.get("query"),
            "body": raw_config.get("body"),
            "json": raw_config.get("json"),
            "timeout": raw_config.get("timeout"),
            "auth": raw_config.get("auth"),
            "auth_type": raw_config.get("auth_type"),
            "auth_token": raw_config.get("auth_token"),
            "files": raw_config.get("files"),
            "verify_ssl": raw_config.get("verify_ssl"),
        }.items() if value is not None}
        raw_requests = raw_config.get("requests")
        if isinstance(raw_requests, list):
            candidates = [item for item in raw_requests if isinstance(item, dict)]
        else:
            candidates = [raw_config]
    else:
        return []
    resolved: list[dict[str, object]] = []
    for candidate in candidates:
        if not _match_tags(candidate, required_tags):
            continue
        merged = dict(defaults)
        merged.update(candidate)
        merged.update(param_overrides)  # step.parameters > metadata defaults
        resolved.append(merged)
    return resolved


def _resolve_browser_inspect_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    parsed_target = parse.urlparse(bundle.target)
    if parsed_target.scheme not in {"http", "https"}:
        return []
    param_overrides = _step_param_overrides(step)
    metadata = bundle.instance.metadata
    raw_config = metadata.get("browser_inspect")
    if raw_config is None:
        if param_overrides.get("url") or param_overrides.get("path"):
            spec = dict(param_overrides)
            if "url" not in spec and "path" not in spec:
                spec["path"] = "/"
            return [spec]
        # Fallback: use bundle.target as URL
        spec = {"url": bundle.target}
        spec.update(param_overrides)
        return [spec]
    required_tags = list(step.parameters.get("required_tags", []))
    if isinstance(raw_config, list):
        candidates = [item for item in raw_config if isinstance(item, dict)]
        defaults: dict[str, object] = {}
    elif isinstance(raw_config, dict):
        if raw_config.get("enabled", True) is False:
            return []
        defaults = {key: value for key, value in {
            "path": raw_config.get("path"),
            "url": raw_config.get("url"),
            "headers": raw_config.get("headers"),
            "timeout": raw_config.get("timeout"),
        }.items() if value is not None}
        raw_pages = raw_config.get("pages")
        if isinstance(raw_pages, list):
            candidates = [item for item in raw_pages if isinstance(item, dict)]
        else:
            candidates = [raw_config]
    else:
        return []
    resolved: list[dict[str, object]] = []
    for candidate in candidates:
        if not _match_tags(candidate, required_tags):
            continue
        merged = dict(defaults)
        merged.update(candidate)
        merged.update(param_overrides)  # step.parameters > metadata defaults
        resolved.append(merged)
    return resolved


def _resolve_artifact_scan_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    parsed_target = parse.urlparse(bundle.target)
    if parsed_target.scheme not in {"file", "http", "https"} and _resolve_local_file_target(bundle.target) is None:
        return []
    param_overrides = _step_param_overrides(step)
    metadata = bundle.instance.metadata
    raw_config = metadata.get("artifact_scan")
    if raw_config is None:
        if param_overrides.get("url") or param_overrides.get("path") or param_overrides.get("location"):
            spec = dict(param_overrides)
            if "location" in spec and "url" not in spec and "path" not in spec:
                spec["url"] = spec["location"]
            return [spec]
        return []
    required_tags = list(step.parameters.get("required_tags", []))
    if isinstance(raw_config, list):
        candidates = [item for item in raw_config if isinstance(item, dict)]
        defaults: dict[str, object] = {}
    elif isinstance(raw_config, dict):
        if raw_config.get("enabled", True) is False:
            return []
        defaults = {key: value for key, value in {
            "path": raw_config.get("path"),
            "url": raw_config.get("url"),
            "preview_bytes": raw_config.get("preview_bytes"),
        }.items() if value is not None}
        raw_files = raw_config.get("files")
        if isinstance(raw_files, list):
            candidates = [item for item in raw_files if isinstance(item, dict)]
        else:
            candidates = [raw_config]
    else:
        return []
    resolved: list[dict[str, object]] = []
    for candidate in candidates:
        if not _match_tags(candidate, required_tags):
            continue
        merged = dict(defaults)
        merged.update(candidate)
        merged.update(param_overrides)  # step.parameters > metadata defaults
        resolved.append(merged)
    return resolved


def _resolve_binary_inspect_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    target_path = _resolve_local_file_target(bundle.target)
    if target_path is None:
        return []
    param_overrides = _step_param_overrides(step)
    metadata = bundle.instance.metadata
    raw_config = metadata.get("binary_inspect")
    if raw_config is None:
        if param_overrides.get("path") or param_overrides.get("url") or param_overrides.get("location"):
            spec = dict(param_overrides)
            if "location" in spec and "path" not in spec and "url" not in spec:
                spec["path"] = spec["location"]
            return [spec]
        return []
    required_tags = list(step.parameters.get("required_tags", []))
    if isinstance(raw_config, list):
        candidates = [item for item in raw_config if isinstance(item, dict)]
        defaults: dict[str, object] = {}
    elif isinstance(raw_config, dict):
        if raw_config.get("enabled", True) is False:
            return []
        defaults = {key: value for key, value in {
            "path": raw_config.get("path"),
            "url": raw_config.get("url"),
            "min_length": raw_config.get("min_length"),
            "max_strings": raw_config.get("max_strings"),
        }.items() if value is not None}
        raw_files = raw_config.get("files")
        if isinstance(raw_files, list):
            candidates = [item for item in raw_files if isinstance(item, dict)]
        else:
            candidates = [raw_config]
    else:
        return []
    resolved: list[dict[str, object]] = []
    for candidate in candidates:
        if not _match_tags(candidate, required_tags):
            continue
        merged = dict(defaults)
        merged.update(candidate)
        merged.update(param_overrides)  # step.parameters > metadata defaults
        resolved.append(merged)
    return resolved


def _perform_http_request(spec: dict[str, object], default_target: str, session_manager: HttpSessionManager | None = None, http_client: Any | None = None) -> dict[str, object]:
    if http_client is not None:
        return http_client.perform_request(spec, default_target, session_manager)
    base_url = str(spec.get("url") or default_target)
    path = str(spec.get("path", "") or "")
    final_url = parse.urljoin(base_url if base_url.endswith("/") else f"{base_url}/", path.lstrip("/")) if path else base_url
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
    if session_manager is not None:
        for name, value in session_manager.get_auth_headers().items():
            if not req.has_header(name):
                req.add_header(name, value)
    if body is not None:
        if "json" in spec and not req.has_header("Content-Type"):
            req.add_header("Content-Type", "application/json")
        if "form" in spec and not req.has_header("Content-Type"):
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
    timeout = float(spec.get("timeout") or 5.0)
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


def _perform_browser_inspect(spec: dict[str, object], default_target: str, session_manager: HttpSessionManager | None = None, extract_scripts: bool = False) -> dict[str, object]:
    base_url = str(spec.get("url") or default_target)
    path = str(spec.get("path", "") or "")
    final_url = parse.urljoin(base_url if base_url.endswith("/") else f"{base_url}/", path.lstrip("/")) if path else base_url
    req = request.Request(final_url, method="GET")
    for key, value in dict(spec.get("headers", {}) or {}).items():
        req.add_header(str(key), str(value))
    timeout = float(spec.get("timeout") or 5.0)
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
    html = raw_body.decode(encoding, errors="replace")
    parsed = _parse_html_page(html, final_url, extract_scripts=extract_scripts)
    return {
        "url": final_url,
        "status_code": status_code,
        "headers": headers,
        "title": parsed["title"],
        "rendered_text": parsed["rendered_text"],
        "comments": parsed["comments"],
        "rendered_nodes": parsed["nodes"],
        "links": parsed["links"],
        "forms": parsed["forms"],
        "content_type": headers.get("Content-Type", ""),
        "response_bytes": len(raw_body),
        "scripts": parsed.get("scripts", []),
        "js_rendered_text": "",
        "console_messages": [],
        "cookies": [],
    }


def _perform_artifact_scan(spec: dict[str, object], default_target: str, session_manager: HttpSessionManager | None = None) -> tuple[dict[str, object], tempfile.TemporaryDirectory | None]:
    target = str(spec.get("url") or spec.get("path") or default_target)
    parsed = parse.urlparse(target)
    resolved_path: Path | None = None
    temp_dir: tempfile.TemporaryDirectory | None = None
    if parsed.scheme in {"http", "https"}:
        temp_dir = tempfile.TemporaryDirectory()
        local_path = _download_artifact(target, Path(temp_dir.name), session_manager)
        resolved_path = local_path
    elif parsed.scheme == "file" or not parsed.scheme:
        resolved_path = _resolve_local_file_target(target)
    if resolved_path is None:
        raise ValueError("artifact_scan_target_unavailable")
    raw_bytes = resolved_path.read_bytes()
    payload: dict[str, object] = {
        "uri": resolved_path.as_uri() if parsed.scheme != "http" else target,
        "name": resolved_path.name,
        "size_bytes": len(raw_bytes),
        "suffix": resolved_path.suffix.lower(),
        "sha1": hashlib.sha1(raw_bytes).hexdigest(),
        "content_type": _guess_content_type(resolved_path.name),
    }
    preview_bytes_val = int(spec.get("preview_bytes") or 512)
    preview = _extract_text_preview(raw_bytes, preview_bytes_val)
    if preview:
        payload["text_preview"] = preview
    max_depth = max(1, int(spec.get("max_depth") or 1))
    max_members = max(1, int(spec.get("max_members") or 20))
    archive_members = _extract_archive_members(resolved_path, max_depth, max_members, preview_bytes_val)
    if archive_members:
        payload["archive_members"] = archive_members
    return payload, temp_dir


def _download_artifact(url: str, dest_dir: Path, session_manager: HttpSessionManager | None = None) -> Path:
    filename = parse.urlparse(url).path.split("/")[-1] or "downloaded"
    dest_path = dest_dir / filename
    opener = session_manager.build_opener() if session_manager else request.build_opener()
    with opener.open(request.Request(url), timeout=10.0) as response:
        dest_path.write_bytes(response.read())
    return dest_path


def _guess_content_type(name: str) -> str:
    ext = Path(name).suffix.lower()
    types = {
        ".txt": "text/plain", ".html": "text/html", ".htm": "text/html",
        ".json": "application/json", ".xml": "application/xml", ".csv": "text/csv",
        ".py": "text/x-python", ".js": "text/javascript", ".sh": "text/x-shellscript",
        ".md": "text/markdown", ".yaml": "text/yaml", ".yml": "text/yaml",
        ".cfg": "text/plain", ".ini": "text/plain", ".conf": "text/plain",
        ".log": "text/plain", ".env": "text/plain",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".svg": "image/svg+xml", ".ico": "image/x-icon",
        ".pdf": "application/pdf", ".pcap": "application/vnd.tcpdump.pcap",
        ".zip": "application/zip", ".gz": "application/gzip",
        ".exe": "application/x-msdownload", ".elf": "application/x-elf",
    }
    return types.get(ext, "application/octet-stream")


def _extract_archive_members(path: Path, max_depth: int, max_members: int, preview_bytes: int = 512) -> list[dict[str, object]] | None:
    suffix = path.suffix.lower()
    # Also handle .tar.gz / .tar.bz2 compound suffixes
    stem = path.stem.lower()
    compound_suffix = f".tar{suffix}" if suffix in {".gz", ".bz2"} and stem.endswith(".tar") else suffix
    effective_suffix = compound_suffix if compound_suffix in {".tar.gz", ".tar.bz2"} else suffix

    members: list[dict[str, object]] = []
    if effective_suffix == ".zip":
        try:
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist()[:max_members]:
                    if info.is_dir():
                        continue
                    entry: dict[str, object] = {
                        "name": info.filename,
                        "size_bytes": info.file_size,
                        "compressed_size": info.compress_size,
                        "content_type": _guess_content_type(info.filename),
                    }
                    try:
                        raw = zf.read(info.filename)
                        preview = _extract_text_preview(raw, preview_bytes)
                        if preview:
                            entry["content_preview"] = preview
                    except (RuntimeError, zipfile.BadZipFile, KeyError):
                        pass
                    members.append(entry)
        except zipfile.BadZipFile:
            return None
    elif effective_suffix in {".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2"}:
        try:
            with tarfile.open(path) as tf:
                for member in tf.getmembers()[:max_members]:
                    if not member.isfile():
                        continue
                    entry: dict[str, object] = {
                        "name": member.name,
                        "size_bytes": member.size,
                        "content_type": _guess_content_type(member.name),
                    }
                    try:
                        f = tf.extractfile(member)
                        if f is not None:
                            raw = f.read(preview_bytes + 1)
                            preview = _extract_text_preview(raw, preview_bytes)
                            if preview:
                                entry["content_preview"] = preview
                            f.close()
                    except (tarfile.TarError, OSError):
                        pass
                    members.append(entry)
        except tarfile.TarError:
            return None
    else:
        return None
    return members if members else None


def _perform_binary_inspect(spec: dict[str, object], default_target: str) -> dict[str, object]:
    resolved_path = _resolve_local_file_target(str(spec.get("url") or spec.get("path") or default_target))
    if resolved_path is None:
        raise ValueError("binary_inspect_target_unavailable")
    raw_bytes = resolved_path.read_bytes()
    min_length = max(4, int(spec.get("min_length") or 4))
    max_strings = max(1, int(spec.get("max_strings") or 20))
    ascii_strings = _extract_printable_strings(raw_bytes, min_length, max_strings)
    utf8_strings = _extract_utf8_strings(raw_bytes, min_length, max_strings)
    wide_strings = _extract_wide_strings(raw_bytes, min_length, max_strings)
    all_strings = ascii_strings
    seen = set(ascii_strings)
    for s in utf8_strings + wide_strings:
        if s not in seen:
            seen.add(s)
            all_strings.append(s)
    encoding_types = []
    if ascii_strings:
        encoding_types.append("ascii")
    if utf8_strings:
        encoding_types.append("utf8")
    if wide_strings:
        encoding_types.append("wide")
    headers = _parse_binary_headers(raw_bytes)
    result: dict[str, object] = {
        "path": resolved_path.as_uri(),
        "scheme": "file",
        "size_bytes": len(raw_bytes),
        "sha1": hashlib.sha1(raw_bytes).hexdigest(),
        "strings": all_strings[:max_strings],
        "string_count": len(all_strings),
        "min_length": min_length,
        "encoding_types": encoding_types,
    }
    if headers:
        result["headers"] = headers
    return result


def _extract_utf8_strings(raw_bytes: bytes, min_length: int, max_strings: int) -> list[str]:
    strings: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(rb"(?:[\x20-\x7e]|[\xc0-\xff][\x80-\xbf]+){%d,}" % min_length)
    for match in pattern.findall(raw_bytes):
        try:
            decoded = match.decode("utf-8", errors="strict")
            if decoded in seen or not decoded.strip():
                continue
            seen.add(decoded)
            strings.append(decoded)
            if len(strings) >= max_strings:
                break
        except UnicodeDecodeError:
            continue
    return strings


def _extract_wide_strings(raw_bytes: bytes, min_length: int, max_strings: int) -> list[str]:
    strings: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % min_length)
    for match in pattern.findall(raw_bytes):
        decoded = match.decode("utf-16-le", errors="ignore").strip()
        if decoded in seen or not decoded:
            continue
        seen.add(decoded)
        strings.append(decoded)
        if len(strings) >= max_strings:
            break
    return strings


def _parse_binary_headers(raw_bytes: bytes) -> dict[str, str] | None:
    if len(raw_bytes) < 16:
        return None
    if raw_bytes[:4] == b"\x7fELF":
        class_type = "64-bit" if raw_bytes[4] == 2 else "32-bit"
        endian = "little" if raw_bytes[5] == 1 else "big"
        e_type = raw_bytes[16] if len(raw_bytes) > 16 else 0
        type_names = {0: "none", 1: "rel", 2: "exec", 3: "dyn"}
        return {"format": "ELF", "class": class_type, "endian": endian, "type": type_names.get(e_type, str(e_type))}
    if raw_bytes[:2] == b"MZ" and len(raw_bytes) > 64:
        pe_offset = int.from_bytes(raw_bytes[60:64], "little")
        if pe_offset < len(raw_bytes) and raw_bytes[pe_offset:pe_offset+4] == b"PE\x00\x00":
            machine = int.from_bytes(raw_bytes[pe_offset+4:pe_offset+6], "little")
            machine_names = {0x14c: "i386", 0x8664: "x86_64", 0x1c0: "ARM"}
            return {"format": "PE", "machine": machine_names.get(machine, f"0x{machine:x}")}
    return None


class _HTMLPageParser(html.parser.HTMLParser):
    _SKIP_TAGS = frozenset({"script", "style"})
    _NODE_TAGS = frozenset({"main", "section", "article", "div"})

    def __init__(self, base_url: str, extract_scripts: bool = False) -> None:
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self._in_title = False
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._skip_tag = ""
        self._text_parts: list[str] = []
        self.comments: list[str] = []
        self.nodes: list[str] = []
        self.links: list[dict[str, str]] = []
        self.forms: list[dict[str, object]] = []
        self._current_form: dict[str, object] | None = None
        self._form_inputs: list[str] = []
        self._extract_scripts = extract_scripts
        self.scripts: list[dict[str, str]] = []
        self._current_script_index: int = -1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        if tag == "script" and self._extract_scripts:
            self.scripts.append({
                "src": attr_dict.get("src", ""),
                "type": attr_dict.get("type", ""),
                "inline": "",
            })
            self._current_script_index = len(self.scripts) - 1
            self._skip_depth += 1
            self._skip_tag = tag
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            self._skip_tag = tag
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "a" and "href" in attr_dict:
            href = attr_dict["href"]
            absolute = parse.urljoin(self.base_url, href)
            parsed_link = parse.urlparse(absolute)
            self.links.append({"path": parsed_link.path or "/", "url": absolute, "text": ""})
        if tag == "form":
            self._current_form = {
                "id": f"form-{len(self.forms)}",
                "action": parse.urljoin(self.base_url, attr_dict.get("action", "")),
                "method": attr_dict.get("method", "GET").upper(),
            }
            self._form_inputs = []
        if tag == "input" and self._current_form is not None and "name" in attr_dict:
            self._form_inputs.append(attr_dict["name"])
        if tag in self._NODE_TAGS and "id" in attr_dict:
            self.nodes.append(f"{tag}#{attr_dict['id']}")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth > 0 and tag == self._skip_tag:
            self._skip_depth -= 1
            if self._current_script_index >= 0:
                self._current_script_index = -1
            self._skip_tag = ""
            return
        if tag == "title":
            self._in_title = False
            self.title = " ".join(self._title_parts).strip()
            self._title_parts = []
        if tag == "form" and self._current_form is not None:
            self._current_form["inputs"] = self._form_inputs
            self.forms.append(self._current_form)
            self._current_form = None
            self._form_inputs = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0 and self._current_script_index >= 0:
            self.scripts[self._current_script_index]["inline"] += data
            return
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        stripped = data.strip()
        if stripped:
            self._text_parts.append(stripped)

    def handle_comment(self, data: str) -> None:
        normalized = re.sub(r"\s+", " ", data).strip()
        if normalized:
            self.comments.append(normalized)

    def get_rendered_text(self) -> str:
        return " ".join(self._text_parts)


def _parse_html_page(html: str, base_url: str, extract_scripts: bool = False) -> dict[str, object]:
    parser = _HTMLPageParser(base_url, extract_scripts=extract_scripts)
    try:
        parser.feed(html)
    except html.parser.HTMLParseError:
        pass
    return {
        "title": parser.title or _extract_html_title(html),
        "rendered_text": parser.get_rendered_text() or _extract_rendered_text(html),
        "comments": parser.comments or _extract_html_comments(html),
        "nodes": parser.nodes or _extract_rendered_nodes(html),
        "links": parser.links,
        "forms": parser.forms or _extract_forms(html, base_url),
        "scripts": parser.scripts,
    }


_COMMON_CSRF_NAMES = ("csrfmiddlewaretoken", "csrf_token", "csrf-token", "_token", "authenticity_token", "X-CSRFToken")


class _CSRFTokenParser(html.parser.HTMLParser):
    """Extract CSRF token from HTML hidden inputs and meta tags."""

    def __init__(self, target_names: tuple[str, ...] = _COMMON_CSRF_NAMES,
                 search_meta: bool = True, search_form: bool = True) -> None:
        super().__init__()
        self._target_names = target_names
        self._search_meta = search_meta
        self._search_form = search_form
        self._token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        if self._search_form and tag == "input":
            if attr_dict.get("type", "").lower() == "hidden" and attr_dict.get("name") in self._target_names:
                value = attr_dict.get("value", "")
                if value and self._token is None:
                    self._token = value
        if self._search_meta and tag == "meta":
            if attr_dict.get("name") in self._target_names:
                content = attr_dict.get("content", "")
                if content and self._token is None:
                    self._token = content

    def get_token(self) -> str | None:
        return self._token


def _extract_csrf_token(html_text: str, csrf_field: str, csrf_source: str) -> str | None:
    target_names = (csrf_field,) if csrf_field else _COMMON_CSRF_NAMES
    search_meta = csrf_source in ("meta", "form")  # meta mode or auto-detect
    search_form = csrf_source in ("form",) or (csrf_source == "meta" and not csrf_field)
    if csrf_source == "meta":
        search_form = False
        search_meta = True
    parser = _CSRFTokenParser(target_names, search_meta=search_meta, search_form=search_form)
    try:
        parser.feed(html_text)
    except html.parser.HTMLParseError:
        pass
    return parser.get_token()


def _execute_session_materialize(step: PrimitiveActionStep, bundle: TaskBundle, session_manager: HttpSessionManager | None = None) -> ActionOutcome:
    session_config = _resolve_session_materialize_specs(step, bundle)
    if not session_config:
        return _clean_fail("session-materialize")
    observations: list[Observation] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("session-materialize", 1.1))
    for index, spec in enumerate(session_config):
        login_url = str(spec.get("login_url", bundle.target))
        method = str(spec.get("method", "POST")).upper()
        form_fields = dict(spec.get("form_fields", {}))
        username = str(spec.get("username", ""))
        password = str(spec.get("password", ""))
        if username and password:
            form_fields.setdefault("username", username)
            form_fields.setdefault("password", password)
        timeout = float(spec.get("timeout") or 5.0)
        json_payload = spec.get("json")
        content_type_override = spec.get("content_type")
        body_type = "form"

        # --- CSRF prefetch ---
        csrf_token_value: str | None = None
        csrf_config = spec.get("csrf_token")
        if csrf_config:
            csrf_field = str(spec.get("csrf_field") or (csrf_config if isinstance(csrf_config, str) else ""))
            csrf_source = str(spec.get("csrf_source") or "form")
            prefetch_opener = session_manager.build_opener() if session_manager else request.build_opener()
            prefetch_headers_dict: dict[str, str] = {}
            prefetch_html = ""
            try:
                prefetch_req = request.Request(login_url, method="GET")
                for key, value in dict(spec.get("headers", {}) or {}).items():
                    prefetch_req.add_header(str(key), str(value))
                with prefetch_opener.open(prefetch_req, timeout=timeout) as prefetch_resp:
                    prefetch_headers_dict = dict(prefetch_resp.headers.items())
                    prefetch_html = prefetch_resp.read().decode("utf-8", errors="replace")
            except (error.HTTPError, error.URLError):
                pass
            if csrf_source == "header":
                for header_name in ("X-CSRFToken", "X-CSRF-Token", "Csrf-Token"):
                    token = prefetch_headers_dict.get(header_name)
                    if token:
                        csrf_token_value = token
                        break
            else:
                csrf_token_value = _extract_csrf_token(prefetch_html, csrf_field, csrf_source)
            # Inject CSRF token
            if csrf_token_value:
                if csrf_source == "form":
                    field_name = csrf_field or "csrfmiddlewaretoken"
                    form_fields[field_name] = csrf_token_value
                else:
                    spec_headers = dict(spec.get("headers", {}) or {})
                    spec_headers["X-CSRFToken"] = csrf_token_value
                    spec["headers"] = spec_headers

        # --- Body encoding ---
        if json_payload and isinstance(json_payload, dict):
            body = json.dumps({str(k): str(v) for k, v in json_payload.items()}, ensure_ascii=True).encode("utf-8")
            req = request.Request(login_url, data=body, method=method)
            req.add_header("Content-Type", content_type_override or "application/json")
            body_type = "json"
        elif content_type_override == "application/json" and form_fields:
            body = json.dumps({str(k): str(v) for k, v in form_fields.items()}, ensure_ascii=True).encode("utf-8")
            req = request.Request(login_url, data=body, method=method)
            req.add_header("Content-Type", "application/json")
            body_type = "json"
        else:
            body = parse.urlencode({str(k): str(v) for k, v in form_fields.items()}).encode("utf-8")
            req = request.Request(login_url, data=body, method=method)
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        for key, value in dict(spec.get("headers", {}) or {}).items():
            req.add_header(str(key), str(value))
        # Inject session auth headers
        if session_manager:
            for name, value in session_manager.get_auth_headers().items():
                if name not in req.headers:
                    req.add_header(name, value)
        opener = session_manager.build_opener() if session_manager else request.build_opener()
        try:
            with opener.open(req, timeout=timeout) as response:
                status_code = int(response.status)
                resp_headers = dict(response.headers.items())
                resp_body = response.read()
        except error.HTTPError as exc:
            status_code = int(exc.code)
            resp_headers = dict(exc.headers.items())
            resp_body = exc.read()
        except error.URLError:
            return ActionOutcome(status="failed", cost=total_cost, novelty=0.0, failure_reason="session_login_failed")
        cookies_obtained = []
        if session_manager:
            cookies_obtained = session_manager.get_cookies_text()
        else:
            cookies_obtained = _extract_cookies(resp_headers)

        # --- Persist auth tokens to session_manager ---
        if session_manager:
            auth_header_value = resp_headers.get("Authorization", "")
            if auth_header_value:
                session_manager.add_auth_header("Authorization", auth_header_value)
            if body_type == "json":
                try:
                    resp_json = json.loads(resp_body.decode("utf-8", errors="replace"))
                    token_value = resp_json.get("token") or resp_json.get("access_token") or resp_json.get("auth_token")
                    if token_value and isinstance(token_value, str):
                        session_manager.add_auth_header("Authorization", f"Bearer {token_value}")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        observation_id = str(spec.get("id") or f"session-materialize-{bundle.action_program.id}-{index}")
        if observation_id in bundle.known_observation_ids:
            continue
        observations.append(
            Observation(
                id=observation_id,
                kind="session-materialized",
                source="session-materialize",
                target=bundle.target,
                payload={
                    "login_url": login_url,
                    "method": method,
                    "status_code": status_code,
                    "cookies_obtained": cookies_obtained,
                    "auth_token": resp_headers.get("Authorization", ""),
                    "csrf_prefetched": csrf_token_value is not None,
                    "csrf_token_value": csrf_token_value or "",
                    "body_type": body_type,
                    "session_type": "cookie" if cookies_obtained else ("token" if resp_headers.get("Authorization") else "unknown"),
                    "valid": status_code in (200, 301, 302),
                },
                confidence=0.88,
                novelty=0.75,
            )
        )
    novelty = sum(observation.novelty for observation in observations)
    return ActionOutcome(
        status="ok" if observations else "failed",
        observations=observations,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if observations else "session_materialize_no_output",
    )


def _resolve_session_materialize_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    param_overrides = _step_param_overrides(step)
    metadata = bundle.instance.metadata
    raw_config = metadata.get("session_materialize")
    if raw_config is None:
        if param_overrides.get("login_url") or param_overrides.get("username"):
            spec = dict(param_overrides)
            if "method" not in spec:
                spec["method"] = "POST"
            return [spec]
        # Fallback: use bundle.target as login_url
        spec = {"login_url": bundle.target, "method": "POST"}
        spec.update(param_overrides)
        return [spec]
    if isinstance(raw_config, dict):
        if raw_config.get("enabled", True) is False:
            return []
        merged = dict(raw_config)
        merged.update(param_overrides)  # step.parameters > metadata defaults
        return [merged]
    if isinstance(raw_config, list):
        results = []
        for item in raw_config:
            if isinstance(item, dict):
                merged = dict(item)
                merged.update(param_overrides)
                results.append(merged)
        return results
    return []


def _execute_structured_parse(step: PrimitiveActionStep, bundle: TaskBundle) -> ActionOutcome:
    parse_source = step.parameters.get("parse_source")
    fmt = step.parameters.get("format")
    # Auto-detect: use most recent observation if parse_source not given
    if parse_source is None and bundle.completed_observations:
        recent = list(bundle.completed_observations.values())[-1]
        parse_source = recent.id
    if fmt is None:
        fmt = "json"
    if parse_source is None or fmt is None:
        return _clean_fail("structured-parse")
    source_id = str(parse_source)
    source_obs = bundle.completed_observations.get(source_id)
    if source_obs is None:
        return _clean_fail("structured-parse")
    extract_fields = list(step.parameters.get("extract_fields", []))
    observations: list[Observation] = []
    hypotheses: list[Hypothesis] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("structured-parse", 0.8))
    parse_result = _perform_structured_parse(source_obs.payload, str(fmt), extract_fields)
    observation_id = str(step.parameters.get("id") or f"structured-parse-{bundle.action_program.id}")
    if observation_id not in bundle.known_observation_ids:
        observations.append(
            Observation(
                id=observation_id,
                kind=f"parsed-{str(fmt)}",
                source="structured-parse",
                target=bundle.target,
                payload=parse_result,
                confidence=0.86,
                novelty=0.72,
            )
        )
    if parse_result.get("potential_secrets") or parse_result.get("suspicious_patterns"):
        hypothesis_id = f"hypothesis-{bundle.action_program.id}"
        if hypothesis_id not in bundle.known_hypothesis_ids:
            hypotheses.append(
                Hypothesis(
                    id=hypothesis_id,
                    statement=f"Structured data from {source_id} contains hidden information",
                    preconditions=[source_id],
                    supporting_observations=[observation_id],
                    confidence=0.7,
                )
            )
    novelty = sum(observation.novelty for observation in observations) + (0.3 * len(hypotheses))
    return ActionOutcome(
        status="ok" if observations else "failed",
        observations=observations,
        derived_hypotheses=hypotheses,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if observations else "structured_parse_no_output",
    )


def _perform_structured_parse(payload: dict[str, Any], fmt: str, extract_fields: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"format": fmt, "source_fields": list(payload.keys())}
    text = payload.get("text", "")
    if not text:
        text = json.dumps(payload, ensure_ascii=True, default=str)

    # Always extract cookies from payload (available regardless of format)
    cookies_raw = payload.get("cookies", [])
    cookie_dict: dict[str, str] = {}
    for cookie_str in cookies_raw:
        if "=" in cookie_str:
            # Parse "key=value; Path=/; HttpOnly" style cookies
            pair = cookie_str.split(";")[0].strip()
            k, _, v = pair.partition("=")
            cookie_dict[k.strip()] = v.strip()
    if cookie_dict:
        result["cookies"] = cookie_dict
        # Auto-decode any cookie values that look like base64
        decoded_cookies: dict[str, str] = {}
        for k, v in cookie_dict.items():
            try:
                decoded = base64.b64decode(v).decode("utf-8", errors="replace")
                if decoded != v:
                    decoded_cookies[k] = decoded
            except Exception:
                pass
        if decoded_cookies:
            result["decoded_cookies"] = decoded_cookies
            # Check for flags in decoded cookies
            for k, v in decoded_cookies.items():
                if re.search(r"flag\{[^}]+\}", v):
                    result["potential_secrets"] = result.get("potential_secrets", [])
                    result["potential_secrets"].append(f"cookie:{k}")

    if fmt == "json":
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                result["parsed_data"] = parsed
                if extract_fields:
                    result["extracted"] = {f: parsed.get(f) for f in extract_fields if f in parsed}
                result["potential_secrets"] = result.get("potential_secrets", []) + [
                    f for f, v in parsed.items()
                    if isinstance(v, str) and any(kw in v.lower() for kw in ("password", "secret", "key", "token", "flag"))
                ]
        except json.JSONDecodeError:
            result["parse_error"] = "invalid_json"
    elif fmt == "html":
        parser = _HTMLPageParser("")
        try:
            parser.feed(text)
        except html.parser.HTMLParseError:
            pass
        result["title"] = parser.title
        result["forms"] = parser.forms
        result["links"] = parser.links
        result["comments"] = parser.comments
        result["suspicious_patterns"] = [c for c in parser.comments if any(kw in c.lower() for kw in ("flag", "secret", "hidden", "admin"))]
    elif fmt == "headers":
        headers = payload.get("headers", {})
        result["parsed_headers"] = headers
        result["interesting_headers"] = {
            k: v for k, v in headers.items()
            if k.lower().startswith(("x-", "auth", "cookie", "set-cookie", "access-control"))
        }
    else:
        result["raw_text"] = text[:500]
    return result


def _execute_diff_compare(step: PrimitiveActionStep, bundle: TaskBundle) -> ActionOutcome:
    baseline_id = step.parameters.get("baseline_observation_id")
    variant_id = step.parameters.get("variant_observation_id")
    if baseline_id is None or variant_id is None:
        return _clean_fail("diff-compare")
    baseline_text = _get_observation_text(str(baseline_id), bundle)
    variant_text = _get_observation_text(str(variant_id), bundle)
    if baseline_text is None or variant_text is None:
        return _clean_fail("diff-compare")
    observations: list[Observation] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("diff-compare", 0.7))
    diff_result = _perform_diff_compare(baseline_text, variant_text, str(baseline_id), str(variant_id))
    observation_id = str(step.parameters.get("id") or f"diff-compare-{bundle.action_program.id}")
    if observation_id not in bundle.known_observation_ids:
        observations.append(
            Observation(
                id=observation_id,
                kind="diff-result",
                source="diff-compare",
                target=bundle.target,
                payload=diff_result,
                confidence=0.87,
                novelty=0.73,
            )
        )
    novelty = sum(observation.novelty for observation in observations)
    return ActionOutcome(
        status="ok" if observations else "failed",
        observations=observations,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if observations else "diff_compare_no_output",
    )


def _get_observation_text(obs_id: str, bundle: TaskBundle) -> str | None:
    obs = bundle.completed_observations.get(obs_id)
    if obs is not None:
        return obs.payload.get("text", json.dumps(obs.payload, ensure_ascii=True, default=str))
    return None


def _perform_diff_compare(baseline: str, variant: str, baseline_id: str, variant_id: str) -> dict[str, Any]:
    baseline_lines = baseline.splitlines()
    variant_lines = variant.splitlines()
    diff_lines = list(difflib.unified_diff(baseline_lines, variant_lines, lineterm="", fromfile=baseline_id, tofile=variant_id))
    added = [line for line in diff_lines if line.startswith("+") and not line.startswith("+++")]
    removed = [line for line in diff_lines if line.startswith("-") and not line.startswith("---")]
    return {
        "baseline_id": baseline_id,
        "variant_id": variant_id,
        "diff_lines": diff_lines,
        "change_count": len(added) + len(removed),
        "added_lines": added,
        "removed_lines": removed,
        "summary": f"{len(added)} additions, {len(removed)} removals",
    }


def _encode_http_request_body(spec: dict[str, object]) -> bytes | None:
    if "json" in spec and spec["json"] is not None:
        return json.dumps(spec["json"], ensure_ascii=True, default=str).encode("utf-8")
    form = spec.get("form")
    if isinstance(form, dict) and form:
        return parse.urlencode({str(key): str(value) for key, value in form.items()}).encode("utf-8")
    body = spec.get("body")
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    return json.dumps(body, ensure_ascii=True, default=str).encode("utf-8")


def _infer_http_encoding(headers: dict[str, str], raw_body: bytes) -> str:
    content_type = headers.get("Content-Type", "")
    match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
    if match:
        return match.group(1)
    if raw_body.startswith(b"\xff\xfe") or raw_body.startswith(b"\xfe\xff"):
        return "utf-16"
    return "utf-8"


def _extract_cookies(headers: dict[str, str]) -> list[str]:
    cookies: list[str] = []
    for key, value in headers.items():
        if key.lower() == "set-cookie":
            cookies.extend([part.strip() for part in value.split(",") if part.strip()])
    return cookies


def _extract_endpoints(text: str, base_url: str) -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.findall(r"""href=["']([^"'#]+)""", text, flags=re.IGNORECASE):
        absolute = parse.urljoin(base_url, match)
        parsed_link = parse.urlparse(absolute)
        path = parsed_link.path or "/"
        if path in seen:
            continue
        seen.add(path)
        discovered.append({"path": path, "url": absolute})
    return discovered


def _extract_forms(text: str, base_url: str) -> list[dict[str, object]]:
    forms: list[dict[str, object]] = []
    for index, form_match in enumerate(re.finditer(r"<form\b([^>]*)>(.*?)</form>", text, flags=re.IGNORECASE | re.DOTALL)):
        attrs = form_match.group(1)
        inner_html = form_match.group(2)
        action_match = re.search(r"""action=["']([^"']+)""", attrs, flags=re.IGNORECASE)
        method_match = re.search(r"""method=["']([^"']+)""", attrs, flags=re.IGNORECASE)
        input_names = [
            input_match
            for input_match in re.findall(r"""<input\b[^>]*name=["']([^"']+)""", inner_html, flags=re.IGNORECASE)
            if input_match
        ]
        forms.append(
            {
                "id": f"form-{index}",
                "action": parse.urljoin(base_url, action_match.group(1)) if action_match else base_url,
                "method": (method_match.group(1).upper() if method_match else "GET"),
                "inputs": input_names,
            }
        )
    return forms


def _extract_auth_clues(text: str, headers: dict[str, str], base_url: str) -> list[str]:
    clues: list[str] = []
    seen: set[str] = set()
    lower_text = text.lower()
    lower_headers = {key.lower(): value.lower() for key, value in headers.items()}
    keyword_rules = [
        ("login_form", bool(re.search(r"<form\b", text, flags=re.IGNORECASE)) and any(token in lower_text for token in ("login", "sign in", "signin"))),
        ("password_field", bool(re.search(r"""<input\b[^>]*type=["']password["']""", text, flags=re.IGNORECASE))),
        ("username_field", bool(re.search(r"""<input\b[^>]*name=["'](?:user|username|email)["']""", text, flags=re.IGNORECASE))),
        ("auth_header", "www-authenticate" in lower_headers or "authorization" in lower_headers),
        ("session_cookie", any("session" in cookie.lower() or "auth" in cookie.lower() or "token" in cookie.lower() for cookie in _extract_cookies(headers))),
        ("auth_path", any(token in parse.urlparse(base_url).path.lower() for token in ("login", "auth", "signin", "session"))),
        ("auth_keywords", any(token in lower_text for token in ("login", "logout", "password", "token", "jwt", "session", "admin", "auth"))),
    ]
    for clue, matched in keyword_rules:
        if matched and clue not in seen:
            seen.add(clue)
            clues.append(clue)
    return clues


def _extract_html_title(html: str) -> str:
    match = re.search(r"<title\b[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _extract_html_comments(html: str) -> list[str]:
    comments: list[str] = []
    for comment in re.findall(r"<!--(.*?)-->", html, flags=re.DOTALL):
        normalized = re.sub(r"\s+", " ", comment).strip()
        if normalized:
            comments.append(normalized)
    return comments


def _extract_rendered_text(html: str) -> str:
    without_comments = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    without_non_rendered = re.sub(r"<(script|style)\b[^>]*>.*?</\\1>", " ", without_comments, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", without_non_rendered)
    return re.sub(r"\s+", " ", text).strip()


def _extract_rendered_nodes(html: str) -> list[str]:
    nodes: list[str] = []
    for match in re.finditer(r"<(main|section|article|div)\b[^>]*\sid=['\"]([^'\"]+)['\"][^>]*>", html, flags=re.IGNORECASE):
        nodes.append(f"{match.group(1).lower()}#{match.group(2)}")
    return nodes


def _resolve_local_file_target(target: str) -> Path | None:
    parsed_target = parse.urlparse(target)
    if parsed_target.scheme != "file":
        return None
    raw_path = parse.unquote(parsed_target.path or "")
    if re.fullmatch(r"/[A-Za-z]:/.*", raw_path):
        raw_path = raw_path[1:]
    candidate = Path(raw_path)
    if not candidate.is_file():
        return None
    return candidate.resolve()


def _extract_printable_strings(raw_bytes: bytes, min_length: int, max_strings: int) -> list[str]:
    matches = re.findall(rb"[\x20-\x7e]{%d,}" % min_length, raw_bytes)
    strings: list[str] = []
    seen: set[str] = set()
    for match in matches:
        decoded = match.decode("ascii", errors="ignore")
        if not decoded or decoded in seen:
            continue
        seen.add(decoded)
        strings.append(decoded)
        if len(strings) >= max_strings:
            break
    return strings


def _extract_text_preview(raw_bytes: bytes, preview_bytes: int) -> str:
    limit = max(0, min(preview_bytes, 4096))
    if not raw_bytes or limit == 0:
        return ""
    sample = raw_bytes[:limit]
    try:
        decoded = sample.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    if "\x00" in decoded:
        return ""
    if any((ord(ch) < 32 and ch not in "\r\n\t") for ch in decoded):
        return ""
    return decoded.strip()


def _execute_code_sandbox(step: PrimitiveActionStep, bundle: TaskBundle, sandbox: CodeSandbox) -> ActionOutcome:
    program_fragment = str(step.parameters.get("program_fragment", "") or bundle.instance.metadata.get("sandbox_program", "result = {'texts': []}"))
    inputs = dict(bundle.instance.metadata.get("sandbox_inputs", {}))
    try:
        result = sandbox.execute(program_fragment, inputs)
    except RuntimeError:
        return _clean_fail("code-sandbox")
    observations: list[Observation] = []
    artifacts: list[Artifact] = []
    candidate_flags: list[CandidateFlag] = []
    for index, text in enumerate(list(result.get("texts", []))):
        observation_id = f"sandbox-observation-{bundle.action_program.id}-{index}"
        if observation_id in bundle.known_observation_ids:
            continue
        observations.append(
            Observation(
                id=observation_id,
                kind="sandbox-output",
                source="code-sandbox",
                target=bundle.target,
                payload={"text": str(text)},
                confidence=0.75,
                novelty=0.5,
            )
        )
    if "artifact" in result:
        artifact_payload = dict(result["artifact"])
        artifact_id = str(artifact_payload.get("id", f"sandbox-artifact-{bundle.action_program.id}"))
        if artifact_id not in bundle.known_artifact_ids:
            artifacts.append(
                Artifact(
                    id=artifact_id,
                    kind=str(artifact_payload.get("kind", "derived")),
                    location=str(artifact_payload.get("location", bundle.target)),
                    fingerprint=str(artifact_payload.get("fingerprint", hashlib.sha1(json.dumps(artifact_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12])),
                    metadata=artifact_payload,
                )
            )
    if "candidate_flag" in result:
        value = str(result["candidate_flag"])
        if value not in bundle.known_candidate_keys:
            candidates = CandidateFlag(
                value=value,
                source_chain=["code-sandbox", bundle.action_program.id],
                confidence=0.9,
                format_match=bool(re.fullmatch(bundle.challenge.flag_pattern, value)),
                dedupe_key=value,
            )
            candidate_flags.append(candidates)
    novelty = sum(observation.novelty for observation in observations) + (0.4 * len(artifacts)) + (0.5 * len(candidate_flags))
    return ActionOutcome(
        status="ok" if novelty > 0 else "failed",
        observations=observations,
        artifacts=artifacts,
        candidate_flags=candidate_flags,
        cost=1.5,
        novelty=novelty,
        failure_reason=None if novelty > 0 else "sandbox_no_output",
    )


def _extract_candidates(step: PrimitiveActionStep, bundle: TaskBundle) -> ActionOutcome:
    texts: list[str] = []
    candidate_flags: list[CandidateFlag] = []
    for obs in bundle.completed_observations.values():
        obs_text = obs.payload.get("text", "")
        if obs_text:
            texts.append(obs_text)
        texts.append(json.dumps(obs.payload, ensure_ascii=True, default=str))
    patterns = [re.compile(bundle.challenge.flag_pattern)]
    extra_patterns = step.parameters.get("patterns")
    if isinstance(extra_patterns, list):
        for p in extra_patterns:
            try:
                patterns.append(re.compile(str(p)))
            except re.error:
                continue
    for pattern in patterns:
        for text in texts:
            for match in pattern.findall(text):
                if match in bundle.known_candidate_keys:
                    continue
                candidate_flags.append(
                    CandidateFlag(
                        value=match,
                        source_chain=["extract-candidate", bundle.action_program.id],
                        confidence=0.92,
                        format_match=bool(re.fullmatch(bundle.challenge.flag_pattern, match)),
                        dedupe_key=match,
                    )
                )
    novelty = 0.6 * len(candidate_flags)
    return ActionOutcome(status="ok" if candidate_flags else "failed", candidate_flags=candidate_flags, cost=0.4, novelty=novelty, failure_reason=None if candidate_flags else "no_flag_found")


class PrimitiveRegistry:
    def __init__(self) -> None:
        specs = [
            PrimitiveActionSpec("http-request", "network/http",
                {"method": "str(GET/POST等)", "path": "str", "url": "str", "headers": "dict",
                 "json": "dict", "form": "dict", "query": "dict", "timeout": "float",
                 "auth": "dict(username/password)", "auth_type": "str(basic/bearer)",
                 "auth_token": "str", "files": "dict(field:path)", "verify_ssl": "bool"},
                {"observations": "list"}, 1.0, "low"),
            PrimitiveActionSpec("browser-inspect", "browser/dom",
                {"path": "str", "url": "str", "headers": "dict", "timeout": "float"},
                {"observations": "list"}, 1.4, "medium"),
            PrimitiveActionSpec("session-materialize", "session/state",
                {"login_url": "str", "method": "str", "form_fields": "dict",
                 "username": "str", "password": "str", "headers": "dict",
                 "json": "dict", "content_type": "str",
                 "csrf_token": "str|bool", "csrf_field": "str", "csrf_source": "str"},
                {"observations": "list"}, 1.1, "medium"),
            PrimitiveActionSpec("artifact-scan", "artifact/fs",
                {"path": "str", "url": "str", "location": "str", "preview_bytes": "int", "max_depth": "int", "max_members": "int"},
                {"artifacts": "list"}, 1.2, "low"),
            PrimitiveActionSpec("structured-parse", "text/parse",
                {"parse_source": "str(observation_id)", "format": "str(json/html/headers)", "extract_fields": "list"},
                {"observations": "list", "hypotheses": "list"}, 0.8, "low"),
            PrimitiveActionSpec("diff-compare", "compare/diff",
                {"baseline_observation_id": "str", "variant_observation_id": "str"},
                {"observations": "list"}, 0.7, "low"),
            PrimitiveActionSpec("code-sandbox", "sandbox/transform",
                {"program_fragment": "str", "inputs": "dict"},
                {"derived": "dict"}, 1.5, "medium"),
            PrimitiveActionSpec("binary-inspect", "binary/strings",
                {"path": "str", "url": "str", "location": "str", "min_length": "int", "max_strings": "int"},
                {"artifacts": "list", "observations": "list"}, 1.2, "low"),
            PrimitiveActionSpec("extract-candidate", "extract/flag",
                {"patterns": "list(regex)", "required_tags": "list"},
                {"candidate_flags": "list"}, 0.4, "low"),
        ]
        self.adapters = {spec.name: PrimitiveAdapter(spec) for spec in specs}

    def visible_primitives(self, profile: WorkerProfile) -> list[str]:
        matrix = {
            WorkerProfile.NETWORK: ["http-request", "session-materialize", "structured-parse", "diff-compare", "code-sandbox", "extract-candidate"],
            WorkerProfile.BROWSER: ["http-request", "browser-inspect", "structured-parse", "diff-compare", "code-sandbox", "extract-candidate"],
            WorkerProfile.ARTIFACT: ["artifact-scan", "structured-parse", "code-sandbox", "extract-candidate"],
            WorkerProfile.BINARY: ["binary-inspect", "structured-parse", "code-sandbox", "extract-candidate"],
            WorkerProfile.SOLVER: ["http-request", "structured-parse", "diff-compare", "code-sandbox", "extract-candidate"],
            WorkerProfile.HYBRID: list(self.adapters.keys()),
        }
        return matrix[profile]


class WorkspaceManager:
    def checkpoint(self, bundle: TaskBundle) -> dict[str, str]:
        return {"run_id": bundle.run_id, "program_id": bundle.action_program.id, "target": bundle.target}


class WorkerRuntime:
    def __init__(self, browser_config: Any | None = None, http_config: Any | None = None) -> None:
        self.registry = PrimitiveRegistry()
        self.workspace = WorkspaceManager()
        self.sandbox = CodeSandbox()
        self._browser_config = browser_config
        self._http_config = http_config

    def run_task(self, task_bundle: TaskBundle, state_service: Any | None = None, project_id: str = "") -> tuple[list[Event], ActionOutcome]:
        session_manager = HttpSessionManager()
        from .browser_adapter import build_browser_inspector_from_config
        browser_inspector = build_browser_inspector_from_config(self._browser_config)
        from .http_adapter import build_http_client_from_config
        http_client = build_http_client_from_config(self._http_config)

        # Restore session state from StateGraphService (cross-cycle persistence)
        if state_service is not None and project_id:
            session_state = getattr(state_service, 'get_session_state', lambda p: None)(project_id)
            if session_state is not None:
                for cookie_info in session_state.cookies:
                    # Reconstruct cookie with proper domain handling
                    domain = cookie_info.get('domain', '127.0.0.1')
                    path = cookie_info.get('path', '/')
                    cookie = http.cookiejar.Cookie(
                        version=0, name=cookie_info.get('name', ''), value=cookie_info.get('value', ''),
                        port=None, port_specified=False,
                        domain=domain, domain_specified=True, domain_initial_dot=False,
                        path=path, path_specified=True,
                        secure=False, expires=None, discard=True, comment=None, comment_url=None,
                        rest={}, rfc2109=False,
                    )
                    session_manager.cookie_jar.set_cookie(cookie)
                # Restore auth headers
                for name, value in session_state.auth_headers.items():
                    session_manager.add_auth_header(name, value)
        aggregate = ActionOutcome(status="failed", failure_reason="no_steps")
        events: list[Event] = []
        try:
            for step in task_bundle.action_program.steps:
                if step.primitive not in task_bundle.visible_primitives:
                    continue
                outcome = self.registry.adapters[step.primitive].execute(step, task_bundle, self.sandbox, session_manager, browser_inspector, http_client)
                aggregate.observations.extend(outcome.observations)
                aggregate.artifacts.extend(outcome.artifacts)
                aggregate.derived_hypotheses.extend(outcome.derived_hypotheses)
                aggregate.candidate_flags.extend(outcome.candidate_flags)
                aggregate.cost += outcome.cost
                aggregate.novelty += outcome.novelty
                if outcome.status == "ok":
                    aggregate.status = "ok"
                    aggregate.failure_reason = None
                elif aggregate.failure_reason is None:
                    aggregate.failure_reason = outcome.failure_reason
                for obs in outcome.observations:
                    task_bundle.completed_observations[obs.id] = obs
        finally:
            browser_inspector.close()
            http_client.close()
        for observation in aggregate.observations:
            events.append(
                Event(
                    type=EventType.OBSERVATION,
                    project_id=task_bundle.project_id,
                    run_id=task_bundle.run_id,
                    payload={
                        "id": observation.id,
                        "kind": observation.kind,
                        "description": observation.kind,
                        "source": observation.source,
                        "confidence": observation.confidence,
                        "novelty": observation.novelty,
                        "payload": observation.payload,
                        "text": observation.payload.get("text", ""),
                        "services": observation.payload.get("services", []),
                        "endpoints": observation.payload.get("endpoints", []),
                        "findings": observation.payload.get("findings", []),
                        "sessions": observation.payload.get("sessions", []),
                    },
                    source=observation.source,
                )
            )
        for artifact in aggregate.artifacts:
            events.append(
                Event(
                    type=EventType.ARTIFACT_ADDED,
                    project_id=task_bundle.project_id,
                    run_id=task_bundle.run_id,
                    payload={
                        "id": artifact.id,
                        "kind": artifact.kind,
                        "location": artifact.location,
                        "fingerprint": artifact.fingerprint,
                        "metadata": artifact.metadata,
                        "evidence_refs": artifact.evidence_refs,
                    },
                    source="runtime",
                )
            )
        for hypothesis in aggregate.derived_hypotheses:
            events.append(
                Event(
                    type=EventType.HYPOTHESIS_ADDED,
                    project_id=task_bundle.project_id,
                    run_id=task_bundle.run_id,
                    payload={
                        "id": hypothesis.id,
                        "statement": hypothesis.statement,
                        "preconditions": hypothesis.preconditions,
                        "supporting_observations": hypothesis.supporting_observations,
                        "confidence": hypothesis.confidence,
                    },
                    source="runtime",
                )
            )
        for candidate in aggregate.candidate_flags:
            events.append(
                Event(
                    type=EventType.CANDIDATE_FLAG,
                    project_id=task_bundle.project_id,
                    run_id=task_bundle.run_id,
                    payload={
                        "value": candidate.value,
                        "source_chain": candidate.source_chain,
                        "confidence": candidate.confidence,
                        "format_match": candidate.format_match,
                        "dedupe_key": candidate.dedupe_key,
                        "evidence_refs": candidate.evidence_refs,
                        "submitted": False,
                    },
                    source="runtime",
                )
            )
        events.append(
            Event(
                type=EventType.ACTION_OUTCOME,
                project_id=task_bundle.project_id,
                run_id=task_bundle.run_id,
                payload={
                    "program_id": task_bundle.action_program.id,
                    "status": aggregate.status,
                    "cost": aggregate.cost,
                    "novelty": aggregate.novelty,
                    "failure_reason": aggregate.failure_reason,
                },
                source="runtime",
            )
        )
        events.append(self.checkpoint(task_bundle))

        # Persist session state to StateGraphService (cross-cycle persistence)
        if state_service is not None and project_id:
            for obs in aggregate.observations:
                if obs.source == "session-materialize":
                    cookies_info = []
                    for cookie_str in obs.payload.get("cookies_obtained", []):
                        if "=" in cookie_str:
                            pair = cookie_str.split(";")[0].strip()
                            k, _, v = pair.partition("=")
                            cookies_info.append({"name": k.strip(), "value": v.strip(), "domain": "127.0.0.1", "path": "/"})
                    # Get any auth tokens from the observation
                    auth_token = obs.payload.get("auth_token", "")
                    auth_headers = {}
                    if auth_token:
                        auth_headers["Authorization"] = auth_token
                    from .state_graph import SessionState
                    session_state = SessionState(
                        cookies=cookies_info,
                        auth_headers=auth_headers,
                        base_url=task_bundle.target,
                        created_at="",
                    )
                    state_service.set_session_state(project_id, session_state)

        return events, aggregate

    def checkpoint(self, bundle: TaskBundle) -> Event:
        return Event(type=EventType.CHECKPOINT, project_id=bundle.project_id, run_id=bundle.run_id, payload=self.workspace.checkpoint(bundle), source="workspace_manager")


class WorkerPool:
    def __init__(self) -> None:
        self.workers = {
            "worker-network": WorkerLease(worker_id="worker-network", profile=WorkerProfile.NETWORK),
            "worker-browser": WorkerLease(worker_id="worker-browser", profile=WorkerProfile.BROWSER),
            "worker-artifact": WorkerLease(worker_id="worker-artifact", profile=WorkerProfile.ARTIFACT),
            "worker-binary": WorkerLease(worker_id="worker-binary", profile=WorkerProfile.BINARY),
            "worker-solver": WorkerLease(worker_id="worker-solver", profile=WorkerProfile.SOLVER),
            "worker-hybrid": WorkerLease(worker_id="worker-hybrid", profile=WorkerProfile.HYBRID),
        }

    def assign(self, profile: WorkerProfile, project_id: str) -> WorkerLease:
        for worker in self.workers.values():
            if worker.profile == profile and worker.healthy:
                worker.project_id = project_id
                return worker
        return WorkerLease(worker_id=f"ephemeral-{new_id('worker')}", profile=profile, project_id=project_id)
