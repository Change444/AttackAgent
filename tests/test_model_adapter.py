import unittest
from unittest.mock import MagicMock, patch
import json
import os

from attack_agent.model_adapter import (
    _extract_json_from_text,
    _resolve_api_key,
    is_available,
    build_model_from_config,
    TASK_PROMPTS,
)
from attack_agent.config import ModelConfig
from attack_agent.reasoning import StaticReasoningModel


class TestExtractJsonFromText(unittest.TestCase):

    def test_direct_json(self):
        """直接JSON字符串解析"""
        text = '{"profile": "network", "reason": "test"}'
        result = _extract_json_from_text(text)
        self.assertEqual(result["profile"], "network")

    def test_markdown_code_block(self):
        """从markdown code block提取JSON"""
        text = 'Here is my response:\n```json\n{"rationale": "test", "steps": []}\n```'
        result = _extract_json_from_text(text)
        self.assertEqual(result["rationale"], "test")

    def test_embedded_json_object(self):
        """从文本中提取嵌入的JSON对象"""
        text = 'The answer is {"candidate_index": 0, "rationale": "best option"} for this challenge.'
        result = _extract_json_from_text(text)
        self.assertEqual(result["candidate_index"], 0)

    def test_nested_json(self):
        """解析嵌套JSON"""
        text = '{"rationale": "test", "steps": [{"primitive": "http-request", "instruction": "test", "parameters": {"url": "/login"}}]}'
        result = _extract_json_from_text(text)
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["primitive"], "http-request")

    def test_failure_raises_runtime_error(self):
        """无法提取JSON时抛出RuntimeError"""
        text = "This is just plain text with no JSON at all."
        with self.assertRaises(RuntimeError) as ctx:
            _extract_json_from_text(text)
        self.assertIn("json_parse_failure", str(ctx.exception))

    def test_markdown_code_block_no_json_label(self):
        """markdown code block无json标签也能提取"""
        text = '```\n{"profile": "browser"}\n```'
        result = _extract_json_from_text(text)
        self.assertEqual(result["profile"], "browser")


class TestResolveApiKey(unittest.TestCase):

    def test_from_env_var(self):
        """从环境变量读取API key"""
        config = ModelConfig(provider="openai", api_key_env="TEST_API_KEY")
        with patch.dict(os.environ, {"TEST_API_KEY": "sk-test123"}):
            key = _resolve_api_key(config)
            self.assertEqual(key, "sk-test123")

    def test_from_literal(self):
        """直接使用api_key字段"""
        config = ModelConfig(provider="openai", api_key="sk-literal")
        key = _resolve_api_key(config)
        self.assertEqual(key, "sk-literal")

    def test_env_var_missing_raises(self):
        """环境变量未设置时抛出ValueError"""
        config = ModelConfig(provider="openai", api_key_env="MISSING_KEY")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                _resolve_api_key(config)

    def test_both_missing_raises(self):
        """api_key和api_key_env都为空时抛出ValueError"""
        config = ModelConfig(provider="openai")
        with self.assertRaises(ValueError):
            _resolve_api_key(config)

    def test_env_var_preferred_over_literal(self):
        """api_key_env优先于api_key"""
        config = ModelConfig(provider="openai", api_key_env="PREFERRED_KEY", api_key="sk-literal")
        with patch.dict(os.environ, {"PREFERRED_KEY": "sk-from-env"}):
            key = _resolve_api_key(config)
            self.assertEqual(key, "sk-from-env")


class TestIsAvailable(unittest.TestCase):

    def test_heuristic_always_available(self):
        self.assertTrue(is_available("heuristic"))

    def test_unknown_provider_not_available(self):
        self.assertFalse(is_available("unknown"))

    def test_openai_check(self):
        # Result depends on whether openai SDK is installed
        result = is_available("openai")
        self.assertIsInstance(result, bool)

    def test_anthropic_check(self):
        result = is_available("anthropic")
        self.assertIsInstance(result, bool)


class TestBuildModelFromConfig(unittest.TestCase):

    def test_heuristic_returns_none(self):
        """heuristic模式返回None"""
        config = ModelConfig(provider="heuristic")
        result = build_model_from_config(config)
        self.assertIsNone(result)

    def test_unknown_provider_raises(self):
        """未知provider抛出ValueError"""
        config = ModelConfig(provider="unknown_provider")
        with self.assertRaises(ValueError):
            build_model_from_config(config)

    def test_openai_without_sdk_raises_import_error(self):
        """openai SDK未安装时抛出ImportError"""
        config = ModelConfig(provider="openai", api_key="sk-test")
        with patch("attack_agent.model_adapter._openai_module", None):
            with self.assertRaises(ImportError):
                build_model_from_config(config)

    def test_anthropic_without_sdk_raises_import_error(self):
        """anthropic SDK未安装时抛出ImportError"""
        config = ModelConfig(provider="anthropic", api_key="sk-test")
        with patch("attack_agent.model_adapter._anthropic_module", None):
            with self.assertRaises(ImportError):
                build_model_from_config(config)


class TestOpenAIReasoningModel(unittest.TestCase):

    def _make_mock_client(self, response_text):
        """创建mock OpenAI client"""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = response_text
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    def test_complete_json_select_worker_profile(self):
        """测试select_worker_profile任务"""
        config = ModelConfig(provider="openai", api_key="sk-test", model_name="gpt-4o")
        response_text = '{"profile": "network", "reason": "web challenge detected"}'

        with patch("attack_agent.model_adapter._openai_module") as mock_module:
            mock_client = self._make_mock_client(response_text)
            mock_module.OpenAI.return_value = mock_client
            mock_module.RateLimitError = Exception
            mock_module.AuthenticationError = Exception
            mock_module.APIConnectionError = Exception

            adapter = __import__("attack_agent.model_adapter", fromlist=["OpenAIReasoningModel"]).OpenAIReasoningModel(config)
            result = adapter.complete_json("select_worker_profile", {"challenge_id": "c1", "category": "web"})

            self.assertEqual(result["profile"], "network")
            mock_client.chat.completions.create.assert_called_once()

    def test_complete_json_generate_constrained_plan_uses_prompt(self):
        """测试generate_constrained_plan使用prompt而非JSON序列化"""
        config = ModelConfig(provider="openai", api_key="sk-test")
        prompt_text = "你是一个渗透测试专家..."
        response_text = '{"rationale": "SQL注入", "steps": [{"primitive": "http-request", "instruction": "发送请求", "parameters": {}}]}'

        with patch("attack_agent.model_adapter._openai_module") as mock_module:
            mock_client = self._make_mock_client(response_text)
            mock_module.OpenAI.return_value = mock_client
            mock_module.RateLimitError = Exception
            mock_module.AuthenticationError = Exception
            mock_module.APIConnectionError = Exception

            adapter = __import__("attack_agent.model_adapter", fromlist=["OpenAIReasoningModel"]).OpenAIReasoningModel(config)
            result = adapter.complete_json("generate_constrained_plan", {"prompt": prompt_text})

            self.assertEqual(result["rationale"], "SQL注入")
            # Verify the prompt text was used as user_content, not json.dumps(payload)
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args[1]["messages"]
            user_msg = messages[1]["content"]
            self.assertEqual(user_msg, prompt_text)


class TestAnthropicReasoningModel(unittest.TestCase):

    def _make_mock_client(self, response_text):
        """创建mock Anthropic client"""
        mock_client = MagicMock()
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = response_text
        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_client.messages.create.return_value = mock_response
        return mock_client

    def test_complete_json_choose_program(self):
        """测试choose_program任务"""
        config = ModelConfig(provider="anthropic", api_key="sk-ant-test", model_name="claude-sonnet-4-20250514")
        response_text = '{"candidate_index": 0, "rationale": "best candidate"}'

        with patch("attack_agent.model_adapter._anthropic_module") as mock_module:
            mock_client = self._make_mock_client(response_text)
            mock_module.Anthropic.return_value = mock_client
            mock_module.RateLimitError = Exception
            mock_module.AuthenticationError = Exception
            mock_module.APIConnectionError = Exception

            adapter = __import__("attack_agent.model_adapter", fromlist=["AnthropicReasoningModel"]).AnthropicReasoningModel(config)
            result = adapter.complete_json("choose_program", {"challenge_id": "c1"})

            self.assertEqual(result["candidate_index"], 0)

    def test_multiple_text_blocks_concatenated(self):
        """测试多个text block拼接"""
        config = ModelConfig(provider="anthropic", api_key="sk-ant-test")
        mock_client = MagicMock()
        block1 = MagicMock()
        block1.type = "text"
        block1.text = '{"rationale'
        block2 = MagicMock()
        block2.type = "text"
        block2.text = '": "test"}'
        mock_response = MagicMock()
        mock_response.content = [block1, block2]
        mock_client.messages.create.return_value = mock_response

        with patch("attack_agent.model_adapter._anthropic_module") as mock_module:
            mock_module.Anthropic.return_value = mock_client
            mock_module.RateLimitError = Exception
            mock_module.AuthenticationError = Exception
            mock_module.APIConnectionError = Exception

            adapter = __import__("attack_agent.model_adapter", fromlist=["AnthropicReasoningModel"]).AnthropicReasoningModel(config)
            result = adapter.complete_json("select_worker_profile", {"challenge_id": "c1"})

            self.assertEqual(result["rationale"], "test")


class TestPlatformWiring(unittest.TestCase):

    def test_no_model_uses_heuristic(self):
        """无model时使用HeuristicReasoner"""
        from attack_agent.platform import CompetitionPlatform
        from attack_agent.platform_models import ChallengeDefinition
        from attack_agent.provider import InMemoryCompetitionProvider
        from attack_agent.reasoning import HeuristicReasoner

        provider = InMemoryCompetitionProvider([
            ChallengeDefinition(id="c1", name="Test", category="web",
                                difficulty="easy", target="http://127.0.0.1:8000",
                                description="test"),
        ])
        platform = CompetitionPlatform(provider)
        planner = platform.strategy.planner
        self.assertIsInstance(planner.reasoner, HeuristicReasoner)

    def test_with_model_uses_enhanced_planner(self):
        """有model时使用EnhancedAPGPlanner"""
        from attack_agent.platform import CompetitionPlatform
        from attack_agent.platform_models import ChallengeDefinition
        from attack_agent.provider import InMemoryCompetitionProvider
        from attack_agent.enhanced_apg import EnhancedAPGPlanner
        from attack_agent.reasoning import LLMReasoner, StaticReasoningModel

        provider = InMemoryCompetitionProvider([
            ChallengeDefinition(id="c1", name="Test", category="web",
                                difficulty="easy", target="http://127.0.0.1:8000",
                                description="test"),
        ])
        model = StaticReasoningModel({"select_worker_profile": {"profile": "network", "reason": "test"}})
        platform = CompetitionPlatform(provider, model=model)
        planner = platform.strategy.planner
        self.assertIsInstance(planner, EnhancedAPGPlanner)
        self.assertIsInstance(planner.reasoner, LLMReasoner)

    def test_backward_compat_with_reasoner_param(self):
        """reasoner参数向后兼容"""
        from attack_agent.platform import CompetitionPlatform
        from attack_agent.platform_models import ChallengeDefinition
        from attack_agent.provider import InMemoryCompetitionProvider
        from attack_agent.reasoning import LLMReasoner, StaticReasoningModel
        from attack_agent.apg import APGPlanner

        provider = InMemoryCompetitionProvider([
            ChallengeDefinition(id="c1", name="Test", category="web",
                                difficulty="easy", target="http://127.0.0.1:8000",
                                description="test"),
        ])
        reasoner = LLMReasoner(StaticReasoningModel({"select_worker_profile": {"profile": "network"}}))
        platform = CompetitionPlatform(provider, reasoner=reasoner)
        # Should use APGPlanner (not Enhanced), with the provided reasoner
        self.assertIsInstance(platform.strategy.planner, APGPlanner)
        self.assertIsInstance(platform.strategy.planner.reasoner, LLMReasoner)


class TestTaskPrompts(unittest.TestCase):

    def test_all_tasks_have_prompts(self):
        """所有task都有对应的系统提示"""
        for task in ["select_worker_profile", "choose_program", "generate_constrained_plan"]:
            self.assertIn(task, TASK_PROMPTS)
            self.assertTrue(len(TASK_PROMPTS[task]) > 0)


if __name__ == "__main__":
    unittest.main()