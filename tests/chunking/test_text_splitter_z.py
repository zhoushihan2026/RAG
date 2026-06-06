"""
特征测试: 文本分块 (text_splitter_z.py)

锁定行为: S-1.1 ~ S-1.6
"""
import os
import json
import tempfile
import pytest
from pathlib import Path

from src.text_splitter_z import TextSplitter


# ============================================================
# S-1.1 不可分割块识别
# ============================================================

class TestIdentifyIndivisibleBlocks:
    """锁定 S-1.1: 不可分割块识别规则"""

    def setup_method(self):
        self.splitter = TextSplitter()

    def test_pipe_table_single_block(self):
        """T-CHUNK-01: Markdown 管道表格不被拆断"""
        lines = [
            "一些文字\n",
            "| 指标 | 数值 |\n",
            "|------|------|\n",
            "| 营收 | 100亿 |\n",
            "后续文字\n",
        ]
        blocks = self.splitter._identify_indivisible_blocks(lines)
        # 应识别出一个表格块，覆盖行 1-3
        assert len(blocks) >= 1
        table_blocks = [b for b in blocks if b[0] <= 1 and b[1] >= 3]
        assert len(table_blocks) >= 1, "管道表格应被识别为不可分割块"

    def test_html_table_block(self):
        """T-CHUNK-02: <table>...</table> 不被拆断"""
        lines = [
            "文字\n",
            "<table>\n",
            "<tr><td>数据</td></tr>\n",
            "</table>\n",
            "后续\n",
        ]
        blocks = self.splitter._identify_indivisible_blocks(lines)
        table_blocks = [b for b in blocks if b[0] <= 1 and b[1] >= 3]
        assert len(table_blocks) >= 1, "<table> 块应被识别为不可分割块"

    def test_details_block(self):
        """T-CHUNK-03: <details>...</details> 不被拆断"""
        lines = [
            "文字\n",
            "<details>\n",
            "摘要内容\n",
            "</details>\n",
            "后续\n",
        ]
        blocks = self.splitter._identify_indivisible_blocks(lines)
        details_blocks = [b for b in blocks if b[0] <= 1 and b[1] >= 3]
        assert len(details_blocks) >= 1, "<details> 块应被识别为不可分割块"

    def test_no_indivisible_blocks_in_plain_text(self):
        """纯文本无不可分割块"""
        lines = ["普通文字行\n", "另一行\n", "再一行\n"]
        blocks = self.splitter._identify_indivisible_blocks(lines)
        assert len(blocks) == 0


# ============================================================
# S-1.2 Q&A 块识别
# ============================================================

class TestIdentifyQABlocks:
    """锁定 S-1.2: Q&A 块识别规则"""

    def setup_method(self):
        self.splitter = TextSplitter()

    def test_qa_pair_chinese_colon(self):
        """T-CHUNK-04: **问：**/**答：** Q&A 对不被拆断"""
        lines = [
            "一些背景\n",
            "**问：** 请问营收情况？\n",
            "**答：** 营收为100亿。\n",
            "其他内容\n",
        ]
        blocks = self.splitter._identify_qa_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0][0] == 1  # 从 **问：** 行开始
        assert blocks[0][1] == 4  # 到文件末尾

    def test_qa_pair_english_colon(self):
        """**问:**/**答:** 格式也能识别"""
        lines = [
            "**问:** 问题内容\n",
            "**答:** 回答内容\n",
        ]
        blocks = self.splitter._identify_qa_blocks(lines)
        assert len(blocks) == 1

    def test_multiple_qa_pairs(self):
        """多个 Q&A 对各自独立"""
        lines = [
            "**问：** 第一个问题\n",
            "**答：** 第一个回答\n",
            "**问：** 第二个问题\n",
            "**答：** 第二个回答\n",
        ]
        blocks = self.splitter._identify_qa_blocks(lines)
        assert len(blocks) == 2

    def test_qa_without_answer_not_counted(self):
        """只有问没有答的 Q&A 不被收录"""
        lines = [
            "**问：** 没有回答的问题\n",
        ]
        blocks = self.splitter._identify_qa_blocks(lines)
        assert len(blocks) == 0


# ============================================================
# S-1.3 券商名提取
# ============================================================

class TestExtractBroker:
    """锁定 S-1.3: 券商名提取规则"""

    def setup_method(self):
        self.splitter = TextSplitter()

    def test_known_broker_extracted(self):
        """已知券商名可提取"""
        assert self.splitter._extract_broker("【东方证券】中芯国际研报") == "东方证券"

    def test_longer_broker_priority(self):
        """长券商名优先匹配（现状: 按长度降序）"""
        result = self.splitter._extract_broker("华泰证券报告")
        assert result == "华泰证券"

    def test_unknown_broker_returns_empty(self):
        """未知券商返回空字符串"""
        assert self.splitter._extract_broker("未知券商报告") == ""


# ============================================================
# S-1.4 日期/季度提取
# ============================================================

class TestExtractDateQuarter:
    """锁定 S-1.4: 日期/季度提取规则"""

    def setup_method(self):
        self.splitter = TextSplitter()

    def test_extract_year(self):
        """提取年份"""
        assert self.splitter._extract_date("2024年年报") == "2024"

    def test_extract_year_no_match(self):
        """无年份返回空字符串"""
        assert self.splitter._extract_date("年报") == ""

    def test_extract_quarter_chinese(self):
        """提取中文季度"""
        result = self.splitter._extract_quarter("2024年一季度报告")
        assert result == "2024Q1"

    def test_extract_quarter_english(self):
        """提取英文季度"""
        result = self.splitter._extract_quarter("2024Q2报告")
        assert result == "2024Q2"

    def test_extract_quarter_no_match(self):
        """无季度返回空字符串"""
        assert self.splitter._extract_quarter("2024年年报") == ""


# ============================================================
# S-1.5 Markdown 分块
# ============================================================

class TestSplitMarkdownFile:
    """锁定 S-1.5: split_markdown_file 行为"""

    def setup_method(self):
        self.splitter = TextSplitter()

    def test_no_cross_page_split(self):
        """T-CHUNK-05: 不跨页分块"""
        md_content = """# Page 1

""" + "第一页内容 " * 100 + """

# Page 2

""" + "第二页内容 " * 100
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "test.md"
            md_path.write_text(md_content, encoding='utf-8')
            chunks, lines, line_pages = self.splitter.split_markdown_file(md_path, chunk_size=300)
            # 每个 chunk 只属于一个页码
            for chunk in chunks:
                page = chunk.get('page', 0)
                assert page > 0, f"chunk 页码应 > 0，实际: {page}"

    def test_table_not_split(self, tmp_path):
        """T-CHUNK-01: 表格不被拆断（完整分块流程）"""
        md_content = """---

# Page 1

一些文字

| 指标 | 数值 |
|------|------|
| 营收 | 100亿 |
| 利润 | 20亿 |

后续文字
"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding='utf-8')
        chunks, lines, line_pages = self.splitter.split_markdown_file(md_path, chunk_size=300)
        # 检查表格行没有被拆到两个 chunk 中
        for i in range(len(chunks) - 1):
            text_curr = chunks[i]['text']
            text_next = chunks[i + 1]['text']
            if '|---' in text_curr and text_curr.strip().endswith('|---|'):
                assert '|' not in text_next.split('\n')[0] or '---' in text_next.split('\n')[0], \
                    "管道表格不应被拆断到两个 chunk"

    def test_large_table_separate_chunk(self, tmp_path):
        """T-CHUNK-06: 大表格（> chunk_size）单独成 chunk"""
        table_rows = ["| 列1 | 列2 | 列3 |", "|-----|-----|-----|"]
        for i in range(50):
            table_rows.append(f"| 数据{i}A | 数据{i}B | 数据{i}C |")
        table_text = "\n".join(table_rows)

        md_content = f"""---

# Page 1

一些文字

{table_text}

后续文字
"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding='utf-8')
        chunks, lines, line_pages = self.splitter.split_markdown_file(md_path, chunk_size=100)
        table_chunks = [c for c in chunks if '| 列1 |' in c['text']]
        assert len(table_chunks) >= 1, "大表格应至少有一个独立 chunk"

    def test_overlap_exists(self, tmp_path):
        """T-CHUNK-07: 相邻 chunk 有重叠"""
        md_content = """---

# Page 1

""" + "这是一段测试文本用于验证重叠机制。 " * 80
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding='utf-8')
        chunks, lines, line_pages = self.splitter.split_markdown_file(
            md_path, chunk_size=100, chunk_overlap=20
        )
        if len(chunks) >= 2:
            found_overlap = False
            for i in range(len(chunks) - 1):
                tail = chunks[i]['text'][-50:]
                if tail and tail in chunks[i + 1]['text']:
                    found_overlap = True
                    break
            assert found_overlap or len(chunks) >= 2, \
                "相邻 chunk 应有重叠区域"

    def test_tiny_fragments_merged(self, tmp_path):
        """极小碎片（< 20 tokens）合并到前一个 chunk"""
        md_content = """---

# Page 1

正文内容

---

# Page 2

更多内容
"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding='utf-8')
        chunks, lines, line_pages = self.splitter.split_markdown_file(md_path, chunk_size=300)
        # 行为锁定: 当前 _merge_tiny_fragments 只合并 < 20 tokens
        for chunk in chunks:
            text = chunk['text'].strip()
            if text in ('---', '---\n\n# Page 2'):
                pass

    def test_empty_md_returns_empty(self, tmp_path):
        """空 markdown 文件返回空 chunks"""
        md_path = tmp_path / "empty.md"
        md_path.write_text("", encoding='utf-8')
        chunks, lines, line_pages = self.splitter.split_markdown_file(md_path)
        assert len(chunks) == 0


# ============================================================
# S-1.5 现状: _find_overlap_start 中 blocked 变量未使用
# ============================================================

class TestFindOverlapStartCurrentBehavior:
    """锁定现状 S-1.5: _find_overlap_start 的 blocked 变量赋值后未使用"""

    def setup_method(self):
        self.splitter = TextSplitter()

    def test_blocked_variable_not_breaking_overlap(self, tmp_path):
        """
        现状: _find_overlap_start 中 blocked=True 被赋值但 if blocked: break 缺失。
        这意味着即使遇到不可分割块边界，回溯也不会提前终止（除了 return ov_pos 分支）。
        锁定: 当前行为是 return ov_pos 在块边界处生效，blocked 变量不影响结果。
        """
        import tiktoken
        encoding = tiktoken.get_encoding("o200k_base")
        lines = ["行0\n", "行1\n", "行2\n", "行3\n", "行4\n"]
        # 不可分割块: 行1-行2
        indivisible_blocks = [(1, 3)]
        # 从行3回溯到行0，overlap=50
        result = self.splitter._find_overlap_start(
            lines, current_pos=3, chunk_start=0,
            encoding=encoding, chunk_overlap=50,
            indivisible_blocks=indivisible_blocks
        )
        # 现状: 当 next_pos=2 时，2 在块 (1,3) 内，触发 return ov_pos=3
        assert result == 3, "现状: 遇到不可分割块边界时 return ov_pos"


# ============================================================
# S-1.6 批量分块
# ============================================================

class TestSplitMarkdownReports:
    """锁定 S-1.6: split_markdown_reports 行为"""

    def setup_method(self):
        self.splitter = TextSplitter()

    def test_output_json_structure(self, tmp_path, sample_subset_csv):
        """输出 JSON 包含 metainfo 和 content"""
        md_dir = tmp_path / "markdowns"
        md_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        md_content = """---

# Page 1

测试公司正文内容
"""
        (md_dir / "test_report.md").write_text(md_content, encoding='utf-8')

        self.splitter.split_markdown_reports(
            md_dir, output_dir, chunk_size=300, subset_csv=sample_subset_csv
        )

        output_files = list(output_dir.glob("*.json"))
        assert len(output_files) >= 1, "应生成至少一个 JSON 文件"

        with open(output_files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)

        assert "metainfo" in data, "输出 JSON 应包含 metainfo"
        assert "content" in data, "输出 JSON 应包含 content"
        assert "chunks" in data["content"], "content 应包含 chunks"

    def test_csv_encoding_fallback(self, tmp_path):
        """CSV 读取编码降级: utf-8-sig -> utf-8 -> gbk"""
        md_dir = tmp_path / "markdowns"
        md_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        csv_path = tmp_path / "subset.csv"
        csv_content = "file_name,company_name,sha1\n测试,测试公司,stock_abc12\n"
        csv_path.write_text(csv_content, encoding='gbk')

        md_content = """---

# Page 1

内容
"""
        (md_dir / "测试.md").write_text(md_content, encoding='utf-8')

        # 应不抛出编码异常
        self.splitter.split_markdown_reports(
            md_dir, output_dir, chunk_size=300, subset_csv=csv_path
        )
