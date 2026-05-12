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
from attack_agent.team.benchmark import BenchmarkRunner
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.tool_broker import ToolRequest


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

    # -- tool broker endpoints --

    @router.get("/tools")
    def list_tools(profile: str = "") -> list[dict[str, Any]]:
        primitives = runtime.list_available_primitives(profile)
        specs = []
        for name in primitives:
            spec = runtime.tool_broker.get_primitive_spec(name)
            if spec:
                specs.append(to_dict(spec))
            else:
                specs.append({"name": name, "capability": "—"})
        return specs

    @router.get("/tools/{name}")
    def get_tool_spec(name: str) -> dict[str, Any]:
        spec = runtime.tool_broker.get_primitive_spec(name)
        if spec is None:
            raise HTTPException(status_code=404, detail="Primitive not found")
        return to_dict(spec)

    @router.post("/projects/{project_id}/request-tool")
    def request_tool(
        project_id: str,
        primitive_name: str = "",
        solver_id: str = "",
        risk_level: str = "low",
        budget_request: float = 0.0,
        reason: str = "",
    ) -> dict[str, Any]:
        if not primitive_name:
            raise HTTPException(status_code=400, detail="primitive_name required")
        result = runtime.request_tool(
            project_id=project_id,
            solver_id=solver_id,
            primitive_name=primitive_name,
            risk_level=risk_level,
            budget_request=budget_request,
            reason=reason,
        )
        return to_dict(result)

    # -- replay / evaluation endpoints --

    @router.get("/projects/{project_id}/replay-steps")
    def get_replay_steps(project_id: str) -> list[dict[str, Any]]:
        steps = runtime.replay_steps(project_id)
        results = []
        for s in steps:
            snap = s.state_snapshot
            results.append({
                "step_index": s.step_index,
                "event_type": s.event.event_type,
                "timestamp": s.timestamp,
                "event_payload": s.event.payload,
                "state_snapshot": {
                    "project": to_dict(snap.project) if snap.project else None,
                    "fact_count": len(snap.facts),
                    "idea_count": len(snap.ideas),
                    "session_count": len(snap.sessions),
                    "project_status": snap.project.status if snap.project else None,
                },
            })
        return results

    @router.get("/projects/{project_id}/metrics")
    def get_metrics(project_id: str) -> dict[str, Any]:
        metrics = runtime.evaluate(project_id)
        return to_dict(metrics)

    @router.post("/regression")
    def run_regression(
        baseline_db: str = "",
        challenge_ids: list[str] = None,
    ) -> dict[str, Any]:
        if not baseline_db:
            raise HTTPException(status_code=400, detail="baseline_db path required")

        baseline_bb = BlackboardService(BlackboardConfig(db_path=baseline_db))
        runner = BenchmarkRunner()

        if challenge_ids is None:
            challenge_ids = []
            cursor = baseline_bb._db.cursor()
            cursor.execute("SELECT DISTINCT project_id FROM events")
            for row in cursor.fetchall():
                challenge_ids.append(row[0])
            cursor2 = runtime.blackboard._db.cursor()
            cursor2.execute("SELECT DISTINCT project_id FROM events")
            for row in cursor2.fetchall():
                if row[0] not in challenge_ids:
                    challenge_ids.append(row[0])

        report = runner.run_regression(challenge_ids, runtime.blackboard, baseline_bb)
        result = {
            "overall_status": report.overall_status,
            "regressions": report.regressions,
            "improvements": report.improvements,
            "baseline_metrics": {k: to_dict(v) for k, v in report.baseline_metrics.items()},
            "current_metrics": {k: to_dict(v) for k, v in report.current_metrics.items()},
        }
        baseline_bb.close()
        return result

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