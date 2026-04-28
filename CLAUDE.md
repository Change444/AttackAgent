# AttackAgent — CLAUDE.md

## Project

AttackAgent 是面向授权靶场和 CTF 竞赛的渗透测试 Agent。设计理念：**约束推理而非候选选择**——框架引导模型决策，不限制创造力。双路径架构（结构化 + 自由探索），外部安全壳确保操作在授权范围内。

语言：中文文档（代码和标识符英文）。技术栈：Python 3.10+，stdlib-first，可选 openai/anthropic/sentence-transformers。

## Quick Start

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

## Architecture (5-Layer)

| 层 | 核心模块 | 职责 |
|----|----------|------|
| 控制层 | CompetitionPlatform (`platform.py`) | 挑战生命周期，配置加载 |
| 调度层 | Dispatcher (`dispatcher.py`) + SecurityShell (`constraints.py`) | 状态机调度，安全壳验证 |
| 规划层 | EnhancedAPGPlanner (`enhanced_apg.py`) | 双路径规划，路径选择/切换 |
| 执行层 | WorkerRuntime (`runtime.py`) | 9 个原语执行，session 持久化 |
| 状态层 | StateGraphService (`state_graph.py`) | 单一真实源，事件日志 |

完整架构：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Module Map

| 模块 | 文件 | 职责 |
|------|------|------|
| CompetitionPlatform | `platform.py` | 主入口，model=None/xxx 分支构建不同规划器 |
| CLI | `__main__.py` | `python -m attack_agent` 命令行接口 |
| Dispatcher | `dispatcher.py` | 状态机调度，集成安全壳 |
| EnhancedAPGPlanner | `enhanced_apg.py` | 双路径规划 |
| ConstraintAwareReasoner | `constraint_aware_reasoner.py` | LLM 约束推理 |
| HeuristicFreeExplorationPlanner | `heuristic_free_exploration.py` | 无 LLM 自由探索 |
| PathSelectionStrategy | `path_selection.py` | 置信度/复杂度路径选择 |
| PatternInjector | `pattern_injector.py` | 动态模式回注 |
| DynamicPatternComposer | `dynamic_pattern_composer.py` | 成功案例模式发现 |
| SemanticRetrievalEngine | `semantic_retrieval.py` | TF-IDF + embedding 混合检索 |
| LightweightSecurityShell | `constraints.py` | 执行前约束验证 |
| ObservationSummarizer | `observation_summarizer.py` | 观测→有限长度文本 |
| AttackAgentConfig | `config.py` | JSON + dataclass 配置 |

## Key Rules

- 安全壳在 runtime 执行前验证；critical 违规阻止执行
- 参数优先级：`step.parameters` > metadata defaults > hardcoded defaults
- SecurityConstraints 值来自 SecurityConfig（单一源），见 `attack_agent/constraints.py`
- 原语无 instance.metadata 配置时走 `_consume_metadata` 回退路径
- CodeSandbox 规则见 `attack_agent/apg.py` SAFE_BUILTINS / SAFE_IMPORTS
- 配置字段定义见 `attack_agent/config.py` 和 `config/settings.json`
- 可选依赖见 `pyproject.toml`

**Dual-Path Planning**:
- model=None → APGPlanner + HeuristicFreeExplorationPlanner（纯规则双路径）
- model=xxx → APGPlanner + ConstraintAwareReasoner（LLM 双路径）
- PathSelectionStrategy 动态选择；ObservationSummarizer 共享注入观测内容

## Known Limitations (摘要)

当前系统**无法接入真实 CTF 靶场并成功解题**。关键差距：
- 无 CTFd/HackTheBox Provider 适配器 + 无认证机制 → 连不上真实靶场
- browser-inspect 不执行 JS、http-request 无 multipart/session-materialize 无 CSRF → web 题 85% 不能解
- 6 族关键词过浅 + 步骤空模板 + 3 次失败放弃 → 规划策略僵硬
- 原语假数据回退路径掩盖能力不足 → runtime.py 膨胀

**完整问题清单 + 四阶段解决计划**：见 [docs/CHANGELOG.md](docs/CHANGELOG.md) "Current Limitations & Roadmap" 章节

## Navigation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构决策 + 概念设计
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — 编码规则 + 项目约束
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — 版本历史 + 已完成里程碑
- [README.md](README.md) — 项目介绍