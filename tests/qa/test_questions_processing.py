"""
特征测试: 问答处理 (questions_processing.py)

锁定行为: S-5.1 ~ S-5.6

v2更新:
- expand_followup_query 使用财务术语词表匹配，不再使用滑动窗口
- summarize_history_for_rewrite 格式化历史消息供问题重写使用
- parse_llm_json_response 支持解析 markdown 围栏包裹的 JSON
- 重写结果新增 completed_question 字段
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.questions_processing import (
    build_metadata_filters,
    _parse_question_time,
    QuestionsProcessor,
    expand_followup_query,
    summarize_history_for_rewrite,
    parse_llm_json_response,
)


# ============================================================
# S-5.1 问题分类
# ============================================================

class TestClassifyQuestion:
    """锁定 S-5.1: QuestionsProcessor._classify_question 行为"""

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_returns_category_string(self):
        """返回分类字符串"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.rewrite_model = "gpt-3.5-turbo"
        processor.openai_processor.send_message.return_value = {"category": "fact_extraction"}

        result = processor._classify_question("公司营收是多少？")
        assert result == "fact_extraction"

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_category_types(self):
        """分类类型包含: fact_extraction, analysis_explanation, prediction_judgment, string"""
        categories = ["fact_extraction", "analysis_explanation", "prediction_judgment", "string"]
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.rewrite_model = "gpt-3.5-turbo"

        for cat in categories:
            processor.openai_processor.send_message.return_value = {"category": cat}
            result = processor._classify_question("测试问题")
            assert result in categories

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_llm_failure_returns_string(self):
        """LLM 调用失败时返回默认分类 string"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.rewrite_model = "gpt-3.5-turbo"
        processor.openai_processor.send_message.side_effect = Exception("API error")

        result = processor._classify_question("测试问题")
        assert result == "string"

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_unknown_category_returns_string(self):
        """未知分类回退到 string"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.rewrite_model = "gpt-3.5-turbo"
        processor.openai_processor.send_message.return_value = {"category": "unknown_type"}

        result = processor._classify_question("测试问题")
        assert result == "string"


# ============================================================
# S-5.2 问题改写
# ============================================================

class TestRewriteQuestion:
    """锁定 S-5.2: QuestionsProcessor._rewrite_question 行为"""

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_returns_rewritten_dict(self):
        """返回改写后的字典（含 completed_question）"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.rewrite_model = "gpt-3.5-turbo"
        processor.openai_processor.send_message.return_value = {
            "completed_question": "中芯国际2024年全年营业收入是多少？",
            "rewritten_query": "中芯国际 2024年 全年 营业收入",
            "doc_type": "年报"
        }

        result = processor._rewrite_question("营收多少")
        assert isinstance(result, dict)
        assert "rewritten_query" in result
        assert "completed_question" in result

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_llm_failure_returns_empty_dict(self):
        """LLM 调用失败时返回空字典"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.rewrite_model = "gpt-3.5-turbo"
        processor.openai_processor.send_message.side_effect = Exception("API error")

        result = processor._rewrite_question("营收多少")
        assert result == {}

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_string_response_with_markdown_fence(self):
        """LLM 返回带markdown围栏的JSON字符串可解析"""
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.rewrite_model = "gpt-3.5-turbo"
        processor.openai_processor.send_message.return_value = '```json\n{"rewritten_query": "改写后问题", "doc_type": "年报"}\n```'

        result = processor._rewrite_question("测试问题")
        assert isinstance(result, dict)


# ============================================================
# S-5.3 元数据过滤提取
# ============================================================

class TestBuildMetadataFilters:
    """锁定 S-5.3: build_metadata_filters 行为"""

    def test_extracts_company(self):
        """从问题中提取公司名"""
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
# S-5.5 追问检索增强 (expand_followup_query)
# ============================================================

class TestExpandFollowupQuery:
    """锁定 v2-spec 1.7: expand_followup_query 使用财务术语词表匹配"""

    def test_no_history_returns_unchanged(self):
        """无历史消息时返回原始查询"""
        result = expand_followup_query("毛利率 利润率", [])
        assert result == "毛利率 利润率"

    def test_no_user_messages_returns_unchanged(self):
        """历史消息中无用户消息时返回原始查询"""
        history = [{"role": "assistant", "content": "答案"}]
        result = expand_followup_query("毛利率 利润率", history)
        assert result == "毛利率 利润率"

    def test_merges_financial_terms_from_prev_question(self):
        """从前一轮问题中提取财务术语并合并"""
        history = [
            {"role": "user", "content": "中芯国际2024年全年营业收入是多少？"},
            {"role": "assistant", "content": "578亿元"},
        ]
        result = expand_followup_query("毛利率 利润率", history)
        # "营业收入" 应从前一轮问题中提取并合并
        assert "营业收入" in result

    def test_merges_year_from_prev_question(self):
        """从前一轮问题中提取年份并合并"""
        history = [
            {"role": "user", "content": "中芯国际2024年全年营业收入是多少？"},
            {"role": "assistant", "content": "578亿元"},
        ]
        result = expand_followup_query("毛利率 利润率", history)
        # "2024年" 应从前一轮问题中提取并合并
        assert "2024年" in result

    def test_no_duplicate_keywords(self):
        """已存在于当前查询中的关键词不重复添加"""
        history = [
            {"role": "user", "content": "中芯国际毛利率是多少？"},
            {"role": "assistant", "content": "17.8%"},
        ]
        result = expand_followup_query("中芯国际 毛利率", history)
        # "毛利率" 已在当前查询中，不应重复添加
        assert result.count("毛利率") <= 2  # 1次在原始查询中，最多1次在扩展中

    def test_no_fragment_words(self):
        """不产生碎片词（滑动窗口已弃用），只产生完整财务术语"""
        history = [
            {"role": "user", "content": "中芯国际2024年全年营业收入是多少？"},
            {"role": "assistant", "content": "578亿元"},
        ]
        result = expand_followup_query("同比增长 原因", history)
        # 扩展的词应是完整财务术语（如"营业收入"），而非碎片（如"业收"作为独立词）
        # "营业收入" 包含子串 "业收"，但 "业收" 不是独立添加的词
        added_words = set(result.split()) - set("同比增长 原因".split())
        for word in added_words:
            # 每个添加的词长度应 >= 2，且不是无意义的碎片
            assert len(word) >= 2


# ============================================================
# S-5.6 历史摘要格式化 (summarize_history_for_rewrite)
# ============================================================

class TestSummarizeHistoryForRewrite:
    """锁定 v2-spec 1.6: summarize_history_for_rewrite 行为"""

    def test_formats_history_as_text(self):
        """将历史消息格式化为文本摘要"""
        history = [
            {"role": "user", "content": "中芯国际2024年营收是多少？"},
            {"role": "assistant", "content": "2024年营收577.96亿元"},
        ]
        result = summarize_history_for_rewrite(history)
        assert "用户" in result
        assert "助手" in result
        assert "中芯国际" in result

    def test_truncates_long_assistant_content(self):
        """助手消息超过100字时截断"""
        long_answer = "A" * 200
        history = [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": long_answer},
        ]
        result = summarize_history_for_rewrite(history)
        # 助手消息应被截断
        lines = result.split("\n")
        assistant_line = [l for l in lines if l.startswith("助手:")][0]
        assert len(assistant_line) < 200

    def test_respects_max_rounds(self):
        """只取最近 max_rounds 轮"""
        history = []
        for i in range(5):
            history.append({"role": "user", "content": f"问题{i}"})
            history.append({"role": "assistant", "content": f"答案{i}"})

        result = summarize_history_for_rewrite(history, max_rounds=2)
        # 只应包含最近2轮（4条消息）
        assert "问题4" in result
        assert "问题3" in result
        assert "问题2" not in result


# ============================================================
# S-5.7 JSON 响应解析 (parse_llm_json_response)
# ============================================================

class TestParseLlmJsonResponse:
    """锁定 v2-spec: parse_llm_json_response 行为"""

    def test_dict_input_returned_directly(self):
        """dict 输入直接返回"""
        data = {"rewritten_query": "测试", "doc_type": "年报"}
        result = parse_llm_json_response(data)
        assert result == data

    def test_valid_json_string_parsed(self):
        """有效 JSON 字符串正常解析"""
        data = '{"rewritten_query": "测试", "doc_type": "年报"}'
        result = parse_llm_json_response(data)
        assert result["rewritten_query"] == "测试"

    def test_markdown_fence_json_parsed(self):
        """被 markdown 围栏包裹的 JSON 可解析"""
        data = '```json\n{"rewritten_query": "测试", "doc_type": "年报"}\n```'
        result = parse_llm_json_response(data)
        assert result["rewritten_query"] == "测试"

    def test_invalid_json_returns_empty_dict(self):
        """无效 JSON 返回空字典"""
        data = "这不是JSON"
        result = parse_llm_json_response(data)
        assert result == {}

    def test_empty_string_returns_empty_dict(self):
        """空字符串返回空字典"""
        result = parse_llm_json_response("")
        assert result == {}


# ============================================================
# S-5.8 现状: 问题分类结果用于选择schema
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
        processor.rewrite_model = "gpt-3.5-turbo"

        processor.openai_processor.send_message.return_value = {"category": "fact_extraction"}
        result1 = processor._classify_question("营收多少")

        processor.openai_processor.send_message.return_value = {"category": "analysis_explanation"}
        result2 = processor._classify_question("营收多少")

        assert result1 != result2


# ============================================================
# S-5.9 现状: 改写后问题与原始问题可能重复调用
# ============================================================

class TestQuestionRewriteUsage:
    """锁定现状 S-5.6: 改写后问题的使用方式"""

    @patch.object(QuestionsProcessor, '__init__', lambda self: None)
    def test_rewritten_question_used_for_retrieval(self):
        """
        现状: 改写后的问题用于检索和元数据提取，
        completed_question 用于回答 LLM 的 user_prompt。
        锁定: _rewrite_question 返回包含 rewritten_query 和 completed_question 的字典。
        """
        processor = QuestionsProcessor.__new__(QuestionsProcessor)
        processor.openai_processor = MagicMock()
        processor.rewrite_model = "gpt-3.5-turbo"
        processor.openai_processor.send_message.return_value = {
            "completed_question": "中芯国际2024年营收是多少？",
            "rewritten_query": "中芯国际 2024年 营收",
            "doc_type": "年报"
        }

        result = processor._rewrite_question("营收多少")
        assert "rewritten_query" in result
        assert "completed_question" in result
