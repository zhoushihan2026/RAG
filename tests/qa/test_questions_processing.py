"""
特征测试: 问答处理 (questions_processing.py)

锁定行为: S-5.1 ~ S-5.6

源码实际导出:
- 模块级函数: build_metadata_filters, _parse_question_time, _check_time_coverage
- 类: QuestionsProcessor (含 _classify_question, _rewrite_question, get_answer_for_company 等方法)
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.questions_processing import (
    build_metadata_filters,
    _parse_question_time,
    QuestionsProcessor,
)


# ============================================================
# S-5.1 问题分类
# ============================================================

class TestClassifyQuestion:
    """锁定 S-5.1: QuestionsProcessor._classify_question 行为"""

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_returns_category_string(self):
        """T-QA-01: 返回分类字符串"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.openai_processor.send_message.return_value = '{"category": "fact_extraction"}'

        result = processor._classify_question("公司营收是多少？")
        assert result == "fact_extraction"

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_category_types(self):
        """分类类型包含: fact_extraction, analysis_explanation, prediction_judgment, string"""
        categories = ["fact_extraction", "analysis_explanation", "prediction_judgment", "string"]
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()

        for cat in categories:
            processor.openai_processor.send_message.return_value = json.dumps({"category": cat})
            result = processor._classify_question("测试问题")
            assert result in categories

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_llm_failure_returns_string(self):
        """LLM 调用失败时返回默认分类 string"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.openai_processor.send_message.side_effect = Exception("API error")

        result = processor._classify_question("测试问题")
        assert result == "string"

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_unknown_category_returns_string(self):
        """未知分类回退到 string"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.openai_processor.send_message.return_value = '{"category": "unknown_type"}'

        result = processor._classify_question("测试问题")
        assert result == "string"


# ============================================================
# S-5.2 问题改写
# ============================================================

class TestRewriteQuestion:
    """锁定 S-5.2: QuestionsProcessor._rewrite_question 行为"""

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_returns_rewritten_dict(self):
        """T-QA-02: 返回改写后的字典"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.openai_processor.send_message.return_value = json.dumps({
            "rewritten_query": "东方证券2024年营业收入是多少？",
            "doc_type": "年报"
        }, ensure_ascii=False)

        result = processor._rewrite_question("营收多少")
        assert isinstance(result, dict)
        assert "rewritten_query" in result

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_llm_failure_returns_empty_dict(self):
        """LLM 调用失败时返回空字典"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.openai_processor.send_message.side_effect = Exception("API error")

        result = processor._rewrite_question("营收多少")
        assert result == {}

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_string_response_with_markdown_fence(self):
        """LLM 返回带markdown围栏的JSON字符串可解析"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.openai_processor.send_message.return_value = '```json\n{"rewritten_query": "改写后问题", "doc_type": "年报"}\n```'

        result = processor._rewrite_question("测试问题")
        assert isinstance(result, dict)


# ============================================================
# S-5.3 元数据过滤提取
# ============================================================

class TestBuildMetadataFilters:
    """锁定 S-5.3: build_metadata_filters 行为"""

    def test_extracts_company(self):
        """T-QA-03: 从问题中提取公司名"""
        import pandas as pd
        companies_df = pd.DataFrame({
            'company_name': ['中芯国际', '东方证券'],
            'sha1': ['abc', 'def']
        })
        rewrite_result = {"rewritten_query": "中芯国际营收", "doc_type": "年报"}

        rewritten_query, filters = build_metadata_filters(
            "中芯国际的营收情况", companies_df, rewrite_result
        )
        assert filters.get("company") == "中芯国际"

    def test_extracts_doc_type_from_rewrite_as_soft(self):
        """LLM推断的doc_type放入soft_doc_type（仅软加权，不硬过滤）"""
        import pandas as pd
        companies_df = pd.DataFrame({
            'company_name': ['中芯国际'],
            'sha1': ['abc']
        })
        rewrite_result = {"rewritten_query": "中芯国际年报信息", "doc_type": "年报"}

        rewritten_query, filters = build_metadata_filters(
            "中芯国际年报信息", companies_df, rewrite_result
        )
        # LLM推断的doc_type放入soft_doc_type，不是硬过滤的doc_type
        assert filters.get("soft_doc_type") == "年报"

    def test_source_doc_type_hard_filter(self):
        """从question_source解析的doc_type放入doc_type（硬过滤）"""
        import pandas as pd
        companies_df = pd.DataFrame({
            'company_name': ['中芯国际'],
            'sha1': ['abc']
        })
        rewrite_result = {"rewritten_query": "中芯国际信息", "doc_type": "年报"}

        rewritten_query, filters = build_metadata_filters(
            "中芯国际信息", companies_df, rewrite_result,
            question_source="【财报】中芯国际2024年年度报告"
        )
        # source标注的doc_type放入doc_type（硬过滤）
        assert filters.get("doc_type") == "年报"

    def test_no_company_returns_empty_filters(self):
        """问题中无公司名时filters中无company"""
        import pandas as pd
        companies_df = pd.DataFrame({
            'company_name': ['中芯国际'],
            'sha1': ['abc']
        })
        rewrite_result = {"rewritten_query": "营收情况"}

        rewritten_query, filters = build_metadata_filters(
            "营收情况", companies_df, rewrite_result
        )
        assert "company" not in filters

    def test_broker_excluded_from_company(self):
        """券商名不被误匹配为公司名"""
        import pandas as pd
        companies_df = pd.DataFrame({
            'company_name': ['中芯国际'],
            'sha1': ['abc']
        })
        rewrite_result = {"rewritten_query": "华泰证券研报中的中芯国际", "doc_type": ""}

        rewritten_query, filters = build_metadata_filters(
            "华泰证券研报中的中芯国际", companies_df, rewrite_result
        )
        assert filters.get("company") == "中芯国际"


# ============================================================
# S-5.4 时间解析
# ============================================================

class TestParseQuestionTime:
    """锁定 S-5.4: _parse_question_time 行为"""

    def test_parse_year(self):
        """解析年份"""
        start, end = _parse_question_time("2024年营收情况")
        assert start is not None
        assert start.year == 2024
        assert end.year == 2024

    def test_parse_quarter(self):
        """解析季度"""
        start, end = _parse_question_time("2024年一季度营收")
        assert start is not None
        assert start.year == 2024
        assert start.month == 1
        assert end.month == 3

    def test_no_time_returns_none(self):
        """无时间信息返回 None"""
        start, end = _parse_question_time("公司营收情况")
        assert start is None
        assert end is None


# ============================================================
# S-5.5 现状: 问题分类结果未使用
# ============================================================

class TestClassificationNotUsed:
    """锁定现状 S-5.5: 问题分类结果仅用于选择schema，不影响检索逻辑"""

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_classification_returns_different_categories(self):
        """
        现状: _classify_question 返回的分类结果用于选择回答schema。
        锁定: 分类函数存在且可调用。
        """
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()

        processor.openai_processor.send_message.return_value = '{"category": "fact_extraction"}'
        result1 = processor._classify_question("营收多少")

        processor.openai_processor.send_message.return_value = '{"category": "analysis_explanation"}'
        result2 = processor._classify_question("营收多少")

        assert result1 != result2


# ============================================================
# S-5.6 现状: 改写后问题与原始问题可能重复调用
# ============================================================

class TestQuestionRewriteUsage:
    """锁定现状 S-5.6: 改写后问题的使用方式"""

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_rewritten_question_used_for_retrieval(self):
        """
        现状: 改写后的问题用于检索和元数据提取，
        原始问题用于最终答案生成。
        锁定: _rewrite_question 返回包含 rewritten_query 的字典。
        """
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.openai_processor.send_message.return_value = json.dumps({
            "rewritten_query": "东方证券2024年营收",
            "doc_type": "年报"
        }, ensure_ascii=False)

        result = processor._rewrite_question("营收多少")
        assert "rewritten_query" in result
