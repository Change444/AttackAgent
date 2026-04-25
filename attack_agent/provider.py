from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib import error, request

from .platform_models import ChallengeDefinition, ChallengeInstance, HintResult, SubmissionResult


class CompetitionProvider(Protocol):
    def list_challenges(self) -> list[ChallengeDefinition]:
        ...

    def start_challenge(self, challenge_id: str) -> ChallengeInstance:
        ...

    def stop_challenge(self, instance_id: str) -> bool:
        ...

    def submit_flag(self, instance_id: str, flag: str) -> SubmissionResult:
        ...

    def request_hint(self, challenge_id: str | None = None, instance_id: str | None = None) -> HintResult:
        ...

    def get_instance_status(self, instance_id: str) -> str:
        ...


@dataclass(slots=True)
class TransportResponse:
    status: int
    payload: dict[str, Any]


class LocalHTTPCompetitionProvider:
    def __init__(self, base_url: str, transport: Callable[[str, str, dict[str, Any] | None], TransportResponse] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or self._urllib_transport

    def list_challenges(self) -> list[ChallengeDefinition]:
        response = self.transport("GET", "/challenges", None)
        return [ChallengeDefinition(**item) for item in response.payload.get("items", [])]

    def start_challenge(self, challenge_id: str) -> ChallengeInstance:
        response = self.transport("POST", "/start_challenge", {"challenge_id": challenge_id})
        return ChallengeInstance(**response.payload["instance"])

    def stop_challenge(self, instance_id: str) -> bool:
        response = self.transport("POST", "/stop_challenge", {"instance_id": instance_id})
        return bool(response.payload.get("stopped", False))

    def submit_flag(self, instance_id: str, flag: str) -> SubmissionResult:
        response = self.transport("POST", "/submit", {"instance_id": instance_id, "flag": flag})
        return SubmissionResult(**response.payload)

    def request_hint(self, challenge_id: str | None = None, instance_id: str | None = None) -> HintResult:
        payload = {"challenge_id": challenge_id, "instance_id": instance_id}
        response = self.transport("POST", "/hint", payload)
        return HintResult(**response.payload)

    def get_instance_status(self, instance_id: str) -> str:
        response = self.transport("GET", f"/status/{instance_id}", None)
        return str(response.payload.get("status", "unknown"))

    def _urllib_transport(self, method: str, path: str, payload: dict[str, Any] | None) -> TransportResponse:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(f"{self.base_url}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with request.urlopen(req, timeout=10) as response:
                body = response.read().decode("utf-8")
                return TransportResponse(status=response.status, payload=json.loads(body) if body else {})
        except TimeoutError as exc:
            raise RuntimeError("provider_timeout") from exc
        except error.HTTPError as exc:
            raise RuntimeError(f"provider_http_{exc.code}") from exc
        except error.URLError as exc:
            raise RuntimeError("provider_unavailable") from exc


class InMemoryCompetitionProvider:
    def __init__(self, challenges: list[ChallengeDefinition]) -> None:
        self.challenges = {challenge.id: challenge for challenge in challenges}
        self.instances: dict[str, ChallengeInstance] = {}
        self.hint_budget: dict[str, int] = {challenge.id: int(challenge.metadata.get("hint_budget", 2)) for challenge in challenges}

    def list_challenges(self) -> list[ChallengeDefinition]:
        return list(self.challenges.values())

    def start_challenge(self, challenge_id: str) -> ChallengeInstance:
        challenge = self.challenges[challenge_id]
        instance = ChallengeInstance(
            instance_id=f"instance-{challenge_id}",
            challenge_id=challenge_id,
            target=challenge.target,
            status="running",
            metadata=dict(challenge.metadata),
        )
        self.instances[instance.instance_id] = instance
        return instance

    def stop_challenge(self, instance_id: str) -> bool:
        instance = self.instances[instance_id]
        instance.status = "stopped"
        return True

    def submit_flag(self, instance_id: str, flag: str) -> SubmissionResult:
        instance = self.instances[instance_id]
        challenge = self.challenges[instance.challenge_id]
        expected = str(challenge.metadata.get("flag", ""))
        accepted = flag == expected
        return SubmissionResult(
            accepted=accepted,
            message="accepted" if accepted else "wrong flag",
            status="accepted" if accepted else "rejected",
        )

    def request_hint(self, challenge_id: str | None = None, instance_id: str | None = None) -> HintResult:
        if challenge_id is None and instance_id is not None:
            challenge_id = self.instances[instance_id].challenge_id
        assert challenge_id is not None
        challenge = self.challenges[challenge_id]
        remaining = max(0, self.hint_budget[challenge_id] - 1)
        self.hint_budget[challenge_id] = remaining
        return HintResult(hint=str(challenge.metadata.get("hint", "no hint")), remaining=remaining)

    def get_instance_status(self, instance_id: str) -> str:
        return self.instances[instance_id].status
