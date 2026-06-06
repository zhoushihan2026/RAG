"""
特征测试: MinerU 结果合并 (merge_json_to_markdown.py)

锁定行为: S-2.1 ~ S-2.3
"""
import json
import os
import pytest
from pathlib import Path

from src.merge_json_to_markdown import (
    _extract_item_text,
    _is_match,
    insert_page_markers,
    convert_content_list_json_to_markdown,
    _fallback_convert,
)


# ============================================================
# S-2.1 页码标记插入
# ============================================================

class TestInsertPageMarkers:
    """锁定 S-2.1: insert_page_markers 行为"""

    def test_page_marker_inserted_at_page_boundary(self):
        """T-MD-01: 页码标记在页码变化处插入"""
        full_md = "第一页标题\n第一页内容\n第二页标题\n第二页内容\n"
        content_list = [
            {"type": "text", "text": "第一页标题", "page_idx": 0},
            {"type": "text", "text": "第一页内容", "page_idx": 0},
            {"type": "text", "text": "第二页标题", "page_idx": 1},
            {"type": "text", "text": "第二页内容", "page_idx": 1},
        ]
        result = insert_page_markers(full_md, content_list)
        assert "# Page 1" in result, "应包含 # Page 1 标记"
        assert "# Page 2" in result, "应包含 # Page 2 标记"
        assert result.index("# Page 1") < result.index("# Page 2")

    def test_page_number_is_one_based(self):
        """页码标记使用 1-based 编号（page_idx + 1）"""
        full_md = "标题\n"
        content_list = [
            {"type": "text", "text": "标题", "page_idx": 0},
        ]
        result = insert_page_markers(full_md, content_list)
        assert "# Page 1" in result, "page_idx=0 应显示为 Page 1"

    def test_marker_format(self):
        """页码标记格式: ---\\n\\n# Page N"""
        full_md = "标题\n"
        content_list = [
            {"type": "text", "text": "标题", "page_idx": 0},
        ]
        result = insert_page_markers(full_md, content_list)
        assert "---\n\n# Page 1\n" in result, "标记格式应为 ---\\n\\n# Page N"

    def test_skip_header_footer_page_number(self):
        """跳过 header/footer/page_number 类型"""
        full_md = "标题\n"
        content_list = [
            {"type": "header", "text": "页眉", "page_idx": 0},
            {"type": "footer", "text": "页脚", "page_idx": 0},
            {"type": "page_number", "text": "1", "page_idx": 0},
            {"type": "text", "text": "标题", "page_idx": 0},
        ]
        result = insert_page_markers(full_md, content_list)
        assert "# Page 1" in result

    def test_no_match_returns_original(self):
        """无可匹配内容时原样返回"""
        full_md = "原始文本\n"
        content_list = []
        result = insert_page_markers(full_md, content_list)
        assert result == full_md

    def test_short_text_skipped(self):
        """匹配文本最小长度 2 字符"""
        full_md = "长标题文本\n"
        content_list = [
            {"type": "text", "text": "长标题文本", "page_idx": 0},
            {"type": "text", "text": "X", "page_idx": 1},
        ]
        result = insert_page_markers(full_md, content_list)
        assert "# Page 1" in result


# ============================================================
# S-2.1 辅助函数
# ============================================================

class TestExtractItemText:
    """锁定 S-2.1: _extract_item_text 行为"""

    def test_text_type(self):
        assert _extract_item_text({"type": "text", "text": "  标题  "}) == "标题"

    def test_list_type_returns_empty(self):
        """list 类型返回空字符串（跳过）"""
        assert _extract_item_text({"type": "list", "list_items": ["a"]}) == ""

    def test_table_type_with_caption(self):
        item = {"type": "table", "table_caption": ["表1"], "table_body": ""}
        assert _extract_item_text(item) == "表1"

    def test_table_type_with_body_fallback(self):
        item = {"type": "table", "table_caption": [], "table_body": "<td>数据</td>"}
        result = _extract_item_text(item)
        assert "数据" in result

    def test_chart_type_returns_empty(self):
        """chart 类型返回空字符串"""
        assert _extract_item_text({"type": "chart"}) == ""

    def test_image_type_returns_basename(self):
        item = {"type": "image", "img_path": "/some/path/images/img_0_0.jpg"}
        result = _extract_item_text(item)
        assert "img_0_0.jpg" in result

    def test_unknown_type_returns_empty(self):
        assert _extract_item_text({"type": "unknown"}) == ""


class TestIsMatch:
    """锁定 S-2.1: _is_match 匹配规则"""

    def test_substring_match(self):
        """子串匹配: 任一方是另一方子串"""
        assert _is_match("标题", "这是标题内容") is True
        assert _is_match("完整标题", "完整标题") is True

    def test_no_match(self):
        assert _is_match("完全不同", "毫无关联") is False

    def test_empty_text_no_match(self):
        """空文本不匹配"""
        assert _is_match("", "内容") is False
        assert _is_match("内容", "") is False

    def test_hash_prefix_stripped(self):
        """去掉 # 前缀后匹配"""
        assert _is_match("# 标题", "标题") is True


# ============================================================
# S-2.2 回退模式
# ============================================================

class TestFallbackConvert:
    """锁定 S-2.2: _fallback_convert 行为"""

    def test_fallback_generates_page_markers(self, tmp_path):
        """T-MD-02: 无 full.md 时回退到 JSON 直接生成"""
        content_list = [
            {"type": "text", "text": "标题", "page_idx": 0, "text_level": 1},
            {"type": "text", "text": "内容", "page_idx": 0},
            {"type": "text", "text": "第二页", "page_idx": 1},
        ]
        output_path = str(tmp_path / "output.md")
        result = _fallback_convert(content_list, output_path)
        assert "# Page 1" in result
        assert "# Page 2" in result
        assert os.path.exists(output_path)

    def test_fallback_text_level(self, tmp_path):
        """text_level > 0 时加 # 前缀"""
        content_list = [
            {"type": "text", "text": "大标题", "page_idx": 0, "text_level": 2},
        ]
        output_path = str(tmp_path / "output.md")
        result = _fallback_convert(content_list, output_path)
        assert "## 大标题" in result

    def test_fallback_table_output(self, tmp_path):
        """table 类型输出 caption + body + footnote"""
        content_list = [
            {"type": "table", "table_caption": ["表1"], "table_body": "<table></table>",
             "table_footnote": ["注1"], "page_idx": 0},
        ]
        output_path = str(tmp_path / "output.md")
        result = _fallback_convert(content_list, output_path)
        assert "表1" in result
        assert "<table></table>" in result
        assert "注1" in result

    def test_fallback_list_output(self, tmp_path):
        """list 类型每项加 - 前缀"""
        content_list = [
            {"type": "list", "list_items": ["项目1", "项目2"], "page_idx": 0},
        ]
        output_path = str(tmp_path / "output.md")
        result = _fallback_convert(content_list, output_path)
        assert "- 项目1" in result
        assert "- 项目2" in result


# ============================================================
# S-2.3 完整流程: convert_content_list_json_to_markdown
# ============================================================

class TestConvertContentListJsonToMarkdown:
    """锁定 S-2.3: 完整转换流程"""

    def test_with_full_md(self, tmp_path):
        """有 full.md 时使用序列对齐"""
        content_list = [
            {"type": "text", "text": "标题", "page_idx": 0},
            {"type": "text", "text": "内容", "page_idx": 0},
        ]
        json_path = tmp_path / "content_list.json"
        json_path.write_text(json.dumps(content_list, ensure_ascii=False), encoding='utf-8')

        full_md_path = tmp_path / "full.md"
        full_md_path.write_text("标题\n内容\n", encoding='utf-8')

        output_path = str(tmp_path / "output.md")
        result = convert_content_list_json_to_markdown(
            str(json_path), output_path, full_md_path=str(full_md_path)
        )
        assert "# Page 1" in result
        assert os.path.exists(output_path)

    def test_without_full_md_fallback(self, tmp_path):
        """T-MD-02: 无 full.md 时回退"""
        content_list = [
            {"type": "text", "text": "标题", "page_idx": 0},
        ]
        json_path = tmp_path / "content_list.json"
        json_path.write_text(json.dumps(content_list, ensure_ascii=False), encoding='utf-8')

        output_path = str(tmp_path / "output.md")
        result = convert_content_list_json_to_markdown(str(json_path), output_path)
        assert "# Page 1" in result

    def test_auto_find_full_md(self, tmp_path):
        """full_md_path=None 时自动在同目录查找"""
        content_list = [
            {"type": "text", "text": "标题", "page_idx": 0},
        ]
        json_path = tmp_path / "content_list.json"
        json_path.write_text(json.dumps(content_list, ensure_ascii=False), encoding='utf-8')

        full_md_path = tmp_path / "full.md"
        full_md_path.write_text("标题\n", encoding='utf-8')

        output_path = str(tmp_path / "output.md")
        result = convert_content_list_json_to_markdown(str(json_path), output_path)
        assert "# Page 1" in result
