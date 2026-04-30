import unittest
from attack_agent.constraints import (
    LightweightSecurityShell,
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


class TestSecurityConfigDefaults(unittest.TestCase):
    """测试 SecurityConfig 默认值一致性"""

    def test_default_security_config_values(self):
        """SecurityConfig 默认值应可用于直接构建 LightweightSecurityShell"""
        config = SecurityConfig()
        shell = LightweightSecurityShell(config)
        self.assertEqual(shell.security_config.max_http_requests, 30)
        self.assertEqual(shell.security_config.max_sandbox_executions, 5)
        self.assertEqual(shell.security_config.max_program_steps, 15)
        self.assertEqual(shell.security_config.require_observation_before_action, True)
        self.assertEqual(shell.security_config.max_estimated_cost, 50.0)
        self.assertEqual(shell.security_config.allowed_hostpatterns, ["127.0.0.1", "localhost"])

    def test_custom_security_config_preserves_values(self):
        """自定义 SecurityConfig 值应被 LightweightSecurityShell 正确使用"""
        config = SecurityConfig(
            allowed_hostpatterns=["10.0.0.1", "target.example.com"],
            max_http_requests=100,
            max_sandbox_executions=3,
            max_program_steps=10,
            require_observation_before_action=False,
            max_estimated_cost=200.0,
        )
        shell = LightweightSecurityShell(config)
        self.assertEqual(shell.security_config.allowed_hostpatterns, ["10.0.0.1", "target.example.com"])
        self.assertEqual(shell.security_config.max_http_requests, 100)
        self.assertEqual(shell.security_config.max_sandbox_executions, 3)
        self.assertEqual(shell.security_config.max_program_steps, 10)
        self.assertEqual(shell.security_config.require_observation_before_action, False)
        self.assertEqual(shell.security_config.max_estimated_cost, 200.0)

    def test_default_security_config_matches_default_shell(self):
        """默认 SecurityConfig 与 LightweightSecurityShell 默认值应一致"""
        config = SecurityConfig()
        shell_with_config = LightweightSecurityShell(config)
        shell_default = LightweightSecurityShell()
        self.assertEqual(shell_with_config.security_config.max_http_requests, shell_default.security_config.max_http_requests)
        self.assertEqual(shell_with_config.security_config.max_program_steps, shell_default.security_config.max_program_steps)
        self.assertEqual(shell_with_config.security_config.max_estimated_cost, shell_default.security_config.max_estimated_cost)
        self.assertEqual(shell_with_config.security_config.allowed_hostpatterns, shell_default.security_config.allowed_hostpatterns)


class TestLightweightSecurityShell(unittest.TestCase):

    def setUp(self):
        self.security_config = SecurityConfig(
            allowed_hostpatterns=["127.0.0.1"],
            max_http_requests=5,
            max_sandbox_executions=2
        )
        self.shell = LightweightSecurityShell(self.security_config)

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
        self.security_config.forbidden_primitive_combinations = [("http-request", "code-sandbox")]
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
        self.security_config.max_estimated_cost = 50.0
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
        self.security_config.max_program_steps = 15
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