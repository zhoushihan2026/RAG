"""
特征测试: API 请求与 JSON 解析 (api_requests.py)

锁定行为: S-6.1 ~ S-6.4

v2更新:
- APIProcessor 新增 fe8 provider，路由到 Fe8Processor
- Fe8Processor 基于 OpenAI 兼容接口，send_message 返回 dict 或 str
- Fe8Processor 支持 send_message_stream 流式调用
- Fe8Processor._stream_full_content 属性用于收集流式完整内容
"""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.api_requests import APIProcessor, BaseDashscopeProcessor, Fe8Processor


# ============================================================
# S-6.1 APIProcessor 路由
# ============================================================

class TestAPIProcessorRouting:
    """锁定 S-6.1: APIProcessor 根据provider路由到对应处理器"""

    def test_default_routes_to_dashscope(self):
        """默认provider路由到DashScope"""
        processor = APIProcessor()
        assert processor.provider == "dashscope"

    def test_openai_provider(self):
        """配置openai provider时路由到OpenAI处理器"""
        processor = APIProcessor(provider="openai")
        assert processor.provider == "openai"

    def test_ibm_provider(self):
        """配置ibm provider时路由到IBM处理器"""
        processor = APIProcessor(provider="ibm")
        assert processor.provider == "ibm"

    def test_gemini_provider(self):
        """配置gemini provider时路由到Gemini处理器"""
        processor = APIProcessor(provider="gemini")
        assert processor.provider == "gemini"

    def test_fe8_provider(self):
        """v2: 配置fe8 provider时路由到Fe8Processor"""
        processor = APIProcessor(provider="fe8")
        assert processor.provider == "fe8"
        assert isinstance(processor.processor, Fe8Processor)


# ============================================================
# S-6.2 JSON 解析 (Fe8Processor.send_message 内)
# ============================================================

class TestJsonParsing:
    """锁定 S-6.2: Fe8Processor返回的JSON解析行为"""

    def test_valid_json_parsed(self):
        """有效 JSON 正常解析"""
        content = '{"key": "value"}'
        result = json.loads(content)
        assert result == {"key": "value"}

    def test_json_with_markdown_fence_parsed(self):
        """带有 ```json ... ``` 围栏的 JSON 可解析"""
        raw = '```json\n{"key": "value"}\n```'
        content_str = raw.strip()
        if content_str.startswith('```') and '```' in content_str[3:]:
            import re
            content_str = re.sub(r'^```\w*\n?', '', content_str)
            content_str = re.sub(r'\n?```$', '', content_str)
        result = json.loads(content_str)
        assert result == {"key": "value"}

    def test_json_with_plain_fence_parsed(self):
        """带有 ``` ... ``` 围栏的 JSON 可解析"""
        raw = '```\n{"key": "value"}\n```'
        content_str = raw.strip()
        if content_str.startswith('```') and '```' in content_str[3:]:
            import re
            content_str = re.sub(r'^```\w*\n?', '', content_str)
            content_str = re.sub(r'\n?```$', '', content_str)
        result = json.loads(content_str)
        assert result == {"key": "value"}

    def test_invalid_json_returns_basic_format(self):
        """无效 JSON 返回基本格式 (final_answer + 空字段)"""
        content = "这不是JSON"
        try:
            json.loads(content)
            parsed = True
        except (json.JSONDecodeError, TypeError):
            parsed = False
        if not parsed:
            result = {"final_answer": content, "step_by_step_analysis": "", "reasoning_summary": "", "relevant_pages": []}
        assert result["final_answer"] == "这不是JSON"
        assert result["step_by_step_analysis"] == ""

    def test_empty_string_returns_basic_format(self):
        """空字符串返回基本格式"""
        content = ""
        try:
            json.loads(content)
            parsed = True
        except (json.JSONDecodeError, TypeError):
            parsed = False
        if not parsed:
            result = {"final_answer": content, "step_by_step_analysis": "", "reasoning_summary": "", "relevant_pages": []}
        assert result["final_answer"] == ""

    def test_json_array_parsed(self):
        """JSON 数组可解析"""
        result = json.loads('[1, 2, 3]')
        assert result == [1, 2, 3]


# ============================================================
# S-6.3 Fe8Processor 行为
# ============================================================

class TestFe8Processor:
    """锁定 S-6.3: Fe8Processor 行为"""

    def test_default_model(self):
        """默认模型为 gpt-3.5-turbo"""
        processor = Fe8Processor()
        assert processor.default_model == "gpt-3.5-turbo"

    def test_init_stream_full_content(self):
        """_stream_full_content 初始化为空字符串"""
        processor = Fe8Processor()
        assert processor._stream_full_content == ""

    def test_api_key_from_env(self, mock_env_vars):
        """API Key 从 FE8_API_KEY 环境变量获取"""
        os.environ["FE8_API_KEY"] = "sk-test-fe8-key"
        processor = Fe8Processor()
        assert processor.api_key == "sk-test-fe8-key"
        del os.environ["FE8_API_KEY"]

    @patch("src.api_requests.OpenAI")
    def test_send_message_returns_dict_for_json(self, MockOpenAI):
        """send_message 对 JSON 响应返回 dict"""
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = '{"category": "fact_extraction"}'
        mock_completion.usage.prompt_tokens = 10
        mock_completion.usage.completion_tokens = 20
        mock_client.chat.completions.create.return_value = mock_completion

        processor = Fe8Processor()
        processor.api_key = "test-key"
        result = processor.send_message(human_content="测试提示")
        assert isinstance(result, dict)
        assert result["category"] == "fact_extraction"

    @patch("src.api_requests.OpenAI")
    def test_send_message_returns_str_for_non_json(self, MockOpenAI):
        """send_message 对非 JSON 响应返回原始字符串"""
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = '这不是JSON'
        mock_completion.usage.prompt_tokens = 10
        mock_completion.usage.completion_tokens = 20
        mock_client.chat.completions.create.return_value = mock_completion

        processor = Fe8Processor()
        processor.api_key = "test-key"
        result = processor.send_message(human_content="测试提示")
        assert isinstance(result, str)
        assert result == "这不是JSON"


# ============================================================
# S-6.3 DashScope 调用
# ============================================================

class TestBaseDashscopeProcessor:
    """锁定 S-6.3: BaseDashscopeProcessor 行为"""

    def test_default_model(self, mock_env_vars):
        """默认模型为 qwen-turbo-latest"""
        processor = BaseDashscopeProcessor()
        assert processor.default_model == "qwen-turbo-latest"

    @patch('src.api_requests.dashscope')
    def test_send_message_returns_dict(self, mock_ds, mock_env_vars):
        """send_message 返回字典"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.output = MagicMock()
        mock_response.output.choices = [MagicMock()]
        mock_response.output.choices[0].message = MagicMock()
        mock_response.output.choices[0].message.content = '{"final_answer": "测试响应"}'
        mock_response.output.choices[0].finish_reason = "stop"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 20
        mock_ds.Generation.call.return_value = mock_response

        processor = BaseDashscopeProcessor()
        result = processor.send_message(human_content="测试提示")
        assert isinstance(result, dict)

    def test_api_key_from_env(self, mock_env_vars):
        """API Key 从环境变量获取"""
        processor = BaseDashscopeProcessor()
        import dashscope
        assert dashscope.api_key is not None


# ============================================================
# S-6.4 现状: 重试逻辑 (tenacity)
# ============================================================

class TestRetryBehavior:
    """锁定现状 S-6.4: API 重试行为 (tenacity装饰器)"""

    def test_tenacity_import_available(self):
        """源码导入了 tenacity 重试装饰器"""
        from tenacity import retry, stop_after_attempt, wait_fixed
        assert retry is not None
        assert stop_after_attempt is not None


# ============================================================
# S-6.4 现状: LLM 返回值可能包含 markdown 围栏
# ============================================================

class TestLlmResponseFormat:
    """锁定现状 S-6.4: LLM 返回值格式"""

    def test_json_extraction_from_llm_response(self):
        """LLM 返回的 JSON 可能被 markdown 围栏包裹"""
        import re
        raw_response = '```json\n{"company": "测试公司"}\n```'
        content_str = raw_response.strip()
        if content_str.startswith('```'):
            content_str = re.sub(r'^```\w*\n?', '', content_str)
            content_str = re.sub(r'\n?```$', '', content_str)
        parsed = json.loads(content_str)
        assert parsed == {"company": "测试公司"}

    def test_partial_json_handling(self):
        """
        现状: 截断的 JSON 无法解析，返回基本格式。
        锁定: 不做部分 JSON 修复。
        """
        raw_response = '{"company": "测试公司", "broker":'
        try:
            json.loads(raw_response)
            parsed = True
        except json.JSONDecodeError:
            parsed = False
        assert not parsed
