"""Tests for ObservationSummarizer: payload summarization with budget constraints."""
from __future__ import annotations

import unittest

from attack_agent.observation_summarizer import (
    ObservationSummarizer,
    ObservationSummarizerConfig,
)
from attack_agent.platform_models import Observation


def _make_obs(kind: str, payload: dict, novelty: float = 0.6, confidence: float = 0.8) -> Observation:
    return Observation(
        id=f"obs-{kind}",
        kind=kind,
        source="test",
        target="http://127.0.0.1:8000",
        payload=payload,
        confidence=confidence,
        novelty=novelty,
    )


class TestObservationSummarizerHTTPResponse(unittest.TestCase):
    def test_http_response_key_fields(self):
        obs = _make_obs("http-response", {
            "url": "http://127.0.0.1:8000/login",
            "method": "POST",
            "status_code": 200,
            "endpoints": [{"path": "/login"}, {"path": "/admin"}, {"path": "/secret"}],
            "forms": [{"action": "/login", "method": "POST", "inputs": ["username", "password"]}],
            "auth_clues": ["login_form", "password_field"],
            "cookies": ["session=abc123"],
            "text": "Welcome to the login page",
        })
        summarizer = ObservationSummarizer()
        result = summarizer.summarize_single(obs, 400)
        self.assertIn("[http-response]", result)
        self.assertIn("/login", result)
        self.assertIn("POST", result)
        self.assertIn("200", result)
        self.assertIn("endpoints:", result)
        self.assertIn("forms:", result)
        self.assertIn("auth_clues:", result)

    def test_http_response_text_truncation(self):
        long_text = "A" * 500
        obs = _make_obs("http-response", {
            "url": "http://127.0.0.1:8000/",
            "method": "GET",
            "status_code": 200,
            "text": long_text,
        })
        config = ObservationSummarizerConfig(text_truncate_chars=100)
        summarizer = ObservationSummarizer(config)
        result = summarizer.summarize_single(obs, 400)
        self.assertNotIn("A" * 200, result)


class TestObservationSummarizerBrowserPage(unittest.TestCase):
    def test_browser_page_summary(self):
        obs = _make_obs("browser-page", {
            "url": "http://127.0.0.1:8000/",
            "title": "Test Page",
            "comments": ["<!-- admin panel -->"],
            "links": [{"path": "/admin"}, {"path": "/secret"}],
            "forms": [{"action": "/login", "method": "POST", "inputs": ["username"]}],
        })
        summarizer = ObservationSummarizer()
        result = summarizer.summarize_single(obs, 400)
        self.assertIn("[browser-page]", result)
        self.assertIn("Test Page", result)
        self.assertIn("comments:", result)
        self.assertIn("admin panel", result)


class TestObservationSummarizerSessionMaterialized(unittest.TestCase):
    def test_session_materialized_summary(self):
        obs = _make_obs("session-materialized", {
            "login_url": "http://127.0.0.1:8000/login",
            "status_code": 200,
            "session_type": "cookie",
            "valid": True,
            "cookies_obtained": ["session=abc"],
        })
        summarizer = ObservationSummarizer()
        result = summarizer.summarize_single(obs, 400)
        self.assertIn("[session-materialized]", result)
        self.assertIn("cookies_obtained:", result)


class TestObservationSummarizerUnknownKind(unittest.TestCase):
    def test_unknown_kind_generic_summary(self):
        obs = _make_obs("custom-kind", {
            "key1": "value1",
            "text": "some content here",
        })
        summarizer = ObservationSummarizer()
        result = summarizer.summarize_single(obs, 400)
        self.assertIn("some content here", result)


class TestObservationSummarizerBudget(unittest.TestCase):
    def test_multiple_observations_sorted_and_limited(self):
        observations = {
            "obs-1": _make_obs("http-response", {"url": "http://x/", "method": "GET", "status_code": 200, "text": "low novelty"}, novelty=0.2, confidence=0.5),
            "obs-2": _make_obs("http-response", {"url": "http://y/", "method": "POST", "status_code": 302, "text": "high novelty"}, novelty=0.9, confidence=0.9),
            "obs-3": _make_obs("browser-page", {"url": "http://z/", "title": "Page", "text": "mid"}, novelty=0.5, confidence=0.7),
        }
        config = ObservationSummarizerConfig(max_observations=2, max_total_chars=500)
        summarizer = ObservationSummarizer(config)
        result = summarizer.summarize_observations(observations)
        # obs-2 (novelty=0.9) should appear first
        self.assertIn("http://y/", result)
        # obs-1 (novelty=0.2) should be omitted due to max_observations=2
        self.assertNotIn("http://x/", result)

    def test_total_chars_budget_respected(self):
        observations = {
            "obs-1": _make_obs("http-response", {"url": "http://a/", "method": "GET", "status_code": 200, "text": "x" * 100}),
            "obs-2": _make_obs("http-response", {"url": "http://b/", "method": "GET", "status_code": 200, "text": "y" * 100}),
        }
        config = ObservationSummarizerConfig(max_total_chars=200, max_per_observation_chars=100)
        summarizer = ObservationSummarizer(config)
        result = summarizer.summarize_observations(observations)
        self.assertLessEqual(len(result), 200)

    def test_empty_observations(self):
        summarizer = ObservationSummarizer()
        result = summarizer.summarize_observations({})
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()