"""
pipeline模块的单元测试
使用mock模拟LLM调用，测试_classify_question和_rewrite_question的解析逻辑

v2更新:
- api_provider 默认改为 fe8，LLM处理器使用 Fe8Processor
- rewrite_model 默认改为 gpt-3.5-turbo
- _rewrite_question 返回结果新增 completed_question 字段
"""
import pytest
from unittest.mock import patch, MagicMock
import json


class TestClassifyQuestion:
    """测试Pipeline._classify_question方法的JSON解析逻辑"""

    def _make_pipeline(self):
        """创建一个最小化的Pipeline实例用于测试"""
        from src.pipeline import Pipeline, RunConfig
        pipeline = object.__new__(Pipeline)
        pipeline.run_config = RunConfig(rewrite_model="gpt-3.5-turbo", api_provider="fe8")
        pipeline.paths = MagicMock()
        return pipeline

    @patch("src.api_requests.Fe8Processor")
    def test_classify_fact_extraction(self, MockProcessor):
        """正确解析事实提取类问题"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {"category": "fact_extraction"}
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._classify_question("中芯国际2024年研发投入占营业收入的比例是多少？")
        assert result == "fact_extraction"

    @patch("src.api_requests.Fe8Processor")
    def test_classify_analysis_explanation(self, MockProcessor):
        """正确解析分析解释类问题"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {"category": "analysis_explanation"}
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._classify_question("中芯国际产能利用率变化的原因是什么？")
        assert result == "analysis_explanation"

    @patch("src.api_requests.Fe8Processor")
    def test_classify_prediction_judgment(self, MockProcessor):
        """正确解析预测判断类问题"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {"category": "prediction_judgment"}
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._classify_question("中芯国际未来产能扩张计划如何？")
        assert result == "prediction_judgment"

    @patch("src.api_requests.Fe8Processor")
    def test_classify_with_string_response(self, MockProcessor):
        """Fe8Processor返回字符串JSON时，应正确解析"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = '{"category": "fact_extraction"}'
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._classify_question("中芯国际2024年营收是多少？")
        assert result == "fact_extraction"

    @patch("src.api_requests.Fe8Processor")
    def test_classify_invalid_json_fallback(self, MockProcessor):
        """LLM返回无效JSON时，回退到string"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = "这不是JSON"
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._classify_question("随便一个问题")
        assert result == "string"

    @patch("src.api_requests.Fe8Processor")
    def test_classify_unknown_category_fallback(self, MockProcessor):
        """LLM返回未知类别时，回退到string"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {"category": "unknown_type"}
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._classify_question("未知类别问题")
        assert result == "string"

    @patch("src.api_requests.Fe8Processor")
    def test_classify_dict_response(self, MockProcessor):
        """Fe8Processor返回dict时，应正确解析"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {"category": "analysis_explanation"}
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._classify_question("分析类问题")
        assert result == "analysis_explanation"

    @patch("src.api_requests.Fe8Processor")
    def test_classify_missing_category_key_fallback(self, MockProcessor):
        """LLM返回的JSON中没有category字段时，回退到string"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {"type": "fact"}
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._classify_question("缺少category字段")
        assert result == "string"


class TestRewriteQuestion:
    """测试Pipeline._rewrite_question方法的JSON解析逻辑"""

    def _make_pipeline(self):
        from src.pipeline import Pipeline, RunConfig
        from unittest.mock import MagicMock
        pipeline = object.__new__(Pipeline)
        pipeline.run_config = RunConfig(rewrite_model="gpt-3.5-turbo", api_provider="fe8")
        pipeline.paths = MagicMock()
        return pipeline

    @patch("src.api_requests.Fe8Processor")
    def test_rewrite_valid_json(self, MockProcessor):
        """正确解析重写结果（含 completed_question 字段）"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {
            "completed_question": "中芯国际2024年研发投入占营收比例是多少？",
            "rewritten_query": "中芯国际2024年研发投入占营收比例",
            "doc_type": "年报",
        }
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._rewrite_question("中芯国际2024年研发投入占营业收入的比例是多少？")
        assert result["rewritten_query"] == "中芯国际2024年研发投入占营收比例"
        assert result["doc_type"] == "年报"
        assert result["completed_question"] == "中芯国际2024年研发投入占营收比例是多少？"

    @patch("src.api_requests.Fe8Processor")
    def test_rewrite_without_completed_question(self, MockProcessor):
        """重写结果中没有 completed_question 时，仍可正常使用"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {
            "rewritten_query": "中芯国际2024年研发投入占营收比例",
            "doc_type": "年报",
        }
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._rewrite_question("中芯国际2024年研发投入占营业收入的比例是多少？")
        assert result["rewritten_query"] == "中芯国际2024年研发投入占营收比例"
        assert "completed_question" not in result

    @patch("src.api_requests.Fe8Processor")
    def test_rewrite_invalid_json_returns_empty(self, MockProcessor):
        """LLM返回无效JSON时，返回空字典"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = "无法解析的文本"
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._rewrite_question("随便一个问题")
        assert result == {}

    @patch("src.api_requests.Fe8Processor")
    def test_rewrite_string_response_with_markdown(self, MockProcessor):
        """Fe8Processor返回带markdown围栏的字符串JSON，应正确解析"""
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = '```json\n{"rewritten_query": "测试", "doc_type": "券商研报"}\n```'
        MockProcessor.return_value = mock_instance

        pipeline = self._make_pipeline()
        result = pipeline._rewrite_question("测试问题")
        assert result["rewritten_query"] == "测试"
        assert result["doc_type"] == "券商研报"
