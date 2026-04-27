import unittest
from attack_agent.constraints import (
    LightweightSecurityShell,
    SecurityConstraints,
    ConstraintViolation,
    ValidationResult
)
from attack_agent.config import SecurityConfig, AttackAgentConfig, PlatformConfig, MemoryConfig, LoggingConfig, PatternDiscoveryConfig, SemanticRetrievalConfig, ModelConfig
from attack_agent.platform_models import DualPathConfig
from attack_agent.platform_models import (
    ActionProgram,
    PrimitiveActionStep,
    TaskBundle,
    ChallengeDefinition,
    ChallengeInstance,
    WorkerProfile
)


class TestSecurityConstraintsDefaults(unittest.TestCase):
    """测试 SecurityConstraints 默认值与 SecurityConfig 对齐"""

    def test_defaults_match_security_config(self):
        """SecurityConstraints 默认值应与 SecurityConfig 默认值一致"""
        constraints = SecurityConstraints()
        config = SecurityConfig()
        self.assertEqual(constraints.max_http_requests, config.max_http_requests)
        self.assertEqual(constraints.max_sandbox_executions, config.max_sandbox_executions)
        self.assertEqual(constraints.max_program_steps, config.max_program_steps)
        self.assertEqual(constraints.require_observation_before_action, config.require_observation_before_action)
        self.assertEqual(constraints.max_estimated_cost, config.max_estimated_cost)
        self.assertEqual(constraints.allowed_hostpatterns, config.allowed_hostpatterns)

    def test_from_config_preserves_values(self):
        """from_config 应将 SecurityConfig 值完整映射到 SecurityConstraints"""
        config = SecurityConfig(
            allowed_hostpatterns=["10.0.0.1", "target.example.com"],
            max_http_requests=100,
            max_sandbox_executions=3,
            max_program_steps=10,
            require_observation_before_action=False,
            max_estimated_cost=200.0,
        )
        constraints = SecurityConstraints.from_config(config)
        self.assertEqual(constraints.allowed_hostpatterns, ["10.0.0.1", "target.example.com"])
        self.assertEqual(constraints.max_http_requests, 100)
        self.assertEqual(constraints.max_sandbox_executions, 3)
        self.assertEqual(constraints.max_program_steps, 10)
        self.assertEqual(constraints.require_observation_before_action, False)
        self.assertEqual(constraints.max_estimated_cost, 200.0)

    def test_from_config_default_security_config(self):
        """from_config 使用默认 SecurityConfig 应产生与默认 SecurityConstraints 相同的结果"""
        config = SecurityConfig()
        constraints_from_config = SecurityConstraints.from_config(config)
        constraints_default = SecurityConstraints()
        self.assertEqual(constraints_from_config.max_http_requests, constraints_default.max_http_requests)
        self.assertEqual(constraints_from_config.max_program_steps, constraints_default.max_program_steps)
        self.assertEqual(constraints_from_config.max_estimated_cost, constraints_default.max_estimated_cost)
        self.assertEqual(constraints_from_config.allowed_hostpatterns, constraints_default.allowed_hostpatterns)


class TestLightweightSecurityShell(unittest.TestCase):

    def setUp(self):
        self.constraints = SecurityConstraints(
            allowed_hostpatterns=["127.0.0.1"],
            max_http_requests=5,
            max_sandbox_executions=2
        )
        self.shell = LightweightSecurityShell(self.constraints)

    def test_allowed_target(self):
        """测试允许的目标通过验证"""
        bundle = self._create_mock_bundle("http://127.0.0.1:8000", ["http-request"])
        result = self.shell.validate(bundle)
        self.assertTrue(result.allowed)

    def test_forbidden_target(self):
        """测试禁止的目标被阻止"""
        bundle = self._create_mock_bundle("http://192.168.1.100:8000", ["http-request"])
        result = self.shell.validate(bundle)
        self.assertFalse(result.allowed)
        self.assertEqual(len(result.violations), 1)
        self.assertEqual(result.violations[0].constraint_type, "target_scope")
        self.assertEqual(result.violations[0].severity, "critical")

    def test_primitive_count_limit(self):
        """测试原始动作计数限制"""
        # 创建超过限制的http请求数量
        steps = ["http-request"] * 6  # 超过max_http_requests=5
        bundle = self._create_mock_bundle("http://127.0.0.1:8000", steps)
        result = self.shell.validate(bundle)
        # 应该是warning级别，不阻止执行
        self.assertTrue(result.allowed)
        self.assertTrue(any(v.constraint_type == "primitive_count" for v in result.violations))

    def test_forbidden_combination(self):
        """测试禁止的组合被阻止"""
        self.constraints.forbidden_primitive_combinations = [("http-request", "code-sandbox")]
        bundle = self._create_mock_bundle("http://127.0.0.1:8000", ["http-request", "code-sandbox"])
        result = self.shell.validate(bundle)
        self.assertFalse(result.allowed)
        critical_violations = [v for v in result.violations if v.severity == "critical"]
        self.assertEqual(len(critical_violations), 1)

    def test_action_order(self):
        """测试操作顺序检查"""
        # code-sandbox在http-request之前
        bundle = self._create_mock_bundle("http://127.0.0.1:8000", ["code-sandbox", "http-request"])
        result = self.shell.validate(bundle)
        # warning级别，不阻止执行
        self.assertTrue(result.allowed)
        self.assertTrue(any(v.constraint_type == "action_order" for v in result.violations))

    def test_resource_limit(self):
        """测试资源限制"""
        # 设置较低的成本限制
        self.constraints.max_estimated_cost = 50.0
        # 创建超过成本限制的程序
        steps = ["code-sandbox"] * 40  # 每个成本1.5，总共60，超过max_estimated_cost=50.0
        bundle = self._create_mock_bundle("http://127.0.0.1:8000", steps)
        result = self.shell.validate(bundle)
        # warning级别，不阻止执行
        self.assertTrue(result.allowed)
        self.assertTrue(any(v.constraint_type == "resource_limit" for v in result.violations))

    def test_program_structure(self):
        """测试程序结构检查"""
        # 创建超过步骤限制的程序
        steps = ["http-request"] * 20  # 超过默认max_program_steps=15
        self.constraints.max_program_steps = 15
        bundle = self._create_mock_bundle("http://127.0.0.1:8000", steps)
        result = self.shell.validate(bundle)
        # warning级别，不阻止执行
        self.assertTrue(result.allowed)
        self.assertTrue(any(v.constraint_type == "program_structure" for v in result.violations))

    def test_clean_program(self):
        """测试干净的程序通过所有检查"""
        steps = ["http-request", "browser-inspect", "structured-parse"]
        bundle = self._create_mock_bundle("http://127.0.0.1:8000", steps)
        result = self.shell.validate(bundle)
        self.assertTrue(result.allowed)
        self.assertEqual(len(result.violations), 0)

    def _create_mock_bundle(self, target: str, primitives: list[str]) -> TaskBundle:
        """创建模拟的TaskBundle用于测试"""
        steps = [
            PrimitiveActionStep(
                primitive=p,
                instruction=f"Execute {p}",
                parameters={}
            )
            for p in primitives
        ]

        program = ActionProgram(
            id="test-program",
            goal="test goal",
            pattern_nodes=["node1"],
            steps=steps,
            allowed_primitives=primitives,
            verification_rules=[],
            required_profile=WorkerProfile.NETWORK,
            memory_refs=[],
            rationale="test",
            planner_source="test"
        )

        challenge = ChallengeDefinition(
            id="test-challenge",
            name="test",
            category="web",
            difficulty="easy",
            target=target,
            description="test challenge"
        )

        instance = ChallengeInstance(
            instance_id="test-instance",
            challenge_id="test-challenge",
            target=target,
            status="running"
        )

        return TaskBundle(
            project_id="test-project",
            run_id="test-run",
            action_program=program,
            stage="explore",
            worker_profile=WorkerProfile.NETWORK,
            target=target,
            challenge=challenge,
            instance=instance,
            handoff_summary="test handoff",
            visible_primitives=primitives,
            known_observation_ids=[],
            known_artifact_ids=[],
            known_hypothesis_ids=[],
            known_candidate_keys=[]
        )


if __name__ == "__main__":
    unittest.main()