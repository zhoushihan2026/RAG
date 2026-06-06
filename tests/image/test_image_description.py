"""
特征测试: 图片描述 (image_description.py)

锁定行为: S-8.1 ~ S-8.3
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.image_description import (
    describe_image,
    is_table_or_chart,
    _load_image_desc_cache,
    _save_image_desc_cache,
    process_report_images,
)


# ============================================================
# S-8.1 图片描述生成
# ============================================================

class TestDescribeImage:
    """锁定 S-8.1: describe_image 行为"""

    @patch('src.image_description._call_vision_model')
    def test_returns_description_string(self, mock_vision):
        """T-IMG-01: 返回图片描述字符串"""
        mock_vision.return_value = "这是一张展示营收增长趋势的图表"
        result = describe_image("fake_image_path.jpg")
        assert isinstance(result, str)
        assert len(result) > 0

    @patch('src.image_description._call_vision_model')
    def test_vision_failure_returns_empty(self, mock_vision):
        """视觉模型调用失败时返回空字符串"""
        mock_vision.return_value = ""
        result = describe_image("fake_image_path.jpg")
        assert isinstance(result, str)


class TestIsTableOrChart:
    """锁定 S-8.1: is_table_or_chart 行为"""

    @patch('src.image_description._call_vision_model')
    def test_returns_true_for_chart(self, mock_vision):
        """图表图片返回 True"""
        mock_vision.return_value = "是"
        result = is_table_or_chart("fake_chart.jpg")
        assert result is True

    @patch('src.image_description._call_vision_model')
    def test_returns_false_for_non_chart(self, mock_vision):
        """非图表图片返回 False"""
        mock_vision.return_value = "否"
        result = is_table_or_chart("fake_photo.jpg")
        assert result is False


# ============================================================
# S-8.2 描述缓存
# ============================================================

class TestDescriptionCache:
    """锁定 S-8.2: 图片描述缓存行为"""

    def test_cache_hit_returns_cached(self, tmp_path):
        """T-IMG-02: 缓存命中时返回缓存描述"""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_data = {
            "img_0_0.jpg": "这是缓存中的图片描述"
        }
        cache_path = cache_dir / "image_desc_cache.json"
        cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding='utf-8')

        result = _load_image_desc_cache(cache_dir)
        assert result["img_0_0.jpg"] == "这是缓存中的图片描述"

    def test_cache_miss_returns_empty_dict(self, tmp_path):
        """缓存目录不存在时返回空字典"""
        cache_dir = tmp_path / "nonexistent"
        result = _load_image_desc_cache(cache_dir)
        assert result == {}

    def test_save_cache(self, tmp_path):
        """保存描述到缓存"""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_data = {"existing.jpg": "已有描述"}
        cache_path = cache_dir / "image_desc_cache.json"
        cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding='utf-8')

        loaded = _load_image_desc_cache(cache_dir)
        loaded["new.jpg"] = "新描述"
        _save_image_desc_cache(cache_dir, loaded)

        reloaded = _load_image_desc_cache(cache_dir)
        assert reloaded["existing.jpg"] == "已有描述"
        assert reloaded["new.jpg"] == "新描述"

    def test_save_creates_new_cache_dir(self, tmp_path):
        """保存时缓存目录不存在则创建"""
        cache_dir = tmp_path / "new_cache"
        assert not cache_dir.exists()

        _save_image_desc_cache(cache_dir, {"new.jpg": "新描述"})

        assert cache_dir.exists()
        loaded = _load_image_desc_cache(cache_dir)
        assert loaded["new.jpg"] == "新描述"


# ============================================================
# S-8.3 报告图片处理
# ============================================================

class TestProcessReportImages:
    """锁定 S-8.3: process_report_images 行为"""

    @patch('src.image_description.describe_image')
    @patch('src.image_description.is_table_or_chart')
    def test_process_non_chart_image(self, mock_classify, mock_describe, tmp_path):
        """T-IMG-03: 非图表图片生成描述并更新markdown"""
        mock_classify.return_value = False
        mock_describe.return_value = "营收增长趋势图"

        # 准备 content_list.json
        content_list = [
            {"type": "image", "content": "", "img_path": "images/img_0_0.jpg"}
        ]
        content_list_path = tmp_path / "content_list.json"
        content_list_path.write_text(json.dumps(content_list, ensure_ascii=False), encoding='utf-8')

        # 准备 markdown 文件
        md_content = "一些文字\n\n![](images/img_0_0.jpg)\n\n更多文字\n"
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding='utf-8')

        # 准备图片文件
        images_dir = tmp_path / "images_base"
        images_dir.mkdir()
        (images_dir / "images").mkdir()
        (images_dir / "images" / "img_0_0.jpg").write_bytes(b"fake image data")

        result = process_report_images(
            content_list_path=str(content_list_path),
            images_base_dir=str(images_dir),
            markdown_path=str(md_path),
            skip_classification=False,
        )

        assert result >= 1
        updated_md = md_path.read_text(encoding='utf-8')
        assert "营收增长趋势图" in updated_md

    def test_no_images_returns_zero(self, tmp_path):
        """无待处理图片时返回 0"""
        content_list = [
            {"type": "text", "content": "纯文本内容"}
        ]
        content_list_path = tmp_path / "content_list.json"
        content_list_path.write_text(json.dumps(content_list, ensure_ascii=False), encoding='utf-8')

        md_path = tmp_path / "test.md"
        md_path.write_text("纯文本\n", encoding='utf-8')

        result = process_report_images(
            content_list_path=str(content_list_path),
            images_base_dir=str(tmp_path),
            markdown_path=str(md_path),
        )

        assert result == 0

    @patch('src.image_description.describe_image')
    @patch('src.image_description.is_table_or_chart')
    def test_cached_report_skips_processing(self, mock_classify, mock_describe, tmp_path):
        """缓存标记为 completed 的报告跳过处理"""
        # 先写入缓存
        cache_dir = tmp_path
        cache_data = {"test": {"status": "completed"}}
        cache_path = cache_dir / "image_desc_cache.json"
        cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding='utf-8')

        content_list = [
            {"type": "image", "content": "", "img_path": "images/img_0_0.jpg"}
        ]
        content_list_path = tmp_path / "content_list.json"
        content_list_path.write_text(json.dumps(content_list, ensure_ascii=False), encoding='utf-8')

        md_path = tmp_path / "test.md"
        md_path.write_text("![](images/img_0_0.jpg)\n", encoding='utf-8')

        result = process_report_images(
            content_list_path=str(content_list_path),
            images_base_dir=str(tmp_path),
            markdown_path=str(md_path),
        )

        assert result == 0
        mock_describe.assert_not_called()
