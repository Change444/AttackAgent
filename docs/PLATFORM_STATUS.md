# AttackAgent 平台使用指南

## 一、今天完成的所有工作

### Phase 2-5：核心架构模块实现

| 模块 | 文件 | 说明 |
|------|------|------|
| ConstraintAwareReasoner | `attack_agent/constraint_aware_reasoner.py` | 约束感知推理器，在安全约束下生成自由攻击计划 |
| PathSelectionStrategy | `attack_agent/path_selection.py` | 双路径选择策略，根据置信度/复杂度决定走结构化还是自由探索 |
| DynamicPatternComposer | `attack_agent/dynamic_pattern_composer.py` | 动态模式组合器，从成功案例发现攻击模式 |
| SemanticRetrievalEngine | `attack_agent/semantic_retrieval.py` | 语义检索引擎，TF-IDF混合检索历史经验 |
| EnhancedAPGPlanner | `attack_agent/enhanced_apg.py` | 增强型规划器，协调双路径规划 |
| LightweightSecurityShell | `attack_agent/constraints.py` | 轻量级安全壳，在执行前验证安全约束 |
| 配置系统 | `attack_agent/config.py` + `config/settings.json` | 完整的配置管理，JSON + dataclass 映射 |
| LLM适配器 | `attack_agent/model_adapter.py` | OpenAI/Anthropic 适配器 + 工厂函数 |

### 关键集成变更

- `attack_agent/platform_models.py` — 新增 PathType、EventType 扩展、PlanningContext、DualPathConfig
- `attack_agent/platform.py` — CompetitionPlatform 接入 EnhancedAPGPlanner，支持 `model` 参数
- `attack_agent/constraint_aware_reasoner.py` — `model: Any` 修正为 `model: ReasoningModel`
- `attack_agent/strategy.py` — StrategyLayer 支持鸭子类型的 planner（APGPlanner 或 EnhancedAPGPlanner）
- `attack_agent/__init__.py` — 导出所有新模块
- `pyproject.toml` — 新增可选依赖组 `[openai]`, `[anthropic]`, `[all-models]`

### 测试

- 127 个测试全部通过（原 40 + 新增 87）
- 新增 7 个测试文件覆盖所有新模块

---

## 二、平台当前架构

```
┌──────────────────────────────────────────────────┐
│  控制层: CompetitionPlatform                      │
│  - solve_all() / run_cycle()                      │
│  - model=None → APGPlanner(HeuristicReasoner)     │
│  - model=xxx → EnhancedAPGPlanner(双路径)         │
└──────────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────────┐
│  调度层: Dispatcher + LightweightSecurityShell     │
│  - schedule() 状态机驱动                          │
│  - SecurityShell 在执行前验证                     │
└──────────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────────┐
│  规划层: EnhancedAPGPlanner (双路径)              │
│                                                    │
│  结构化路径                    自由探索路径          │
│  ├─ PatternLibrary             ├─ ConstraintAware  │
│  ├─ LLMReasoner                │   Reasoner        │
│  └─ EpisodeMemory              ├─ DynamicPattern   │
│                                 │   Composer        │
│                                 └─ SemanticRetrieval│
│                                    Engine           │
└──────────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────────┐
│  执行层: WorkerRuntime + PrimitiveAdapter          │
│  - http-request, browser-inspect, code-sandbox 等 │
└──────────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────────┐
│  状态层: StateGraphService                        │
│  - 项目记录、事件日志、模式图、候选flag           │
└──────────────────────────────────────────────────┘
```

---

## 三、如何使用

### 3.1 纯规则模式（无需 LLM，无需安装任何 SDK）

```python
from attack_agent.platform import CompetitionPlatform
from attack_agent.provider import LocalHTTPCompetitionProvider

# 连接本地靶场平台
provider = LocalHTTPCompetitionProvider("http://127.0.0.1:8000")

# 无模型时，自动使用 HeuristicReasoner（纯规则推理）
platform = CompetitionPlatform(provider)
platform.solve_all()
```

此时 Agent 使用结构化路径（APGPlanner），基于模式图和启发式规则进行攻击，**不调用任何 LLM**。

### 3.2 接入 OpenAI 模型

```bash
# 安装 OpenAI SDK
pip install attack-agent[openai]
# 或
pip install openai>=1.0
```

```python
import os
from attack_agent.platform import CompetitionPlatform
from attack_agent.provider import LocalHTTPCompetitionProvider
from attack_agent.model_adapter import build_model_from_config
from attack_agent.config import ModelConfig

# 通过环境变量配置 API Key（推荐）
os.environ["OPENAI_API_KEY"] = "sk-your-key"

model_config = ModelConfig(
    provider="openai",
    model_name="gpt-4o",
    api_key_env="OPENAI_API_KEY",
    temperature=0.3,
)

model = build_model_from_config(model_config)

provider = LocalHTTPCompetitionProvider("http://127.0.0.1:8000")
platform = CompetitionPlatform(provider, model=model)
platform.solve_all()
```

接入模型后，平台自动构建 EnhancedAPGPlanner，启用**双路径规划**：
- **结构化路径**：LLMReasoner 在候选程序中做选择题
- **自由探索路径**：ConstraintAwareReasoner 在约束条件下自由生成攻击计划

### 3.3 接入 Anthropic (Claude) 模型

```bash
pip install attack-agent[anthropic]
# 或
pip install anthropic>=0.20
```

```python
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-your-key"

model_config = ModelConfig(
    provider="anthropic",
    model_name="claude-sonnet-4-20250514",
    api_key_env="ANTHROPIC_API_KEY",
)

model = build_model_from_config(model_config)
platform = CompetitionPlatform(provider, model=model)
platform.solve_all()
```

### 3.4 通过配置文件启动

```python
from pathlib import Path
from attack_agent.config import AttackAgentConfig
from attack_agent.model_adapter import build_model_from_config

# 加载配置
config = AttackAgentConfig.from_file(Path("config/settings.json"))

# 修改配置中的 model section 后:
# config/settings.json 中 "model": {"provider": "openai", "api_key_env": "OPENAI_API_KEY", ...}

model = build_model_from_config(config.model)
platform = CompetitionPlatform(provider, model=model)
```

### 3.5 连接靶场

Agent 通过 `CompetitionProvider` 协议与靶场通信。支持两种方式：

**方式1：HTTP API（真实靶场）**

靶场平台需提供以下 REST API 端点：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/challenges` | GET | 列出所有挑战 |
| `/start_challenge` | POST | 启动挑战实例 |
| `/stop_challenge` | POST | 停止实例 |
| `/submit` | POST | 提交 flag |
| `/hint` | POST | 请求提示 |
| `/status/{instance_id}` | GET | 查询实例状态 |

```python
provider = LocalHTTPCompetitionProvider("http://靶场地址:端口")
```

**方式2：内存模拟（开发/测试）**

```python
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.platform_models import ChallengeDefinition

provider = InMemoryCompetitionProvider([
    ChallengeDefinition(
        id="web-sqli",
        name="SQL注入挑战",
        category="web",
        difficulty="easy",
        target="http://127.0.0.1:8080",
        description="一个包含SQL注入漏洞的登录页面",
        metadata={"flag": "flag{sql_injection}", "hint": "尝试在登录表单中注入"},
    ),
])
```

---

## 四、平台能完成什么任务

| 能力 | 状态 | 说明 |
|------|------|------|
| 纯规则攻击（结构化路径） | 已完成 | HeuristicReasoner + PatternLibrary + APGPlanner |
| LLM辅助攻击（选择题模式） | 已完成 | LLMReasoner 从候选程序中选择最佳方案 |
| 约束自由推理（自由探索路径） | 已完成 | ConstraintAwareReasoner 在约束条件下生成攻击计划 |
| 双路径自动切换 | 已完成 | PathSelectionStrategy 根据上下文动态选择路径 |
| 安全约束验证 | 已完成 | LightweightSecurityShell 在执行前拦截危险操作 |
| 动态模式发现 | 已完成 | 从成功案例自动发现新攻击模式 |
| 语义经验检索 | 已完成 | TF-IDF 混合检索历史经验 |
| OpenAI/Anthropic 适配 | 已完成 | model_adapter.py，惰性导入，可选依赖 |
| 配置系统 | 已完成 | JSON + dataclass，支持文件加载 |
| 状态追踪与交接 | 已完成 | StateGraphService，完整的事件日志 |

---

## 五、当前缺点与局限性

### 5.1 执行层原语是模拟实现

WorkerRuntime 中的 PrimitiveAdapter（http-request, browser-inspect 等）当前是**模拟执行**，返回硬编码或随机数据。这意味着：

- Agent 能**规划**出正确的攻击步骤，但**无法真正执行** HTTP 请求、浏览器检查等操作
- 要对接真实靶场，需要实现真实的 PrimitiveAdapter（发送真实 HTTP 请求、解析真实 HTML 等）

### 5.2 语义检索仅使用 TF-IDF

SemanticRetrievalEngine 的向量存储是 `InMemoryVectorStore`，基于 TF-IDF/token 重叠计算相似度，没有使用真正的 embedding 模型。这意味着：

- 检索精度有限，对语义相近但词汇不同的案例可能漏检
- 要提升检索质量，需接入真正的向量数据库和 embedding 模型

### 5.3 模式图是静态预定义的

PatternLibrary 的模式族（6 种攻击模式）是硬编码的关键词匹配。DynamicPatternComposer 可以动态发现新模式，但发现的模式目前只在自由探索路径中使用，没有自动回注到模式图。

### 5.4 无 CLI 入口

目前没有命令行工具（如 `attack-agent run --config settings.json`），只能通过 Python API 启动。

### 5.5 SecurityConstraints 硬编码在 Dispatcher 中

Dispatcher 和 CompetitionPlatform 中的 SecurityConstraints 是硬编码的默认值，没有从 AttackAgentConfig.security 中读取。配置系统的安全约束和实际使用的约束可能不一致。

### 5.6 双路径只在有 model 时激活

没有 model 时，Agent 只走结构化路径（APGPlanner），不具备自由探索能力。即使不使用 LLM，也可以让 ConstraintAwareReasoner 使用启发式模板生成计划，但目前未实现。

---

## 六、下一步建议

### 优先级 P0（必须做）

1. **实现真实 PrimitiveAdapter** — http-request 需要发送真实 HTTP 请求并解析响应，extract-candidate 需要真正匹配 flag 格式。这是让 Agent 在真实靶场上工作的前提。

2. **SecurityConstraints 与 Config 对齐** — Dispatcher 和 CompetitionPlatform 应从 `AttackAgentConfig.security` 读取约束，而非硬编码默认值。

### 优先级 P1（强烈建议）

3. **CLI 入口** — 添加 `__main__.py` 或 CLI 工具，支持 `python -m attack_agent --config config/settings.json` 启动。

4. **真实靶场集成测试** — 搭建一个本地 CTF 靶场（如 CTFd），验证从 `solve_all()` 到 flag 提交的完整流程。

5. **接入真正 embedding 模型** — 将 SemanticRetrievalEngine 的 InMemoryVectorStore 替换为支持真实 embedding 的实现（如 sentence-transformers 或外部向量数据库）。

### 优先级 P2（增强功能）

6. **启发式自由探索模板** — 在无 LLM 时，ConstraintAwareReasoner 也能基于启发式模板生成自由计划，让双路径在纯规则模式下也能工作。

7. **模式回注机制** — DynamicPatternComposer 发现的模式自动注入到 PatternLibrary，让结构化路径也能使用新发现的模式。

8. **日志与监控** — 完善日志系统，添加性能指标收集，支持外部监控系统。

9. **多轮对话式交互** — 支持 Human-in-the-loop，在关键决策点暂停等待人工确认。

---

## 七、快速开始检查清单

```bash
# 1. 克隆项目
git clone <repo-url> && cd AttackAgent

# 2. 运行测试验证
python -m unittest discover tests/

# 3. 纯规则模式启动（无需任何外部依赖）
python -c "
from attack_agent.platform import CompetitionPlatform
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.platform_models import ChallengeDefinition

provider = InMemoryCompetitionProvider([
    ChallengeDefinition(id='c1', name='Test', category='web',
                         difficulty='easy', target='http://127.0.0.1:8000',
                         description='test'),
])
platform = CompetitionPlatform(provider)
print('Platform created, planner:', type(platform.strategy.planner).__name__)
"

# 4. 接入 LLM（可选）
pip install attack-agent[openai]    # 或 pip install openai>=1.0
# 设置 OPENAI_API_KEY 环境变量后即可使用

# 5. 查看配置
python -c "
from attack_agent.config import AttackAgentConfig
from pathlib import Path
config = AttackAgentConfig.from_file(Path('config/settings.json'))
print('Model provider:', config.model.provider)
print('All config loaded OK')
"
```