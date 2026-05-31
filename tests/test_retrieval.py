"""
retrieval模块的单元测试
测试_normalize_scores等纯函数，不依赖外部API
"""
import pytest
import copy


class TestNormalizeScores:
    """测试HybridBM25VectorRetriever._normalize_scores方法"""

    def _make_retriever(self):
        """创建一个最小化的retriever实例用于测试"""
        from src.retrieval import HybridBM25VectorRetriever
        from pathlib import Path
        retriever = object.__new__(HybridBM25VectorRetriever)
        return retriever

    def test_basic_normalization_higher_is_better(self):
        """基础归一化：higher_is_better=True时，最大值归1，最小值归0"""
        retriever = self._make_retriever()
        results = [
            {"distance": 10, "text": "a"},
            {"distance": 20, "text": "b"},
            {"distance": 30, "text": "c"},
        ]
        normalized = retriever._normalize_scores(copy.deepcopy(results), higher_is_better=True)
        assert normalized[0]["normalized_score"] == 0.0
        assert normalized[1]["normalized_score"] == 0.5
        assert normalized[2]["normalized_score"] == 1.0

    def test_basic_normalization_lower_is_better(self):
        """higher_is_better=False时，最小值归1，最大值归0（距离越小越相似）"""
        retriever = self._make_retriever()
        results = [
            {"distance": 0.1, "text": "a"},
            {"distance": 0.5, "text": "b"},
            {"distance": 0.9, "text": "c"},
        ]
        normalized = retriever._normalize_scores(copy.deepcopy(results), higher_is_better=False)
        assert normalized[0]["normalized_score"] == 1.0
        assert normalized[2]["normalized_score"] == 0.0

    def test_same_values_no_division_by_zero(self):
        """所有值相同时不应除零，全部归一化为0"""
        retriever = self._make_retriever()
        results = [
            {"distance": 5.0, "text": "a"},
            {"distance": 5.0, "text": "b"},
            {"distance": 5.0, "text": "c"},
        ]
        normalized = retriever._normalize_scores(copy.deepcopy(results), higher_is_better=True)
        for r in normalized:
            assert r["normalized_score"] == 0.0

    def test_empty_results(self):
        """空列表直接返回"""
        retriever = self._make_retriever()
        results = []
        normalized = retriever._normalize_scores(results, higher_is_better=True)
        assert normalized == []

    def test_single_result(self):
        """单个结果归一化为0"""
        retriever = self._make_retriever()
        results = [{"distance": 42.0, "text": "a"}]
        normalized = retriever._normalize_scores(copy.deepcopy(results), higher_is_better=True)
        assert normalized[0]["normalized_score"] == 0.0

    def test_negative_distances(self):
        """负数距离也能正确归一化"""
        retriever = self._make_retriever()
        results = [
            {"distance": -10, "text": "a"},
            {"distance": 0, "text": "b"},
            {"distance": 10, "text": "c"},
        ]
        normalized = retriever._normalize_scores(copy.deepcopy(results), higher_is_better=True)
        assert normalized[0]["normalized_score"] == 0.0
        assert normalized[1]["normalized_score"] == 0.5
        assert normalized[2]["normalized_score"] == 1.0

    def test_precision_rounding(self):
        """归一化结果保留6位小数"""
        retriever = self._make_retriever()
        results = [
            {"distance": 0, "text": "a"},
            {"distance": 3, "text": "b"},
        ]
        normalized = retriever._normalize_scores(copy.deepcopy(results), higher_is_better=True)
        assert normalized[1]["normalized_score"] == 1.0
        assert isinstance(normalized[0]["normalized_score"], float)
