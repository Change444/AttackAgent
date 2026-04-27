# AttackAgent 项目架构文档

**版本：** 3.0
**最后更新：** 2026-04-26
**状态：** 活跃开发中
**目的：** 本文档为 AttackAgent 项目的唯一真实架构源，所有开发决策和实施必须以此文档为准。

---

## 文档目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [核心模块](#3-核心模块)
4. [数据结构](#4-数据结构)
5. [接口规范](#5-接口规范)
6. [集成流程](#6-集成流程)
7. [配置管理](#7-配置管理)
8. [实施计划](#8-实施计划)
9. [验收标准](#9-验收标准)

---

## 1. 项目概述

### 1.1 项目愿景

构建一个解题能力极强的渗透测试 Agent，通过框架引导模型做出正确决策，同时不限制模型的创造力。系统采用"约束推理"而非"候选选择"的设计理念，为未来模型能力提升预留扩展空间。

### 1.2 核心价值

- **安全第一**：通过外部安全壳确保所有操作在授权范围内
- **框架引导**：提供约束条件而非固定选项，引导模型推理
- **渐进增强**：双路径架构确保稳定性，逐步探索创新
- **自适应性**：从实践中学习，动态发现和优化模式
- **可观测性**：完整的决策追踪和事件记录

### 1.3 设计原则

1. **渐进式改进**：保留现有功能，并行添加新能力
2. **约束推理**：通过约束条件引导模型，而非限制选择
3. **动态模式**：从固定模式转向动态发现和学习
4. **语义增强**：从词汇匹配转向语义理解
5. **单一真实源**：本文档为架构决策的唯一权威来源

### 1.4 技术栈

- **编程语言**：Python 3.10+
- **核心依赖**：标准库为主，最小化外部依赖
- **数据存储**：JSON 文件（可扩展为数据库）
- **向量检索**：可选，用于语义检索增强
- **模型接口**：通过协议定义，支持多种模型后端

---

## 2. 整体架构

### 2.1 架构层次图

```
┌─────────────────────────────────────────────────────────┐
│                    控制层 (Control Plane)                 │
│  ┌────────────────────────────────────────────────────┐  │
│  │  CompetitionPlatform (主平台入口)                   │  │
│  │  - solve_all() / run_cycle()                       │  │
│  │  - 提供竞赛流程管理                                 │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                   调度层 (Dispatch Layer)                 │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Dispatcher (任务调度器)                           │  │
│  │  - schedule() - 主调度逻辑                         │  │
│  │  - assign_worker() - 工作者分配                    │  │
│  │  - heartbeat() - 工作者心跳                        │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  LightweightSecurityShell (轻量级安全壳) ✅        │  │
│  │  - validate() - 安全约束验证                       │  │
│  │  - 在 runtime 执行前验证                           │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                   规划层 (Planning Layer)                 │
│  ┌────────────────────────────────────────────────────┐  │
│  │  EnhancedAPGPlanner (增强型规划器) 🆕               │  │
│  │  - plan() - 统一规划接口                           │  │
│  │  - 协调双路径规划                                  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────┐  ┌─────────────────────────┐ │
│  │  结构化路径              │  │  自由探索路径 🆕        │ │
│  │  Structured Path        │  │  Free Exploration Path  │ │
│  │                          │  │                         │ │
│  │  - PatternLibrary       │  │  - ConstraintAware      │ │
│  │  - HeuristicReasoner    │  │    Reasoner             │ │
│  │  - LLMReasoner (选择题)  │  │  - DynamicPattern       │ │
│  │  - EpisodeMemory        │  │    Composer            │ │
│  │  - 词汇检索             │  │  - SemanticRetrieval    │ │
│  │                          │  │    Engine              │ │
│  └──────────────────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                   执行层 (Execution Layer)                 │
│  ┌────────────────────────────────────────────────────┐  │
│  │  WorkerRuntime (工作者运行时)                       │  │
│  │  - run_task() - 任务执行                           │  │
│  │  - PrimitiveAdapter.execute() - 原始动作执行       │  │
│  │  - HttpSessionManager - 会话持久化管理 🆕          │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                  状态层 (State Layer)                      │
│  ┌────────────────────────────────────────────────────┐  │
│  │  StateGraphService (状态图服务)                    │  │
│  │  - 项目的单一真实源                                │  │
│  │  - 记录所有事件和状态变化                          │  │
│  │  - 提供查询和导出功能                              │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 2.2 双路径规划架构

```
规划请求 (Planning Request)
           ↓
┌─────────────────────────────────────────────┐
│  DualPathPlanner                            │
│  - 评估规划上下文                            │
│  - 选择路径类型                             │
└─────────────────────────────────────────────┘
           ↓
    ┌──────┴──────┐
    ↓             ↓
┌────────┐  ┌────────────┐
│结构化  │  │ 自由探索   │
│路径    │  │ 路径       │
└────────┘  └────────────┘
    ↓             ↓
ActionProgram  ActionProgram
    ↓             ↓
    └──────┬──────┘
           ↓
    SecurityShell验证
           ↓
    Runtime执行
```

### 2.3 核心设计模式

| 模式 | 应用场景 | 说明 |
|------|----------|------|
| 策略模式 | 路径选择 | 根据上下文动态选择规划策略 |
| 工厂模式 | 原始动作执行 | 根据类型创建对应的适配器 |
| 观察者模式 | 事件系统 | 组件订阅和响应状态变化 |
| 责任链模式 | 安全验证 | 多层约束验证 |
| 模板方法模式 | 规划流程 | 定义规划骨架，子类实现细节 |

---

## 3. 核心模块

### 3.1 控制层模块

#### 3.1.1 CompetitionPlatform

**文件位置：** `attack_agent/platform.py`

**职责：**
- 提供竞赛平台的端到端流程
- 管理挑战的生命周期
- 协调各个层的交互

**核心接口：**
```python
class CompetitionPlatform:
    def __init__(self,
                 provider: CompetitionProvider,
                 state_graph: StateGraphService,
                 dispatcher: Dispatcher,
                 controller: Controller):
        """初始化平台"""

    def solve_all(self, max_cycles: int = 50) -> None:
        """解决所有挑战"""

    def run_cycle(self) -> None:
        """执行单次循环"""
```

**关键流程：**
1. 从 Provider 获取挑战列表
2. 为每个挑战创建项目记录
3. 调度器执行任务
4. 控制器管理提交和提示
5. 更新状态和记录结果

#### 3.1.2 Controller

**文件位置：** `attack_agent/controller.py`

**职责：**
- 管理挑战状态转换
- 处理提交和提示逻辑
- 执行提交策略

**核心接口：**
```python
class Controller:
    def __init__(self,
                 provider: CompetitionProvider,
                 state_graph: StateGraphService,
                 submit_classifier: SubmitClassifier):
        """初始化控制器"""

    def submit_flag(self, project_id: str, candidate: CandidateFlag) -> SubmissionResult:
        """提交候选 flag"""

    def request_hint(self, project_id: str) -> HintResult:
        """请求提示"""
```

### 3.2 调度层模块

#### 3.2.1 Dispatcher

**文件位置：** `attack_agent/dispatcher.py`

**职责：**
- 任务调度和工作者分配
- 集成安全壳验证
- 管理工作者生命周期

**核心接口：**
```python
class Dispatcher:
    def __init__(self,
                 state_graph: StateGraphService,
                 runtime: WorkerRuntime,
                 strategy: StrategyLayer,
                 worker_pool: WorkerPool | None = None):
        """初始化调度器"""

    def schedule(self, project_id: str) -> None:
        """调度单个项目的任务"""

    def assign_worker(self, project_id: str) -> WorkerLease:
        """分配工作者"""

    def heartbeat(self, worker_id: str) -> None:
        """工作者心跳"""

    def mark_timeout(self, run_id: str) -> None:
        """标记超时"""

    def requeue(self, project_id: str, reason: str) -> None:
        """重新排队任务"""
```

**调度流程：**
```python
def schedule(self, project_id: str) -> None:
    # 1. 获取项目记录
    record = self.state_graph.projects[project_id]

    # 2. 状态转换处理
    if record.snapshot.stage == ProjectStage.BOOTSTRAP:
        # 选择工作者配置文件
        record.snapshot.worker_profile = self.strategy.select_profile(record.snapshot)
        record.snapshot.stage = ProjectStage.REASON
        return

    if record.snapshot.stage == ProjectStage.REASON:
        # 初始化模式图
        self.strategy.initialize_graph(record)
        return

    if record.snapshot.stage != ProjectStage.EXPLORE:
        return

    # 3. 生成计划
    program, memory_hits = self.strategy.next_program(record)
    if program is None:
        record.snapshot.stage = ProjectStage.CONVERGE
        return

    # 4. 分配工作者
    record.snapshot.worker_profile = program.required_profile
    worker = self.assign_worker(project_id)
    visible_primitives = self.runtime.registry.visible_primitives(program.required_profile)

    # 5. 编译任务包
    bundle = self.strategy.task_compiler.compile_bundle(
        record, program, program.required_profile, visible_primitives, memory_hits
    )

    # 6. ⭐ 安全壳验证（轻量级）
    validation = self.security_shell.validate(bundle)
    if validation.violations:
        # 记录验证事件
        self._record_validation_event(project_id, bundle.run_id, validation, program.id)

    # 7. 只有 critical 级别违规才阻止执行
    if not validation.allowed:
        return

    # 8. 执行任务
    events, outcome = self.runtime.run_task(bundle)

    # 9. 后续处理
    self.heartbeat(worker.worker_id)
    self.state_graph.record_program(project_id, program, outcome)
    for event in events:
        self.state_graph.append_event(event)
    self._record_outcome(record, program, outcome)
    self.strategy.update_after_outcome(record, program, outcome)
    record.snapshot.stage = self.strategy.stage_after_program(record)
```

#### 3.2.2 LightweightSecurityShell

**文件位置：** `attack_agent/constraints.py`

**职责：**
- 在 runtime 执行前验证约束
- 快速轻量级的安全检查
- 记录违规但不阻断决策

**核心接口：**
```python
class LightweightSecurityShell:
    def __init__(self, constraints: SecurityConstraints | None = None):
        """初始化安全壳"""

    def validate(self, bundle: TaskBundle) -> ValidationResult:
        """验证任务包是否满足安全约束"""
```

**验证规则：**
1. **目标范围验证**：检查目标是否在允许的 host 范围内
2. **原始动作计数验证**：检查原始动作调用次数限制
3. **程序结构验证**：检查程序步骤数量
4. **操作顺序验证**：检查是否先观察后行动
5. **资源限制验证**：检查预估成本
6. **禁止组合验证**：检查禁止的原始动作组合

**违规等级：**
- **critical**：阻止执行
- **warning**：记录但不阻止

### 3.3 规划层模块

#### 3.3.1 EnhancedAPGPlanner

**文件位置：** `attack_agent/enhanced_apg.py` 🆕

**职责：**
- 提供统一的双路径规划接口
- 协调结构化路径和自由探索路径
- 管理路径切换逻辑

**核心接口：**
```python
class EnhancedAPGPlanner:
    def __init__(self,
                 structured_planner: APGPlanner,
                 free_exploration_planner: ConstraintAwareReasoner,
                 semantic_retrieval: SemanticRetrievalEngine,
                 pattern_composer: DynamicPatternComposer,
                 config: DualPathConfig | None = None):
        """初始化增强型规划器"""

    def plan(self, record: ProjectRecord) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        """双路径规划"""

    def select_path(self, context: PlanningContext) -> PathType:
        """选择规划路径"""

    def switch_path(self, record: ProjectRecord, reason: str) -> None:
        """切换规划路径"""
```

**规划流程：**
```python
def plan(self, record: ProjectRecord) -> tuple[ActionProgram | None, list[RetrievalHit]]:
    # 1. 构建规划上下文
    context = self._build_planning_context(record)

    # 2. 选择路径
    path_type = self.select_path(context)

    # 3. 记录路径选择事件
    self._record_path_selection(record, path_type, context)

    # 4. 根据路径类型执行规划
    if path_type == PathType.STRUCTURED:
        program, hits = self._plan_structured(record, context)
    elif path_type == PathType.FREE_EXPLORATION:
        program, hits = self._plan_free_exploration(record, context)
    else:  # HYBRID
        program, hits = self._plan_hybrid(record, context)

    # 5. 更新探索预算
    if path_type == PathType.FREE_EXPLORATION:
        context.exploration_budget -= 1

    return program, hits
```

#### 3.3.2 结构化路径模块

##### PatternLibrary

**文件位置：** `attack_agent/apg.py`

**职责：**
- 定义静态模式族和关键词
- 根据挑战特征构建模式图
- 提供模式族得分

**核心接口：**
```python
class PatternLibrary:
    def build(self, project: ProjectSnapshot) -> PatternGraph:
        """构建模式图"""

    def _score_family(self, text: str, family: str) -> int:
        """为模式族评分"""
```

**模式族定义：**
```python
FAMILY_KEYWORDS = {
    "identity-boundary": ("login", "token", "cookie", "session", "jwt", "admin", "role", "auth"),
    "input-interpreter-boundary": ("sql", "query", "template", "command", "eval", "parser", "interpreter", "filter"),
    "reflection-render-boundary": ("render", "reflect", "html", "script", "browser", "dom", "comment", "xss"),
    "file-archive-forensics": ("zip", "archive", "file", "upload", "extract", "pcap", "image", "stego", "forensics"),
    "encoding-transform": ("base64", "decode", "encode", "cipher", "hash", "xor", "hex", "transform"),
    "binary-string-extraction": ("binary", "strings", "elf", "byte", "reverse", "symbol", "assembly", "pe"),
}
```

##### HeuristicReasoner

**文件位置：** `attack_agent/reasoning.py`

**职责：**
- 基于规则的候选选择
- 提供稳定的回退方案

**核心接口：**
```python
class HeuristicReasoner:
    def choose_profile(self, project: ProjectSnapshot) -> tuple[WorkerProfile, str]:
        """选择工作者配置文件"""

    def choose_program(self, context: ReasoningContext) -> ProgramDecision | None:
        """基于规则选择程序"""
```

##### LLMReasoner

**文件位置：** `attack_agent/reasoning.py`

**职责：**
- 基于模型的候选选择（选择题模式）
- 提供验证和回退机制

**核心接口：**
```python
class LLMReasoner(HeuristicReasoner):
    def __init__(self, model: ReasoningModel, fallback: HeuristicReasoner | None = None):
        """初始化 LLM 推理器"""

    def choose_profile(self, project: ProjectSnapshot) -> tuple[WorkerProfile, str]:
        """使用模型选择工作者配置文件"""

    def choose_program(self, context: ReasoningContext) -> ProgramDecision | None:
        """使用模型选择程序（从候选列表中）"""

    def _validate_program_response(self, context: ReasoningContext, response: dict) -> ProgramDecision | None:
        """验证模型响应"""
```

#### 3.3.3 自由探索路径模块 🆕

##### ConstraintAwareReasoner

**文件位置：** `attack_agent/constraint_aware_reasoner.py` 🆕

**职责：**
- 在约束条件下生成自由计划
- 不限制模型的推理过程
- 提供约束上下文构建

**核心接口：**
```python
class ConstraintAwareReasoner:
    def __init__(self,
                 model: ReasoningModel,
                 context_builder: ConstraintContextBuilder,
                 validator: LightweightSecurityShell):
        """初始化约束感知推理器"""

    def generate_constrained_plan(self, context: PlanningContext) -> ActionProgram | None:
        """生成约束感知的自由计划"""

    def _build_constraint_context(self, context: PlanningContext) -> ConstraintContext:
        """构建约束上下文"""

    def _generate_model_prompt(self, context: PlanningContext, constraints: ConstraintContext) -> str:
        """生成模型提示"""
```

**约束上下文构建：**
```python
@dataclass
class ConstraintContext:
    """约束上下文（用于模型）"""

    # 可用能力
    available_primitives: list[str]
    primitive_descriptions: dict[str, str]

    # 安全边界
    target_scope: str
    safety_rules: list[str]

    # 结构约束
    max_steps: int
    required_phases: list[str]

    # 资源约束
    max_estimated_cost: float
    time_budget_seconds: int

    # 语义约束
    attack_phases: list[str]
    observation_before_action: bool

    # 成功标准
    success_criteria: str

    def to_model_prompt(self, current_state: str) -> str:
        """生成模型可理解的约束描述"""
        # 生成结构化的约束说明
        # 重点：只说明约束，不限制具体步骤
```

**模型提示模板：**
```python
CONSTRAINT_AWARE_PROMPT = """
你是一个渗透测试专家，需要在一个CTF挑战中找到flag。

## 约束条件

### 可用的工具（原始动作）
{primitive_descriptions}

### 安全边界
- 目标范围：{target_scope}
- 安全规则：
{safety_rules}

### 计划结构要求
- 最大步骤数：{max_steps}
- 必须包含的阶段：{required_phases}
- 操作顺序：{observation_before_action}

### 攻击阶段要求
{attack_phases}

### 成功标准
{success_criteria}

## 当前状态
{current_state}

## 任务
基于上述约束条件，生成一个详细的执行计划。
计划应包含具体的步骤和工具使用，但不能违反任何约束条件。

请以JSON格式返回你的计划：
{{
    "rationale": "你的推理过程",
    "steps": [
        {{
            "primitive": "工具名称",
            "instruction": "具体说明",
            "parameters": {{}}
        }}
    ]
}}
"""
```

##### DynamicPatternComposer

**文件位置：** `attack_agent/dynamic_pattern_composer.py` 🆕

**职责：**
- 从成功案例动态发现模式
- 模式参数化和泛化
- 模式应用和组合

**核心接口：**
```python
class DynamicPatternComposer:
    def __init__(self, discovery_threshold: int = 3):
        """初始化动态模式组合器"""

    def compose_pattern(self, steps: list[PrimitiveActionStep]) -> PatternTemplate:
        """从具体步骤抽象出模式模板"""

    def apply_pattern(self, template: PatternTemplate, context: dict) -> list[PrimitiveActionStep]:
        """应用模式模板到具体上下文"""

    def discover_patterns(self, success_cases: list[EpisodeEntry]) -> list[PatternTemplate]:
        """从成功案例中发现新模式"""

    def store_pattern(self, pattern: PatternTemplate) -> None:
        """存储发现的模式"""

    def retrieve_patterns(self, context: dict) -> list[PatternTemplate]:
        """检索适用的模式"""
```

**模式模板数据结构：**
```python
@dataclass
class PatternTemplate:
    """动态模式模板"""
    id: str
    name: str
    description: str
    applicability_conditions: list[str]  # 适用条件
    steps_template: list[StepTemplate]
    parameters: dict[str, ParameterSpec]
    created_at: str
    usage_count: int = 0
    success_rate: float = 0.0

@dataclass
class StepTemplate:
    """步骤模板"""
    primitive: str
    instruction_template: str  # 包含占位符的指令
    parameter_defaults: dict[str, Any]

@dataclass
class ParameterSpec:
    """参数规范"""
    name: str
    type: str
    default_value: Any
    description: str
    required: bool
```

**模式发现算法：**
```python
class PatternDiscoveryAlgorithm:
    def find_common_sequences(self, sequences: list[list[str]], min_support: int = 3) -> list[list[str]]:
        """发现常见的步骤序列"""

    def parameterize_sequence(self, sequence: list[str], examples: list[list[dict]]) -> dict:
        """参数化步骤序列"""

    def compute_pattern_confidence(self, pattern: list[str], success_cases: list[EpisodeEntry]) -> float:
        """计算模式置信度"""
```

##### SemanticRetrievalEngine

**文件位置：** `attack_agent/semantic_retrieval.py` 🆕

**职责：**
- 基于语义相似性的历史案例检索
- 支持向量检索和混合检索
- 提供检索质量评分

**核心接口：**
```python
class SemanticRetrievalEngine:
    def __init__(self,
                 vector_store: VectorStore | None = None,
                 hybrid_alpha: float = 0.7):
        """初始化语义检索引擎"""

    def search(self, query: str, limit: int = 5) -> list[SemanticRetrievalHit]:
        """语义检索"""

    def index_episode(self, episode: EpisodeEntry) -> None:
        """索引新案例"""

    def update_index(self, episodes: list[EpisodeEntry]) -> None:
        """批量更新索引"""

    def compute_similarity(self, query: str, episode: EpisodeEntry) -> float:
        """计算语义相似度"""
```

**检索命中数据结构：**
```python
@dataclass
class SemanticRetrievalHit:
    """语义检索命中"""
    episode_id: str
    summary: str
    pattern_families: list[str]
    stop_reason: str

    # 语义相关字段
    semantic_similarity: float  # 语义相似度
    lexical_overlap: float      # 词汇重叠度
    hybrid_score: float         # 混合评分
    confidence: float           # 整体置信度
    relevance_explanation: str  # 相关性解释
```

**混合检索策略：**
```python
class HybridRetrievalStrategy:
    def search(self, query: str, episodes: list[EpisodeEntry]) -> list[SemanticRetrievalHit]:
        """混合检索：语义 + 词汇"""

    def compute_hybrid_score(self, semantic_sim: float, lexical_overlap: float) -> float:
        """混合评分计算：α * semantic_sim + β * lexical_overlap"""

    def rank_hits(self, hits: list[SemanticRetrievalHit]) -> list[SemanticRetrievalHit]:
        """重新排序检索结果"""
```

#### 3.3.4 路径选择模块 🆕

##### PathSelectionStrategy

**文件位置：** `attack_agent/path_selection.py` 🆕

**职责：**
- 评估当前状态适合哪条路径
- 根据复杂度、置信度、历史成功率决定
- 处理路径切换和回退

**核心接口：**
```python
class PathSelectionStrategy:
    def __init__(self, config: DualPathConfig):
        """初始化路径选择策略"""

    def select_path(self, context: PlanningContext) -> PathType:
        """选择规划路径"""

    def _evaluate_factors(self, context: PlanningContext) -> PathSelectionFactors:
        """评估路径选择因子"""

    def _should_use_free_exploration(self, factors: PathSelectionFactors) -> bool:
        """判断是否使用自由探索路径"""

    def _mixed_selection(self, context: PlanningContext, ratio: float = 0.7) -> PathType:
        """混合选择策略"""
```

**路径选择因子：**
```python
@dataclass
class PathSelectionFactors:
    """路径选择因子"""
    confidence_low: bool        # 置信度低
    complexity_high: bool       # 复杂度高
    stable_pattern_exists: bool # 存在稳定模式
    exploration_remaining: bool # 探索预算剩余
    fallback_available: bool    # 回退方案可用
```

**路径选择逻辑：**
```python
def select_path(self, context: PlanningContext) -> PathType:
    # 1. 评估因子
    factors = self._evaluate_factors(context)

    # 2. 检查硬性条件
    if not factors.exploration_remaining:
        return PathType.STRUCTURED

    if not factors.fallback_available and factors.confidence_low:
        return PathType.STRUCTURED  # 无回退时不冒险

    # 3. 复杂度高时优先自由探索
    if factors.confidence_low and factors.complexity_high:
        return PathType.FREE_EXPLORATION

    # 4. 存在稳定模式时使用结构化路径
    if factors.stable_pattern_exists:
        return PathType.STRUCTURED

    # 5. 混合策略
    return self._mixed_selection(context, self.config.structured_path_weight)
```

### 3.4 执行层模块

#### 3.4.1 WorkerRuntime

**文件位置：** `attack_agent/runtime.py`

**职责：**
- 执行 ActionProgram
- 管理原始动作适配器
- 创建 HttpSessionManager 并跨步骤传递
- 增量填充 completed_observations
- 聚合执行结果

**核心接口：**
```python
class WorkerRuntime:
    def __init__(self):
        """初始化工作者运行时"""

    def run_task(self, task_bundle: TaskBundle) -> tuple[list[Event], ActionOutcome]:
        """执行任务"""

    def checkpoint(self, bundle: TaskBundle) -> Event:
        """创建检查点"""
```

**执行流程：**
```python
def run_task(self, task_bundle: TaskBundle) -> tuple[list[Event], ActionOutcome]:
    aggregate = ActionOutcome(status="failed", failure_reason="no_steps")
    events: list[Event] = []

    # 创建会话管理器（每次 run_task 创建一个）
    session_manager = HttpSessionManager()

    # 循环执行每个步骤
    for step in task_bundle.action_program.steps:
        # 检查权限
        if step.primitive not in task_bundle.visible_primitives:
            continue

        # 执行原始动作（传入 session_manager）
        outcome = self.registry.adapters[step.primitive].execute(
            step, task_bundle, self.sandbox, session_manager
        )

        # 增量填充 completed_observations（供后续步骤引用）
        for obs in outcome.observations:
            task_bundle.completed_observations[obs.id] = obs

        # 聚合结果
        aggregate.observations.extend(outcome.observations)
        aggregate.artifacts.extend(outcome.artifacts)
        aggregate.derived_hypotheses.extend(outcome.derived_hypotheses)
        aggregate.candidate_flags.extend(outcome.candidate_flags)
        aggregate.cost += outcome.cost
        aggregate.novelty += outcome.novelty

        # 更新状态
        if outcome.status == "ok":
            aggregate.status = "ok"
            aggregate.failure_reason = None
        elif aggregate.failure_reason is None:
            aggregate.failure_reason = outcome.failure_reason

    # 生成事件
    for observation in aggregate.observations:
        events.append(self._create_observation_event(task_bundle, observation))

    for artifact in aggregate.artifacts:
        events.append(self._create_artifact_event(task_bundle, artifact))

    for hypothesis in aggregate.derived_hypotheses:
        events.append(self._create_hypothesis_event(task_bundle, hypothesis))

    for candidate in aggregate.candidate_flags:
        events.append(self._create_candidate_event(task_bundle, candidate))

    events.append(self._create_action_outcome_event(task_bundle, aggregate))
    events.append(self.checkpoint(task_bundle))

    return events, aggregate
```

#### 3.4.2 PrimitiveAdapter

**文件位置：** `attack_agent/runtime.py`

**职责：**
- 执行具体的原始动作
- 所有 9 个原始动作均支持真实执行路径
- 无配置时自动回退到元数据消费路径

**核心接口：**
```python
class PrimitiveAdapter:
    def execute(self,
                step: PrimitiveActionStep,
                bundle: TaskBundle,
                sandbox: CodeSandbox,
                session_manager: HttpSessionManager | None = None) -> ActionOutcome:
        """执行原始动作，session_manager 用于跨步骤会话持久化"""
```

**支持的原始动作：**

| 原始动作 | 真实执行路径 | 触发方式 | 回退路径 |
|----------|-------------|----------|----------|
| `http-request` | HTTP GET/POST/PUT/DELETE，cookie 持久化，重定向跟随 | `metadata.http_request` | `_consume_metadata` |
| `browser-inspect` | HTTP 抓取 + HTMLParser 解析，会话共享 | `metadata.browser_inspect` | `_consume_metadata` |
| `artifact-scan` | 本地文件扫描 + HTTP 下载 + zip/tar 解压 | `metadata.artifact_scan` 或 `step.parameters.location` (http/https/file) | `_consume_metadata` |
| `binary-inspect` | ASCII/UTF-8/UTF-16LE 字串提取 + ELF/PE 头解析 | `metadata.binary_inspect` 或 `step.parameters.location` | `_consume_metadata` |
| `code-sandbox` | AST 安全验证的 Python 执行 | `step.instruction` 含 Python 代码 | `_consume_metadata` |
| `session-materialize` | HTTP POST 登录 + cookie 持久化 | `metadata.session_materialize` | `_consume_metadata` |
| `structured-parse` | JSON/HTML/headers 解析 + 字段提取 | `step.parameters.parse_source/format/extract_fields` | `_consume_metadata` |
| `diff-compare` | difflib 序列对比 + 变更统计 | `step.parameters.baseline_observation_id/variant_observation_id` | `_consume_metadata` |
| `extract-candidate` | 多模式正则提取 + completed_observations 搜索 | `step.parameters.patterns` 或 `challenge.flag_pattern` | `_consume_metadata` |

#### 3.4.3 HttpSessionManager 🆕

**文件位置：** `attack_agent/runtime.py`

**职责：**
- 管理 HTTP 会话的 cookie 持久化
- 构建带 cookie 处理和重定向跟随的 opener
- 跨步骤共享会话状态

**数据结构：**
```python
@dataclass(slots=True)
class HttpSessionManager:
    cookie_jar: http.cookiejar.CookieJar = field(default_factory=http.cookiejar.CookieJar)
    max_redirects: int = 5

    def build_opener(self) -> request.OpenerDirector:
        """构建带 cookie 处理和重定向的 opener"""

    def get_cookies_text(self) -> list[str]:
        """获取所有 cookie 的文本表示"""
```

**使用方式：**
- `WorkerRuntime.run_task` 在每次任务执行开始时创建一个 `HttpSessionManager`
- 将 `session_manager` 传递给每个 `PrimitiveAdapter.execute` 调用
- `http-request`、`browser-inspect`、`session-materialize`、`artifact-scan` 共享同一会话

#### 3.4.4 CodeSandbox

**文件位置：** `attack_agent/apg.py`

**职责：**
- 安全执行 Python 代码片段
- AST 级别的安全验证
- 限制可用的内置函数和导入模块

**安全规则：**

允许的内置函数 (SAFE_BUILTINS)：
```python
SAFE_BUILTINS = {
    "print": print, "len": len, "range": range, "int": int, "str": str,
    "float": float, "list": list, "dict": dict, "tuple": tuple, "set": set,
    "bool": bool, "bytes": bytes, "bytearray": bytearray, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter, "sorted": sorted, "reversed": reversed,
    "min": min, "max": max, "sum": sum, "abs": abs, "isinstance": isinstance,
    "type": type, "ord": ord, "chr": chr, "hex": hex, "bin": bin,
    "round": round, "abs": abs, "all": all, "any": any,
    "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
    "IndexError": IndexError, "AttributeError": AttributeError,
    "RuntimeError": RuntimeError, "Exception": Exception, "__import__": __import__,
}
```

允许的导入模块 (SAFE_IMPORTS)：
```python
SAFE_IMPORTS = frozenset({
    "hashlib", "base64", "struct", "binascii", "itertools",
    "collections", "math", "re", "json",
})
```

AST 验证规则 (_SafeAstValidator)：
- **允许**：Import（仅 SAFE_IMPORTS）、ImportFrom（仅 SAFE_IMPORTS）、FunctionDef、Try、Assign
- **禁止**：ClassDef、Lambda、With、Raise、Global、Delete、dunder 属性访问
- **调用验证**：允许调用 `allowed_builtins | safe_imports | defined_names`

### 3.5 状态层模块

#### 3.5.1 StateGraphService

**文件位置：** `attack_agent/state_graph.py`

**职责：**
- 项目的单一真实源
- 记录所有事件和状态变化
- 提供查询和导出功能

**核心接口：**
```python
class StateGraphService:
    def __init__(self):
        """初始化状态图服务"""

    def upsert_project(self, project_snapshot: ProjectSnapshot) -> None:
        """插入或更新项目"""

    def append_event(self, event: Event) -> None:
        """添加事件"""

    def get_record(self, project_id: str) -> ProjectRecord | None:
        """获取项目记录"""

    def record_program(self, project_id: str, program: ActionProgram, outcome: ActionOutcome) -> None:
        """记录程序执行"""

    def export_handoff(self, project_id: str) -> HandoffMemory:
        """导出交接信息"""

    def import_handoff(self, handoff: HandoffMemory) -> ProjectRecord:
        """导入交接信息"""
```

**项目记录结构：**
```python
@dataclass
class ProjectRecord:
    snapshot: ProjectSnapshot
    world_state: WorldState
    run_journal: list[Event]
    candidate_flags: dict[str, CandidateFlag]
    handoff: HandoffMemory | None
    checkpoints: list[dict[str, Any]]
    submission_history: list[dict[str, Any]]
    observations: dict[str, Observation]
    artifacts: dict[str, Artifact]
    hypotheses: dict[str, Hypothesis]
    pattern_graph: PatternGraph | None
    stagnation_counter: int
    tombstones: list[str]
```

---

## 4. 数据结构

### 4.1 核心数据模型

#### ProjectSnapshot
```python
@dataclass
class ProjectSnapshot:
    project_id: str
    challenge: ChallengeDefinition
    priority: int = 100
    stage: ProjectStage = ProjectStage.BOOTSTRAP
    status: str = "new"
    worker_profile: WorkerProfile = WorkerProfile.NETWORK
    instance: ChallengeInstance | None = None
```

#### ChallengeDefinition
```python
@dataclass
class ChallengeDefinition:
    id: str
    name: str
    category: str
    difficulty: str
    target: str
    description: str = ""
    flag_pattern: str = r"flag\{[^}]+\}"
    metadata: dict[str, Any] = field(default_factory=dict)
```

#### ActionProgram
```python
@dataclass
class ActionProgram:
    id: str
    goal: str
    pattern_nodes: list[str]
    steps: list[PrimitiveActionStep]
    allowed_primitives: list[str]
    verification_rules: list[str]
    required_profile: WorkerProfile
    memory_refs: list[str] = field(default_factory=list)
    rationale: str = ""
    planner_source: str = "heuristic"
```

#### PrimitiveActionStep
```python
@dataclass
class PrimitiveActionStep:
    primitive: str
    instruction: str
    parameters: dict[str, Any] = field(default_factory=dict)
```

#### TaskBundle
```python
@dataclass
class TaskBundle:
    project_id: str
    run_id: str
    action_program: ActionProgram
    stage: ProjectStage
    worker_profile: WorkerProfile
    target: str
    challenge: ChallengeDefinition
    instance: ChallengeInstance
    handoff_summary: str
    visible_primitives: list[str]
    memory_hits: list[RetrievalHit] = field(default_factory=list)
    known_observation_ids: list[str] = field(default_factory=list)
    known_artifact_ids: list[str] = field(default_factory=list)
    known_hypothesis_ids: list[str] = field(default_factory=list)
    known_candidate_keys: list[str] = field(default_factory=list)
    completed_observations: dict[str, Observation] = field(default_factory=dict)  # 🆕
```

> **completed_observations** 🆕：WorkerRuntime.run_task 在每步执行后增量填充此字典。后续步骤（如 `structured-parse`、`diff-compare`、`extract-candidate`）可通过 observation ID 查找前序步骤产出的观测结果。

#### Event
```python
@dataclass
class Event:
    type: EventType
    project_id: str
    run_id: str
    payload: dict[str, Any]
    cost: float = 0.0
    source: str = "system"
    timestamp: Any = field(default_factory=utc_now)
```

### 4.2 枚举类型

#### ProjectStage
```python
class ProjectStage(str, Enum):
    BOOTSTRAP = "bootstrap"
    REASON = "reason"
    EXPLORE = "explore"
    CONVERGE = "converge"
    DONE = "done"
    ABANDONED = "abandoned"
```

#### WorkerProfile
```python
class WorkerProfile(str, Enum):
    NETWORK = "network"
    BROWSER = "browser"
    ARTIFACT = "artifact"
    BINARY = "binary"
    SOLVER = "solver"
    HYBRID = "hybrid"
```

#### EventType
```python
class EventType(str, Enum):
    PROJECT_UPSERTED = "project_upserted"
    INSTANCE_STARTED = "instance_started"
    OBSERVATION = "observation"
    ARTIFACT_ADDED = "artifact_added"
    HYPOTHESIS_ADDED = "hypothesis_added"
    CANDIDATE_FLAG = "candidate_flag"
    PROGRAM_COMPILED = "program_compiled"
    ACTION_OUTCOME = "action_outcome"
    SUBMISSION = "submission"
    HINT = "hint"
    WORKER_ASSIGNED = "worker_assigned"
    WORKER_HEARTBEAT = "worker_heartbeat"
    WORKER_TIMEOUT = "worker_timeout"
    REQUEUE = "requeue"
    CHECKPOINT = "checkpoint"
    MEMORY_STORED = "memory_stored"
    PROJECT_DONE = "project_done"
    PROJECT_ABANDONED = "project_abandoned"
    SECURITY_VALIDATION = "security_validation"
    PATH_SELECTION = "path_selection"              # 新增
    PATTERN_DISCOVERED = "pattern_discovered"      # 新增
    SEMANTIC_RETRIEVAL = "semantic_retrieval"      # 新增
    FREE_EXPLORATION_PLAN = "free_exploration_plan"  # 新增
```

#### PathType 🆕
```python
class PathType(str, Enum):
    STRUCTURED = "structured"            # 结构化路径
    FREE_EXPLORATION = "free_exploration"  # 自由探索路径
    HYBRID = "hybrid"                    # 混合路径
```

### 4.3 新增数据结构 🆕

#### PlanningContext 🆕
```python
@dataclass
class PlanningContext:
    """规划上下文"""
    record: ProjectRecord
    attempt_count: int
    historical_success_rate: float
    complexity_score: float
    pattern_confidence: float
    exploration_budget: int
    current_path: PathType = PathType.STRUCTURED
```

#### ConstraintContext 🆕
```python
@dataclass
class ConstraintContext:
    """约束上下文（用于模型）"""
    available_primitives: list[str]
    primitive_descriptions: dict[str, str]
    target_scope: str
    safety_rules: list[str]
    max_steps: int
    required_phases: list[str]
    max_estimated_cost: float
    time_budget_seconds: int
    attack_phases: list[str]
    observation_before_action: bool
    success_criteria: str
```

#### PatternTemplate 🆕
```python
@dataclass
class PatternTemplate:
    """动态模式模板"""
    id: str
    name: str
    description: str
    applicability_conditions: list[str]
    steps_template: list[StepTemplate]
    parameters: dict[str, ParameterSpec]
    created_at: str
    usage_count: int = 0
    success_rate: float = 0.0
```

#### SemanticRetrievalHit 🆕
```python
@dataclass
class SemanticRetrievalHit:
    """语义检索命中"""
    episode_id: str
    summary: str
    pattern_families: list[str]
    stop_reason: str
    semantic_similarity: float
    lexical_overlap: float
    hybrid_score: float
    confidence: float
    relevance_explanation: str
```

#### DualPathConfig 🆕
```python
@dataclass
class DualPathConfig:
    """双路径配置"""
    structured_path_weight: float = 0.7
    free_exploration_weight: float = 0.3
    max_exploration_attempts: int = 5
    exploration_budget_per_project: int = 3
    enable_pattern_discovery: bool = True
    pattern_discovery_threshold: int = 3
    enable_semantic_retrieval: bool = True
    semantic_retrieval_limit: int = 5
    hybrid_score_alpha: float = 0.7
    hybrid_score_beta: float = 0.3
```

---

## 5. 接口规范

### 5.1 规划器接口

#### 基础规划器接口
```python
class BasePlanner(Protocol):
    """基础规划器接口"""

    def plan(self, record: ProjectRecord) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        """规划接口"""
        ...

    def create_graph(self, project: ProjectSnapshot) -> PatternGraph:
        """创建模式图"""
        ...

    def update_graph(self, record: ProjectRecord, program: ActionProgram, outcome: ActionOutcome) -> None:
        """更新模式图"""
        ...
```

#### 增强规划器接口 🆕
```python
class EnhancedPlanner(Protocol):
    """增强规划器接口"""

    def plan(self, record: ProjectRecord) -> tuple[ActionProgram | None, list[RetrievalHit]]:
        """双路径规划接口"""
        ...

    def select_path(self, context: PlanningContext) -> PathType:
        """选择规划路径"""
        ...

    def switch_path(self, record: ProjectRecord, reason: str) -> None:
        """切换规划路径"""
        ...
```

### 5.2 推理器接口

#### 基础推理器接口
```python
class BaseReasoner(Protocol):
    """基础推理器接口"""

    def choose_profile(self, project: ProjectSnapshot) -> tuple[WorkerProfile, str]:
        """选择工作者配置文件"""
        ...

    def choose_program(self, context: ReasoningContext) -> ProgramDecision | None:
        """选择程序"""
        ...
```

#### 约束感知推理器接口 🆕
```python
class ConstraintAwareReasoner(Protocol):
    """约束感知推理器接口"""

    def generate_constrained_plan(self, context: PlanningContext) -> ActionProgram | None:
        """生成约束感知的自由计划"""
        ...

    def build_constraint_context(self, context: PlanningContext) -> ConstraintContext:
        """构建约束上下文"""
        ...

    def generate_model_prompt(self, context: PlanningContext, constraints: ConstraintContext) -> str:
        """生成模型提示"""
        ...
```

### 5.3 检索引擎接口 🆕

#### 语义检索引擎接口
```python
class SemanticRetrievalEngine(Protocol):
    """语义检索引擎接口"""

    def search(self, query: str, limit: int = 5) -> list[SemanticRetrievalHit]:
        """语义检索"""
        ...

    def index_episode(self, episode: EpisodeEntry) -> None:
        """索引新案例"""
        ...

    def update_index(self, episodes: list[EpisodeEntry]) -> None:
        """批量更新索引"""
        ...

    def compute_similarity(self, query: str, episode: EpisodeEntry) -> float:
        """计算语义相似度"""
        ...
```

#### 模式组合器接口 🆕
```python
class DynamicPatternComposer(Protocol):
    """动态模式组合器接口"""

    def compose_pattern(self, steps: list[PrimitiveActionStep]) -> PatternTemplate:
        """从具体步骤抽象出模式模板"""
        ...

    def apply_pattern(self, template: PatternTemplate, context: dict) -> list[PrimitiveActionStep]:
        """应用模式模板到具体上下文"""
        ...

    def discover_patterns(self, success_cases: list[EpisodeEntry]) -> list[PatternTemplate]:
        """从成功案例中发现新模式"""
        ...

    def store_pattern(self, pattern: PatternTemplate) -> None:
        """存储发现的模式"""
        ...

    def retrieve_patterns(self, context: dict) -> list[PatternTemplate]:
        """检索适用的模式"""
        ...
```

### 5.4 验证器接口

#### 安全壳验证器接口
```python
class SecurityValidator(Protocol):
    """安全验证器接口"""

    def validate(self, bundle: TaskBundle) -> ValidationResult:
        """验证任务包是否满足安全约束"""
        ...
```

### 5.5 模型接口

#### 推理模型接口
```python
class ReasoningModel(Protocol):
    """推理模型接口"""

    def complete_json(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        """JSON 补全接口"""
        ...
```

---

## 6. 集成流程

### 6.1 完整执行流程

```
1. 平台启动
   ↓
   CompetitionPlatform.solve_all()
   ↓
2. 挑战加载
   ↓
   Controller.sync_challenges()
   StateGraphService.upsert_project()
   ↓
3. 项目调度
   ↓
   Dispatcher.schedule(project_id)
   ↓
4. 工作者配置
   ↓
   Strategy.select_profile()
   ↓
5. 模式图初始化
   ↓
   EnhancedAPGPlanner.create_graph()
   ↓
6. 规划选择
   ↓
   PathSelectionStrategy.select_path()
   ├─→ 结构化路径
   │    ↓
   │    APGPlanner.plan()
   │    ├─ PatternLibrary.build()
   │    ├─ EpisodeMemory.search()
   │    └─ HeuristicReasoner.choose_program()
   │
   └─→ 自由探索路径 🆕
        ↓
        ConstraintAwareReasoner.generate_constrained_plan()
        ├─ SemanticRetrievalEngine.search()
        ├─ DynamicPatternComposer.retrieve_patterns()
        └─ Model.complete_json()
   ↓
7. 任务编译
   ↓
   TaskPromptCompiler.compile_bundle()
   ↓
8. 安全验证 ⭐
   ↓
   LightweightSecurityShell.validate()
   ├─→ allowed: True → 继续执行
   └─→ allowed: False → 记录事件，返回
   ↓
9. 任务执行
   ↓
   WorkerRuntime.run_task()
   ├─ HttpSessionManager 创建 🆕
   ├─ PrimitiveAdapter.execute(step, bundle, sandbox, session_manager) [每个步骤]
   │  ├─ http-request: GET/POST + cookie 持久化
   │  ├─ browser-inspect: HTMLParser + 会话共享
   │  ├─ session-materialize: HTTP POST 登录
   │  ├─ structured-parse: JSON/HTML/headers 解析
   │  ├─ diff-compare: difflib 序列对比
   │  ├─ artifact-scan: HTTP 下载 + 解压
   │  ├─ binary-inspect: UTF-8/wide + ELF/PE 头
   │  ├─ code-sandbox: AST 安全执行
   │  └─ extract-candidate: 多模式正则
   ├─ completed_observations 增量填充 🆕
   └─ 聚合结果
   ↓
10. 状态更新
    ↓
    StateGraphService.record_program()
    StateGraphService.append_event()
    ↓
11. 模式更新
    ↓
    EnhancedAPGPlanner.update_graph()
    ↓
12. 模式发现 🆕
    ↓
    DynamicPatternComposer.discover_patterns()
    ↓
13. 案例索引 🆕
    ↓
    SemanticRetrievalEngine.index_episode()
    ↓
14. 后续决策
    ↓
    Strategy.stage_after_program()
    ↓
15. 提交判断
    ↓
    Controller.submit_flag()
    ↓
16. 循环或结束
```

### 6.2 自由探索路径详细流程 🆕

```
1. 上下文构建
   ↓
   _build_planning_context(record)
   ├─ 分析当前状态
   ├─ 计算复杂度得分
   ├─ 评估历史成功率
   └─ 确定探索预算
   ↓
2. 约束构建
   ↓
   _build_constraint_context(context)
   ├─ 确定可用原始动作
   ├─ 设置安全边界
   ├─ 配置结构约束
   └─ 定义成功标准
   ↓
3. 语义检索
   ↓
   SemanticRetrievalEngine.search(query)
   ├─ 向量相似性搜索
   ├─ 词汇重叠匹配
   ├─ 混合评分计算
   └─ 结果排序
   ↓
4. 模式检索
   ↓
   DynamicPatternComposer.retrieve_patterns(context)
   ├─ 匹配适用条件
   ├─ 按成功率排序
   └─ 返回相关模式
   ↓
5. 模型推理
   ↓
   ReasoningModel.complete_json("generate_constrained_plan", payload)
   ├─ 生成约束提示
   ├─ 包含检索结果
   ├─ 包含相关模式
   └─ 请求模型生成计划
   ↓
6. 计划解析
   ↓
   _parse_plan_response(response, context)
   ├─ 验证响应格式
   ├─ 提取步骤列表
   ├─ 构建推理说明
   └─ 生成 ActionProgram
   ↓
7. 约束验证
   ↓
   LightweightSecurityShell.validate(bundle)
   ├─ 目标范围验证
   ├─ 原始动作计数验证
   ├─ 程序结构验证
   ├─ 操作顺序验证
   ├─ 资源限制验证
   └─ 禁止组合验证
   ↓
8. 结果返回
   ↓
   ActionProgram, RetrievalHit[]
```

### 6.3 模式发现流程 🆕

```
1. 成功案例收集
   ↓
   从 EpisodeMemory 获取成功案例
   ├─ stop_reason == "candidate_found"
   ├─ success == True
   └─ novelty > 0
   ↓
2. 步骤序列提取
   ↓
   从每个成功案例提取步骤序列
   ├─ 提取原始动作序列
   ├─ 提取参数值
   └─ 提取执行顺序
   ↓
3. 共同模式发现
   ↓
   PatternDiscoveryAlgorithm.find_common_sequences()
   ├─ 使用序列模式挖掘
   ├─ 统计序列出现频率
   └─ 过滤低频序列
   ↓
4. 参数化处理
   ↓
   PatternDiscoveryAlgorithm.parameterize_sequence()
   ├─ 比较多个示例
   ├─ 识别可变参数
   ├─ 识别固定参数
   └─ 生成参数规范
   ↓
5. 模板构建
   ↓
   DynamicPatternComposer.compose_pattern()
   ├─ 设置模板ID和名称
   ├─ 定义适用条件
   ├─ 生成步骤模板
   └─ 设置参数规范
   ↓
6. 质量评估
   ↓
   PatternDiscoveryAlgorithm.compute_pattern_confidence()
   ├─ 计算使用成功率
   ├─ 计算使用频率
   └─ 综合评估质量
   ↓
7. 模式存储
   ↓
   DynamicPatternComposer.store_pattern()
   ├─ 持久化模式模板
   ├─ 更新模式索引
   └─ 记录发现时间
```

---

## 7. 配置管理

### 7.1 配置文件结构

#### 主配置文件：`config/settings.json`
```json
{
  "platform": {
    "max_cycles": 50,
    "timeout_seconds": 300,
    "enable_auto_submit": true
  },
  "dual_path": {
    "structured_path_weight": 0.7,
    "free_exploration_weight": 0.3,
    "max_exploration_attempts": 5,
    "exploration_budget_per_project": 3
  },
  "pattern_discovery": {
    "enable": true,
    "threshold": 3,
    "auto_apply": false
  },
  "semantic_retrieval": {
    "enable": true,
    "limit": 5,
    "hybrid_alpha": 0.7,
    "hybrid_beta": 0.3,
    "vector_store": {
      "type": "memory",
      "embedding_model": "sentence-transformers/all-MiniLM-L6-v2"
    }
  },
  "security": {
    "allowed_hostpatterns": ["127.0.0.1", "localhost"],
    "max_http_requests": 30,
    "max_sandbox_executions": 5,
    "max_program_steps": 15,
    "require_observation_before_action": true,
    "max_estimated_cost": 50.0
  },
  "memory": {
    "persistence_enabled": true,
    "store_path": "data/episodes.json",
    "max_entries": 10000
  },
  "logging": {
    "level": "INFO",
    "enable_event_logging": true,
    "enable_performance_logging": false
  }
}
```

### 7.2 可选依赖 🆕

**文件位置：** `pyproject.toml`

```toml
[project.optional-dependencies]
openai = ["openai>=1.0"]
anthropic = ["anthropic>=0.20"]
http = ["requests>=2.28"]          # 🆕 HTTP 高级功能（stdlib 为默认回退）
browser = ["playwright>=1.40"]     # 🆕 浏览器自动化（stdlib HTTP 为默认回退）
all-models = ["openai>=1.0", "anthropic>=0.20"]
all = ["openai>=1.0", "anthropic>=0.20", "requests>=2.28", "playwright>=1.40"]
```

> **回退机制**：所有原始动作的默认实现使用 Python 标准库（`urllib.request`、`html.parser`、`json` 等）。安装 `requests` 或 `playwright` 后可获得增强功能，但未安装时系统仍可正常运行。

### 7.3 配置加载

```python
from dataclasses import dataclass
import json
from pathlib import Path

@dataclass
class PlatformConfig:
    max_cycles: int = 50
    timeout_seconds: int = 300
    enable_auto_submit: bool = True

@dataclass
class DualPathConfig:
    structured_path_weight: float = 0.7
    free_exploration_weight: float = 0.3
    max_exploration_attempts: int = 5
    exploration_budget_per_project: int = 3

@dataclass
class PatternDiscoveryConfig:
    enable: bool = True
    threshold: int = 3
    auto_apply: bool = False

@dataclass
class SemanticRetrievalConfig:
    enable: bool = True
    limit: int = 5
    hybrid_alpha: float = 0.7
    hybrid_beta: float = 0.3
    vector_store_type: str = "memory"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

@dataclass
class SecurityConfig:
    allowed_hostpatterns: list[str] = None
    max_http_requests: int = 30
    max_sandbox_executions: int = 5
    max_program_steps: int = 15
    require_observation_before_action: bool = True
    max_estimated_cost: float = 50.0

    def __post_init__(self):
        if self.allowed_hostpatterns is None:
            self.allowed_hostpatterns = ["127.0.0.1", "localhost"]

@dataclass
class MemoryConfig:
    persistence_enabled: bool = True
    store_path: str = "data/episodes.json"
    max_entries: int = 10000

@dataclass
class LoggingConfig:
    level: str = "INFO"
    enable_event_logging: bool = True
    enable_performance_logging: bool = False

@dataclass
class AttackAgentConfig:
    platform: PlatformConfig
    dual_path: DualPathConfig
    pattern_discovery: PatternDiscoveryConfig
    semantic_retrieval: SemanticRetrievalConfig
    security: SecurityConfig
    memory: MemoryConfig
    logging: LoggingConfig

    @classmethod
    def from_file(cls, config_path: Path) -> "AttackAgentConfig":
        """从配置文件加载"""
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return cls(
            platform=PlatformConfig(**data.get("platform", {})),
            dual_path=DualPathConfig(**data.get("dual_path", {})),
            pattern_discovery=PatternDiscoveryConfig(**data.get("pattern_discovery", {})),
            semantic_retrieval=SemanticRetrievalConfig(**data.get("semantic_retrieval", {})),
            security=SecurityConfig(**data.get("security", {})),
            memory=MemoryConfig(**data.get("memory", {})),
            logging=LoggingConfig(**data.get("logging", {})),
        )
```

---

## 8. 实施计划

### 8.1 实施阶段

#### 阶段1：基础架构（已完成 ✅）
- [x] 轻量级安全壳（LightweightSecurityShell）
- [x] 现有结构化路径（APGPlanner）
- [x] 基础规划器接口
- [x] 集成到 Dispatcher

#### 阶段2：自由探索路径（已完成 ✅）
- [x] 实现 ConstraintAwareReasoner
- [x] 实现约束上下文构建
- [x] 实现模型提示生成
- [x] 实现 EnhancedAPGPlanner
- [x] 实现路径选择逻辑
- [x] 集成到现有架构

#### 阶段3：动态模式发现（已完成 ✅）
- [x] 实现 DynamicPatternComposer
- [x] 实现模式发现算法
- [x] 实现模式存储和检索
- [x] 添加模式事件记录

#### 阶段4：语义检索增强（已完成 ✅）
- [x] 实现 SemanticRetrievalEngine
- [x] 实现向量存储接口
- [x] 实现混合检索策略
- [x] 集成向量嵌入模型

#### 阶段5：真实 PrimitiveAdapter 实现（已完成 ✅） 🆕
- [x] HttpSessionManager 会话持久化
- [x] http-request POST/PUT/DELETE + cookie + 重定向
- [x] session-materialize HTTP POST 登录
- [x] structured-parse JSON/HTML/headers 解析
- [x] diff-compare difflib 序列对比
- [x] browser-inspect HTMLParser + 无 localhost 限制 + 会话共享
- [x] artifact-scan HTTP 下载 + zip/tar 解压
- [x] binary-inspect UTF-8/wide 字串 + ELF/PE 头解析
- [x] extract-candidate 多模式正则 + completed_observations 搜索
- [x] CodeSandbox 安全导入白名单 + FunctionDef/Try 支持
- [x] TaskBundle.completed_observations 跨步骤数据共享

#### 阶段6：自适应和优化
- [ ] 实现路径选择自适应
- [ ] 添加性能监控
- [ ] 优化检索质量
- [ ] 优化规划延迟

### 8.2 开发优先级

| 优先级 | 模块 | 预计工作量 | 依赖 | 状态 |
|--------|------|------------|------|------|
| P0 | ConstraintAwareReasoner | 3天 | 安全壳 | ✅ 完成 |
| P0 | EnhancedAPGPlanner | 2天 | ConstraintAwareReasoner | ✅ 完成 |
| P0 | 路径选择逻辑 | 2天 | EnhancedAPGPlanner | ✅ 完成 |
| P0 | 真实 PrimitiveAdapter | 4天 | HttpSessionManager | ✅ 完成 |
| P1 | DynamicPatternComposer | 4天 | EnhancedAPGPlanner | ✅ 完成 |
| P1 | SemanticRetrievalEngine | 5天 | 向量模型 | ✅ 完成 |
| P2 | 自适应优化 | 3天 | 以上所有 | 待开发 |

### 8.3 里程碑

| 里程碑 | 目标 | 预计时间 | 状态 |
|--------|------|----------|------|
| M1 | 自由探索路径可用 | 1周 | ✅ 完成 |
| M2 | 双路径切换正常 | 1.5周 | ✅ 完成 |
| M3 | 模式发现功能 | 2.5周 | ✅ 完成 |
| M4 | 语义检索集成 | 3.5周 | ✅ 完成 |
| M5 | 真实 PrimitiveAdapter | 4.5周 | ✅ 完成 |
| M6 | 完整架构验证 | 5周 | 待开发 |

---

## 9. 验收标准

### 9.1 功能验收

#### 自由探索路径验收
- [x] 能够生成符合约束的自由计划
- [x] 模型提示包含正确的约束信息
- [x] 路径选择逻辑正常工作
- [x] 能够回退到结构化路径

#### 模式发现验收
- [x] 能够从成功案例发现新模式
- [x] 模式参数化正确
- [x] 模式应用准确
- [x] 模式质量评估合理

#### 语义检索验收
- [x] 能够索引新案例
- [x] 语义检索准确
- [x] 混合评分有效
- [x] 检索延迟可接受

#### 真实 PrimitiveAdapter 验收 🆕
- [x] 所有 9 个原始动作支持真实执行
- [x] HttpSessionManager cookie 持久化正常
- [x] POST/PUT/DELETE + form 编码正常
- [x] session-materialize HTTP POST 登录正常
- [x] structured-parse JSON/HTML/headers 解析正常
- [x] diff-compare 序列对比 + 变更统计正常
- [x] artifact-scan HTTP 下载 + zip/tar 解压正常
- [x] binary-inspect UTF-8/wide 字串 + ELF/PE 头正常
- [x] browser-inspect HTMLParser 正常，无 localhost 限制
- [x] CodeSandbox 安全导入 + FunctionDef/Try 正常
- [x] 元数据回退路径向后兼容正常

### 9.2 性能验收

| 指标 | 目标 | 测量方法 |
|------|------|----------|
| 规划延迟 | < 500ms | 计时测试 |
| 检索延迟 | < 200ms | 计时测试 |
| 内存使用 | < 500MB | 内存监控 |
| 模式发现时间 | < 1s | 计时测试 |

### 9.3 质量验收

- [ ] 代码覆盖率 > 80%
- [ ] 所有单元测试通过
- [ ] 集成测试通过
- [ ] 文档完整
- [ ] 代码审查通过

### 9.4 稳定性验收

- [ ] 连续运行 24 小时无崩溃
- [ ] 处理 100+ 挑战无异常
- [ ] 错误处理正确
- [ ] 日志记录完整

---

## 附录

### A. 文件组织

```
attack_agent/
├── __init__.py
├── platform.py              # 平台入口
├── controller.py            # 控制器
├── dispatcher.py            # 调度器
├── state_graph.py           # 状态图服务
├── runtime.py               # 运行时执行 (PrimitiveAdapter + HttpSessionManager 🆕)
├── strategy.py              # 策略层
├── apg.py                   # APG 规划器 (CodeSandbox 🆕)
├── reasoning.py             # 推理器
├── constraints.py           # 约束验证 ✅
├── models.py                # 基础模型
├── platform_models.py       # 平台模型 (TaskBundle.completed_observations 🆕)
├── world_state.py           # 世界状态
├── compilers.py             # 编译器
├── console.py               # 控制台
├── platform_demo.py         # 平台演示
├── config.py                # 配置管理 🆕
├── llm_adapters.py          # LLM 适配器 🆕
├── enhanced_apg.py          # 增强规划器 🆕
├── constraint_aware_reasoner.py  # 约束感知推理器 🆕
├── dynamic_pattern_composer.py  # 动态模式组合器 🆕
├── semantic_retrieval.py    # 语义检索引擎 🆕
└── path_selection.py        # 路径选择策略 🆕

config/
├── settings.json            # 主配置文件
├── dual_path.json           # 双路径配置
├── security.json            # 安全配置
└── logging.json             # 日志配置

tests/
├── test_platform_flow.py
├── test_apg_engine.py
├── test_state_graph.py
├── test_world_state.py
├── test_provider.py
├── test_constraints.py      # 约束测试 ✅
├── test_enhanced_apg.py     # 增强规划器测试 🆕
├── test_constraint_aware_reasoner.py  # 约束推理测试 🆕
├── test_dynamic_pattern_composer.py   # 模式组合测试 🆕
├── test_semantic_retrieval.py         # 语义检索测试 🆕
├── test_path_selection.py            # 路径选择测试 🆕
├── test_real_primitives.py           # 真实原始动作测试 🆕 (38 tests)
├── test_config.py                    # 配置测试
├── test_llm_adapters.py              # LLM适配器测试
└── test_semantic_retrieval_unit.py   # 语义检索单元测试

docs/
├── ARCHITECTURE.md          # 本文档
├── ARCHITECTURE_IMPROVEMENT_PLAN.md  # 改进方案
├── CURRENT_STATE.md
├── NEXT_STEPS.md
└── API.md                   # API 文档

data/
├── episodes.json            # 案例记忆
├── patterns.json            # 发现的模式
└── vectors/                 # 向量存储 🆕
```

### B. 术语表

| 术语 | 定义 |
|------|------|
| ActionProgram | 动作程序，包含原始动作步骤的执行计划 |
| PrimitiveActionStep | 原始动作步骤，不可再分解的基本操作 |
| TaskBundle | 任务包，包含执行一个程序所需的所有信息 |
| PatternGraph | 模式图，表示挑战解决的模式结构 |
| EpisodeMemory | 案例记忆，存储历史解决案例 |
| RetrievalHit | 检索命中，检索到的相关案例 |
| ConstraintViolation | 约束违规，违反安全约束的记录 |
| ValidationResult | 验证结果，约束验证的输出 |
| SecurityShell | 安全壳，外部约束验证层 |
| DualPathPlanner | 双路径规划器，支持结构化和自由探索路径 |
| ConstraintAwareReasoner | 约束感知推理器，在约束条件下生成计划 |
| DynamicPatternComposer | 动态模式组合器，发现和应用模式 |
| SemanticRetrievalEngine | 语义检索引擎，基于语义相似性检索 |
| PathType | 路径类型，结构化、自由探索、混合 |
| PlanningContext | 规划上下文，规划过程的信息 |
| ConstraintContext | 约束上下文，用于模型的约束信息 |
| HttpSessionManager | HTTP 会话管理器，管理 cookie 持久化和重定向 | 🆕 |
| completed_observations | 完成的观测字典，TaskBundle 上跨步骤数据共享 | 🆕 |
| SAFE_IMPORTS | CodeSandbox 允许导入的模块白名单 | 🆕 |
| SAFE_BUILTINS | CodeSandbox 允许的内置函数白名单 | 🆕 |
| _SafeAstValidator | AST 安全验证器，跟踪 defined_names | 🆕 |
| _HTMLPageParser | HTML 解析器，替代 regex 提取 | 🆕 |

### C. 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| 3.0 | 2026-04-26 | 真实 PrimitiveAdapter 实现，HttpSessionManager，completed_observations，CodeSandbox 增强 |
| 2.0 | 2026-04-25 | 添加双路径架构，完整重写 |
| 1.0 | - | 初始版本 |

---

**文档维护者：** AttackAgent 开发团队
**最后审核：** 2026-04-26
**下次审核：** 实施完成后