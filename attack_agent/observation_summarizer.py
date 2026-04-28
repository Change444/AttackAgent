"""Observation summarizer: compresses observation payloads into bounded-length
text suitable for LLM prompt injection, respecting token budget constraints."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .platform_models import Observation


@dataclass(slots=True)
class ObservationSummarizerConfig:
    max_total_chars: int = 2000
    max_per_observation_chars: int = 400
    max_observations: int = 5
    text_truncate_chars: int = 200
    max_list_items: int = 5


class ObservationSummarizer:
    """Summarize observation payloads into compact text for LLM prompts."""

    def __init__(self, config: ObservationSummarizerConfig | None = None) -> None:
        self.config = config or ObservationSummarizerConfig()

    def summarize_observations(self, observations: dict[str, Observation]) -> str:
        """Summarize up to max_observations, sorted by novelty/confidence."""
        if not observations:
            return ""
        sorted_obs = sorted(
            observations.values(),
            key=lambda o: (-o.novelty, -o.confidence),
        )
        selected = sorted_obs[:self.config.max_observations]
        per_budget = min(
            self.config.max_per_observation_chars,
            self.config.max_total_chars // max(len(selected), 1),
        )
        parts: list[str] = []
        total_used = 0
        sep_len = 1  # "\n" separator between parts
        for obs in selected:
            summary = self.summarize_single(obs, per_budget)
            added = len(summary) + (sep_len if parts else 0)
            if total_used + added > self.config.max_total_chars:
                break
            parts.append(summary)
            total_used += added
        return "\n".join(parts)

    def summarize_single(self, obs: Observation, budget: int) -> str:
        """Dispatch to kind-specific summarizer."""
        dispatch = {
            "http-response": self._summarize_http_response,
            "browser-page": self._summarize_browser_page,
            "session-materialized": self._summarize_session_materialized,
            "parsed-data": self._summarize_parsed,
            "diff-result": self._summarize_diff_result,
            "artifact-file": self._summarize_artifact_file,
            "binary-strings": self._summarize_binary_strings,
            "sandbox-output": self._summarize_sandbox_output,
        }
        handler = dispatch.get(obs.kind, self._generic_summarize)
        result = handler(obs.payload, budget)
        return self._truncate(result, budget)

    def _truncate(self, text: str, budget: int) -> str:
        if len(text) <= budget:
            return text
        return text[:budget - 3] + "..."

    def _short_list(self, items: list[str], max_items: int) -> str:
        if not items:
            return ""
        trimmed = items[:max_items]
        suffix = f" (+{len(items) - max_items} more)" if len(items) > max_items else ""
        return ", ".join(trimmed) + suffix

    def _short_text(self, text: str | None, limit: int) -> str:
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[:limit - 3] + "..."

    # ── Kind-specific summarizers ──

    def _summarize_http_response(self, payload: dict, budget: int) -> str:
        parts: list[str] = []
        url = payload.get("url", "")
        method = payload.get("method", "")
        status = payload.get("status_code", "")
        parts.append(f"[http-response] {url} {method} {status}")

        endpoints = payload.get("endpoints", [])
        if endpoints:
            paths = [str(e.get("path", "")) for e in endpoints if e.get("path")]
            ep_str = self._short_list(paths, self.config.max_list_items)
            parts.append(f"endpoints: {ep_str}")

        forms = payload.get("forms", [])
        if forms:
            form_strs = []
            for f in forms[:self.config.max_list_items]:
                action = f.get("action", "")
                method_f = f.get("method", "")
                inputs = list(f.get("inputs", []))[:3]
                form_strs.append(f"{method_f} {action} [{','.join(inputs)}]")
            parts.append(f"forms: {', '.join(form_strs)}")

        auth_clues = payload.get("auth_clues", [])
        if auth_clues:
            parts.append(f"auth_clues: {self._short_list([str(a) for a in auth_clues], self.config.max_list_items)}")

        cookies = payload.get("cookies", [])
        if cookies:
            parts.append(f"cookies: {self._short_list([str(c) for c in cookies], 3)}")

        text = payload.get("text", "")
        if text:
            parts.append(f"text({len(text)}chars): {self._short_text(str(text), self.config.text_truncate_chars)}")

        findings = payload.get("findings", [])
        if findings:
            parts.append(f"findings: {self._short_list([str(f.get('title', f)) for f in findings], self.config.max_list_items)}")

        return "\n".join(parts)

    def _summarize_browser_page(self, payload: dict, budget: int) -> str:
        parts: list[str] = []
        url = payload.get("url", "")
        title = payload.get("title", "")
        parts.append(f"[browser-page] {url} title: {title}")

        comments = payload.get("comments", [])
        if comments:
            parts.append(f"comments: {self._short_list([str(c) for c in comments], self.config.max_list_items)}")

        links = payload.get("links", [])
        if links:
            link_strs = [str(l.get("path", l)) for l in links if l.get("path")]
            parts.append(f"links: {self._short_list(link_strs, self.config.max_list_items)}")

        forms = payload.get("forms", [])
        if forms:
            form_strs = []
            for f in forms[:self.config.max_list_items]:
                action = f.get("action", "")
                method = f.get("method", "")
                inputs = list(f.get("inputs", []))[:3]
                form_strs.append(f"{method} {action} [{','.join(inputs)}]")
            parts.append(f"forms: {', '.join(form_strs)}")

        rendered = payload.get("rendered_text", "")
        if rendered:
            parts.append(f"rendered({len(str(rendered))}chars): {self._short_text(str(rendered), self.config.text_truncate_chars)}")

        return "\n".join(parts)

    def _summarize_session_materialized(self, payload: dict, budget: int) -> str:
        parts: list[str] = []
        login_url = payload.get("login_url", "")
        status = payload.get("status_code", "")
        session_type = payload.get("session_type", "")
        valid = payload.get("valid", "")
        parts.append(f"[session-materialized] {login_url} {status} type={session_type} valid={valid}")

        cookies = payload.get("cookies_obtained", [])
        if cookies:
            parts.append(f"cookies_obtained: {self._short_list([str(c) for c in cookies], 3)}")

        token = payload.get("auth_token", "")
        if token:
            parts.append(f"token: {self._short_text(str(token), 50)}")

        return "\n".join(parts)

    def _summarize_parsed(self, payload: dict, budget: int) -> str:
        parts: list[str] = []
        fmt = payload.get("format", "")
        parts.append(f"[parsed-{fmt}]")

        keys = [k for k in payload.keys() if k not in ("format", "text")]
        if keys:
            parts.append(f"keys: {self._short_list(keys, self.config.max_list_items)}")

        secrets = payload.get("potential_secrets", [])
        if secrets:
            parts.append(f"secrets: {self._short_list([str(s) for s in secrets], 3)}")

        text = payload.get("text", "")
        if text:
            parts.append(f"content: {self._short_text(str(text), self.config.text_truncate_chars)}")

        return "\n".join(parts)

    def _summarize_diff_result(self, payload: dict, budget: int) -> str:
        parts: list[str] = []
        summary = payload.get("summary", "")
        change_count = payload.get("change_count", "")
        parts.append(f"[diff-result] {summary} changes={change_count}")

        added = payload.get("added_lines", [])
        if added:
            parts.append(f"added: {self._short_list([str(l) for l in added], 3)}")
        removed = payload.get("removed_lines", [])
        if removed:
            parts.append(f"removed: {self._short_list([str(l) for l in removed], 3)}")

        return "\n".join(parts)

    def _summarize_artifact_file(self, payload: dict, budget: int) -> str:
        parts: list[str] = []
        name = payload.get("name", "")
        suffix = payload.get("suffix", "")
        size = payload.get("size_bytes", "")
        parts.append(f"[artifact-file] {name}.{suffix} size={size}")

        members = payload.get("archive_members", [])
        if members:
            member_names = [str(m.get("name", m)) for m in members]
            parts.append(f"members: {self._short_list(member_names, self.config.max_list_items)}")

        preview = payload.get("text_preview", "")
        if preview:
            parts.append(f"preview: {self._short_text(str(preview), self.config.text_truncate_chars)}")

        return "\n".join(parts)

    def _summarize_binary_strings(self, payload: dict, budget: int) -> str:
        parts: list[str] = []
        path = payload.get("path", "")
        size = payload.get("size_bytes", "")
        headers = payload.get("headers", {})
        header_fmt = headers.get("format", "") if isinstance(headers, dict) else ""
        parts.append(f"[binary-strings] {path} size={size} format={header_fmt}")

        strings = payload.get("strings", [])
        if strings:
            parts.append(f"top_strings: {self._short_list([str(s) for s in strings[:5]], 5)}")

        return "\n".join(parts)

    def _summarize_sandbox_output(self, payload: dict, budget: int) -> str:
        text = payload.get("text", "")
        return f"[sandbox-output] {self._short_text(str(text) if text else '', self.config.text_truncate_chars)}"

    def _generic_summarize(self, payload: dict, budget: int) -> str:
        top_keys = list(payload.keys())
        text = payload.get("text", "")
        if text:
            preview = self._short_text(str(text), self.config.text_truncate_chars)
            return f"[{top_keys[:5]}] {preview}"
        dump = json.dumps(payload, default=str, ensure_ascii=False)
        return self._truncate(dump, budget)