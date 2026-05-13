"""IOContextProvider — L8.

Provides IO context objects (HttpSessionManager, browser_inspector, http_client)
to ToolBroker for executing IO-dependent primitives. Abstracts away object
creation and lifecycle so ToolBroker stays decoupled from runtime internals.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..browser_adapter import build_browser_inspector_from_config
from ..config import BrowserConfig, HttpConfig
from ..http_adapter import build_http_client_from_config
from ..runtime import HttpSessionManager
from ..state_graph import StateGraphService


__all__ = [
    "IOContextProvider",
    "WorkerRuntimeIOContextProvider",
    "NullIOContextProvider",
]


@runtime_checkable
class IOContextProvider(Protocol):
    """Protocol for providing IO context objects to ToolBroker."""

    def get_session_manager(self, project_id: str, solver_id: str) -> HttpSessionManager | None:
        ...

    def get_browser_inspector(self, project_id: str, solver_id: str) -> Any | None:
        ...

    def get_http_client(self, project_id: str, solver_id: str) -> Any | None:
        ...

    def release_context(self, project_id: str, solver_id: str) -> None:
        ...


class NullIOContextProvider:
    """Returns None for all IO context — backward compat and testing."""

    def get_session_manager(self, project_id: str, solver_id: str) -> HttpSessionManager | None:
        return None

    def get_browser_inspector(self, project_id: str, solver_id: str) -> Any | None:
        return None

    def get_http_client(self, project_id: str, solver_id: str) -> Any | None:
        return None

    def release_context(self, project_id: str, solver_id: str) -> None:
        pass


class WorkerRuntimeIOContextProvider:
    """Concrete provider using BrowserConfig, HttpConfig, and optional StateGraphService.

    Creates HttpSessionManager per (project_id, solver_id) with session state
    restoration from StateGraphService. Builds browser_inspector and http_client
    from config. Caches objects per (project_id, solver_id) so they persist
    across multiple primitive executions within the same solver cycle.
    """

    def __init__(
        self,
        browser_config: BrowserConfig | None = None,
        http_config: HttpConfig | None = None,
        state_graph: StateGraphService | None = None,
    ) -> None:
        self._browser_config = browser_config or BrowserConfig()
        self._http_config = http_config or HttpConfig()
        self._state_graph = state_graph
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def get_session_manager(self, project_id: str, solver_id: str) -> HttpSessionManager:
        key = (project_id, solver_id)
        entry = self._cache.get(key)
        if entry is not None and "session_manager" in entry:
            return entry["session_manager"]

        session_manager = HttpSessionManager()

        # Restore session state from StateGraphService if available
        if self._state_graph is not None:
            record = self._state_graph.projects.get(project_id)
            if record is not None:
                for oid, obs in record.episode_memory.completed_observations.items():
                    if obs.kind == "session_state":
                        for cookie_text in obs.payload.get("cookies", []):
                            # Parse simple cookie strings back into jar
                            # (full restoration requires http.cookiejar.Cookie obj)
                            pass
                        auth_data = obs.payload.get("auth_headers", {})
                        for k, v in auth_data.items():
                            session_manager.add_auth_header(k, v)

        self._ensure_cache_entry(key)
        self._cache[key]["session_manager"] = session_manager
        return session_manager

    def get_browser_inspector(self, project_id: str, solver_id: str) -> Any:
        key = (project_id, solver_id)
        entry = self._cache.get(key)
        if entry is not None and "browser_inspector" in entry:
            return entry["browser_inspector"]

        inspector = build_browser_inspector_from_config(self._browser_config)
        self._ensure_cache_entry(key)
        self._cache[key]["browser_inspector"] = inspector
        return inspector

    def get_http_client(self, project_id: str, solver_id: str) -> Any:
        key = (project_id, solver_id)
        entry = self._cache.get(key)
        if entry is not None and "http_client" in entry:
            return entry["http_client"]

        client = build_http_client_from_config(self._http_config)
        self._ensure_cache_entry(key)
        self._cache[key]["http_client"] = client
        return client

    def release_context(self, project_id: str, solver_id: str) -> None:
        key = (project_id, solver_id)
        entry = self._cache.pop(key, None)
        if entry is None:
            return
        inspector = entry.get("browser_inspector")
        if inspector is not None and hasattr(inspector, "close"):
            inspector.close()
        client = entry.get("http_client")
        if client is not None and hasattr(client, "close"):
            client.close()

    def _ensure_cache_entry(self, key: tuple[str, str]) -> None:
        if key not in self._cache:
            self._cache[key] = {}