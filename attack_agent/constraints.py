"""
轻量级安全壳约束验证系统
位置：Agent Loop外部，在runtime执行前验证
特点：快速、轻量、不阻断模型决策
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from urllib.parse import urlparse

from .config import SecurityConfig
from .platform_models import ActionProgram, TaskBundle, WorkerProfile


@dataclass(slots=True)
class ConstraintViolation:
    """约束违规记录"""
    constraint_type: str
    severity: str  # "critical" | "warning"
    message: str


@dataclass(slots=True)
class ValidationResult:
    """验证结果"""
    allowed: bool  # 是否允许执行
    violations: list[ConstraintViolation]


class LightweightSecurityShell:
    """轻量级安全壳验证器 — 直接使用 SecurityConfig 作为约束源"""

    def __init__(self, security_config: SecurityConfig | None = None):
        self.security_config = security_config or SecurityConfig()

    def validate(self, bundle: TaskBundle) -> ValidationResult:
        """快速验证TaskBundle是否满足安全约束"""
        violations = []

        # 1. 目标范围验证（轻量级）
        violations.extend(self._check_target_scope(bundle))

        # 2. 原始动作计数验证（快速计数）
        violations.extend(self._check_primitive_counts(bundle))

        # 3. 结构验证（简单检查）
        violations.extend(self._check_program_structure(bundle))

        # 4. 顺序验证（快速模式匹配）
        violations.extend(self._check_action_order(bundle))

        # 5. 成本估算（快速计算）
        violations.extend(self._check_resource_limits(bundle))

        # 6. 禁止组合验证（快速查找）
        violations.extend(self._check_forbidden_combinations(bundle))

        # 7. 参数范围验证 — step.parameters 中 URL 目标 scope
        violations.extend(self._check_parameter_scope(bundle))

        # 判定：critical级别违规才阻止执行
        critical_violations = [v for v in violations if v.severity == "critical"]
        return ValidationResult(
            allowed=len(critical_violations) == 0,
            violations=violations
        )

    def _check_target_scope(self, bundle: TaskBundle) -> list[ConstraintViolation]:
        """检查目标是否在允许的范围内"""
        violations = []

        parsed = urlparse(bundle.target)

        # file:// 协议通常是本地文件系统，允许通过
        if parsed.scheme == "file":
            return violations

        # 对于其他协议，检查hostname是否在允许范围内
        if parsed.hostname:
            if parsed.hostname not in self.security_config.allowed_hostpatterns:
                violations.append(ConstraintViolation(
                    constraint_type="target_scope",
                    severity="critical",
                    message=f"目标host不在允许范围内: {parsed.hostname}"
                ))

        return violations

    def _check_primitive_counts(self, bundle: TaskBundle) -> list[ConstraintViolation]:
        """检查原始动作调用次数"""
        violations = []
        primitives = [step.primitive for step in bundle.action_program.steps]
        counts = Counter(primitives)

        if counts.get("http-request", 0) > self.security_config.max_http_requests:
            violations.append(ConstraintViolation(
                constraint_type="primitive_count",
                severity="warning",
                message=f"http-request调用次数过多: {counts['http-request']}"
            ))

        if counts.get("code-sandbox", 0) > self.security_config.max_sandbox_executions:
            violations.append(ConstraintViolation(
                constraint_type="primitive_count",
                severity="warning",
                message=f"code-sandbox调用次数过多: {counts['code-sandbox']}"
            ))

        return violations

    def _check_program_structure(self, bundle: TaskBundle) -> list[ConstraintViolation]:
        """检查程序结构"""
        violations = []

        if len(bundle.action_program.steps) > self.security_config.max_program_steps:
            violations.append(ConstraintViolation(
                constraint_type="program_structure",
                severity="warning",
                message=f"程序步骤过多: {len(bundle.action_program.steps)}"
            ))

        return violations

    def _check_action_order(self, bundle: TaskBundle) -> list[ConstraintViolation]:
        """检查操作顺序（先观察后行动）"""
        violations = []

        if not self.security_config.require_observation_before_action:
            return violations

        observation_primitives = {"http-request", "browser-inspect", "artifact-scan", "binary-inspect"}
        action_primitives = {"code-sandbox"}

        first_action_idx = None
        first_observe_idx = None

        for i, step in enumerate(bundle.action_program.steps):
            if step.primitive in observation_primitives and first_observe_idx is None:
                first_observe_idx = i
            if step.primitive in action_primitives and first_action_idx is None:
                first_action_idx = i

        if first_action_idx is not None and first_observe_idx is not None:
            if first_action_idx <= first_observe_idx:
                violations.append(ConstraintViolation(
                    constraint_type="action_order",
                    severity="warning",
                    message="在观察之前尝试执行代码操作"
                ))

        return violations

    def _check_resource_limits(self, bundle: TaskBundle) -> list[ConstraintViolation]:
        """检查资源限制"""
        violations = []

        cost_map = {
            "http-request": 1.0,
            "browser-inspect": 1.4,
            "artifact-scan": 1.2,
            "binary-inspect": 1.2,
            "code-sandbox": 1.5,
            "extract-candidate": 0.4,
            "structured-parse": 0.8,
            "diff-compare": 0.7,
        }

        estimated_cost = sum(
            cost_map.get(step.primitive, 1.0)
            for step in bundle.action_program.steps
        )

        if estimated_cost > self.security_config.max_estimated_cost:
            violations.append(ConstraintViolation(
                constraint_type="resource_limit",
                severity="warning",
                message=f"预估成本超过限制: {estimated_cost:.1f}"
            ))

        return violations

    def _check_forbidden_combinations(self, bundle: TaskBundle) -> list[ConstraintViolation]:
        """检查禁止的原始动作组合"""
        violations = []
        primitives = [step.primitive for step in bundle.action_program.steps]

        for combo in self.security_config.forbidden_primitive_combinations:
            if all(p in primitives for p in combo):
                violations.append(ConstraintViolation(
                    constraint_type="forbidden_combination",
                    severity="critical",
                    message=f"禁止的原始动作组合: {' -> '.join(combo)}"
                ))

        return violations

    # URL-containing parameter keys per primitive
    _URL_PARAM_KEYS: dict[str, list[str]] = {
        "http-request": ["url"],
        "browser-inspect": ["url"],
        "session-materialize": ["login_url"],
        "artifact-scan": ["url", "location"],
        "binary-inspect": ["url", "location"],
    }

    def _check_parameter_scope(self, bundle: TaskBundle) -> list[ConstraintViolation]:
        """验证 step.parameters 中的 URL 是否在 allowed_hostpatterns 范围内"""
        violations = []
        for step in bundle.action_program.steps:
            url_keys = self._URL_PARAM_KEYS.get(step.primitive, [])
            for key in url_keys:
                value = step.parameters.get(key)
                if not value or not isinstance(value, str):
                    continue
                if not value.startswith(("http://", "https://")):
                    continue
                parsed = urlparse(value)
                hostname = parsed.hostname
                if hostname and hostname not in self.security_config.allowed_hostpatterns:
                    violations.append(ConstraintViolation(
                        constraint_type="parameter_scope",
                        severity="critical",
                        message=f"step.parameters.{key} 指向外部host: {hostname}"
                    ))
        return violations