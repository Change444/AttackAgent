"""Team API — Phase H.

FastAPI read-only + review governance endpoints.
All endpoints delegate to TeamRuntime.
"""

from __future__ import annotations

from typing import Any

try:
    from contextlib import asynccontextmanager
    from fastapi import APIRouter, FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    raise ImportError("fastapi is required. Run: pip install attack-agent[api]")

from attack_agent.team.protocol import HumanDecisionChoice, MemoryKind, ReviewRequest, to_dict
from attack_agent.team.runtime import TeamRuntime


def make_api_router(runtime: TeamRuntime) -> APIRouter:
    """Create an APIRouter wired to a TeamRuntime instance."""
    router = APIRouter(prefix="/api", tags=["team"])

    # -- project endpoints --

    @router.get("/projects")
    def list_projects() -> list[dict[str, Any]]:
        return [to_dict(r) for r in runtime.list_projects()]

    @router.get("/projects/{project_id}")
    def get_project_status(project_id: str) -> dict[str, Any]:
        report = runtime.get_status(project_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return to_dict(report)

    @router.get("/projects/{project_id}/ideas")
    def get_ideas(project_id: str) -> list[dict[str, Any]]:
        ideas = runtime.blackboard.list_ideas(project_id)
        return [to_dict(i) for i in ideas]

    @router.get("/projects/{project_id}/memory")
    def get_memory(project_id: str) -> list[dict[str, Any]]:
        entries = runtime.memory.get_deduped_entries(project_id, MemoryKind.FACT, limit=50)
        return [to_dict(e) for e in entries]

    @router.get("/projects/{project_id}/solvers")
    def get_solvers(project_id: str) -> list[dict[str, Any]]:
        sessions = runtime.blackboard.list_sessions(project_id)
        return [to_dict(s) for s in sessions]

    @router.get("/projects/{project_id}/reviews")
    def get_reviews(project_id: str) -> list[dict[str, Any]]:
        reviews = runtime.get_pending_reviews(project_id)
        return [to_dict(r) for r in reviews]

    @router.get("/projects/{project_id}/events")
    def get_events(project_id: str) -> list[dict[str, Any]]:
        return runtime.replay(project_id)

    @router.get("/projects/{project_id}/observe")
    def get_observation(project_id: str) -> dict[str, Any]:
        report = runtime.observe(project_id)
        return to_dict(report)

    # -- review action endpoints --

    @router.post("/reviews/{request_id}/approve")
    def approve_review(request_id: str, project_id: str = "", reason: str = "") -> dict[str, Any]:
        result = runtime.resolve_review(
            request_id, HumanDecisionChoice.APPROVED, reason=reason, project_id=project_id
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Review not found or already resolved")
        return to_dict(result)

    @router.post("/reviews/{request_id}/reject")
    def reject_review(request_id: str, project_id: str = "", reason: str = "") -> dict[str, Any]:
        result = runtime.resolve_review(
            request_id, HumanDecisionChoice.REJECTED, reason=reason, project_id=project_id
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Review not found or already resolved")
        return to_dict(result)

    @router.post("/reviews/{request_id}/modify")
    def modify_review(request_id: str, project_id: str = "", reason: str = "") -> dict[str, Any]:
        result = runtime.resolve_review(
            request_id, HumanDecisionChoice.MODIFIED, reason=reason, project_id=project_id
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Review not found or already resolved")
        return to_dict(result)

    return router


def create_app(runtime: TeamRuntime) -> FastAPI:
    """Create a FastAPI application with TeamRuntime injected."""
    @asynccontextmanager
    async def lifespan(app):
        yield
        runtime.close()

    app = FastAPI(
        title="AttackAgent Team API",
        version="0.1.0",
        description="Read-only introspection + review governance for Team Runtime.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    router = make_api_router(runtime)
    app.include_router(router)

    app.state.runtime = runtime

    return app