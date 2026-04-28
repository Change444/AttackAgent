"""Tests for CTFdCompetitionProvider."""
import json
import unittest
from typing import Any

from attack_agent.ctfd_provider import CTFdCompetitionProvider, CTFdTransportResponse
from attack_agent.platform_models import ChallengeDefinition, ChallengeInstance, HintResult, SubmissionResult


def _make_mock_transport(responses: dict[str, CTFdTransportResponse]):
    """Create a mock transport that maps (method, path) → response."""
    def transport(method: str, path: str, payload: dict[str, Any] | None = None) -> CTFdTransportResponse:
        key = f"{method} {path}"
        if key in responses:
            return responses[key]
        return CTFdTransportResponse(status=404, payload={})
    return transport


class TestCTFdListChallenges(unittest.TestCase):
    def test_list_challenges_maps_ctfd_api(self):
        provider = CTFdCompetitionProvider(
            "http://ctfd.example.com",
            api_token="test-token",
        )
        # Monkey-patch _request
        provider._request = _make_mock_transport({
            "GET /api/v1/challenges": CTFdTransportResponse(
                status=200,
                payload={
                    "data": [
                        {"id": 1, "name": "Web Login", "category": "web", "difficulty": "easy",
                         "description": "Bypass the login page"},
                        {"id": 2, "name": "Crypto RSA", "category": "crypto", "difficulty": "medium",
                         "description": "Decrypt the ciphertext"},
                    ],
                },
            ),
        })
        challenges = provider.list_challenges()
        self.assertEqual(len(challenges), 2)
        self.assertEqual(challenges[0].id, "1")
        self.assertEqual(challenges[0].name, "Web Login")
        self.assertEqual(challenges[0].category, "web")


class TestCTFdStartChallenge(unittest.TestCase):
    def test_start_challenge_synthesizes_instance(self):
        provider = CTFdCompetitionProvider(
            "http://ctfd.example.com",
            api_token="test-token",
        )
        provider._request = _make_mock_transport({
            "GET /api/v1/challenges/5": CTFdTransportResponse(
                status=200,
                payload={"data": {"id": 5, "name": "SQL Inject", "category": "web",
                                   "hostname": "http://target.example.com:8080"}},
            ),
        })
        instance = provider.start_challenge("5")
        self.assertEqual(instance.instance_id, "ctfd-5")
        self.assertEqual(instance.challenge_id, "5")
        self.assertEqual(instance.target, "http://target.example.com:8080")
        self.assertEqual(instance.status, "running")
        # Internal mapping stored
        self.assertEqual(provider._challenge_map["ctfd-5"], "5")


class TestCTFdSubmitFlag(unittest.TestCase):
    def test_submit_flag_correct(self):
        provider = CTFdCompetitionProvider(
            "http://ctfd.example.com",
            api_token="test-token",
        )
        provider._challenge_map["ctfd-1"] = "1"
        provider._request = _make_mock_transport({
            "POST /api/v1/challenges/attempt": CTFdTransportResponse(
                status=200,
                payload={"data": {"status": "correct"}},
            ),
        })
        result = provider.submit_flag("ctfd-1", "flag{test}")
        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "accepted")

    def test_submit_flag_wrong(self):
        provider = CTFdCompetitionProvider(
            "http://ctfd.example.com",
            api_token="test-token",
        )
        provider._challenge_map["ctfd-1"] = "1"
        provider._request = _make_mock_transport({
            "POST /api/v1/challenges/attempt": CTFdTransportResponse(
                status=200,
                payload={"data": {"status": "wrong", "message": "Incorrect flag"}},
            ),
        })
        result = provider.submit_flag("ctfd-1", "wrong_flag")
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "rejected")

    def test_submit_flag_unknown_instance(self):
        provider = CTFdCompetitionProvider(
            "http://ctfd.example.com",
            api_token="test-token",
        )
        result = provider.submit_flag("nonexistent", "flag{test}")
        self.assertFalse(result.accepted)


class TestCTFdStopChallenge(unittest.TestCase):
    def test_stop_challenge_is_noop(self):
        provider = CTFdCompetitionProvider("http://ctfd.example.com")
        self.assertTrue(provider.stop_challenge("ctfd-1"))


class TestCTFdRequestHint(unittest.TestCase):
    def test_request_hint_returns_description(self):
        provider = CTFdCompetitionProvider("http://ctfd.example.com", api_token="tok")
        provider._challenge_map["ctfd-3"] = "3"
        provider._request = _make_mock_transport({
            "GET /api/v1/challenges/3": CTFdTransportResponse(
                status=200,
                payload={"data": {"id": 3, "description": "Look at the cookies"}},
            ),
        })
        result = provider.request_hint(instance_id="ctfd-3")
        self.assertEqual(result.hint, "Look at the cookies")
        self.assertEqual(result.remaining, 0)

    def test_request_hint_no_challenge_id(self):
        provider = CTFdCompetitionProvider("http://ctfd.example.com")
        result = provider.request_hint(challenge_id=None, instance_id=None)
        self.assertEqual(result.hint, "no hint available")


class TestCTFdGetInstanceStatus(unittest.TestCase):
    def test_status_always_running(self):
        provider = CTFdCompetitionProvider("http://ctfd.example.com")
        self.assertEqual(provider.get_instance_status("ctfd-1"), "running")


class TestCTFdChallengeMapping(unittest.TestCase):
    def test_ctfd_challenge_to_definition(self):
        from attack_agent.ctfd_provider import _ctfd_challenge_to_definition
        item = {"id": 10, "name": "Buffer Overflow", "category": "pwn",
                "difficulty": "hard", "description": "Exploit the buffer"}
        defn = _ctfd_challenge_to_definition(item)
        self.assertEqual(defn.id, "10")
        self.assertEqual(defn.name, "Buffer Overflow")
        self.assertEqual(defn.category, "pwn")
        self.assertEqual(defn.description, "Exploit the buffer")


if __name__ == "__main__":
    unittest.main()