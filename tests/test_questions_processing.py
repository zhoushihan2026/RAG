"""
questions_processing模块的单元测试
测试build_metadata_filters等纯函数
"""
import pytest
import pandas as pd


class TestBuildMetadataFilters:
    """测试build_metadata_filters函数"""

    @pytest.fixture
    def companies_df(self):
        """构建测试用的公司数据DataFrame"""
        return pd.DataFrame({
            "company_name": ["中芯国际", "中芯国际", "中芯国际", "中芯国际", "中芯国际", "中芯国际", "中芯国际"],
            "doc_type": ["年报", "券商研报", "券商研报", "券商研报", "券商研报", "券商研报", "调研纪要"],
            "broker": [None, "东方证券", "光大证券", "国信证券", "上海证券", "中原证券", None],
        })

    def test_extract_company_from_question(self, companies_df):
        """从问题文本中正确提取公司名"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际研发投入"}
        rewritten_query, filters = build_metadata_filters(
            "中芯国际2024年研发投入占营业收入的比例是多少？",
            companies_df,
            rewrite_result
        )
        assert filters.get("company") == "中芯国际"

    def test_broker_from_question_text(self, companies_df):
        """从问题文本中识别券商名"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际产能利用率"}
        _, filters = build_metadata_filters(
            "东方证券对中芯国际的产能利用率有何评价？",
            companies_df,
            rewrite_result
        )
        assert filters.get("broker") == "东方证券"

    def test_broker_from_source(self, companies_df):
        """从question_source中解析券商名（优先级高于问题文本推断）"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际产能利用率"}
        _, filters = build_metadata_filters(
            "中芯国际产能利用率如何？",
            companies_df,
            rewrite_result,
            question_source="【光大证券】中芯国际研报"
        )
        assert filters.get("broker") == "光大证券"
        assert filters.get("doc_type") == "券商研报"

    def test_doc_type_from_source_annual_report(self, companies_df):
        """从source中解析年报类型（【财报】→年报）"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际研发投入"}
        _, filters = build_metadata_filters(
            "中芯国际2024年研发投入占营业收入的比例是多少？",
            companies_df,
            rewrite_result,
            question_source="【财报】中芯国际2024年年度报告"
        )
        assert filters.get("doc_type") == "年报"

    def test_doc_type_from_source_research_note(self, companies_df):
        """从source中解析调研纪要类型"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际产能规划"}
        _, filters = build_metadata_filters(
            "中芯国际的产能规划如何？",
            companies_df,
            rewrite_result,
            question_source="中芯国际机构调研纪要"
        )
        assert filters.get("doc_type") == "调研纪要"

    def test_doc_type_llm_inference_soft_filter(self, companies_df):
        """LLM推断的doc_type使用软加权（soft_doc_type），不硬过滤"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际研发投入", "doc_type": "年报"}
        _, filters = build_metadata_filters(
            "中芯国际2024年研发投入占营业收入的比例是多少？",
            companies_df,
            rewrite_result
        )
        assert "soft_doc_type" in filters
        assert filters["soft_doc_type"] == "年报"
        assert "doc_type" not in filters or filters.get("doc_type") != "年报"

    def test_year_extraction(self, companies_df):
        """从问题中提取年份"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际研发投入"}
        _, filters = build_metadata_filters(
            "中芯国际2024年研发投入占营业收入的比例是多少？",
            companies_df,
            rewrite_result
        )
        assert filters.get("publish_date") == "2024"

    def test_quarter_extraction(self, companies_df):
        """从问题中提取季度"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际业绩"}
        _, filters = build_metadata_filters(
            "中芯国际2025年一季度业绩如何？",
            companies_df,
            rewrite_result
        )
        assert filters.get("quarter") == "2025Q1"

    def test_no_company_in_question(self, companies_df):
        """问题中不包含已知公司名时，不设置company过滤"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "某公司业绩"}
        _, filters = build_metadata_filters(
            "某公司2024年业绩如何？",
            companies_df,
            rewrite_result
        )
        assert "company" not in filters

    def test_rewritten_query_from_rewrite_result(self, companies_df):
        """使用重写后的query而非原始问题"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {"rewritten_query": "中芯国际研发投入占营收比例"}
        rewritten_query, _ = build_metadata_filters(
            "中芯国际2024年研发投入占营业收入的比例是多少？",
            companies_df,
            rewrite_result
        )
        assert rewritten_query == "中芯国际研发投入占营收比例"

    def test_rewritten_query_fallback_to_original(self, companies_df):
        """重写结果中没有rewritten_query时，回退到原始问题"""
        from src.questions_processing import build_metadata_filters
        rewrite_result = {}
        rewritten_query, _ = build_metadata_filters(
            "中芯国际2024年研发投入占营业收入的比例是多少？",
            companies_df,
            rewrite_result
        )
        assert rewritten_query == "中芯国际2024年研发投入占营业收入的比例是多少？"


class TestParseQuestionTime:
    """测试_parse_question_time函数"""

    def test_parse_year(self):
        """解析年份"""
        from src.questions_processing import _parse_question_time
        start, end = _parse_question_time("中芯国际2024年研发投入")
        assert start.year == 2024
        assert start.month == 1
        assert end.year == 2024
        assert end.month == 12

    def test_parse_quarter(self):
        """解析季度"""
        from src.questions_processing import _parse_question_time
        start, end = _parse_question_time("中芯国际2025年一季度业绩")
        assert start.year == 2025
        assert start.month == 1
        assert end.month == 3

    def test_parse_no_time(self):
        """没有时间信息时返回None"""
        from src.questions_processing import _parse_question_time
        start, end = _parse_question_time("中芯国际产能利用率")
        assert start is None
        assert end is None

    def test_parse_q2(self):
        """解析二季度"""
        from src.questions_processing import _parse_question_time
        start, end = _parse_question_time("2024年二季度营收")
        assert start.month == 4
        assert end.month == 6

    def test_parse_q3(self):
        """解析三季度"""
        from src.questions_processing import _parse_question_time
        start, end = _parse_question_time("2024年三季度营收")
        assert start.month == 7
        assert end.month == 9

    def test_parse_q4(self):
        """解析四季度"""
        from src.questions_processing import _parse_question_time
        start, end = _parse_question_time("2024年四季度营收")
        assert start.month == 10
        assert end.month == 12
