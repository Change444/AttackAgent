from __future__ import annotations

from .models import ActionRecord, new_id, utc_now
from .platform_models import Event, EventType, ProjectStage
from .runtime import WorkerPool, WorkerRuntime
from .state_graph import StateGraphService
from .strategy import StrategyLayer
from .constraints import LightweightSecurityShell, SecurityConstraints


class Dispatcher:
    def __init__(self, state_graph: StateGraphService, runtime: WorkerRuntime, strategy: StrategyLayer, worker_pool: WorkerPool | None = None) -> None:
        self.state_graph = state_graph
        self.runtime = runtime
        self.strategy = strategy
        self.worker_pool = worker_pool or WorkerPool()
        # 添加轻量级安全壳
        self.security_shell = LightweightSecurityShell(
            SecurityConstraints(
                allowed_hostpatterns=["127.0.0.1", "localhost"],
                max_http_requests=30,
                max_sandbox_executions=5,
                max_program_steps=15,
                require_observation_before_action=True,
                max_estimated_cost=50.0
            )
        )

    def schedule(self, project_id: str) -> None:
        record = self.state_graph.projects[project_id]
        if record.snapshot.stage == ProjectStage.BOOTSTRAP:
            record.snapshot.worker_profile = self.strategy.select_profile(record.snapshot)
            record.snapshot.stage = ProjectStage.REASON
            return
        if record.snapshot.stage == ProjectStage.REASON:
            self.strategy.initialize_graph(record)
            return
        if record.snapshot.stage != ProjectStage.EXPLORE:
            return
        program, memory_hits = self.strategy.next_program(record)
        if program is None:
            record.snapshot.stage = ProjectStage.CONVERGE
            return
        record.snapshot.worker_profile = program.required_profile
        worker = self.assign_worker(project_id)
        visible_primitives = self.runtime.registry.visible_primitives(program.required_profile)
        bundle = self.strategy.task_compiler.compile_bundle(record, program, program.required_profile, visible_primitives, memory_hits)

        # 安全壳验证（轻量级，快速）
        validation = self.security_shell.validate(bundle)

        # 记录验证事件（不阻断warning级别的违规）
        if validation.violations:
            violation_payload = [
                {
                    "type": v.constraint_type,
                    "severity": v.severity,
                    "message": v.message
                }
                for v in validation.violations
            ]
            self.state_graph.append_event(Event(
                type=EventType.SECURITY_VALIDATION,
                project_id=project_id,
                run_id=bundle.run_id,
                payload={
                    "allowed": validation.allowed,
                    "violations": violation_payload,
                    "program_id": program.id
                },
                source="security_shell"
            ))

        # 只有critical级别的违规才阻止执行
        if not validation.allowed:
            return  # 静默阻止，记录已通过事件系统

        events, outcome = self.runtime.run_task(bundle)
        self.heartbeat(worker.worker_id)
        self.state_graph.record_program(project_id, program, outcome)
        for event in events:
            self.state_graph.append_event(event)
        self._record_outcome(record, program, outcome)
        self.strategy.update_after_outcome(record, program, outcome)
        record.snapshot.stage = self.strategy.stage_after_program(record)

    def assign_worker(self, project_id: str):
        record = self.state_graph.projects[project_id]
        worker = self.worker_pool.assign(record.snapshot.worker_profile, project_id)
        self.state_graph.append_event(
            Event(
                type=EventType.WORKER_ASSIGNED,
                project_id=project_id,
                run_id=f"assign-{project_id}",
                payload={"worker_id": worker.worker_id, "profile": worker.profile.value},
                source="dispatcher",
            )
        )
        return worker

    def heartbeat(self, worker_id: str) -> None:
        worker = self.worker_pool.workers.get(worker_id)
        if worker is None:
            return
        worker.last_seen_at = utc_now()
        if worker.project_id is None:
            return
        self.state_graph.append_event(
            Event(
                type=EventType.WORKER_HEARTBEAT,
                project_id=worker.project_id,
                run_id=f"heartbeat-{worker_id}",
                payload={"worker_id": worker_id},
                source="dispatcher",
            )
        )

    def mark_timeout(self, run_id: str) -> None:
        emitted = False
        for worker in self.worker_pool.workers.values():
            if worker.project_id is None:
                continue
            worker.healthy = False
            self.state_graph.append_event(
                Event(
                    type=EventType.WORKER_TIMEOUT,
                    project_id=worker.project_id,
                    run_id=run_id,
                    payload={"worker_id": worker.worker_id},
                    source="dispatcher",
                )
            )
            emitted = True
        if emitted:
            return
        for project_id, record in self.state_graph.projects.items():
            if record.snapshot.stage not in {ProjectStage.DONE, ProjectStage.ABANDONED}:
                self.state_graph.append_event(
                    Event(
                        type=EventType.WORKER_TIMEOUT,
                        project_id=project_id,
                        run_id=run_id,
                        payload={"worker_id": "unassigned"},
                        source="dispatcher",
                    )
                )
                return

    def requeue(self, project_id: str, reason: str) -> None:
        record = self.state_graph.projects[project_id]
        if record.snapshot.stage != ProjectStage.DONE:
            record.snapshot.stage = ProjectStage.REASON if reason == "hint" else ProjectStage.EXPLORE
        self.state_graph.append_event(
            Event(
                type=EventType.REQUEUE,
                project_id=project_id,
                run_id=f"requeue-{project_id}",
                payload={"reason": reason},
                source="dispatcher",
            )
        )

    def _record_outcome(self, record, program, outcome) -> None:
        success = outcome.status == "ok" and (outcome.novelty > 0 or outcome.candidate_flags)
        record.world_state.record_action(
            ActionRecord(
                id=new_id("action"),
                source="dispatcher",
                tool_name=program.goal,
                target=record.snapshot.challenge.target,
                status="ok" if success else "failed",
                cost=outcome.cost,
            )
        )
        if success:
            return
        if self.strategy.should_abandon(record):
            record.snapshot.stage = ProjectStage.ABANDONED
            record.snapshot.status = "abandoned"
            self.state_graph.append_event(
                Event(
                    type=EventType.PROJECT_ABANDONED,
                    project_id=record.snapshot.project_id,
                    run_id=f"abandon-{record.snapshot.project_id}",
                    payload={"reason": "graph_stagnation"},
                    source="dispatcher",
                )
            )
