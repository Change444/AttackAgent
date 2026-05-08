# AttackAgent — CLAUDE.md

Behavioral guidelines for working with this codebase. Merge with project-specific instructions below.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 5. Project Overview

**AttackAgent** 是面向授权靶场和 CTF 竞赛的渗透测试 Agent。设计理念：**约束推理而非候选选择**——框架引导模型决策，不限制创造力。双路径架构（结构化 + 自由探索），外部安全壳确保操作在授权范围内。

语言：中文文档（代码和标识符英文）。技术栈：Python 3.10+，stdlib-first，可选 openai/anthropic/sentence-transformers。

### Quick Start

```bash
# 运行全部测试
python -m unittest discover tests/

# 纯规则模式
python -m attack_agent --config config/settings.json

# 对接 HTTP 靶场
python -m attack_agent --provider-url http://127.0.0.1:8080

# 接入 LLM
python -m attack_agent --config config/settings.json --model openai --verbose
```

Python API（无需 LLM）：
```python
from attack_agent.platform import CompetitionPlatform
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.platform_models import ChallengeDefinition
provider = InMemoryCompetitionProvider([...])
platform = CompetitionPlatform(provider)
platform.solve_all()
```

### Architecture (5-Layer)

| 层 | 核心模块 | 职责 |
|----|----------|------|
| 控制层 | CompetitionPlatform (`platform.py`) | 挑战生命周期，配置加载 |
| 调度层 | Dispatcher (`dispatcher.py`) + SecurityShell (`constraints.py`) | 状态机调度，策略逻辑(stagnation/submit)，安全壳验证 |
| 规划层 | EnhancedAPGPlanner (`enhanced_apg.py`) | 双路径规划，路径选择/切换 |
| 执行层 | WorkerRuntime (`runtime.py`) | 9 个原语执行，session 持久化 |
| 状态层 | StateGraphService (`state_graph.py`) | 单一真实源，事件日志 |

完整架构：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

### Module Map

| 模块 | 文件 | 职责 |
|------|------|------|
| CompetitionPlatform | `platform.py` | 主入口，model=None/xxx 分支构建不同规划器 |
| CLI | `__main__.py` | `python -m attack_agent` 命令行接口 |
| Dispatcher | `dispatcher.py` | 状态机调度，策略逻辑（stagnation/submit/stage），cycle/program/outcome trace |
| EnhancedAPGPlanner | `enhanced_apg.py` | 双路径规划 |
| ConstraintAwareReasoner | `constraint_aware_reasoner.py` | LLM 约束推理 |
| HeuristicFreeExplorationPlanner | `heuristic_free_exploration.py` | 无 LLM 自由探索 |
| PathSelectionStrategy | `path_selection.py` | 置信度/复杂度路径选择 |
| PatternInjector | `pattern_injector.py` | 动态模式回注 |
| DynamicPatternComposer | `dynamic_pattern_composer.py` | 成功案例模式发现 |
| SemanticRetrievalEngine | `semantic_retrieval.py` | TF-IDF + embedding 混合检索 |
| PlaywrightBrowserInspector / StdlibBrowserInspector | `browser_adapter.py` | JS 渲染 + script 读取（Playwright），stdlib 回退 |
| RequestsHttpClient / StdlibHttpClient | `http_adapter.py` | multipart + Basic Auth + Bearer Auth + SSL bypass（requests），stdlib 回退 |
| WorkerRuntime (session-materialize) | `runtime.py` | CSRF 预取(form/meta/header) + JSON body + auth token 持久化 + login_url/credentials 注入 |
| WorkerRuntime (http-request) | `runtime.py` | {observe.*} 模板替换 + session cookie 恢复 + cookie 自动传递 |
| WorkerRuntime (session persistence) | `runtime.py` | SessionState 跨 Cycle 持久化（cookies/auth_headers 恢复 + 持久化） |
| WorkerRuntime (structured-parse) | `runtime.py` | 自动提取 cookies + base64 解码(decoded_cookies) + potential_secrets |
| WorkerRuntime (artifact-scan) | `runtime.py` | ZIP/tar 内容提取(content_preview) + MIME 映射(_guess_content_type) + 预览 512→4096 + temp_dir 延迟清理 |
| LightweightSecurityShell | `constraints.py` | 执行前约束验证（直接持有 SecurityConfig） |
| SubmitClassifier / TaskPromptCompiler | `strategy.py` | 提交分类 + 任务编译 |
| ObservationSummarizer | `observation_summarizer.py` | 观测→有限长度文本 |
| AttackAgentConfig | `config.py` | JSON + dataclass 配置 |
| OpenAI/Anthropic ReasoningModel | `model_adapter.py` | LLM 适配器（thinking model + verbose trace + GBK safe_print） |
| Local CTF Range | `scripts/local_range.py` | 本地靶场服务器（4 题） |

### Key Rules

- 安全壳在 runtime 执行前验证；critical 违规阻止执行
- 参数优先级：`step.parameters` > metadata defaults > hardcoded defaults
- SecurityConstraints 已删除，SecurityConfig 直接作为 LightweightSecurityShell 约束源，见 `attack_agent/constraints.py` 和 `attack_agent/config.py`
- 原语无配置时干净失败（`_clean_fail`），不再假装工作
- CodeSandbox 规则见 `attack_agent/apg.py` SAFE_BUILTINS / SAFE_IMPORTS（class/with/raise 已允许，lambda/global/nonlocal/delete/async 仍禁止；SAFE_IMPORTS 含 zlib/csv）
- 族关键词见 `attack_agent/apg.py` FAMILY_KEYWORDS（14 族：identity/input-interpreter/reflection-render/file-archive/encoding/binary + ssrf-server/ssti-template/csrf-state/idor-access/crypto-math/pwn-memory/protocol-logic/race-condition）
- 配置字段定义见 `attack_agent/config.py` 和 `config/settings.json`
- 可选依赖见 `pyproject.toml`

**Dual-Path Planning**:
- model=None → APGPlanner + HeuristicFreeExplorationPlanner（纯规则双路径）
- model=xxx → APGPlanner + ConstraintAwareReasoner（LLM 双路径）
- PathSelectionStrategy 动态选择；ObservationSummarizer 共享注入观测内容
- switch_path() 自动切换：STRUCTURED→FREE_EXPLORATION（停滞≥3次时）+ FREE_EXPLORATION→STRUCTURED（预算耗尽或置信度≥0.7时回切）
- 多族组合：_compose_multi_family_candidates() 融合 2 族步骤（观察→主族 + 操作→副族 + 验证→主族，副族得分≥0.7×主族得分时组合）

### Known Limitations (摘要)

当前系统**本地靶场解题率 4/4**（v4.4，全部通过）。关键进展：
- encoding-transform：structured-parse 自动提取 cookie + base64 解码，cookie 中的 flag 可被发现
- protocol-logic-boundary：token_chain + {observe.*} 模板替换支持多步 API 链式调用
- identity-boundary：SessionState 跨 Cycle 持久化，session-materialize 登录后 cookie 自动携带到后续请求
- Session 持久化：ProjectRecord.session_state 保存 cookies/auth_headers，下一个 planning cycle 自动恢复

**已知问题**：
- code-sandbox 仍禁止 lambda + 无 crypto 库 → 高级密码题不能解
- browser-inspect 不执行 JS → JS 渲染类 web 题受限（Playwright 可用但默认 stdlib 回退）

**本地靶场测试**：`python scripts/local_range.py` 启动 4 题（web-auth-easy/web-render-easy/web-encoding-medium/web-chain-medium）

**完整问题清单 + 四阶段解决计划**：见 [docs/CHANGELOG.md](docs/CHANGELOG.md) "Current Limitations & Roadmap" 章节

### Navigation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构决策 + 概念设计
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — 编码规则 + 项目约束
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — 版本历史 + 已完成里程碑
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — 用户操作手册
- [README.md](README.md) — 项目介绍
