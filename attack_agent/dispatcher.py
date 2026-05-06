from __future__ import annotations

import re

from .config import SecurityConfig
from .constraints import LightweightSecurityShell
from .models import ActionRecord, new_id, utc_now
from .platform_models import ActionProgram, CandidateFlag, Event, EventType, PatternNodeKind, ProjectSnapshot, ProjectStage, TaskBundle, WorkerProfile
from .runtime import WorkerPool, WorkerRuntime
from .state_graph import StateGraphService
from .strategy import SubmitClassifier, TaskPromptCompiler


class Dispatcher:
    def __init__(self, state_graph: StateGraphService, runtime: WorkerRuntime, planner,
                 worker_pool: WorkerPool | None = None,
                 security_config: SecurityConfig | None = None,
                 stagnation_threshold: int = 8,
                 confidence_threshold: float = 0.6) -> None:
        self.state_graph = state_graph
        self.runtime = runtime
        self.planner = planner
        self.worker_pool = worker_pool or WorkerPool()
        self.security_shell = LightweightSecurityShell(security_config)
        self.stagnation_threshold = stagnation_threshold
        self.task_compiler = TaskPromptCompiler()
        self.submit_classifier = SubmitClassifier(confidence_threshold)
        self._cycle_counters: dict[str, int] = {}

    def schedule(self, project_id: str) -> None:
        record = self.state_graph.projects[project_id]

        # ── Cycle trace header ──────────────────────────────────────────
        self._cycle_counters[project_id] = self._cycle_counters.get(project_id, 0) + 1
        cycle = self._cycle_counters[project_id]
        ch = record.snapshot.challenge
        print(f"\n{'═' * 70}", flush=True)
        print(f"  CYCLE #{cycle} | Project: {project_id} | {ch.name} ({ch.category})", flush=True)
        print(f"  Stage: {record.snapshot.stage.value} | Stagnation: {record.stagnation_counter}", flush=True)
        print(f"{'═' * 70}", flush=True)
        # ────────────────────────────────────────────────────────────────

        if record.snapshot.stage == ProjectStage.BOOTSTRAP:
            profile, _reason = self.planner.reasoner.choose_profile(record.snapshot)
            record.snapshot.worker_profile = profile
            record.snapshot.stage = ProjectStage.REASON
            return
        if record.snapshot.stage == ProjectStage.REASON:
            record.pattern_graph = self.planner.create_graph(record.snapshot)
            record.snapshot.stage = ProjectStage.EXPLORE
            return
        if record.snapshot.stage != ProjectStage.EXPLORE:
            return
        program, memory_hits = self.planner.plan(record)
        if program is None:
            record.snapshot.stage = ProjectStage.CONVERGE
            print(f"  >> No program produced — converging", flush=True)
            return

        # ── Trace program ───────────────────────────────────────────────
        print(f"  Path: {self.planner._current_paths.get(project_id, 'N/A')}", flush=True)
        print(f"  Program: {program.id} | Goal: {program.goal}", flush=True)
        print(f"  Source: {getattr(program, 'planner_source', 'N/A')} | Profile: {program.required_profile.value}", flush=True)
        print(f"  Steps ({len(program.steps)}):", flush=True)
        for i, s in enumerate(program.steps):
            print(f"    {i+1}. {s.primitive}: {s.instruction[:120]}", flush=True)
        if program.rationale:
            print(f"  Rationale: {program.rationale[:300]}", flush=True)
        print(f"  ───────────────────────────", flush=True)
        # ────────────────────────────────────────────────────────────────
        record.snapshot.worker_profile = program.required_profile
        worker = self.assign_worker(project_id)
        visible_primitives = self.runtime.registry.visible_primitives(program.required_profile)
        bundle = self.task_compiler.compile_bundle(record, program, program.required_profile, visible_primitives, memory_hits)

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

        # ── Trace execution outcome ─────────────────────────────────────
        print(f"  Execution: {outcome.status} | Novelty: {outcome.novelty:.2f} | Cost: {outcome.cost:.2f}", flush=True)
        if outcome.candidate_flags:
            print(f"  Candidate flags: {outcome.candidate_flags}", flush=True)
        if outcome.failure_reason:
            print(f"  Failure: {outcome.failure_reason}", flush=True)
        obs_count = sum(1 for e in events if e.type == EventType.OBSERVATION)
        print(f"  Events: {len(events)} ({obs_count} observations)", flush=True)
        print(f"{'─' * 70}", flush=True)
        # ────────────────────────────────────────────────────────────────
        self.heartbeat(worker.worker_id)
        self.state_graph.record_program(project_id, program, outcome)
        for event in events:
            self.state_graph.append_event(event)
        self._record_outcome(record, program, outcome)
        self._update_after_outcome(record, program, outcome)
        record.snapshot.stage = self._stage_after_program(record)

        # Check abandon after outcome
        success = outcome.status == "ok" and (outcome.novelty > 0 or outcome.candidate_flags)
        if not success and self.should_abandon(record):
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

    def _update_after_outcome(self, record, program: ActionProgram, outcome) -> None:
        self.planner.update_graph(record, program, outcome)
        # Also update EnhancedAPGPlanner stagnation counter for path switching
        if hasattr(self.planner, 'record_outcome'):
            self.planner.record_outcome(record, program, outcome)
        if outcome.status == "ok" and outcome.novelty > 0.0:
            record.stagnation_counter = 0
            return
        record.stagnation_counter += 1

    def _stage_after_program(self, record) -> ProjectStage:
        if record.candidate_flags:
            return ProjectStage.CONVERGE
        if record.pattern_graph is None:
            return ProjectStage.CONVERGE
        unfinished = [node for node in record.pattern_graph.nodes.values() if node.kind != PatternNodeKind.GOAL and node.status in {"pending", "active"}]
        return ProjectStage.EXPLORE if unfinished else ProjectStage.CONVERGE

    def should_abandon(self, record) -> bool:
        recent_failures = record.world_state.recent_failures(limit=4)
        if record.stagnation_counter < self.stagnation_threshold:
            return False
        repeated_dead_ends = len(record.tombstones) >= 2
        low_novelty = all(failure.status == "failed" for failure in recent_failures) if recent_failures else True
        return repeated_dead_ends or low_novelty