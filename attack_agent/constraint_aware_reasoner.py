from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import new_id
from .platform_models import (
    ActionProgram,
    PlanningContext,
    PrimitiveActionStep,
    WorkerProfile,
)
from .constraints import LightweightSecurityShell, SecurityConstraints
from .reasoning import ReasoningModel
from .observation_summarizer import ObservationSummarizer


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
            "parameters": {{
                "根据工具说明填入具体参数，没有需要的参数时留空{{}}"
            }}
        }}
    ]
}}

示例步骤：
{{
    "primitive": "http-request",
    "instruction": "访问登录页面获取表单信息",
    "parameters": {{
        "method": "GET",
        "path": "/login"
    }}
}}
"""


@dataclass(slots=True)
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

    def to_model_prompt(self, current_state: str) -> str:
        """生成模型可理解的约束描述"""
        primitive_desc_lines = "\n".join(
            f"- {name}: {desc}" for name, desc in self.primitive_descriptions.items()
        )
        safety_lines = "\n".join(f"- {rule}" for rule in self.safety_rules)
        phases_str = ", ".join(self.attack_phases)
        required_str = ", ".join(self.required_phases)

        return CONSTRAINT_AWARE_PROMPT.format(
            primitive_descriptions=primitive_desc_lines,
            target_scope=self.target_scope,
            safety_rules=safety_lines,
            max_steps=self.max_steps,
            required_phases=required_str,
            observation_before_action="先观察再行动" if self.observation_before_action else "无顺序限制",
            attack_phases=phases_str,
            success_criteria=self.success_criteria,
            current_state=current_state,
        )


PRIMITIVE_DESCRIPTIONS: dict[str, str] = {
    "http-request": "发送HTTP请求，获取响应。参数: method(GET/POST等), path, url, headers, json, form, query, timeout",
    "browser-inspect": "使用浏览器检查网页内容。参数: path, url, headers, timeout",
    "session-materialize": "会话物化(登录)。参数: login_url, method, form_fields, username, password, headers",
    "artifact-scan": "扫描文件内容。参数: path, url, location, preview_bytes",
    "binary-inspect": "检查二进制文件。参数: path, url, location, min_length, max_strings",
    "code-sandbox": "在沙盒中执行代码。参数: program_fragment, inputs",
    "structured-parse": "解析结构化数据。参数: parse_source(observation_id), format(json/html/headers), extract_fields",
    "diff-compare": "对比两个内容差异。参数: baseline_observation_id, variant_observation_id",
    "extract-candidate": "提取候选flag。参数: patterns(regex列表), required_tags",
}

ATTACK_PHASES = ["侦察", "分析", "利用", "验证"]

SAFETY_RULES_TEMPLATE = [
    "只攻击授权范围内的目标",
    "不执行破坏性操作",
    "不尝试越权访问",
    "所有操作需可追溯",
]


_PRIMITIVE_PARAM_KEYS: dict[str, set[str]] = {
    "http-request": {"method", "path", "url", "headers", "json", "form", "query", "timeout"},
    "browser-inspect": {"path", "url", "headers", "timeout"},
    "session-materialize": {"login_url", "method", "form_fields", "username", "password", "headers"},
    "artifact-scan": {"path", "url", "location", "preview_bytes"},
    "binary-inspect": {"path", "url", "location", "min_length", "max_strings"},
    "code-sandbox": {"program_fragment", "inputs"},
    "structured-parse": {"parse_source", "format", "extract_fields", "id"},
    "diff-compare": {"baseline_observation_id", "variant_observation_id", "id"},
    "extract-candidate": {"patterns", "required_tags"},
}


class ConstraintContextBuilder:
    """约束上下文构建器"""

    def __init__(self, security_constraints: SecurityConstraints) -> None:
        self.security_constraints = security_constraints

    def build(self, context: PlanningContext) -> ConstraintContext:
        """从规划上下文和安全约束构建约束上下文"""
        record = context.record
        challenge = record.snapshot.challenge

        available = list(PRIMITIVE_DESCRIPTIONS.keys())
        target = challenge.target
        if record.snapshot.instance is not None:
            target = record.snapshot.instance.target

        return ConstraintContext(
            available_primitives=available,
            primitive_descriptions=dict(PRIMITIVE_DESCRIPTIONS),
            target_scope=target,
            safety_rules=list(SAFETY_RULES_TEMPLATE),
            max_steps=self.security_constraints.max_program_steps,
            required_phases=["侦察", "利用"],
            max_estimated_cost=self.security_constraints.max_estimated_cost,
            time_budget_seconds=300,
            attack_phases=ATTACK_PHASES,
            observation_before_action=self.security_constraints.require_observation_before_action,
            success_criteria=f"找到匹配模式 {challenge.flag_pattern} 的flag",
        )


class ConstraintAwareReasoner:
    """约束感知推理器：在约束条件下生成自由计划"""

    def __init__(self,
                 model: ReasoningModel,
                 context_builder: ConstraintContextBuilder,
                 validator: LightweightSecurityShell,
                 summarizer: ObservationSummarizer | None = None) -> None:
        self.model = model
        self.context_builder = context_builder
        self.validator = validator
        self._summarizer = summarizer or ObservationSummarizer()

    def generate_constrained_plan(self, context: PlanningContext) -> ActionProgram | None:
        """生成约束感知的自由计划"""
        constraints = self._build_constraint_context(context)
        prompt = self._generate_model_prompt(context, constraints)
        current_state = self._extract_current_state(context)

        try:
            response = self.model.complete_json(
                "generate_constrained_plan",
                {"prompt": prompt, "constraints": {
                    "max_steps": constraints.max_steps,
                    "target_scope": constraints.target_scope,
                }},
            )
        except Exception:
            return None

        return self._parse_plan_response(response, context)

    def _build_constraint_context(self, context: PlanningContext) -> ConstraintContext:
        """构建约束上下文"""
        return self.context_builder.build(context)

    def _generate_model_prompt(self, context: PlanningContext, constraints: ConstraintContext) -> str:
        """生成模型提示"""
        current_state = self._extract_current_state(context)
        return constraints.to_model_prompt(current_state)

    def _extract_current_state(self, context: PlanningContext) -> str:
        """提取当前状态描述 — 含实际观测内容而非计数"""
        record = context.record
        parts = [
            f"挑战: {record.snapshot.challenge.name}",
            f"类别: {record.snapshot.challenge.category}",
            f"目标: {record.snapshot.challenge.target}",
        ]
        if record.observations:
            summary = self._summarizer.summarize_observations(record.observations)
            if summary:
                parts.append(f"已有观察详情:\n{summary}")
            else:
                parts.append(f"已有观察: {len(record.observations)} 个")
        # Surface world_state highlights
        ws = record.world_state
        if ws.endpoints:
            ep_strs = [f"{e.method} {e.path}" for e in ws.endpoints.values()]
            parts.append(f"已知端点: {'; '.join(ep_strs)}")
        if ws.credentials:
            cred_strs = [f"{c.username}@{c.service}" for c in ws.credentials.values()]
            parts.append(f"已知凭据: {'; '.join(cred_strs)}")
        if ws.findings:
            find_strs = [f.text for f in ws.findings.values()]
            parts.append(f"已知发现: {'; '.join(find_strs)}")
        if record.artifacts:
            parts.append(f"已有证据: {len(record.artifacts)} 个")
        if record.candidate_flags:
            parts.append(f"已有候选flag: {len(record.candidate_flags)} 个")
        return "\n".join(parts)

    def _parse_plan_response(self, response: dict[str, Any], context: PlanningContext) -> ActionProgram | None:
        """解析模型返回的计划 — strip unknown parameter keys"""
        if not isinstance(response, dict):
            return None

        rationale = response.get("rationale", "")
        steps_data = response.get("steps", [])
        if not isinstance(steps_data, list) or len(steps_data) == 0:
            return None

        steps: list[PrimitiveActionStep] = []
        for step_data in steps_data:
            if not isinstance(step_data, dict):
                continue
            primitive = step_data.get("primitive", "")
            instruction = step_data.get("instruction", "")
            parameters = step_data.get("parameters", {})
            if not primitive or not instruction:
                continue
            if not isinstance(parameters, dict):
                parameters = {}
            # Strip unknown parameter keys per primitive whitelist
            allowed_keys = _PRIMITIVE_PARAM_KEYS.get(primitive)
            if allowed_keys is not None:
                parameters = {k: v for k, v in parameters.items() if k in allowed_keys}
            steps.append(PrimitiveActionStep(
                primitive=primitive,
                instruction=instruction,
                parameters=parameters,
            ))

        if not steps:
            return None

        challenge = context.record.snapshot.challenge
        return ActionProgram(
            id=f"plan-free-{new_id('plan')}",
            goal=f"自由探索: {challenge.name}",
            pattern_nodes=["free_exploration"],
            steps=steps,
            allowed_primitives=list(PRIMITIVE_DESCRIPTIONS.keys()),
            verification_rules=[f"flag匹配: {challenge.flag_pattern}"],
            required_profile=WorkerProfile.HYBRID,
            rationale=rationale,
            planner_source="free_exploration",
        )