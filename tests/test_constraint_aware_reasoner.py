import unittest
from unittest.mock import MagicMock

from attack_agent.constraint_aware_reasoner import (
    ConstraintAwareReasoner,
    ConstraintContext,
    ConstraintContextBuilder,
    CONSTRAINT_AWARE_PROMPT,
    PRIMITIVE_DESCRIPTIONS,
)
from attack_agent.constraints import LightweightSecurityShell, SecurityConstraints
from attack_agent.platform_models import (
    ActionProgram,
    ChallengeDefinition,
    ChallengeInstance,
    DualPathConfig,
    PathType,
    PlanningContext,
    PrimitiveActionStep,
    ProjectSnapshot,
    ProjectStage,
    WorkerProfile,
)
from attack_agent.state_graph import StateGraphService, ProjectRecord


class TestConstraintContext(unittest.TestCase):

    def test_to_model_prompt_includes_all_fields(self):
        """测试约束上下文生成完整的模型提示"""
        ctx = ConstraintContext(
            available_primitives=["http-request", "browser-inspect"],
            primitive_descriptions={"http-request": "HTTP请求", "browser-inspect": "浏览器检查"},
            target_scope="http://127.0.0.1:8000",
            safety_rules=["只攻击授权目标"],
            max_steps=10,
            required_phases=["侦察", "利用"],
            max_estimated_cost=50.0,
            time_budget_seconds=300,
            attack_phases=["侦察", "分析", "利用", "验证"],
            observation_before_action=True,
            success_criteria="找到flag",
        )
        prompt = ctx.to_model_prompt("当前: 无观察")
        self.assertIn("HTTP请求", prompt)
        self.assertIn("http-request", prompt)
        self.assertIn("127.0.0.1", prompt)
        self.assertIn("10", prompt)
        self.assertIn("侦察", prompt)
        self.assertIn("先观察再行动", prompt)
        self.assertIn("当前: 无观察", prompt)


class TestConstraintContextBuilder(unittest.TestCase):

    def setUp(self):
        self.constraints = SecurityConstraints(
            allowed_hostpatterns=["127.0.0.1"],
            max_http_requests=30,
            max_sandbox_executions=5,
            max_program_steps=15,
            require_observation_before_action=True,
            max_estimated_cost=50.0,
        )
        self.builder = ConstraintContextBuilder(self.constraints)
        self.challenge = ChallengeDefinition(
            id="test-1", name="Test Challenge", category="web",
            difficulty="easy", target="http://127.0.0.1:8000",
            description="A test challenge",
        )
        self.snapshot = ProjectSnapshot(
            project_id="p1", challenge=self.challenge,
            stage=ProjectStage.EXPLORE, worker_profile=WorkerProfile.NETWORK,
        )

    def test_build_creates_constraint_context(self):
        """测试构建器生成正确的约束上下文"""
        sg = StateGraphService()
        self.snapshot.instance = ChallengeInstance(
            instance_id="i1", challenge_id="test-1",
            target="http://127.0.0.1:8000", status="running",
        )
        sg.upsert_project(self.snapshot)
        record = sg.projects["p1"]
        planning_ctx = PlanningContext(
            record=record, attempt_count=0, historical_success_rate=0.5,
            complexity_score=0.3, pattern_confidence=0.4, exploration_budget=3,
        )
        result = self.builder.build(planning_ctx)
        self.assertIsInstance(result, ConstraintContext)
        self.assertIn("http-request", result.available_primitives)
        self.assertEqual(result.max_steps, 15)
        self.assertTrue(result.observation_before_action)
        self.assertEqual(result.max_estimated_cost, 50.0)


class TestConstraintAwareReasoner(unittest.TestCase):

    def setUp(self):
        self.constraints = SecurityConstraints(
            allowed_hostpatterns=["127.0.0.1"],
            max_program_steps=15,
            require_observation_before_action=True,
            max_estimated_cost=50.0,
        )
        self.shell = LightweightSecurityShell(self.constraints)
        self.builder = ConstraintContextBuilder(self.constraints)
        self.challenge = ChallengeDefinition(
            id="test-1", name="SQL注入", category="web",
            difficulty="easy", target="http://127.0.0.1:8000",
            description="SQL injection challenge",
        )

    def _make_planning_context(self):
        snapshot = ProjectSnapshot(
            project_id="p1", challenge=self.challenge,
            stage=ProjectStage.EXPLORE,
        )
        sg = StateGraphService()
        sg.upsert_project(snapshot)
        record = sg.projects["p1"]
        return PlanningContext(
            record=record, attempt_count=0, historical_success_rate=0.5,
            complexity_score=0.3, pattern_confidence=0.4, exploration_budget=3,
        )

    def test_generate_constrained_plan_with_valid_model_response(self):
        """测试有效模型响应生成正确的计划"""
        model_response = {
            "rationale": "尝试SQL注入",
            "steps": [
                {"primitive": "http-request", "instruction": "发送注入请求", "parameters": {"url": "/login"}},
                {"primitive": "extract-candidate", "instruction": "提取flag", "parameters": {}},
            ]
        }
        from attack_agent.reasoning import StaticReasoningModel
        model = StaticReasoningModel({"generate_constrained_plan": model_response})

        reasoner = ConstraintAwareReasoner(model, self.builder, self.shell)
        ctx = self._make_planning_context()
        program = reasoner.generate_constrained_plan(ctx)

        self.assertIsNotNone(program)
        self.assertEqual(program.planner_source, "free_exploration")
        self.assertEqual(len(program.steps), 2)
        self.assertEqual(program.steps[0].primitive, "http-request")
        self.assertIn("SQL注入", program.rationale)

    def test_generate_constrained_plan_returns_none_on_invalid_response(self):
        """测试无效模型响应返回None"""
        from attack_agent.reasoning import StaticReasoningModel
        model = StaticReasoningModel({"generate_constrained_plan": {"invalid": True}})
        reasoner = ConstraintAwareReasoner(model, self.builder, self.shell)
        ctx = self._make_planning_context()
        result = reasoner.generate_constrained_plan(ctx)
        self.assertIsNone(result)

    def test_generate_constrained_plan_returns_none_on_exception(self):
        """测试模型异常返回None"""
        model = MagicMock()
        model.complete_json.side_effect = RuntimeError("model error")
        reasoner = ConstraintAwareReasoner(model, self.builder, self.shell)
        ctx = self._make_planning_context()
        result = reasoner.generate_constrained_plan(ctx)
        self.assertIsNone(result)

    def test_generate_constrained_plan_skips_steps_without_primitive(self):
        """测试跳过缺少primitive的步骤"""
        model_response = {
            "rationale": "测试",
            "steps": [
                {"primitive": "http-request", "instruction": "请求", "parameters": {}},
                {"primitive": "", "instruction": "空primitive", "parameters": {}},
            ]
        }
        from attack_agent.reasoning import StaticReasoningModel
        model = StaticReasoningModel({"generate_constrained_plan": model_response})
        reasoner = ConstraintAwareReasoner(model, self.builder, self.shell)
        ctx = self._make_planning_context()
        program = reasoner.generate_constrained_plan(ctx)
        self.assertIsNotNone(program)
        self.assertEqual(len(program.steps), 1)

    def test_build_constraint_context(self):
        """测试构建约束上下文"""
        reasoner = ConstraintAwareReasoner(
            MagicMock(), self.builder, self.shell
        )
        ctx = self._make_planning_context()
        constraint_ctx = reasoner._build_constraint_context(ctx)
        self.assertIsInstance(constraint_ctx, ConstraintContext)
        self.assertTrue(len(constraint_ctx.available_primitives) > 0)

    def test_generate_model_prompt_contains_constraints(self):
        """测试生成的模型提示包含约束信息"""
        reasoner = ConstraintAwareReasoner(
            MagicMock(), self.builder, self.shell
        )
        ctx = self._make_planning_context()
        constraint_ctx = reasoner._build_constraint_context(ctx)
        prompt = reasoner._generate_model_prompt(ctx, constraint_ctx)
        self.assertIn("约束条件", prompt)
        self.assertIn("http-request", prompt)


if __name__ == "__main__":
    unittest.main()