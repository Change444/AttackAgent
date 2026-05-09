# AttackAgent Team 平台使用指南

**版本：** 4.13
**最后更新：** 2026-05-09

---

## 1. 概述

AttackAgent Team 平台是多 Solver 协作的渗透测试运行环境。通过 TeamRuntime 串联全部 Phase A~G 组件（Blackboard/Manager/Scheduler/Memory/Idea/Context/Policy/Review/Solver/Merge/Submission/Observer），提供 CLI、Python API、HTTP API 三种操作面。

**设计原则：CLI/API 先于 Web UI** — runtime 稳定后再暴露操作面，先 introspection 后治理。

---

## 2. 安装

```bash
# Team 全功能（CLI + API）
pip install -e ".[team]"

# 仅 CLI（click + rich）
pip install -e ".[cli]"

# 仅 API（fastapi + uvicorn + httpx）
pip install -e ".[api]"
```

依赖内容：

| 组 | 包 |
|---|---|
| `api` | fastapi>=0.100, uvicorn>=0.20, httpx>=0.24 |
| `cli` | click>=8, rich>=13 |
| `team` | 以上全部 |

---

## 3. CLI 使用

所有 Team 命令通过 `python -m attack_agent team <子命令>` 调用。

### 3.1 运行项目

```bash
python -m attack_agent team run --config config/team_settings.json
```

`config/team_settings.json` 格式（可选，缺失时使用默认值）：

```json
{
  "blackboard_db_path": "data/blackboard.db",
  "max_project_solvers": 1,
  "max_cycles": 12,
  "stagnation_threshold": 3,
  "confidence_threshold": 0.6,
  "max_submissions": 3,
  "flag_pattern": "flag\\{[^}]+\\}"
}
```

运行结束后 rich 表格汇总结果：project_id / challenge_id / status / solver_count / idea_count / pending_reviews。

### 3.2 查看项目状态

```bash
# 列出所有项目
python -m attack_agent team status

# 查看指定项目详情（rich Panel）
python -m attack_agent team status <project_id>
```

输出包含：project_id / challenge_id / status / solver_count / idea_count / fact_count / pending_review_count / candidate_flags / last_observation_severity。

### 3.3 回放事件日志

```bash
python -m attack_agent team replay <project_id>
```

输出完整 Blackboard event journal（JSON 格式），含 causal_ref 因果链和 timestamp 排序。

### 3.4 查看/处理审批请求

```bash
# 列出所有待审批请求
python -m attack_agent team reviews

# 列出指定项目的待审批请求
python -m attack_agent team reviews <project_id>

# 批准
python -m attack_agent team review approve <request_id> --project-id <pid> --reason "looks good"

# 拒绝
python -m attack_agent team review reject <request_id> --project-id <pid> --reason "bad flag"

# 修改
python -m attack_agent team review modify <request_id> --project-id <pid> --reason "adjust approach"
```

### 3.5 观察分析

```bash
python -m attack_agent team observe <project_id>
```

运行 Observer 全部 5 个检测器（repeated_action / low_novelty / ignored_failure_boundary / stagnation / tool_misuse），输出 severity 分级（critical/warning/info）和 suggested_actions。

### 3.6 启动 API 服务器

```bash
python -m attack_agent team serve --port 8000
```

启动 FastAPI HTTP API，默认端口 8000。

---

## 4. Python API 使用

### 4.1 基础用法

```python
from attack_agent.team.runtime import TeamRuntime, TeamRuntimeConfig

# 默认配置
runtime = TeamRuntime()

# 自定义配置
config = TeamRuntimeConfig(
    blackboard_db_path="data/blackboard.db",
    max_cycles=12,
    max_project_solvers=1,
    max_submissions=3,
)
runtime = TeamRuntime(config)

# 运行项目
project = runtime.run_project("web-auth-easy")
print(f"Status: {project.status}")

# 运行多个项目
results = runtime.run_all(["web-auth-easy", "web-render-easy"])
for cid, proj in results.items():
    print(f"{cid}: {proj.status}")

# 查看状态
report = runtime.get_status(project.project_id)
print(f"Solvers: {report.solver_count}, Ideas: {report.idea_count}")

# 列出所有项目
for report in runtime.list_projects():
    print(f"{report.project_id}: {report.status}")

# 清理
runtime.close()
```

### 4.2 提交 Flag

```python
result = runtime.submit_flag(
    project_id="abc123",
    flag_value="flag{test_flag}",
    idea_id="idea-1"
)
print(f"Status: {result.status}")  # submitted / needs_review / rejected / failed
print(f"Verification: {result.verification_result.status}")
print(f"Policy: {result.policy_decision}")
print(f"Review created: {result.review_created}")
```

提交链路：SubmissionVerifier → PolicyHarness → (needs_review → HumanReviewGate) → Blackboard SUBMISSION event。

### 4.3 处理审批

```python
from attack_agent.team.protocol import HumanDecisionChoice

# 查看待审批
reviews = runtime.get_pending_reviews(project_id="abc123")

# 批准
result = runtime.resolve_review(
    request_id="rev-1",
    decision=HumanDecisionChoice.APPROVED,
    reason="flag format verified",
    decided_by="operator",
    project_id="abc123"
)

# 拒绝
result = runtime.resolve_review(
    request_id="rev-2",
    decision=HumanDecisionChoice.REJECTED,
    reason="flag not matching evidence",
    project_id="abc123"
)
```

### 4.4 观察与回放

```python
# 观察分析
report = runtime.observe("abc123")
print(f"Severity: {report.severity}")
for note in report.observations:
    print(f"  {note.kind}: {note.description}")
for action in report.suggested_actions:
    print(f"  Action: {action}")

# 事件回放
events = runtime.replay("abc123")
for ev in events:
    print(f"  {ev['event_type']} @ {ev['timestamp']}")
```

---

## 5. HTTP API 使用

### 5.1 启动

```bash
python -m attack_agent team serve --port 8000
```

或通过 uvicorn 直接启动：

```python
from attack_agent.team.runtime import TeamRuntime
from attack_agent.team.api import create_app
import uvicorn

runtime = TeamRuntime()
app = create_app(runtime)
uvicorn.run(app, host="0.0.0.0", port=8000)
```

### 5.2 只读端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/projects` | GET | 项目列表（ProjectStatusReport） |
| `/api/projects/{id}` | GET | 项目详情（ProjectStatusReport） |
| `/api/projects/{id}/ideas` | GET | 项目 idea 列表（IdeaEntry） |
| `/api/projects/{id}/memory` | GET | 项目去重记忆（MemoryEntry, deduped facts） |
| `/api/projects/{id}/solvers` | GET | Solver session 列表（SolverSession） |
| `/api/projects/{id}/reviews` | GET | 待审批请求列表（ReviewRequest） |
| `/api/projects/{id}/events` | GET | 完整事件日志 |
| `/api/projects/{id}/observe` | GET | 观察报告（ObservationReport） |

### 5.3 审批端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/reviews/{id}/approve` | POST | 批准审批请求 |
| `/api/reviews/{id}/reject` | POST | 拒绝审批请求 |
| `/api/reviews/{id}/modify` | POST | 修改审批请求 |

参数：`project_id`（query, 查找 review 所需）+ `reason`（query, 可选）。

### 5.4 示例

```bash
# 查看所有项目
curl http://localhost:8000/api/projects

# 查看项目详情
curl http://localhost:8000/api/projects/abc123

# 查看项目 ideas
curl http://localhost:8000/api/projects/abc123/ideas

# 查看事件日志
curl http://localhost:8000/api/projects/abc123/events

# 批准审批
curl -X POST "http://localhost:8000/api/reviews/rev-1/approve?project_id=abc123&reason=verified"

# 拒绝审批
curl -X POST "http://localhost:8000/api/reviews/rev-2/reject?project_id=abc123&reason=bad_flag"
```

---

## 6. 架构概览

### 6.1 TeamRuntime 串联的 11 个组件

```
TeamRuntime (runtime.py)
 ├── BlackboardService     — SQLite append-only event journal + materialized state
 ├── TeamManager           — 纯决策函数 → StrategyAction
 ├── SyncScheduler         — 同步调度 loop until done/abandoned
 ├── SolverSessionManager  — Solver 状态机 + 并发控制
 ├── MemoryService         — 结构化记忆 store/query/dedupe
 ├── IdeaService           — 攻击路线 propose/claim/verify/fail
 ├── ContextCompiler       — Manager/Solver 上下文编译
 ├── PolicyHarness         — 统一安全决策 validate_action → PolicyDecision
 ├── HumanReviewGate       — 人工审批 create/resolve/auto_expire
 ├── MergeHub              — 多 Solver 结果归并 + 共识 boost
 ├── SubmissionVerifier    — 提交验证 5 pass
 └── Observer              — 异常检测 → CHECKPOINT 事件
```

### 6.2 数据流

```
用户 → CLI / Python API / HTTP API
         ↓
    TeamRuntime
         ↓
    run_project → SyncScheduler.run_project → [schedule_cycle loop]
         ↓                                    ↓
    TeamManager.decide_* → StrategyAction    Blackboard.append_event
         ↓                                    ↓
    PolicyHarness.validate_action             Blackboard.rebuild_state
         ↓                                    ↓
    (needs_review?) → HumanReviewGate        MaterializedState
         ↓                                    ↓
    SubmissionVerifier.run_all_passes         get_status / list_projects
```

### 6.3 Blackboard 事件类型

所有状态变更通过 Blackboard 事件记录：

| EventType | 来源 | 用途 |
|-----------|------|------|
| project_upserted | Scheduler/Runtime | 项目状态更新 |
| worker_assigned | SolverSessionManager | Solver 分配 |
| observation | MemoryService | 事实/凭据/endpoint 记录 |
| candidate_flag | IdeaService | 攻击路线提出/状态演变 |
| action_outcome | Solver/MemoryService | 执行结果/failure boundary |
| submission | TeamRuntime | flag 提交 |
| security_validation | PolicyHarness/Review | 安全决策/review 创建/解决 |
| checkpoint | Observer | 观察报告 |
| worker_heartbeat/timeout | SolverSessionManager | Solver 心跳/超时 |
| requeue | Scheduler | Solver 重调度 |

---

## 7. TeamRuntimeConfig 字段

| 字段 | 默认值 | 说明 |
|------|-------|------|
| `blackboard_db_path` | `"data/blackboard.db"` | SQLite 数据库路径 |
| `max_project_solvers` | `1` | 单项目最大 Solver 数 |
| `session_timeout_seconds` | `300` | Solver session 超时 |
| `budget_per_session` | `20.0` | 单 session 预算 |
| `max_submissions` | `3` | 单项目最大提交次数 |
| `flag_pattern` | `r"flag\{[^}]+\}"` | flag 正则匹配 |
| `max_cycles` | `12` | 单项目最大调度循环数 |
| `stagnation_threshold` | `3` | 停滞阈值 |
| `confidence_threshold` | `0.6` | flag 置信度门槛 |

---

## 8. 常见问题

### Blackboard 数据库路径

默认 `data/blackboard.db`，首次运行自动创建。重启后数据持久化，可跨 session 查询历史。

### API 端口冲突

`serve --port <N>` 指定端口。默认 8000。

### 项目不存在

`get_status()` 对不存在项目返回 None（API 返回 404）。`list_projects()` 只返回有事件记录的项目。

### observe 会写事件

Observer.generate_report() 写入 CHECKPOINT 事件。这是预期行为（建议性事件），不影响项目状态。如需纯只读分析，直接调用 Observer.detect_* 方法而非 generate_report()。

### review 需要指定 project_id

resolve_review 需要传入 project_id 参数，因为 HumanReviewGate 从事件日志查找 review，需要 project 范围限定。

---

## 9. 测试

```bash
# 全量测试（含 Team Runtime）
python -m unittest discover tests/ -v

# 仅 Team Runtime 测试
python -m unittest tests/test_team_runtime.py tests/test_team_cli.py tests/test_team_api.py -v
```

当前：598 测试全通过（562 原有 + 36 Phase H 新增）。