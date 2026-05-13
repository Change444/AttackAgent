"""Team API — Phase H + L9.

FastAPI read-only + review governance + project lifecycle + event stream endpoints.
All endpoints delegate to TeamRuntime. Data source is Blackboard only.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

try:
    from contextlib import asynccontextmanager
    from fastapi import APIRouter, FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse
except ImportError:
    raise ImportError("fastapi is required. Run: pip install attack-agent[api]")

try:
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path
except ImportError:
    StaticFiles = None  # type: ignore[assignment,misc]

from attack_agent.platform_models import EventType
from attack_agent.team.event_compat import is_genuine_candidate_flag
from attack_agent.team.protocol import HumanDecisionChoice, MemoryKind, ReviewRequest, to_dict, _gen_id
from attack_agent.team.runtime import TeamRuntime
from attack_agent.team.benchmark import BenchmarkRunner
from attack_agent.team.blackboard_config import BlackboardConfig
from attack_agent.team.blackboard import BlackboardService
from attack_agent.team.tool_broker import ToolRequest

_SSE_EVENT_MAP: dict[str, str] = {
    EventType.PROJECT_UPSERTED.value: "project_updated",
    EventType.WORKER_ASSIGNED.value: "solver_updated",
    EventType.WORKER_HEARTBEAT.value: "solver_updated",
    EventType.WORKER_TIMEOUT.value: "solver_updated",
    EventType.IDEA_PROPOSED.value: "idea_updated",
    EventType.IDEA_CLAIMED.value: "idea_updated",
    EventType.IDEA_VERIFIED.value: "idea_updated",
    EventType.IDEA_FAILED.value: "idea_updated",
    EventType.OBSERVATION.value: "memory_added",
    EventType.MEMORY_STORED.value: "memory_added",
    EventType.OBSERVER_REPORT.value: "observer_reported",
    EventType.SECURITY_VALIDATION.value: "review_created",
    EventType.CANDIDATE_FLAG.value: "candidate_flag_found",
    EventType.ACTION_OUTCOME.value: "tool_event",
    EventType.TOOL_REQUEST.value: "tool_event",
    EventType.HINT.value: "hint_added",
    EventType.KNOWLEDGE_PACKET_PUBLISHED.value: "knowledge_published",
    EventType.KNOWLEDGE_PACKET_MERGED.value: "knowledge_merged",
}


def _map_event_to_sse(event_type: str, payload: dict) -> str:
    """Map Blackboard EventType to SSE channel name.

    SECURITY_VALIDATION is polymorphic: pending → review_created,
    review outcome → review_decided.
    """
    if event_type == EventType.SECURITY_VALIDATION.value:
        outcome = payload.get("outcome", "")
        status = payload.get("status", "")
        if status in ("approved", "rejected", "modified"):
            return "review_decided"
        if outcome.startswith("review_"):
            return "review_decided"
        return "review_created"
    return _SSE_EVENT_MAP.get(event_type, "unknown")


def _explain_decision(step) -> str:
    """Generate a human-readable explanation for a replay step."""
    et = step.event.event_type
    p = step.event.payload
    if et == EventType.STRATEGY_ACTION.value:
        return f"Manager decided {p.get('action_type', '')}: {p.get('reason', '')}"
    if et == EventType.WORKER_ASSIGNED.value:
        return f"Solver {p.get('solver_id', '')} assigned to idea {p.get('active_idea_id', '')}"
    if et == EventType.CANDIDATE_FLAG.value:
        return f"Candidate flag found: {p.get('flag', '')} (confidence={p.get('confidence', 0)})"
    if et == EventType.SECURITY_VALIDATION.value:
        return f"Security review {p.get('outcome', '')} for {p.get('action_type', '')}"
    if et == EventType.PROJECT_UPSERTED.value:
        return f"Project status → {p.get('status', '')}, stage → {p.get('stage', '')}"
    if et == EventType.OBSERVER_REPORT.value:
        return f"Observer report: severity={p.get('severity', '')}"
    if et == EventType.ACTION_OUTCOME.value:
        return f"Action outcome: {p.get('status', '')} via {p.get('primitive_name', '')}"
    if et == EventType.HINT.value:
        return f"Hint added: {p.get('content', '')}"
    if et == EventType.WORKER_HEARTBEAT.value:
        return f"Solver {p.get('solver_id', '')} heartbeat: status={p.get('status', '')}"
    return f"Event: {et}"


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

    # -- L9: project lifecycle endpoints --

    @router.post("/projects/start-project")
    def start_project(challenge_id: str = "demo-1") -> dict[str, Any]:
        pid = runtime.start_project(challenge_id)
        return {"project_id": pid, "status": "started"}

    @router.post("/projects/{project_id}/pause")
    def pause_project(project_id: str) -> dict[str, Any]:
        result = runtime.pause_project(project_id)
        if not result:
            raise HTTPException(status_code=409, detail="Project not running or already paused")
        return {"project_id": project_id, "status": "paused"}

    @router.post("/projects/{project_id}/resume")
    def resume_project(project_id: str) -> dict[str, Any]:
        result = runtime.resume_project(project_id)
        if not result:
            raise HTTPException(status_code=409, detail="Project not paused")
        return {"project_id": project_id, "status": "running"}

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

    # -- L9: missing read endpoints --

    @router.post("/projects/{project_id}/hint")
    def add_hint(project_id: str, content: str = "", confidence: float = 1.0) -> dict[str, Any]:
        if not content:
            raise HTTPException(status_code=400, detail="content required")
        runtime.blackboard.append_event(
            project_id=project_id,
            event_type="hint",
            payload={"content": content, "confidence": confidence, "hint_id": _gen_id()},
            source="api_user",
        )
        return {"project_id": project_id, "hint": content}

    @router.get("/projects/{project_id}/graph")
    def get_graph(project_id: str) -> dict[str, Any]:
        state = runtime.blackboard.rebuild_state(project_id)
        if state.project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {
            "project_id": project_id,
            "fact_nodes": [to_dict(f) for f in state.facts],
            "idea_nodes": [to_dict(i) for i in state.ideas],
            "solver_nodes": [to_dict(s) for s in state.sessions],
            "packet_nodes": [to_dict(p) for p in state.packets],
        }

    @router.get("/projects/{project_id}/observer-reports")
    def get_observer_reports(project_id: str) -> list[dict[str, Any]]:
        events = runtime.blackboard.load_events(project_id)
        return [
            {"event_id": ev.event_id, "payload": ev.payload, "timestamp": ev.timestamp}
            for ev in events
            if ev.event_type == EventType.OBSERVER_REPORT.value
        ]

    @router.get("/projects/{project_id}/candidate-flags")
    def get_candidate_flags(project_id: str) -> list[dict[str, Any]]:
        events = runtime.blackboard.load_events(project_id)
        return [
            {"event_id": ev.event_id, "payload": ev.payload, "timestamp": ev.timestamp}
            for ev in events
            if ev.event_type == EventType.CANDIDATE_FLAG.value
            and is_genuine_candidate_flag(ev.event_type, ev.payload, ev.source)
        ]

    @router.get("/projects/{project_id}/artifacts")
    def get_artifacts(project_id: str) -> list[dict[str, Any]]:
        events = runtime.blackboard.load_events(project_id)
        return [
            {"event_id": ev.event_id, "payload": ev.payload, "timestamp": ev.timestamp}
            for ev in events
            if ev.event_type == EventType.ARTIFACT_ADDED.value
        ]

    @router.get("/projects/{project_id}/replay-timeline")
    def get_replay_timeline(project_id: str) -> list[dict[str, Any]]:
        steps = runtime.replay_steps(project_id)
        timeline = []
        for s in steps:
            explanation = _explain_decision(s)
            snap = s.state_snapshot
            timeline.append({
                "step_index": s.step_index,
                "event_type": s.event.event_type,
                "timestamp": s.timestamp,
                "payload": s.event.payload,
                "explanation": explanation,
                "state_summary": {
                    "status": snap.project.status if snap.project else None,
                    "fact_count": len(snap.facts),
                    "idea_count": len(snap.ideas),
                    "solver_count": len(snap.sessions),
                },
            })
        return timeline

    @router.get("/projects/{project_id}/verify-consistency")
    def verify_consistency(project_id: str) -> dict[str, Any]:
        """Verify API data matches Blackboard event journal (ReplayEngine check)."""
        api_state = runtime.blackboard.rebuild_state(project_id)
        if api_state.project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        steps = runtime.replay_steps(project_id)
        if not steps:
            raise HTTPException(status_code=404, detail="No events found")
        final_state = steps[-1].state_snapshot

        mismatches = []
        if len(api_state.facts) != len(final_state.facts):
            mismatches.append(f"fact_count: api={len(api_state.facts)}, replay={len(final_state.facts)}")
        if len(api_state.ideas) != len(final_state.ideas):
            mismatches.append(f"idea_count: api={len(api_state.ideas)}, replay={len(final_state.ideas)}")
        if len(api_state.sessions) != len(final_state.sessions):
            mismatches.append(f"session_count: api={len(api_state.sessions)}, replay={len(final_state.sessions)}")

        return {
            "project_id": project_id,
            "consistent": len(mismatches) == 0,
            "mismatches": mismatches,
            "api_fact_count": len(api_state.facts),
            "replay_fact_count": len(final_state.facts),
        }

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

    # -- L9: global review queue --

    @router.get("/reviews")
    def list_all_reviews(status: str = "") -> list[dict[str, Any]]:
        """List pending reviews across all projects.

        Optional status filter: pending, approved, rejected, modified.
        """
        db = runtime.blackboard._db
        if db is None:
            return []
        cursor = db.cursor()
        cursor.execute("SELECT DISTINCT project_id FROM events")
        project_ids = [row[0] for row in cursor.fetchall()]

        all_reviews = []
        for pid in project_ids:
            reviews = runtime.get_pending_reviews(pid)
            all_reviews.extend(reviews)

        if status:
            from attack_agent.team.protocol import ReviewStatus
            try:
                target = ReviewStatus(status)
                all_reviews = [r for r in all_reviews if r.status == target]
            except ValueError:
                pass

        return [to_dict(r) for r in all_reviews]

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

    # -- L9: SSE event stream --

    @router.get("/events/stream")
    async def event_stream(
        request: Request,
        project_id: str = "",
        last_event_id: str = "",
    ):
        """SSE endpoint for real-time event streaming.

        Polls Blackboard for events newer than last_event_id every 1 second.
        Optional project_id filter for project-specific stream.
        """
        async def generate():
            last_seen = last_event_id
            while True:
                if await request.is_disconnected():
                    break
                try:
                    if project_id:
                        new_events = runtime.blackboard.load_events_after(project_id, last_seen)
                    else:
                        new_events = runtime.blackboard.load_all_events_after(last_seen)
                except Exception:
                    new_events = []
                for ev in new_events:
                    sse_type = _map_event_to_sse(ev.event_type, ev.payload)
                    payload_json = json.dumps({
                        "event_id": ev.event_id,
                        "project_id": ev.project_id,
                        "event_type": ev.event_type,
                        "payload": ev.payload,
                        "timestamp": ev.timestamp,
                    }, ensure_ascii=False)
                    yield f"id: {ev.event_id}\nevent: {sse_type}\ndata: {payload_json}\n\n"
                    last_seen = ev.event_id
                await asyncio.sleep(1.0)
        return StreamingResponse(generate(), media_type="text/event-stream")

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

    # Mount built Web UI static assets if available
    if StaticFiles is not None:
        web_dist = Path(__file__).parent.parent.parent / "web" / "dist"
        if web_dist.is_dir():
            app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    return app