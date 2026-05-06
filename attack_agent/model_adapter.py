from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any

from .config import ModelConfig
from .reasoning import ReasoningModel

# Lazy SDK imports — not required at module level
try:
    import openai as _openai_module
except ImportError:
    _openai_module = None  # type: ignore[assignment]

try:
    import anthropic as _anthropic_module
except ImportError:
    _anthropic_module = None  # type: ignore[assignment]


TASK_PROMPTS: dict[str, str] = {
    "select_worker_profile": (
        "你是一个渗透测试编排器。根据挑战描述，从允许列表中选择最合适的工作者配置。\n"
        "以JSON格式回复：{\"profile\": \"<配置名>\", \"reason\": \"<解释>\"}"
    ),
    "choose_program": (
        "你是一个渗透测试策略家。根据挑战上下文和候选程序，选择最佳程序。\n"
        "以JSON格式回复：{\"candidate_index\": <整数索引>, \"rationale\": \"<解释>\"}\n"
        "或：{\"family\": \"<族名>\", \"node_id\": \"<节点ID>\", \"step_primitives\": [\"<原语列表>\"], \"rationale\": \"<解释>\"}"
    ),
    "generate_constrained_plan": (
        "你是一个渗透测试规划器，在安全约束下工作。"
        "生成详细的攻击计划，严格遵守所有约束条件。\n"
        "以JSON格式回复：{\"rationale\": \"<推理过程>\", \"steps\": [{\"primitive\": \"<工具>\", \"instruction\": \"<说明>\", \"parameters\": {}}]}"
    ),
}


def is_available(provider: str) -> bool:
    """Check if the SDK for a given provider is installed."""
    if provider == "openai":
        return _openai_module is not None
    if provider == "anthropic":
        return _anthropic_module is not None
    if provider == "heuristic":
        return True
    return False


def build_model_from_config(model_config: ModelConfig) -> ReasoningModel | None:
    """Factory: create a ReasoningModel from config, or None for heuristic."""
    if model_config.provider == "heuristic":
        return None
    if model_config.provider == "openai":
        if not is_available("openai"):
            raise ImportError("openai package not installed; run: pip install attack-agent[openai]")
        return OpenAIReasoningModel(model_config)
    if model_config.provider == "anthropic":
        if not is_available("anthropic"):
            raise ImportError("anthropic package not installed; run: pip install attack-agent[anthropic]")
        return AnthropicReasoningModel(model_config)
    raise ValueError(f"unknown model provider: {model_config.provider}")


def _resolve_api_key(config: ModelConfig) -> str:
    """Resolve API key from env var or literal value."""
    if config.api_key_env:
        key = os.environ.get(config.api_key_env, "")
        if not key:
            raise ValueError(f"environment variable {config.api_key_env} not set")
        return key
    if config.api_key:
        return config.api_key
    raise ValueError("no api_key or api_key_env configured for non-heuristic provider")


def _safe_print(text: str) -> None:
    """Print text safely, replacing characters the terminal can't encode."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        safe = text.encode(encoding, errors="replace").decode(encoding)
        print(safe, flush=True)


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """Robustly extract a JSON dict from model response text."""
    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block (greedy match for nested braces)
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = -1

    raise RuntimeError("model_adapter_json_parse_failure")


class OpenAIReasoningModel:
    """OpenAI API adapter implementing ReasoningModel Protocol."""

    def __init__(self, config: ModelConfig) -> None:
        assert _openai_module is not None
        self._config = config
        api_key = _resolve_api_key(config)
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self._client = _openai_module.OpenAI(**client_kwargs, max_retries=0)
        self._model = config.model_name or "gpt-4o"

    def complete_json(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        system_prompt = TASK_PROMPTS.get(task, "Respond in JSON format.")
        if task == "generate_constrained_plan":
            user_content = str(payload.get("prompt", ""))
        else:
            user_content = json.dumps(payload, ensure_ascii=False, indent=2)

        # ── Verbose LLM trace ──────────────────────────────────────────
        banner = f"╔══ LLM CALL: {task} ══"
        _safe_print(f"\n{banner}")
        _safe_print(f"║ Model: {self._model}")
        _safe_print(f"║ System: {system_prompt[:200]}...")
        if len(user_content) > 2000:
            _safe_print(f"║ User prompt ({len(user_content)} chars, truncated):")
            _safe_print(f"║ {user_content[:1500]}...")
        else:
            _safe_print(f"║ User prompt ({len(user_content)} chars):")
            _safe_print(f"║ {user_content}")
        _safe_print(f"╚{'═' * (len(banner) - 2)}╝")
        # ────────────────────────────────────────────────────────────────

        for attempt in range(self._config.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    response_format={"type": "json_object"},
                    timeout=self._config.timeout_seconds,
                )
                text = response.choices[0].message.content or ""
                result = _extract_json_from_text(text)

                # ── Verbose LLM response trace ─────────────────────────
                _safe_print(f"\n>>> LLM RESPONSE ({task}):")
                _safe_print(f"{json.dumps(result, ensure_ascii=False, indent=2)}")
                _safe_print(f"--- end response ---\n")
                # ────────────────────────────────────────────────────────

                return result
            except _openai_module.RateLimitError:
                if attempt < self._config.max_retries:
                    time.sleep(2 ** attempt)
                else:
                    raise RuntimeError("model_adapter_rate_limit_exhausted") from None
            except _openai_module.AuthenticationError as exc:
                raise RuntimeError("model_adapter_auth_error") from exc
            except _openai_module.APIConnectionError:
                if attempt < self._config.max_retries:
                    time.sleep(2 ** attempt)
                else:
                    raise RuntimeError("model_adapter_connection_error") from None
            except Exception as exc:
                raise RuntimeError("model_adapter_error") from exc
        raise RuntimeError("model_adapter_retry_exhausted")


class AnthropicReasoningModel:
    """Anthropic (Claude) API adapter implementing ReasoningModel Protocol."""

    def __init__(self, config: ModelConfig) -> None:
        assert _anthropic_module is not None
        self._config = config
        api_key = _resolve_api_key(config)
        # Clear conflicting Anthropic env vars so SDK uses only the configured key
        for env_key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
            os.environ.pop(env_key, None)
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self._client = _anthropic_module.Anthropic(max_retries=0, **client_kwargs)
        self._model = config.model_name or "claude-sonnet-4-20250514"

    def complete_json(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        system_prompt = TASK_PROMPTS.get(task, "Respond in JSON format.")
        if task == "generate_constrained_plan":
            user_content = str(payload.get("prompt", ""))
        else:
            user_content = json.dumps(payload, ensure_ascii=False, indent=2)

        # ── Verbose LLM trace ──────────────────────────────────────────
        banner = f"╔══ LLM CALL: {task} ══"
        _safe_print(f"\n{banner}")
        _safe_print(f"║ Model: {self._model}")
        _safe_print(f"║ System: {system_prompt[:300]}")
        if len(user_content) > 2000:
            _safe_print(f"║ User prompt ({len(user_content)} chars, truncated):")
            _safe_print(f"║ {user_content[:1500]}...")
        else:
            _safe_print(f"║ User prompt ({len(user_content)} chars):")
            _safe_print(f"║ {user_content}")
        _safe_print(f"╚{'═' * (len(banner) - 2)}╝")
        # ────────────────────────────────────────────────────────────────

        for attempt in range(self._config.max_retries + 1):
            try:
                create_kwargs: dict[str, Any] = {
                    "model": self._model,
                    "max_tokens": self._config.max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_content}],
                    "timeout": self._config.timeout_seconds,
                }
                if self._config.enable_thinking:
                    create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": min(self._config.max_tokens // 3, 2048)}
                    create_kwargs["temperature"] = 1  # Required when thinking is enabled
                else:
                    create_kwargs["temperature"] = self._config.temperature
                response = self._client.messages.create(**create_kwargs)
                text = ""
                thinking_text = ""
                for block in response.content:
                    if block.type == "text":
                        text += block.text
                    elif block.type == "thinking":
                        thinking_text += getattr(block, "thinking", "") or ""

                # If thinking consumed all output budget and no text was produced,
                # re-request without thinking to get the actual JSON response.
                if not text and thinking_text and self._config.enable_thinking:
                    _safe_print("  >> Thinking consumed output budget; re-requesting without thinking")
                    no_thinking_kwargs = dict(create_kwargs)
                    no_thinking_kwargs.pop("thinking", None)
                    no_thinking_kwargs["temperature"] = self._config.temperature
                    retry_response = self._client.messages.create(**no_thinking_kwargs)
                    for block in retry_response.content:
                        if block.type == "text":
                            text += block.text

                if not text:
                    raise RuntimeError("model_adapter_empty_response")

                result = _extract_json_from_text(text)

                # ── Verbose LLM response trace ─────────────────────────
                _safe_print(f"\n>>> LLM RESPONSE ({task}):")
                _safe_print(f"{json.dumps(result, ensure_ascii=False, indent=2)}")
                _safe_print(f"--- end response ---\n")
                # ────────────────────────────────────────────────────────

                return result
            except _anthropic_module.RateLimitError:
                if attempt < self._config.max_retries:
                    time.sleep(2 ** attempt)
                else:
                    raise RuntimeError("model_adapter_rate_limit_exhausted") from None
            except _anthropic_module.AuthenticationError as exc:
                raise RuntimeError("model_adapter_auth_error") from exc
            except _anthropic_module.APIConnectionError:
                if attempt < self._config.max_retries:
                    time.sleep(2 ** attempt)
                else:
                    raise RuntimeError("model_adapter_connection_error") from None
            except Exception as exc:
                raise RuntimeError("model_adapter_error") from exc
        raise RuntimeError("model_adapter_retry_exhausted")