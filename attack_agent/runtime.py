from __future__ import annotations

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


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


@dataclass(slots=True)
class HttpSessionManager:
    cookie_jar: http.cookiejar.CookieJar = field(default_factory=http.cookiejar.CookieJar)
    max_redirects: int = 5

    def build_opener(self) -> request.OpenerDirector:
        return request.build_opener(
            request.HTTPCookieProcessor(self.cookie_jar),
            request.HTTPRedirectHandler,
        )

    def get_cookies_text(self) -> list[str]:
        return [f"{c.name}={c.value}" for c in self.cookie_jar]


@dataclass(slots=True)
class PrimitiveAdapter:
    spec: PrimitiveActionSpec

    def execute(self, step: PrimitiveActionStep, bundle: TaskBundle, sandbox: CodeSandbox, session_manager: HttpSessionManager | None = None) -> ActionOutcome:
        if step.primitive == "http-request":
            return _execute_http_request(step, bundle, session_manager)
        if step.primitive == "browser-inspect":
            return _execute_browser_inspect(step, bundle, session_manager)
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
        return _consume_metadata(step, bundle, self.spec.name)


def _match_tags(item: dict[str, object], required_tags: list[str]) -> bool:
    if not required_tags:
        return True
    tags = set(item.get("tags", []))
    return bool(tags.intersection(required_tags))


def _consume_metadata(step: PrimitiveActionStep, bundle: TaskBundle, primitive_name: str) -> ActionOutcome:
    metadata = bundle.instance.metadata
    payloads = metadata.get("primitive_payloads", {}).get(primitive_name, [])
    required_tags = list(step.parameters.get("required_tags", []))
    observations: list[Observation] = []
    artifacts: list[Artifact] = []
    hypotheses: list[Hypothesis] = []
    candidate_flags: list[CandidateFlag] = []
    total_cost = float(metadata.get("primitive_costs", {}).get(primitive_name, 1.0))
    for item in payloads:
        if not _match_tags(item, required_tags):
            continue
        item_type = str(item.get("type", "observation"))
        if item_type == "observation":
            obs_id = str(item.get("id", new_id("observation")))
            if obs_id in bundle.known_observation_ids:
                continue
            payload = dict(item.get("payload", {}))
            if "text" in item:
                payload["text"] = str(item["text"])
            observations.append(
                Observation(
                    id=obs_id,
                    kind=str(item.get("kind", primitive_name)),
                    source=primitive_name,
                    target=bundle.target,
                    payload=payload,
                    confidence=float(item.get("confidence", 0.8)),
                    novelty=float(item.get("novelty", 0.6)),
                )
            )
        elif item_type == "artifact":
            artifact_id = str(item.get("id", new_id("artifact")))
            if artifact_id in bundle.known_artifact_ids:
                continue
            metadata_payload = dict(item.get("metadata", {}))
            if "content" in item:
                metadata_payload["content"] = str(item["content"])
            artifacts.append(
                Artifact(
                    id=artifact_id,
                    kind=str(item.get("kind", "artifact")),
                    location=str(item.get("location", bundle.target)),
                    fingerprint=str(item.get("fingerprint", _hash_payload(metadata_payload))),
                    metadata=metadata_payload,
                    evidence_refs=list(item.get("evidence_refs", [])),
                )
            )
        elif item_type == "hypothesis":
            hypothesis_id = str(item.get("id", new_id("hypothesis")))
            if hypothesis_id in bundle.known_hypothesis_ids:
                continue
            hypotheses.append(
                Hypothesis(
                    id=hypothesis_id,
                    statement=str(item["statement"]),
                    preconditions=list(item.get("preconditions", [])),
                    supporting_observations=list(item.get("supporting_observations", [])),
                    confidence=float(item.get("confidence", 0.75)),
                )
            )
        elif item_type == "candidate_flag":
            key = str(item.get("dedupe_key", item.get("value", "")))
            if key in bundle.known_candidate_keys:
                continue
            value = str(item["value"])
            candidate_flags.append(
                CandidateFlag(
                    value=value,
                    source_chain=[primitive_name, bundle.action_program.id],
                    confidence=float(item.get("confidence", 0.95)),
                    format_match=bool(re.fullmatch(bundle.challenge.flag_pattern, value)),
                    dedupe_key=key,
                    evidence_refs=list(item.get("evidence_refs", [])),
                )
            )
    novelty = sum(observation.novelty for observation in observations) + (0.4 * len(artifacts)) + (0.3 * len(hypotheses)) + (0.5 * len(candidate_flags))
    return ActionOutcome(
        status="ok" if novelty > 0 else "failed",
        observations=observations,
        artifacts=artifacts,
        derived_hypotheses=hypotheses,
        candidate_flags=candidate_flags,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if novelty > 0 else "no_new_outputs",
    )


def _execute_http_request(step: PrimitiveActionStep, bundle: TaskBundle, session_manager: HttpSessionManager | None = None) -> ActionOutcome:
    request_specs = _resolve_http_request_specs(step, bundle)
    if not request_specs:
        return _consume_metadata(step, bundle, "http-request")
    observations: list[Observation] = []
    artifacts: list[Artifact] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("http-request", 1.0))
    for index, spec in enumerate(request_specs):
        try:
            response_data = _perform_http_request(spec, bundle.target, session_manager)
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


def _execute_browser_inspect(step: PrimitiveActionStep, bundle: TaskBundle, session_manager: HttpSessionManager | None = None) -> ActionOutcome:
    inspect_specs = _resolve_browser_inspect_specs(step, bundle)
    if not inspect_specs:
        return _consume_metadata(step, bundle, "browser-inspect")
    observations: list[Observation] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("browser-inspect", 1.4))
    for index, spec in enumerate(inspect_specs):
        try:
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
        return _consume_metadata(step, bundle, "binary-inspect")
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
        return _consume_metadata(step, bundle, "artifact-scan")
    observations: list[Observation] = []
    artifacts: list[Artifact] = []
    total_cost = float(bundle.instance.metadata.get("primitive_costs", {}).get("artifact-scan", 1.2))
    for index, spec in enumerate(inspect_specs):
        artifact_data = _perform_artifact_scan(spec, bundle.target, session_manager)
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
    novelty = sum(observation.novelty for observation in observations)
    return ActionOutcome(
        status="ok" if observations else "failed",
        observations=observations,
        cost=total_cost,
        novelty=novelty,
        failure_reason=None if observations else "artifact_scan_no_new_outputs",
    )


def _resolve_http_request_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    parsed_target = parse.urlparse(bundle.target)
    if parsed_target.scheme not in {"http", "https"}:
        return []
    metadata = bundle.instance.metadata
    raw_config = metadata.get("http_request")
    if raw_config is None:
        return []
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
        resolved.append(merged)
    return resolved


def _resolve_browser_inspect_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    parsed_target = parse.urlparse(bundle.target)
    if parsed_target.scheme not in {"http", "https"}:
        return []
    metadata = bundle.instance.metadata
    raw_config = metadata.get("browser_inspect")
    if raw_config is None:
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
        resolved.append(merged)
    return resolved


def _resolve_artifact_scan_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    parsed_target = parse.urlparse(bundle.target)
    if parsed_target.scheme not in {"file", "http", "https"} and _resolve_local_file_target(bundle.target) is None:
        return []
    metadata = bundle.instance.metadata
    raw_config = metadata.get("artifact_scan")
    if raw_config is None:
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
        resolved.append(merged)
    return resolved


def _resolve_binary_inspect_specs(step: PrimitiveActionStep, bundle: TaskBundle) -> list[dict[str, object]]:
    target_path = _resolve_local_file_target(bundle.target)
    if target_path is None:
        return []
    metadata = bundle.instance.metadata
    raw_config = metadata.get("binary_inspect")
    if raw_config is None:
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
        resolved.append(merged)
    return resolved


def _perform_http_request(spec: dict[str, object], default_target: str, session_manager: HttpSessionManager | None = None) -> dict[str, object]:
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
    }


def _perform_browser_inspect(spec: dict[str, object], default_target: str, session_manager: HttpSessionManager | None = None) -> dict[str, object]:
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
    parsed = _parse_html_page(html, final_url)
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
    }


def _perform_artifact_scan(spec: dict[str, object], default_target: str, session_manager: HttpSessionManager | None = None) -> dict[str, object]:
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
    }
    preview = _extract_text_preview(raw_bytes, int(spec.get("preview_bytes") or 64))
    if preview:
        payload["text_preview"] = preview
    max_depth = max(1, int(spec.get("max_depth") or 1))
    max_members = max(1, int(spec.get("max_members") or 20))
    archive_members = _extract_archive_members(resolved_path, max_depth, max_members)
    if archive_members:
        payload["archive_members"] = archive_members
    if temp_dir:
        temp_dir.cleanup()
    return payload


def _download_artifact(url: str, dest_dir: Path, session_manager: HttpSessionManager | None = None) -> Path:
    filename = parse.urlparse(url).path.split("/")[-1] or "downloaded"
    dest_path = dest_dir / filename
    opener = session_manager.build_opener() if session_manager else request.build_opener()
    with opener.open(request.Request(url), timeout=10.0) as response:
        dest_path.write_bytes(response.read())
    return dest_path


def _extract_archive_members(path: Path, max_depth: int, max_members: int) -> list[dict[str, object]] | None:
    suffix = path.suffix.lower()
    members: list[dict[str, object]] = []
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist()[:max_members]:
                    if info.is_dir():
                        continue
                    members.append({"name": info.filename, "size_bytes": info.file_size, "compressed_size": info.compress_size})
        except zipfile.BadZipFile:
            return None
    elif suffix in {".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2"}:
        try:
            with tarfile.open(path) as tf:
                for member in tf.getmembers()[:max_members]:
                    if not member.isfile():
                        continue
                    members.append({"name": member.name, "size_bytes": member.size})
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

    def __init__(self, base_url: str) -> None:
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
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


def _parse_html_page(html: str, base_url: str) -> dict[str, object]:
    parser = _HTMLPageParser(base_url)
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
    }


def _execute_session_materialize(step: PrimitiveActionStep, bundle: TaskBundle, session_manager: HttpSessionManager | None = None) -> ActionOutcome:
    session_config = _resolve_session_materialize_specs(step, bundle)
    if not session_config:
        return _consume_metadata(step, bundle, "session-materialize")
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
        body = parse.urlencode({str(k): str(v) for k, v in form_fields.items()}).encode("utf-8")
        req = request.Request(login_url, data=body, method=method)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        for key, value in dict(spec.get("headers", {}) or {}).items():
            req.add_header(str(key), str(value))
        timeout = float(spec.get("timeout") or 5.0)
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
    metadata = bundle.instance.metadata
    raw_config = metadata.get("session_materialize")
    if raw_config is None:
        return []
    if isinstance(raw_config, dict):
        if raw_config.get("enabled", True) is False:
            return []
        return [raw_config]
    if isinstance(raw_config, list):
        return [item for item in raw_config if isinstance(item, dict)]
    return []


def _execute_structured_parse(step: PrimitiveActionStep, bundle: TaskBundle) -> ActionOutcome:
    parse_source = step.parameters.get("parse_source")
    fmt = step.parameters.get("format")
    if parse_source is None or fmt is None:
        return _consume_metadata(step, bundle, "structured-parse")
    source_id = str(parse_source)
    source_obs = bundle.completed_observations.get(source_id)
    if source_obs is None:
        for item in bundle.instance.metadata.get("primitive_payloads", {}).get("structured-parse", []):
            if str(item.get("id", "")) == source_id:
                source_obs = Observation(
                    id=source_id, kind="metadata", source="structured-parse",
                    target=bundle.target, payload=dict(item.get("payload", {})),
                    confidence=0.8, novelty=0.6,
                )
                break
    if source_obs is None:
        return _consume_metadata(step, bundle, "structured-parse")
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
    if fmt == "json":
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                result["parsed_data"] = parsed
                if extract_fields:
                    result["extracted"] = {f: parsed.get(f) for f in extract_fields if f in parsed}
                result["potential_secrets"] = [
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
        return _consume_metadata(step, bundle, "diff-compare")
    baseline_text = _get_observation_text(str(baseline_id), bundle)
    variant_text = _get_observation_text(str(variant_id), bundle)
    if baseline_text is None or variant_text is None:
        return _consume_metadata(step, bundle, "diff-compare")
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
    for item in bundle.instance.metadata.get("primitive_payloads", {}).get("diff-compare", []):
        if str(item.get("id", "")) == obs_id:
            payload = item.get("payload", {})
            if isinstance(payload, dict):
                return payload.get("text", json.dumps(payload, ensure_ascii=True, default=str))
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
    limit = max(0, min(preview_bytes, 128))
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
    result = sandbox.execute(program_fragment, inputs)
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
                    fingerprint=str(artifact_payload.get("fingerprint", _hash_payload(artifact_payload))),
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
    for item in bundle.instance.metadata.get("primitive_payloads", {}).get("extract-candidate", []):
        if not _match_tags(item, list(step.parameters.get("required_tags", []))):
            continue
        if item.get("type") == "candidate_flag" and "value" in item:
            value = str(item["value"])
            key = str(item.get("dedupe_key", value))
            if key in bundle.known_candidate_keys:
                continue
            candidate_flags.append(
                CandidateFlag(
                    value=value,
                    source_chain=["extract-candidate", bundle.action_program.id],
                    confidence=float(item.get("confidence", 0.95)),
                    format_match=bool(re.fullmatch(bundle.challenge.flag_pattern, value)),
                    dedupe_key=key,
                    evidence_refs=list(item.get("evidence_refs", [])),
                )
            )
            continue
        if "value" in item:
            texts.append(str(item["value"]))
    for group in bundle.instance.metadata.get("primitive_payloads", {}).values():
        for row in group:
            if "text" in row:
                texts.append(str(row["text"]))
            payload = row.get("payload", {})
            if isinstance(payload, dict):
                texts.append(json.dumps(payload, ensure_ascii=True, default=str))
            metadata = row.get("metadata", {})
            if isinstance(metadata, dict):
                texts.append(json.dumps(metadata, ensure_ascii=True, default=str))
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
            PrimitiveActionSpec("http-request", "network/http", {"request": "dict"}, {"observations": "list"}, 1.0, "low"),
            PrimitiveActionSpec("browser-inspect", "browser/dom", {"request": "dict"}, {"observations": "list"}, 1.4, "medium"),
            PrimitiveActionSpec("session-materialize", "session/state", {"request": "dict"}, {"observations": "list"}, 1.1, "medium"),
            PrimitiveActionSpec("artifact-scan", "artifact/fs", {"request": "dict"}, {"artifacts": "list"}, 1.2, "low"),
            PrimitiveActionSpec("structured-parse", "text/parse", {"blob": "dict"}, {"observations": "list", "hypotheses": "list"}, 0.8, "low"),
            PrimitiveActionSpec("diff-compare", "compare/diff", {"baseline": "dict", "variant": "dict"}, {"observations": "list"}, 0.7, "low"),
            PrimitiveActionSpec("code-sandbox", "sandbox/transform", {"program_fragment": "str", "inputs": "dict"}, {"derived": "dict"}, 1.5, "medium"),
            PrimitiveActionSpec("binary-inspect", "binary/strings", {"blob": "dict"}, {"artifacts": "list", "observations": "list"}, 1.2, "low"),
            PrimitiveActionSpec("extract-candidate", "extract/flag", {"texts": "list"}, {"candidate_flags": "list"}, 0.4, "low"),
        ]
        self.adapters = {spec.name: PrimitiveAdapter(spec) for spec in specs}

    def visible_primitives(self, profile: WorkerProfile) -> list[str]:
        matrix = {
            WorkerProfile.NETWORK: ["http-request", "session-materialize", "structured-parse", "diff-compare", "code-sandbox", "extract-candidate"],
            WorkerProfile.BROWSER: ["http-request", "browser-inspect", "structured-parse", "diff-compare", "code-sandbox", "extract-candidate"],
            WorkerProfile.ARTIFACT: ["artifact-scan", "structured-parse", "code-sandbox", "extract-candidate"],
            WorkerProfile.BINARY: ["binary-inspect", "structured-parse", "code-sandbox", "extract-candidate"],
            WorkerProfile.SOLVER: ["structured-parse", "diff-compare", "code-sandbox", "extract-candidate"],
            WorkerProfile.HYBRID: list(self.adapters.keys()),
        }
        return matrix[profile]


class WorkspaceManager:
    def checkpoint(self, bundle: TaskBundle) -> dict[str, str]:
        return {"run_id": bundle.run_id, "program_id": bundle.action_program.id, "target": bundle.target}


class WorkerRuntime:
    def __init__(self) -> None:
        self.registry = PrimitiveRegistry()
        self.workspace = WorkspaceManager()
        self.sandbox = CodeSandbox()

    def run_task(self, task_bundle: TaskBundle) -> tuple[list[Event], ActionOutcome]:
        session_manager = HttpSessionManager()
        aggregate = ActionOutcome(status="failed", failure_reason="no_steps")
        events: list[Event] = []
        for step in task_bundle.action_program.steps:
            if step.primitive not in task_bundle.visible_primitives:
                continue
            outcome = self.registry.adapters[step.primitive].execute(step, task_bundle, self.sandbox, session_manager)
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
