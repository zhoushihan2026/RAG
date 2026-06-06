"""
特征测试: Pipeline 合并逻辑 (pipeline.py _merge_mineru_results)

锁定行为: S-2.3 (Pipeline 层合并)
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.pipeline import Pipeline, RunConfig


class TestPipelineMergeMineruResults:
    """锁定 S-2.3: _merge_mineru_results 的 page_idx 偏移修正"""

    def test_page_idx_offset_correction(self, tmp_path):
        """T-MERGE-01: 拆分 PDF 后 content_list.json 的 page_idx 偏移修正"""
        root = tmp_path / "data"
        root.mkdir()
        pipeline = Pipeline(root, run_config=RunConfig())

        part1_json = tmp_path / "part1.json"
        part1_content = [
            {"type": "text", "text": "第一部分", "page_idx": 0},
            {"type": "text", "text": "第一部分第二页", "page_idx": 1},
        ]
        part1_json.write_text(json.dumps(part1_content, ensure_ascii=False), encoding='utf-8')

        part2_json = tmp_path / "part2.json"
        part2_content = [
            {"type": "text", "text": "第二部分", "page_idx": 0},
            {"type": "text", "text": "第二部分第二页", "page_idx": 1},
        ]
        part2_json.write_text(json.dumps(part2_content, ensure_ascii=False), encoding='utf-8')

        part1_md = tmp_path / "part1.md"
        part1_md.write_text("第一部分\n第一部分第二页\n", encoding='utf-8')
        part2_md = tmp_path / "part2.md"
        part2_md.write_text("第二部分\n第二部分第二页\n", encoding='utf-8')

        pipeline.paths.mineru_markdown_path.mkdir(parents=True, exist_ok=True)
        pipeline.paths.mineru_json_path.mkdir(parents=True, exist_ok=True)

        part_results = [
            (str(part1_md), str(part1_json)),
            (str(part2_md), str(part2_json)),
        ]
        start_pages = [0, 200]

        merged_md, merged_json = pipeline._merge_mineru_results(
            part_results, start_pages, "test_report"
        )

        with open(merged_json, 'r', encoding='utf-8') as f:
            merged_content = json.load(f)

        assert merged_content[0]["page_idx"] == 0
        assert merged_content[1]["page_idx"] == 1
        assert merged_content[2]["page_idx"] == 200
        assert merged_content[3]["page_idx"] == 201

    def test_merge_md_concatenation(self, tmp_path):
        """T-MERGE-02: markdown 直接拼接"""
        root = tmp_path / "data"
        root.mkdir()
        pipeline = Pipeline(root, run_config=RunConfig())

        part1_md = tmp_path / "part1.md"
        part1_md.write_text("第一部分内容", encoding='utf-8')
        part2_md = tmp_path / "part2.md"
        part2_md.write_text("第二部分内容", encoding='utf-8')

        pipeline.paths.mineru_markdown_path.mkdir(parents=True, exist_ok=True)
        pipeline.paths.mineru_json_path.mkdir(parents=True, exist_ok=True)

        part_results = [(str(part1_md), None), (str(part2_md), None)]
        start_pages = [0, 200]

        merged_md, merged_json = pipeline._merge_mineru_results(
            part_results, start_pages, "test_report"
        )

        with open(merged_md, 'r', encoding='utf-8') as f:
            content = f.read()

        assert "第一部分内容" in content
        assert "第二部分内容" in content
