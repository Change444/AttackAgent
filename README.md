# AttackAgent

面向授权靶场和 CTF 竞赛的渗透测试 Agent。核心设计：**约束推理而非候选选择**——框架引导模型决策，不限制创造力。

本项目**不**包含攻击载荷、互联网扫描或任意命令生成。runtime 仅用于授权本地靶场和受控 fixture。

## Quick Start

```bash
# 安装
pip install -e .
# LLM 支持
pip install -e ".[openai]"   # 或 pip install openai>=1.0

# 运行测试
python -m unittest discover tests/

# 纯规则模式
python -m attack_agent --config config/settings.json

# 对接 HTTP 靶场
python -m attack_agent --provider-url http://127.0.0.1:8080

# 接入 LLM
python -m attack_agent --config config/settings.json --model openai --verbose
```

## Architecture

| 层 | 核心模块 | 职责 |
|----|----------|------|
| 控制层 | CompetitionPlatform | 挑战生命周期，配置加载 |
| 调度层 | Dispatcher + SecurityShell | 状态机调度，安全壳验证 |
| 规划层 | EnhancedAPGPlanner | 双路径规划（结构化 + 自由探索） |
| 执行层 | WorkerRuntime (9 原语) | 真实执行 + session 持久化 |
| 状态层 | StateGraphService | 单一真实源，事件日志 |

完整架构详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## Documentation

- [CLAUDE.md](CLAUDE.md) — AI agent onboarding（使用 Claude Code 时首先阅读）
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构决策 + 概念设计
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — 编码规则 + 项目约束
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — 版本历史 + 已完成里程碑
- [config/settings.json](config/settings.json) — 默认配置

## Design Choices

- 安全壳在执行前验证约束，critical 违规阻止执行
- 原语适配器是主要扩展机制，不是每种挑战类型一个插件
- 双路径架构：结构化路径提供稳定回退，自由探索路径利用模型创造力
- 状态图服务是项目、日志、证据、交接、模式状态的单一真实源
- 推理在边界候选中选择，不绕过 Provider、Runtime 或 StateGraph 边界