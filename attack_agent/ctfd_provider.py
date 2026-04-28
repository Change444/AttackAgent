"""CTFd CompetitionProvider — connect AttackAgent to real CTFd platforms.

Supports two auth methods:
- Session auth: POST /login with username/password → session cookie
- API token: Authorization: Bearer <token> header

CTFd API mapping:
- list_challenges → GET /api/v1/challenges
- start_challenge → GET /api/v1/challenges/{id} + synthesize ChallengeInstance
- stop_challenge → no-op (CTFd has no start/stop concept for challenges)
- submit_flag → POST /api/v1/challenges/attempt with challenge_id + submission
- request_hint → fallback: return challenge description or "no hint available"
- get_instance_status → always return "running"
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any
from urllib import error, request

from .platform_models import ChallengeDefinition, ChallengeInstance, HintResult, SubmissionResult


@dataclass(slots=True)
class CTFdTransportResponse:
    status: int
    payload: dict[str, Any]


class CTFdCompetitionProvider:
    """CompetitionProvider adapter for CTFd platforms."""

    def __init__(self, base_url: str,
                 username: str | None = None,
                 password: str | None = None,
                 api_token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._cookie_jar = CookieJar()
        self._instances: dict[str, ChallengeInstance] = {}
        self._challenge_map: dict[str, str] = {}  # instance_id → challenge_id

        if username and password:
            self._login(username, password)

    def list_challenges(self) -> list[ChallengeDefinition]:
        resp = self._request("GET", "/api/v1/challenges")
        items = resp.payload.get("data", [])
        return [_ctfd_challenge_to_definition(item) for item in items]

    def start_challenge(self, challenge_id: str) -> ChallengeInstance:
        resp = self._request("GET", f"/api/v1/challenges/{challenge_id}")
        data = resp.payload.get("data", {})
        instance_id = f"ctfd-{challenge_id}"
        target = data.get("hostname", "") or data.get("connection_info", "") or ""
        instance = ChallengeInstance(
            instance_id=instance_id,
            challenge_id=challenge_id,
            target=target,
            status="running",
            metadata=dict(data),
        )
        self._instances[instance_id] = instance
        self._challenge_map[instance_id] = challenge_id
        return instance

    def stop_challenge(self, instance_id: str) -> bool:
        return True

    def submit_flag(self, instance_id: str, flag: str) -> SubmissionResult:
        challenge_id = self._challenge_map.get(instance_id, "")
        if not challenge_id:
            return SubmissionResult(accepted=False, message="unknown instance", status="rejected")
        resp = self._request("POST", "/api/v1/challenges/attempt", {
            "challenge_id": challenge_id,
            "submission": flag,
        })
        data = resp.payload.get("data", {})
        status_val = data.get("status", "")
        accepted = status_val == "correct"
        message = "accepted" if accepted else data.get("message", "wrong flag")
        return SubmissionResult(
            accepted=accepted,
            message=message,
            status="accepted" if accepted else "rejected",
        )

    def request_hint(self, challenge_id: str | None = None,
                      instance_id: str | None = None) -> HintResult:
        if challenge_id is None and instance_id is not None:
            challenge_id = self._challenge_map.get(instance_id)
        if challenge_id is None:
            return HintResult(hint="no hint available", remaining=0)
        resp = self._request("GET", f"/api/v1/challenges/{challenge_id}")
        data = resp.payload.get("data", {})
        hint_text = data.get("description", "") or "no hint available"
        return HintResult(hint=hint_text, remaining=0)

    def get_instance_status(self, instance_id: str) -> str:
        return "running"

    def _login(self, username: str, password: str) -> None:
        """Session auth via CTFd login endpoint."""
        self._request("POST", "/login", {
            "name": username,
            "password": password,
        })

    def _request(self, method: str, path: str,
                 payload: dict[str, Any] | None = None) -> CTFdTransportResponse:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}{path}"
        req = request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")

        if self._api_token:
            req.add_header("Authorization", f"Bearer {self._api_token}")

        opener = request.build_opener(request.HTTPCookieProcessor(self._cookie_jar))
        try:
            with opener.open(req, timeout=15) as response:
                body = response.read().decode("utf-8")
                return CTFdTransportResponse(
                    status=response.status,
                    payload=json.loads(body) if body else {},
                )
        except TimeoutError as exc:
            raise RuntimeError("provider_timeout") from exc
        except error.HTTPError as exc:
            raise RuntimeError(f"provider_http_{exc.code}") from exc
        except error.URLError as exc:
            raise RuntimeError("provider_unavailable") from exc


def _ctfd_challenge_to_definition(item: dict[str, Any]) -> ChallengeDefinition:
    """Map a CTFd challenge API item to ChallengeDefinition."""
    return ChallengeDefinition(
        id=str(item.get("id", "")),
        name=item.get("name", ""),
        category=item.get("category", "unknown"),
        difficulty=item.get("difficulty", ""),
        target=item.get("hostname", "") or item.get("connection_info", "") or "",
        description=item.get("description", ""),
        flag_pattern=r"flag\{[^}]+\}",
        metadata=dict(item),
    )