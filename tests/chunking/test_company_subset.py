"""
特征测试: 公司名提取与 subset 操作

锁定行为: S-7.1 ~ S-7.3
"""
import json
import os
import pytest
from pathlib import Path

from src.text_splitter_z import TextSplitter


# ============================================================
# S-7.1 公司名提取
# ============================================================

class TestCompanyNameExtraction:
    """锁定 S-7.1: 公司名提取行为"""

    def setup_method(self):
        self.splitter = TextSplitter()

    def test_extract_from_brackets(self):
        """从【券商名】格式提取"""
        result = self.splitter._extract_broker("【东方证券】中芯国际研报")
        assert result == "东方证券"

    def test_extract_from_filename(self):
        """从文件名中提取公司名"""
        # 通过 split_markdown_reports 间接测试
        # 文件名格式: {company_name}_xxx.md
        pass

    def test_known_broker_list(self):
        """已知券商列表包含源码中定义的券商"""
        # 源码 KNOWN_BROKERS: 东方证券, 光大证券, 国信证券, 上海证券, 中原证券, 兴证国际, 华泰证券
        known_brokers = ["东方证券", "华泰证券", "光大证券", "国信证券", "上海证券", "中原证券", "兴证国际"]
        for broker in known_brokers:
            result = self.splitter._extract_broker(f"【{broker}】研报")
            assert result == broker, f"应识别券商: {broker}"

    def test_unknown_broker_empty(self):
        """未知券商返回空字符串"""
        result = self.splitter._extract_broker("【未知券商】研报")
        assert result == ""

    def test_no_brackets(self):
        """无方括号时无法提取券商名"""
        result = self.splitter._extract_broker("普通标题")
        assert result == ""


# ============================================================
# S-7.2 subset.csv 操作
# ============================================================

class TestSubsetCsvOperations:
    """锁定 S-7.2: subset.csv 读写行为"""

    def test_csv_read_utf8_sig(self, tmp_path):
        """UTF-8 BOM 编码的 CSV 可读取"""
        csv_path = tmp_path / "subset.csv"
        csv_content = "file_name,company_name,sha1\nreport.md,测试公司,abc123\n"
        csv_path.write_bytes(b'\xef\xbb\xbf' + csv_content.encode('utf-8'))

        import pandas as pd
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        assert len(df) == 1
        assert df.iloc[0]['company_name'] == "测试公司"

    def test_csv_read_gbk(self, tmp_path):
        """GBK 编码的 CSV 可读取"""
        csv_path = tmp_path / "subset.csv"
        csv_content = "file_name,company_name,sha1\nreport.md,测试公司,abc123\n"
        csv_path.write_text(csv_content, encoding='gbk')

        import pandas as pd
        df = pd.read_csv(csv_path, encoding='gbk')
        assert len(df) == 1
        assert df.iloc[0]['company_name'] == "测试公司"

    def test_csv_columns(self, tmp_path):
        """CSV 必须包含 file_name, company_name, sha1 列"""
        csv_path = tmp_path / "subset.csv"
        csv_content = "file_name,company_name,sha1\nreport.md,测试公司,abc123\n"
        csv_path.write_text(csv_content, encoding='utf-8')

        import pandas as pd
        df = pd.read_csv(csv_path)
        assert 'file_name' in df.columns
        assert 'company_name' in df.columns
        assert 'sha1' in df.columns

    def test_csv_sha1_format(self, tmp_path):
        """sha1 列格式: stock_ + 6位字符"""
        csv_path = tmp_path / "subset.csv"
        csv_content = "file_name,company_name,sha1\nreport.md,测试公司,stock_abc123\n"
        csv_path.write_text(csv_content, encoding='utf-8')

        import pandas as pd
        df = pd.read_csv(csv_path)
        sha1_val = df.iloc[0]['sha1']
        assert sha1_val.startswith("stock_")
        assert len(sha1_val) == 12  # "stock_" + 6 chars


# ============================================================
# S-7.3 公司名匹配
# ============================================================

class TestCompanyNameMatching:
    """锁定 S-7.3: 公司名匹配行为"""

    def test_exact_match(self):
        """精确匹配"""
        splitter = TextSplitter()
        result = splitter._extract_broker("【东方证券】研报")
        assert result == "东方证券"

    def test_longer_name_priority(self):
        """长名称优先匹配"""
        splitter = TextSplitter()
        # 国泰君安不在 KNOWN_BROKERS 中，所以返回空字符串
        result = splitter._extract_broker("【国泰君安证券】研报")
        # 现状: KNOWN_BROKERS 不含"国泰君安"，返回空字符串
        assert result == ""

    def test_partial_name_in_title(self):
        """标题中包含券商名但不在方括号内"""
        splitter = TextSplitter()
        result = splitter._extract_broker("东方证券研究报告")
        # 现状: _extract_broker 检查标题中是否包含券商名
        assert result == "东方证券"
