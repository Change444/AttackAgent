"""Tests for IOContextProvider — L8."""

import unittest

from attack_agent.config import BrowserConfig, HttpConfig
from attack_agent.runtime import HttpSessionManager
from attack_agent.team.io_context import (
    IOContextProvider,
    NullIOContextProvider,
    WorkerRuntimeIOContextProvider,
)


class TestNullIOContextProvider(unittest.TestCase):

    def setUp(self):
        self.provider = NullIOContextProvider()

    def test_get_session_manager_returns_none(self):
        result = self.provider.get_session_manager("p1", "s1")
        self.assertIsNone(result)

    def test_get_browser_inspector_returns_none(self):
        result = self.provider.get_browser_inspector("p1", "s1")
        self.assertIsNone(result)

    def test_get_http_client_returns_none(self):
        result = self.provider.get_http_client("p1", "s1")
        self.assertIsNone(result)

    def test_release_context_is_noop(self):
        self.provider.release_context("p1", "s1")


class TestWorkerRuntimeIOContextProvider(unittest.TestCase):

    def setUp(self):
        self.provider = WorkerRuntimeIOContextProvider(
            browser_config=BrowserConfig(engine="stdlib"),
            http_config=HttpConfig(engine="stdlib"),
        )

    def tearDown(self):
        # Release all cached contexts
        for key in list(self.provider._cache.keys()):
            self.provider.release_context(*key)

    def test_get_session_manager_returns_http_session(self):
        sm = self.provider.get_session_manager("p1", "s1")
        self.assertIsInstance(sm, HttpSessionManager)

    def test_get_session_manager_caches_per_project_solver(self):
        sm1 = self.provider.get_session_manager("p1", "s1")
        sm2 = self.provider.get_session_manager("p1", "s1")
        self.assertIs(sm1, sm2)

    def test_different_keys_get_different_sessions(self):
        sm1 = self.provider.get_session_manager("p1", "s1")
        sm2 = self.provider.get_session_manager("p1", "s2")
        self.assertIsNot(sm1, sm2)

    def test_get_browser_inspector_returns_object(self):
        inspector = self.provider.get_browser_inspector("p1", "s1")
        self.assertIsNotNone(inspector)

    def test_get_browser_inspector_caches(self):
        i1 = self.provider.get_browser_inspector("p1", "s1")
        i2 = self.provider.get_browser_inspector("p1", "s1")
        self.assertIs(i1, i2)

    def test_get_http_client_returns_object(self):
        client = self.provider.get_http_client("p1", "s1")
        self.assertIsNotNone(client)

    def test_get_http_client_caches(self):
        c1 = self.provider.get_http_client("p1", "s1")
        c2 = self.provider.get_http_client("p1", "s1")
        self.assertIs(c1, c2)

    def test_release_context_removes_cache(self):
        self.provider.get_session_manager("p1", "s1")
        self.provider.release_context("p1", "s1")
        self.assertNotIn(("p1", "s1"), self.provider._cache)

    def test_release_context_calls_close_on_browser(self):
        inspector = self.provider.get_browser_inspector("p1", "s1")
        close_called = False
        if hasattr(inspector, "close"):
            original_close = inspector.close
            def tracked_close():
                nonlocal close_called
                close_called = True
                original_close()
            inspector.close = tracked_close
        self.provider.release_context("p1", "s1")
        self.assertTrue(close_called)

    def test_release_context_noop_for_unknown_key(self):
        self.provider.release_context("unknown", "unknown")


class TestIOContextProviderProtocol(unittest.TestCase):

    def test_null_provider_satisfies_protocol(self):
        provider = NullIOContextProvider()
        self.assertIsInstance(provider, IOContextProvider)

    def test_worker_provider_satisfies_protocol(self):
        provider = WorkerRuntimeIOContextProvider()
        self.assertIsInstance(provider, IOContextProvider)


if __name__ == "__main__":
    unittest.main()