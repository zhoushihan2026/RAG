# Qwen-Turbo API的基础限流设置为每分钟不超过500次API调用（QPM）。同时，Token消耗限流为每分钟不超过500,000 Tokens
from dataclasses import dataclass
from pathlib import Path
from pyprojroot import here
import logging
import os
import json
import pandas as pd
import shutil
import tempfile
import time
import copy
import hashlib

# from src import pdf_mineru
from src import pdf_mineru_z as pdf_mineru
from src.parsed_reports_merging import PageTextPreparation
from src.text_splitter_z import TextSplitter
from src.ingestion import VectorDBIngestor
from src.ingestion import BM25Ingestor
from src.questions_processing import QuestionsProcessor
from src import prompts
from src.tables_serialization import TableSerializer
from src.image_description import process_report_images, process_all_reports_images

@dataclass
class PipelineConfig:
    def __init__(self, root_path: Path, subset_name: str = "subset.csv", questions_file_name: str = "questions.json", pdf_reports_dir_name: str = "pdf_reports", serialized: bool = False, config_suffix: str = ""):
        # 路径配置，支持不同流程和数据目录
        self.root_path = root_path
        suffix = "_ser_tab" if serialized else ""

        self.subset_path = root_path / subset_name
        self.questions_file_path = root_path / questions_file_name
        self.pdf_reports_dir = root_path / pdf_reports_dir_name
        
        self.answers_path = root_path / "answers"
        self.answers_file_path = self.answers_path / f"answers{config_suffix}.json"
        self.debug_data_path = root_path / "debug_data"
        self.databases_path = root_path / f"databases{suffix}"
        
        self.vector_db_dir = self.databases_path / "vector_dbs"
        self.documents_dir = self.databases_path / "chunked_reports"
        self.bm25_db_path = self.databases_path / "bm25_dbs"
        self.metadata_path = self.databases_path / "chunks_metadata.json"

        # MinerU 解析结果目录
        self.mineru_markdown_path = self.debug_data_path / "01_mineru_markdown"
        self.mineru_json_path = self.debug_data_path / "01_mineru_json"
        self.mineru_images_path = self.debug_data_path / "01_mineru_images"
        # 合并JSON页码数据后的markdown目录
        self.reports_markdown_path = self.debug_data_path / "02_reports_markdown"

@dataclass
class RunConfig:
    # 运行流程参数配置
    use_serialized_tables: bool = False          # 是否使用序列化表格（将表格转为文本加入分块），mineru可以替代
    parent_document_retrieval: bool = False      # 是否启用父文档检索（检索chunk后返回整页内容）
    use_vector_dbs: bool = True                  # 是否使用向量检索
    use_bm25_db: bool = False                    # 是否使用BM25检索
    llm_reranking: bool = False                  # 是否启用LLM重排（使用HybridRetriever）
    llm_reranking_sample_size: int = 30          # LLM重排时的候选采样数
    hybrid_bm25_vector: bool = False             # 是否启用BM25+Vector混合检索+DashScope Rerank（需use_vector_dbs和use_bm25_db同时为True）
    hybrid_bm25_vector_alpha: float = 0.5        # 混合检索中向量权重（1-alpha为BM25权重）
    hybrid_bm25_vector_recall_n: int = 30        # 混合检索第一阶段召回候选数
    top_n_retrieval: int = 5                    # 最终返回给LLM的检索结果数
    parallel_requests: int = 1                   # 并行请求数，需限制否则qwen-turbo会超出阈值
    pipeline_details: str = ""                   # 流程描述信息，写入答案文件用于区分不同配置
    submission_file: bool = True                 # 是否生成提交格式的答案文件
    full_context: bool = False                   # 是否使用全量上下文（跳过检索，直接返回整篇报告）
    api_provider: str = "dashscope"              # API提供商：dashscope 或 openai
    answering_model: str = "qwen3.6-max-preview"   # 回答模型：qwen-turbo-latest / qwen3.6-max-preview / gpt-4o-mini-2024-07-18 / gpt-4o-2024-08-06
    rewrite_model: str = "qwen-turbo"            # 重写/分类模型（轻量快速）
    config_suffix: str = ""                      # 配置后缀，用于区分不同实验的输出文件名
    use_metadata_filter: bool = False            # 是否启用元数据过滤检索（统一向量库+元数据过滤+问题重写）

class Pipeline:
    def __init__(self, root_path: Path, subset_name: str = "subset.csv", questions_file_name: str = "questions.json", pdf_reports_dir_name: str = "pdf_reports", run_config: RunConfig = RunConfig()):
        # 初始化主流程，加载路径和配置
        self.run_config = run_config
        self.paths = self._initialize_paths(root_path, subset_name, questions_file_name, pdf_reports_dir_name)
        self._convert_json_to_csv_if_needed()

    def _initialize_paths(self, root_path: Path, subset_name: str, questions_file_name: str, pdf_reports_dir_name: str) -> PipelineConfig:
        """根据配置初始化所有路径"""
        return PipelineConfig(
            root_path=root_path,
            subset_name=subset_name,
            questions_file_name=questions_file_name,
            pdf_reports_dir_name=pdf_reports_dir_name,
            serialized=self.run_config.use_serialized_tables,
            config_suffix=self.run_config.config_suffix
        )

    def _convert_json_to_csv_if_needed(self):
        """
        检查是否存在subset.json且无subset.csv，若是则自动转换为CSV。
        """
        json_path = self.paths.root_path / "subset.json"
        csv_path = self.paths.root_path / "subset.csv"
        
        if json_path.exists() and not csv_path.exists():
            try:
                with open(json_path, 'r') as f:
                    data = json.load(f)
                
                df = pd.DataFrame(data)
                
                df.to_csv(csv_path, index=False)
                
            except Exception as e:
                print(f"Error converting JSON to CSV: {str(e)}")

    @staticmethod
    def download_docling_models(): 
        # 下载Docling所需模型，避免首次运行时自动下载
        from src.pdf_parsing import PDFParser
        logging.basicConfig(level=logging.DEBUG)
        parser = PDFParser(output_dir=here())
        parser.parse_and_export(input_doc_paths=[here() / "src/dummy_report.pdf"])

    def parse_pdf_reports_parallel(self, chunk_size: int = 2, max_workers: int = 10):
        """多进程并行解析PDF报告，提升处理效率
        参数：
            chunk_size: 每个worker处理的PDF数
            num_workers: 并发worker数
        """
        from src.pdf_parsing import PDFParser
        logging.basicConfig(level=logging.DEBUG)
        
        pdf_parser = PDFParser(
            output_dir=self.paths.parsed_reports_path,
            csv_metadata_path=self.paths.subset_path
        )
        pdf_parser.debug_data_path = self.paths.parsed_reports_debug_path

        input_doc_paths = list(self.paths.pdf_reports_dir.glob("*.pdf"))
        
        pdf_parser.parse_and_export_parallel(
            input_doc_paths=input_doc_paths,
            optimal_workers=max_workers,
            chunk_size=chunk_size
        )
        print(f"PDF reports parsed and saved to {self.paths.parsed_reports_path}")

    # MinerU 单次可接受的最大页数
    MINERU_MAX_PAGES = 200

    def _split_pdf(self, pdf_path: str, max_pages: int = 200):
        """
        将 PDF 按页数拆分为多个临时文件，每个不超过 max_pages 页。
        :param pdf_path: 原始 PDF 的完整路径
        :param max_pages: 每个拆分部分的最大页数
        :return: 拆分后的临时 PDF 路径列表，以及每部分的起始页码列表（0-based）
        """
        from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        print(f"PDF 总页数: {total_pages}，最大允许 {max_pages} 页/次")

        if total_pages <= max_pages:
            # 不需要拆分
            return [pdf_path], [0]

        split_paths = []
        start_pages = []
        base_name = os.path.splitext(pdf_path)[0]
        temp_dir = tempfile.mkdtemp(prefix="mineru_split_")

        for i in range(0, total_pages, max_pages):
            writer = PdfWriter()
            end = min(i + max_pages, total_pages)
            for page_num in range(i, end):
                writer.add_page(reader.pages[page_num])
            part_path = os.path.join(temp_dir, f"{os.path.basename(base_name)}_part{i//max_pages + 1}.pdf")
            with open(part_path, "wb") as f:
                writer.write(f)
            split_paths.append(part_path)
            start_pages.append(i)
            print(f"已拆分: 第 {i+1}-{end} 页 -> {os.path.basename(part_path)}")

        return split_paths, start_pages

    def _merge_mineru_results(self, part_results, start_pages, base_name):
        """
        合并多个拆分部分的 MinerU 解析结果（full.md 和 content_list.json）。
        对 content_list.json 中的 page_idx 进行偏移修正，对 full.md 直接拼接。
        :param part_results: 列表，每项为 (md_src_path, json_src_path) 或 (md_src_path, None)
        :param start_pages: 每部分的起始页码列表（0-based）
        :param base_name: 输出文件的基础名（不含扩展名）
        :return: (merged_md_path, merged_json_path) 合并后的文件路径
        """
        os.makedirs(self.paths.mineru_markdown_path, exist_ok=True)
        os.makedirs(self.paths.mineru_json_path, exist_ok=True)

        merged_md_path = os.path.join(self.paths.mineru_markdown_path, f"{base_name}.md")
        merged_json_path = os.path.join(self.paths.mineru_json_path, f"{base_name}.json")

        # 合并 markdown：直接拼接各部分的 full.md
        md_parts = []
        for md_src, _ in part_results:
            if md_src and os.path.exists(md_src):
                with open(md_src, "r", encoding="utf-8") as f:
                    md_parts.append(f.read())
        merged_md_text = "\n\n".join(md_parts)
        with open(merged_md_path, "w", encoding="utf-8") as f:
            f.write(merged_md_text)
        print(f"已合并 markdown: {merged_md_path}")

        # 合并 content_list.json：修正 page_idx 偏移
        merged_content_list = []
        for part_idx, (_, json_src) in enumerate(part_results):
            if json_src and os.path.exists(json_src):
                with open(json_src, "r", encoding="utf-8") as f:
                    content_list = json.load(f)
                page_offset = start_pages[part_idx]
                for item in content_list:
                    new_item = copy.deepcopy(item)
                    # 修正 page_idx
                    if "page_idx" in new_item:
                        new_item["page_idx"] += page_offset
                    merged_content_list.append(new_item)
        with open(merged_json_path, "w", encoding="utf-8") as f:
            json.dump(merged_content_list, f, ensure_ascii=False, indent=2)
        print(f"已合并 content_list.json: {merged_json_path}")

        return merged_md_path, merged_json_path

    def export_reports_to_markdown(self, file_name):
        """
        使用 pdf_mineru_z.py，将指定 PDF 文件转换为 markdown。
        支持超过200页的大文件：自动拆分上传，合并结果。
        流程：
        1. 检查是否已解析过（避免重复上传），若已解析则直接使用已有数据
        2. 检查页数，若超过限制则拆分PDF
        3. 逐部分上传PDF并解析，下载解压到系统临时目录
        4. 合并各部分的解析结果（markdown + content_list.json）
        5. 将合并后的 markdown 保存到 01_mineru_markdown
        6. 将合并后的 content_list.json 保存到 01_mineru_json
        7. 基于 content_list.json 生成带页码标记的新 markdown，保存到 02_reports_markdown
        8. 清理系统临时目录
        :param file_name: PDF 文件名（如 '【财报】中芯国际：中芯国际2024年年度报告.pdf'）
        """
        from src.merge_json_to_markdown import convert_content_list_json_to_markdown

        # 构造本地PDF完整路径
        local_pdf_path = str(self.paths.pdf_reports_dir / file_name)
        base_name = os.path.splitext(file_name)[0]

        # 计算PDF文件的SHA1哈希，用于判断文件是否变动
        pdf_sha1 = self._compute_file_sha1(local_pdf_path)

        # 检查是否已解析过：如果 01_mineru_markdown 和 01_mineru_json 中已有对应文件，则跳过上传
        existing_md = os.path.join(self.paths.mineru_markdown_path, f"{base_name}.md")
        existing_json = os.path.join(self.paths.mineru_json_path, f"{base_name}.json")
        if os.path.exists(existing_md) and os.path.exists(existing_json):
            # 检查PDF文件是否变动
            cache_record = self._get_mineru_cache_record(base_name)
            if cache_record and cache_record.get("pdf_sha1") == pdf_sha1:
                print(f"PDF文件未变动，跳过上传: {base_name}")
            else:
                if cache_record:
                    print(f"PDF文件已变动，需重新上传: {base_name}")
                else:
                    print(f"无缓存记录，需重新上传: {base_name}")
                # 删除旧的解析结果，重新上传
                if os.path.exists(existing_md):
                    os.remove(existing_md)
                if os.path.exists(existing_json):
                    os.remove(existing_json)
                # 删除旧的图片目录
                old_images_dir = os.path.join(str(self.paths.mineru_images_path), base_name)
                if os.path.isdir(old_images_dir):
                    shutil.rmtree(old_images_dir)
                # 跳过return，继续执行上传逻辑
                # 注意：这里不能直接return，需要继续执行下面的上传代码
                # 所以我们重新检查文件是否存在
                if os.path.exists(existing_md) or os.path.exists(existing_json):
                    # 如果删除失败，也继续上传
                    pass
                else:
                    # 文件已删除，跳到上传逻辑
                    pass

        # 再次检查（可能刚被删除了）
        existing_md = os.path.join(self.paths.mineru_markdown_path, f"{base_name}.md")
        existing_json = os.path.join(self.paths.mineru_json_path, f"{base_name}.json")
        if os.path.exists(existing_md) and os.path.exists(existing_json):
            # 处理非表格图表图片并添加描述（从永久目录01_mineru_images查找图片）
            self._describe_images_for_report(
                base_name, existing_json, existing_md
            )
            # 但仍需检查 02_reports_markdown 是否存在，不存在则重新生成
            target_md_path = os.path.join(self.paths.reports_markdown_path, f"{base_name}.md")
            if not os.path.exists(target_md_path):
                os.makedirs(self.paths.reports_markdown_path, exist_ok=True)
                convert_content_list_json_to_markdown(existing_json, target_md_path, full_md_path=existing_md)
                print(f"已补充生成带页码标记的 markdown: {target_md_path}")
            else:
                # 02_reports_markdown已存在，但01_mineru_markdown可能已更新了图片描述，需重新生成
                convert_content_list_json_to_markdown(existing_json, target_md_path, full_md_path=existing_md)
                print(f"已重新生成带页码标记的 markdown（含图片描述）: {target_md_path}")
            # 更新缓存记录
            self._save_mineru_cache_record(base_name, pdf_sha1)
            # 确保文件信息写入 subset.csv（跳过上传时也需要）
            self._add_file_to_subset_csv(file_name, local_pdf_path)
            return

        # 使用系统临时目录存放MinerU下载的zip和解压文件，处理完后立即清理
        mineru_temp_dir = tempfile.mkdtemp(prefix="mineru_parse_")
        try:
            # 拆分PDF（若超过页数限制）
            split_paths, start_pages = self._split_pdf(local_pdf_path, self.MINERU_MAX_PAGES)
            need_split = len(split_paths) > 1
            if need_split:
                print(f"PDF 已拆分为 {len(split_paths)} 个部分，将逐部分上传解析")

            # 逐部分上传解析
            part_results = []
            extract_dirs = []
            for part_idx, part_pdf_path in enumerate(split_paths):
                part_label = f"第 {part_idx + 1}/{len(split_paths)} 部分" if need_split else ""
                print(f"开始处理: {file_name} {part_label}")
                batch_id = pdf_mineru.upload_and_parse(part_pdf_path)
                print(f"batch_id: {batch_id} {part_label}")
                extract_dir = pdf_mineru.get_result(batch_id, output_dir=mineru_temp_dir)
                if not extract_dir:
                    print(f"解析失败，跳过: {file_name} {part_label}")
                    continue
                extract_dirs.append(extract_dir)

                md_src = os.path.join(extract_dir, "full.md")
                json_src = None
                for fname in os.listdir(extract_dir):
                    if fname.endswith("_content_list.json"):
                        json_src = os.path.join(extract_dir, fname)
                        break
                part_results.append((md_src if os.path.exists(md_src) else None, json_src))

            if not part_results:
                print(f"所有部分均解析失败: {file_name}")
                return

            # 合并各部分结果
            if need_split:
                merged_md_path, merged_json_path = self._merge_mineru_results(
                    part_results, start_pages, base_name
                )
            else:
                os.makedirs(self.paths.mineru_markdown_path, exist_ok=True)
                os.makedirs(self.paths.mineru_json_path, exist_ok=True)

                md_src, json_src = part_results[0]
                merged_md_path = os.path.join(self.paths.mineru_markdown_path, f"{base_name}.md")
                merged_json_path = os.path.join(self.paths.mineru_json_path, f"{base_name}.json")

                if md_src and os.path.exists(md_src):
                    shutil.copy2(md_src, merged_md_path)
                    print(f"已保存原始 markdown: {merged_md_path}")
                if json_src and os.path.exists(json_src):
                    shutil.copy2(json_src, merged_json_path)
                    print(f"已保存 content_list.json: {merged_json_path}")

            # 保存图片到永久目录（01_mineru_images），以便后续图片描述处理
            self._save_images_to_permanent_dir(base_name, extract_dirs)

            # 确保目标目录存在
            os.makedirs(self.paths.reports_markdown_path, exist_ok=True)

            # 在生成02_reports_markdown之前，处理非表格图表图片并添加描述到01_mineru_markdown
            self._describe_images_for_report(
                base_name, merged_json_path, merged_md_path
            )

            # 生成带页码标记的新 markdown 到 02_reports_markdown
            target_md_path = os.path.join(self.paths.reports_markdown_path, f"{base_name}.md")
            if os.path.exists(merged_json_path) and os.path.exists(merged_md_path):
                convert_content_list_json_to_markdown(merged_json_path, target_md_path, full_md_path=merged_md_path)
                print(f"已生成带页码标记的 markdown: {target_md_path}")
            elif os.path.exists(merged_md_path):
                shutil.copy2(merged_md_path, target_md_path)
                print(f"警告：使用无页码标记的原始 markdown: {target_md_path}")
            else:
                print(f"错误：无可用 markdown 文件，跳过: {file_name}")

            # 保存缓存记录（PDF文件SHA1）
            self._save_mineru_cache_record(base_name, pdf_sha1)
            
            # 确保文件信息写入 subset.csv（批量处理时也需要）
            self._add_file_to_subset_csv(file_name, local_pdf_path)
        finally:
            # 无论成功或失败，都清理临时目录
            try:
                shutil.rmtree(mineru_temp_dir, ignore_errors=True)
                print(f"已清理临时目录: {mineru_temp_dir}")
            except Exception as e:
                print(f"清理临时目录时出错: {e}")

    @staticmethod
    def _compute_file_sha1(file_path: str, chunk_size: int = 8192) -> str:
        """计算文件的SHA1哈希值"""
        sha1 = hashlib.sha1()
        with open(file_path, "rb") as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                sha1.update(data)
        return sha1.hexdigest()

    def _get_cache_file_path(self) -> str:
        """获取缓存文件路径"""
        return os.path.join(str(self.paths.mineru_json_path), "file_cache.json")

    def _load_cache(self) -> dict:
        """加载缓存记录"""
        cache_path = self._get_cache_file_path()
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_cache(self, cache: dict):
        """保存缓存记录"""
        cache_path = self._get_cache_file_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

    def _get_mineru_cache_record(self, base_name: str) -> dict:
        """获取指定报告的MinerU缓存记录"""
        cache = self._load_cache()
        return cache.get(base_name)

    def _save_mineru_cache_record(self, base_name: str, pdf_sha1: str):
        """保存指定报告的MinerU缓存记录"""
        cache = self._load_cache()
        cache[base_name] = {
            "pdf_sha1": pdf_sha1,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self._save_cache(cache)
        print(f"已保存缓存记录: {base_name}")

    def _save_images_to_permanent_dir(self, base_name, extract_dirs):
        """
        将MinerU解析的图片保存到永久目录（01_mineru_images）。
        :param base_name: 报告基础名称
        :param extract_dirs: MinerU解压目录列表
        """
        permanent_dir = os.path.join(str(self.paths.mineru_images_path), base_name)
        permanent_images_dir = os.path.join(permanent_dir, "images")

        if os.path.isdir(permanent_images_dir):
            return

        for extract_dir in extract_dirs:
            src_images_dir = os.path.join(extract_dir, "images")
            if os.path.isdir(src_images_dir):
                os.makedirs(permanent_dir, exist_ok=True)
                shutil.copytree(src_images_dir, permanent_images_dir)
                print(f"已保存图片到永久目录: {permanent_images_dir}")
                return

    def _describe_images_for_report(
        self, base_name, json_path, md_path
    ):
        """
        为单个报告处理非表格图表图片，生成描述并更新markdown。
        从永久图片目录（01_mineru_images）查找图片。
        :param base_name: 报告基础名称
        :param json_path: content_list.json路径
        :param md_path: markdown文件路径
        """
        images_base_dir = None

        # 从永久图片目录查找
        permanent_images_dir = os.path.join(str(self.paths.mineru_images_path), base_name)
        if os.path.isdir(os.path.join(permanent_images_dir, "images")):
            images_base_dir = permanent_images_dir

        if not images_base_dir:
            print(f"未找到图片目录，跳过图片描述: {base_name}")
            return

        print(f"开始处理非表格图表图片: {base_name}")
        process_report_images(
            content_list_path=json_path,
            images_base_dir=images_base_dir,
            markdown_path=md_path,
        )

    def describe_report_images(self, file_name=None):
        """
        独立调用：为已解析的报告处理非表格图表图片。
        如果指定file_name则处理单个报告，否则处理所有报告。
        :param file_name: PDF文件名（可选），如不指定则处理所有报告
        """
        if file_name:
            base_name = os.path.splitext(file_name)[0]
            json_path = os.path.join(self.paths.mineru_json_path, f"{base_name}.json")
            md_path = os.path.join(self.paths.mineru_markdown_path, f"{base_name}.md")

            if not os.path.exists(json_path) or not os.path.exists(md_path):
                print(f"报告解析结果不存在，请先运行 export_reports_to_markdown: {base_name}")
                return

            self._describe_images_for_report(
                base_name, json_path, md_path
            )

            # 重新生成02_reports_markdown
            target_md_path = os.path.join(self.paths.reports_markdown_path, f"{base_name}.md")
            if os.path.exists(target_md_path):
                convert_content_list_json_to_markdown(json_path, target_md_path, full_md_path=md_path)
                print(f"已重新生成带页码标记的 markdown（含图片描述）: {target_md_path}")
        else:
            total = process_all_reports_images(
                mineru_json_dir=str(self.paths.mineru_json_path),
                mineru_markdown_dir=str(self.paths.mineru_markdown_path),
                mineru_images_dir=str(self.paths.mineru_images_path),
            )
            # 重新生成所有02_reports_markdown
            if total > 0:
                for json_filename in os.listdir(self.paths.mineru_json_path):
                    if not json_filename.endswith(".json"):
                        continue
                    base_name = os.path.splitext(json_filename)[0]
                    json_path = os.path.join(self.paths.mineru_json_path, json_filename)
                    md_path = os.path.join(self.paths.mineru_markdown_path, f"{base_name}.md")
                    target_md_path = os.path.join(self.paths.reports_markdown_path, f"{base_name}.md")
                    if os.path.exists(md_path):
                        os.makedirs(self.paths.reports_markdown_path, exist_ok=True)
                        convert_content_list_json_to_markdown(json_path, target_md_path, full_md_path=md_path)
                        print(f"已重新生成: {target_md_path}")

    @staticmethod
    def _compute_dir_hash(dir_path: Path, pattern: str = "*.md") -> str:
        """计算目录下所有匹配文件的SHA1哈希，用于判断输入是否变动"""
        if not dir_path.exists():
            return ""
        sha1 = hashlib.sha1()
        for file_path in sorted(dir_path.glob(pattern)):
            sha1.update(file_path.name.encode("utf-8"))
            with open(file_path, "rb") as f:
                sha1.update(f.read())
        return sha1.hexdigest()

    def chunk_reports(self, include_serialized_tables: bool = False):
        """
        将规整后 markdown 报告分块，便于后续向量化和检索
        如果输入文件未变动且已存在切片输出，则跳过切片
        """
        input_dir = self.paths.reports_markdown_path
        output_dir = self.paths.documents_dir

        input_hash = self._compute_dir_hash(input_dir, "*.md")
        cache_dir = output_dir.parent
        cache_path = cache_dir / "chunking_cache.json"

        if cache_path.exists() and input_hash:
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                if cache.get("input_hash") == input_hash:
                    existing_files = list(output_dir.glob("*.json"))
                    if existing_files:
                        print(f"切片缓存命中，输入文件未变动，跳过切片（已有 {len(existing_files)} 个切片文件）")
                        return
            except Exception:
                pass

        print(f"开始分割 {input_dir} 目录下的 markdown 文件...")
        text_splitter_z = TextSplitter()
        text_splitter_z.split_markdown_reports(
            all_md_dir=input_dir,
            output_dir=output_dir,
            subset_csv=self.paths.subset_path
        )

        chunk_files = list(output_dir.glob("*.json"))
        if not chunk_files:
            print(f"错误：分割后未生成任何 chunk 文件。")
            print(f"请确保已先执行步骤4（MinerU解析PDF生成markdown），且 {input_dir} 目录下有 .md 文件。")
            print(f"如果 MinerU API Key 未配置，请在项目根目录创建 .env 文件并设置 MINERU_API_KEY。")
            return
        print(f"分割完成，共生成 {len(chunk_files)} 个 chunk 文件，结果已保存到 {output_dir}")

        output_dir.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"input_hash": input_hash}, f, ensure_ascii=False, indent=2)

    def create_vector_dbs(self):
        """从分块报告创建向量数据库"""
        input_dir = self.paths.documents_dir
        output_dir = self.paths.vector_db_dir
        
        vdb_ingestor = VectorDBIngestor()
        vdb_ingestor.process_reports(input_dir, output_dir)
        print(f"Vector databases created in {output_dir}")
    
    def create_bm25_db(self):
        """从分块报告创建BM25数据库"""
        input_dir = self.paths.documents_dir
        output_file = self.paths.bm25_db_path
        
        bm25_ingestor = BM25Ingestor()
        bm25_ingestor.process_reports(input_dir, output_file)
        print(f"BM25 database created at {output_file}")
    
    def parse_pdf_reports(self, parallel: bool = True, chunk_size: int = 2, max_workers: int = 10):
        # 解析PDF报告，支持并行处理
        if parallel:
            self.parse_pdf_reports_parallel(chunk_size=chunk_size, max_workers=max_workers)

    def process_parsed_reports(self):
        """
        处理已解析的PDF报告，主要流程：
        1. 对报告进行分块
        2. 创建向量数据库
        """
        print("开始处理报告流程...")
        
        print("步骤1：报告分块...")
        self.chunk_reports()
        
        print("步骤2：创建向量数据库...")
        self.create_vector_dbs()
        
        print("报告处理流程已成功完成！")
        
    def _get_next_available_filename(self, base_path: Path) -> Path:
        """
        获取下一个可用的文件名，如果文件已存在则自动添加编号后缀。
        例如：若answers.json已存在，则返回answers_01.json等。
        """
        if not base_path.exists():
            return base_path
            
        stem = base_path.stem
        suffix = base_path.suffix
        parent = base_path.parent
        
        counter = 1
        while True:
            new_filename = f"{stem}_{counter:02d}{suffix}"
            new_path = parent / new_filename
            
            if not new_path.exists():
                return new_path
            counter += 1

    def process_questions(self):
        # 处理所有问题，生成答案文件
        processor = QuestionsProcessor(
            vector_db_dir=self.paths.vector_db_dir,
            documents_dir=self.paths.documents_dir,
            questions_file_path=self.paths.questions_file_path,
            new_challenge_pipeline=True,
            subset_path=self.paths.subset_path,
            parent_document_retrieval=self.run_config.parent_document_retrieval,
            use_vector_dbs=self.run_config.use_vector_dbs,
            use_bm25_db=self.run_config.use_bm25_db,
            llm_reranking=self.run_config.llm_reranking,
            llm_reranking_sample_size=self.run_config.llm_reranking_sample_size,
            hybrid_bm25_vector=self.run_config.hybrid_bm25_vector,
            hybrid_bm25_vector_alpha=self.run_config.hybrid_bm25_vector_alpha,
            hybrid_bm25_vector_recall_n=self.run_config.hybrid_bm25_vector_recall_n,
            bm25_db_dir=self.paths.bm25_db_path,
            top_n_retrieval=self.run_config.top_n_retrieval,
            parallel_requests=self.run_config.parallel_requests,
            api_provider=self.run_config.api_provider,
            answering_model=self.run_config.answering_model,
            full_context=self.run_config.full_context,
            metadata_path=self.paths.metadata_path,
            use_metadata_filter=self.run_config.use_metadata_filter
        )
        
        self.paths.answers_path.mkdir(parents=True, exist_ok=True)
        output_path = self._get_next_available_filename(self.paths.answers_file_path)
        
        _ = processor.process_all_questions(
            output_path=output_path,
            submission_file=self.run_config.submission_file,
            pipeline_details=self.run_config.pipeline_details
        )
        print(f"Answers saved to {output_path}")

    def _add_file_to_subset_csv(self, file_name: str, pdf_path: str) -> str:
        """
        将新上传的文件信息写入 subset.csv
        格式与已有记录保持一致：sha1 用占位符(如 stock_10003)，file_name 不带扩展名，company_name 提取简短名称
        
        :param file_name: PDF 文件名（含扩展名）
        :param pdf_path: PDF 文件完整路径
        :return: 分配的占位符 sha1 值
        """
        import csv as _csv
        import re as _re
        
        subset_path = self.paths.subset_path
        
        # file_name 不带扩展名（与已有记录格式一致）
        base_name = os.path.splitext(file_name)[0]
        
        # 从文件名提取 company_name
        # 优先取【】内的内容作为公司名
        # 【光大证券】中芯国际2025年一季度业绩点评：... -> 光大证券
        # 【东方证券】产能利用率提升... -> 东方证券
        # 【财报】中芯国际：中芯国际2024年年度报告 -> 中芯国际（取 】和 ：之间的内容）
        # 中芯国际机构调研纪要 -> 中芯国际（从已有 company_name 列匹配）
        company_name = base_name
        m = _re.search(r'【(.+?)】', base_name)
        if m:
            bracket_content = m.group(1)
            # 如果【】内是"财报"等非公司名，则取 】和 ：之间的内容
            if bracket_content in ('财报', '年报', '季报', '半年报', '研报'):
                m2 = _re.search(r'】([^：]+?)：', base_name)
                if m2:
                    company_name = m2.group(1)
                else:
                    company_name = bracket_content
            else:
                company_name = bracket_content
        else:
            # 没有【】的文件名，尝试从已有 subset.csv 的 company_name 列匹配已知公司名
            existing_companies = set()
            if subset_path.exists():
                try:
                    import pandas as _pd2
                    _df = None
                    for enc in ['utf-8-sig', 'utf-8', 'gbk']:
                        try:
                            _df = _pd2.read_csv(subset_path, encoding=enc)
                            break
                        except Exception:
                            continue
                    if _df is not None and 'company_name' in _df.columns:
                        existing_companies = set(_df['company_name'].dropna().unique())
                except Exception:
                    pass
            # 按长度降序匹配，优先匹配更长的公司名
            for c in sorted(existing_companies, key=len, reverse=True):
                if c in base_name:
                    company_name = c
                    break
        
        try:
            rows_to_write = []
            file_names_set = set()
            max_stock_num = 0
            fieldnames = ['sha1', 'file_name', 'company_name']
            
            if subset_path.exists():
                # 尝试多种编码读取 subset.csv
                df = None
                for enc in ['utf-8-sig', 'utf-8', 'gbk']:
                    try:
                        import pandas as _pd
                        df = _pd.read_csv(subset_path, encoding=enc)
                        print(f"[subset] 使用 {enc} 编码成功读取 subset.csv")
                        break
                    except Exception:
                        continue
                
                if df is not None:
                    for _, row in df.iterrows():
                        rows_to_write.append(row.to_dict())
                        fn = str(row.get('file_name', ''))
                        if fn:
                            file_names_set.add(fn)
                        # 找出最大的 stock_XXXXX 编号
                        sha1_val = str(row.get('sha1', ''))
                        stock_m = _re.match(r'stock_(\d+)', sha1_val)
                        if stock_m:
                            num = int(stock_m.group(1))
                            if num > max_stock_num:
                                max_stock_num = num
                    if 'sha1' in df.columns and 'file_name' in df.columns and 'company_name' in df.columns:
                        fieldnames = ['sha1', 'file_name', 'company_name']
                    else:
                        fieldnames = list(df.columns)
            
            # 检查是否已存在（用不带扩展名的 file_name 匹配）
            if base_name in file_names_set:
                print(f"[subset] {base_name} 已在 subset.csv 中")
                # 返回已有的 sha1
                for row in rows_to_write:
                    if str(row.get('file_name', '')) == base_name:
                        return str(row.get('sha1', ''))
                return f"stock_{max_stock_num + 1:05d}"
            
            # 生成新的占位符 sha1
            new_sha1 = f"stock_{max_stock_num + 1:05d}"
            
            # 添加新记录（file_name 不带扩展名）
            new_row = {'sha1': new_sha1, 'file_name': base_name, 'company_name': company_name}
            rows_to_write.append(new_row)
            
            # 使用 utf-8-sig 编码写入（兼容 Excel）
            with open(subset_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = _csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(rows_to_write)
                f.flush()
                os.fsync(f.fileno())
            
            print(f"[subset] 已添加到 subset.csv: file_name={base_name}, sha1={new_sha1}, company_name={company_name}")
            return new_sha1
            
        except Exception as e:
            print(f"[subset] 写入失败: {e}")
            import traceback as _tb
            _tb.print_exc()
            return f"stock_99999"

    def process_single_pdf_file(self, file_path: str, original_filename: str = None) -> dict:
        """
        处理单个PDF文件的完整流程：解析、分块、向量化、BM25索引
        返回状态信息字典
        
        :param file_path: PDF文件路径（绝对路径）
        :param original_filename: 原始文件名（用于保存时使用正确的名称）
        :return: dict 包含 status, message, file_name 等信息
        """
        import shutil as _shutil
        result = {"status": "unknown", "message": "", "file_name": ""}
        
        try:
            # 获取完整路径
            if not os.path.isabs(file_path):
                full_path = str(self.paths.pdf_reports_dir / file_path)
            else:
                full_path = file_path
            
            if not os.path.exists(full_path):
                return {"status": "error", "message": f"文件不存在: {full_path}", "file_name": original_filename or os.path.basename(file_path)}
            
            # 使用原始文件名（如果提供），否则使用路径中的文件名
            if original_filename:
                file_name = original_filename
            else:
                file_name = os.path.basename(full_path)
            
            base_name = os.path.splitext(file_name)[0]
            result["file_name"] = base_name
            
            print(f"[上传] 开始处理文件: {file_name}")
            
            # 1. 复制到 pdf_reports 目录（使用正确的文件名）
            target_pdf_path = str(self.paths.pdf_reports_dir / file_name)
            if full_path != target_pdf_path:
                _shutil.copy2(full_path, target_pdf_path)
                print(f"[上传] 已复制文件到: {target_pdf_path}")
            
            # 2. 将文件信息写入 subset.csv（如果不存在）
            written_sha1 = self._add_file_to_subset_csv(file_name, target_pdf_path)
            
            # 验证 subset.csv 是否包含该文件的 sha1（用于调试）
            import pandas as _pd_verify
            try:
                verify_df = None
                for _enc in ['utf-8-sig', 'utf-8', 'gbk']:
                    try:
                        verify_df = _pd_verify.read_csv(self.paths.subset_path, encoding=_enc)
                        break
                    except Exception:
                        continue
                if verify_df is not None:
                    match_rows = verify_df[verify_df['file_name'] == base_name]
                    if len(match_rows) > 0:
                        verify_sha1 = match_rows.iloc[0]['sha1']
                        print(f"[上传] 验证: {base_name} 在 subset.csv 中, sha1={verify_sha1}")
                    else:
                        print(f"[上传] 警告: {base_name} 未在 subset.csv 中找到!")
            except Exception as ve:
                print(f"[上传] 验证 subset.csv 失败: {ve}")
            
            # 3. 检查是否已完全处理过（解析+分块+向量化+BM25）
            existing_md = os.path.join(self.paths.mineru_markdown_path, f"{base_name}.md")
            existing_json = os.path.join(self.paths.mineru_json_path, f"{base_name}.json")
            existing_chunked = os.path.join(self.paths.documents_dir, f"{base_name}.json")
            
            # 计算 PDF 真实 SHA1（用于判断文件是否变动）
            pdf_real_sha1 = self._compute_file_sha1(target_pdf_path)
            
            # 从 subset.csv 获取 company_name（用于命名 faiss/bm25 文件）
            company_name = ""
            if os.path.exists(str(self.paths.subset_path)):
                try:
                    import pandas as _pd3
                    _df3 = None
                    for enc in ['utf-8-sig', 'utf-8', 'gbk']:
                        try:
                            _df3 = _pd3.read_csv(self.paths.subset_path, encoding=enc)
                            break
                        except Exception:
                            continue
                    if _df3 is not None and 'file_name' in _df3.columns and 'company_name' in _df3.columns:
                        match_rows = _df3[_df3['file_name'] == base_name]
                        if len(match_rows) > 0:
                            company_name = str(match_rows.iloc[0]['company_name'])
                except Exception:
                    pass
            if not company_name:
                company_name = base_name
            
            if os.path.exists(existing_md) and os.path.exists(existing_json) and os.path.exists(existing_chunked):
                cache_record = self._get_mineru_cache_record(base_name)
                
                # 检查向量数据库是否存在（按 company_name 命名）
                faiss_file = self.paths.vector_db_dir / f"{company_name}.faiss"
                
                # 检查 BM25 数据库是否存在（按 company_name 命名）
                bm25_file = self.paths.bm25_db_path / f"{company_name}.pkl"
                
                if (cache_record and cache_record.get("pdf_sha1") == pdf_real_sha1 
                    and faiss_file.exists() and bm25_file.exists()):
                    print(f"[上传] 文件已存在于数据库中: {base_name}")
                    return {"status": "exists", "message": f"该文件已在数据库中", "file_name": base_name}
                else:
                    print(f"[上传] 检测到部分处理结果，但数据库不完整，重新处理: {base_name}")
            
            # 4. PDF解析为markdown
            print(f"[上传] 步骤1/4: 解析PDF...")
            self.export_reports_to_markdown(file_name)
            
            # 5. 分块
            print(f"[上传] 步骤2/4: 文本分块...")
            self.chunk_reports()
            
            # 6. 创建向量数据库
            print(f"[上传] 步骤3/4: 创建向量数据库...")
            self.create_vector_dbs()
            
            # 7. 创建BM25数据库
            print(f"[上传] 步骤4/4: 创建BM25数据库...")
            self.create_bm25_db()
            
            print(f"[上传] 处理完成: {base_name}")
            return {"status": "success", "message": "上传数据库成功", "file_name": base_name}
            
        except Exception as e:
            error_msg = f"处理失败: {str(e)}"
            print(f"[上传] 错误: {error_msg}")
            import traceback as _tb
            _tb.print_exc()
            result["status"] = "error"
            result["message"] = error_msg
            return result

    def answer_single_question(self, question: str, kind: str = "string"):
        """
        单条问题即时推理，返回结构化答案（dict）。
        kind: 支持 'string'、'number'、'boolean'、'names' 等
        """
        t0 = time.time()
        print("[计时] 开始初始化 QuestionsProcessor ...")
        processor = self._create_processor()
        t1 = time.time()
        print(f"[计时] QuestionsProcessor 初始化耗时: {t1-t0:.2f} 秒")

        if kind == "string":
            effective_kind = self._classify_question(question)
        else:
            effective_kind = kind

        print("[计时] 开始调用 process_single_question ...")
        answer = processor.process_single_question(question, kind=effective_kind)
        t2 = time.time()
        print(f"[计时] process_single_question 推理耗时: {t2-t1:.2f} 秒")
        
        source_files = self._get_source_file_names()
        
        if isinstance(answer, dict):
            answer["source_files"] = source_files
        
        print(f"[计时] answer_single_question 总耗时: {t2-t0:.2f} 秒")
        return answer

    def _create_processor(self, answering_model=None, top_n_retrieval=None):
        """创建QuestionsProcessor实例，统一参数传递"""
        from src.questions_processing import QuestionsProcessor
        return QuestionsProcessor(
            vector_db_dir=self.paths.vector_db_dir,
            documents_dir=self.paths.documents_dir,
            questions_file_path=None,
            new_challenge_pipeline=True,
            subset_path=self.paths.subset_path,
            parent_document_retrieval=self.run_config.parent_document_retrieval,
            use_vector_dbs=self.run_config.use_vector_dbs,
            use_bm25_db=self.run_config.use_bm25_db,
            llm_reranking=self.run_config.llm_reranking,
            llm_reranking_sample_size=self.run_config.llm_reranking_sample_size,
            hybrid_bm25_vector=self.run_config.hybrid_bm25_vector,
            hybrid_bm25_vector_alpha=self.run_config.hybrid_bm25_vector_alpha,
            hybrid_bm25_vector_recall_n=self.run_config.hybrid_bm25_vector_recall_n,
            bm25_db_dir=self.paths.bm25_db_path,
            top_n_retrieval=top_n_retrieval or self.run_config.top_n_retrieval,
            parallel_requests=1,
            api_provider=self.run_config.api_provider,
            answering_model=answering_model or self.run_config.answering_model,
            full_context=self.run_config.full_context,
            metadata_path=self.paths.metadata_path,
            use_metadata_filter=self.run_config.use_metadata_filter
        )

    def _classify_question(self, question):
        """对问题进行分类，返回类别字符串"""
        import json as _json
        import re
        from src.api_requests import BaseDashscopeProcessor
        classify_processor = BaseDashscopeProcessor()
        classify_resp = classify_processor.send_message(
            model=self.run_config.rewrite_model,
            system_content=prompts.QUESTION_CLASSIFICATION_SYSTEM_PROMPT,
            human_content=f"请分类以下问题：\n{question}",
            is_structured=False
        )
        question_category = "string"
        if isinstance(classify_resp, str):
            try:
                resp_str = classify_resp.strip()
                if resp_str.startswith("```"):
                    resp_str = re.sub(r'^```\w*\n?', '', resp_str)
                    resp_str = re.sub(r'\n?```$', '', resp_str)
                classify_result = _json.loads(resp_str)
                question_category = classify_result.get("category", "string")
            except (_json.JSONDecodeError, TypeError):
                question_category = "string"
        elif isinstance(classify_resp, dict):
            question_category = classify_resp.get("category", "string")
        if question_category not in ("fact_extraction", "analysis_explanation", "prediction_judgment"):
            question_category = "string"
        print(f"[计时] 问题分类({self.run_config.rewrite_model}): 类别={question_category}")
        return question_category

    def _rewrite_question(self, question):
        """对问题进行重写，返回重写结果字典"""
        import json as _json
        import re
        from src.api_requests import BaseDashscopeProcessor
        rewrite_processor = BaseDashscopeProcessor()
        rewrite_resp = rewrite_processor.send_message(
            model=self.run_config.rewrite_model,
            system_content=prompts.QUESTION_REWRITE_SYSTEM_PROMPT,
            human_content=f"请分析以下问题：\n{question}",
            is_structured=False
        )
        rewrite_result = {}
        if isinstance(rewrite_resp, str):
            try:
                resp_str = rewrite_resp.strip()
                if resp_str.startswith("```"):
                    resp_str = re.sub(r'^```\w*\n?', '', resp_str)
                    resp_str = re.sub(r'\n?```$', '', resp_str)
                rewrite_result = _json.loads(resp_str)
            except (_json.JSONDecodeError, TypeError):
                rewrite_result = {}
        elif isinstance(rewrite_resp, dict):
            rewrite_result = rewrite_resp
        print(f"[计时] 问题重写({self.run_config.rewrite_model}): 结果: {rewrite_result}")
        return rewrite_result

    def _rewrite_and_classify_parallel(self, question):
        """并行执行问题重写和分类，使用asyncio.to_thread包装同步调用实现并发"""
        import asyncio
        import json as _json
        import re
        from src.api_requests import BaseDashscopeProcessor

        classify_processor = BaseDashscopeProcessor()
        rewrite_processor = BaseDashscopeProcessor()

        async def _run_parallel():
            classify_task = asyncio.to_thread(
                classify_processor.send_message,
                model=self.run_config.rewrite_model,
                system_content=prompts.QUESTION_CLASSIFICATION_SYSTEM_PROMPT,
                human_content=f"请分类以下问题：\n{question}",
                is_structured=False
            )
            rewrite_task = asyncio.to_thread(
                rewrite_processor.send_message,
                model=self.run_config.rewrite_model,
                system_content=prompts.QUESTION_REWRITE_SYSTEM_PROMPT,
                human_content=f"请分析以下问题：\n{question}",
                is_structured=False
            )
            classify_resp, rewrite_resp = await asyncio.gather(classify_task, rewrite_task)
            return rewrite_resp, classify_resp

        t_start = time.time()
        rewrite_resp, classify_resp = asyncio.run(_run_parallel())
        print(f"[计时] 并行重写+分类总耗时: {time.time()-t_start:.2f}s")

        # 解析分类结果
        question_category = "string"
        if isinstance(classify_resp, dict):
            question_category = classify_resp.get("category", "string")
        elif isinstance(classify_resp, str):
            try:
                resp_str = classify_resp.strip()
                if resp_str.startswith("```"):
                    resp_str = re.sub(r'^```\w*\n?', '', resp_str)
                    resp_str = re.sub(r'\n?```$', '', resp_str)
                classify_result = _json.loads(resp_str)
                question_category = classify_result.get("category", "string")
            except (_json.JSONDecodeError, TypeError):
                question_category = "string"
        if question_category not in ("fact_extraction", "analysis_explanation", "prediction_judgment"):
            question_category = "string"
        print(f"[计时] 问题分类({self.run_config.rewrite_model}): 类别={question_category}")

        # 解析重写结果
        rewrite_result = {}
        if isinstance(rewrite_resp, dict):
            rewrite_result = rewrite_resp
        elif isinstance(rewrite_resp, str):
            try:
                resp_str = rewrite_resp.strip()
                if resp_str.startswith("```"):
                    resp_str = re.sub(r'^```\w*\n?', '', resp_str)
                    resp_str = re.sub(r'\n?```$', '', resp_str)
                rewrite_result = _json.loads(resp_str)
            except (_json.JSONDecodeError, TypeError):
                rewrite_result = {}
        print(f"[计时] 问题重写({self.run_config.rewrite_model}): 结果: {rewrite_result}")

        return rewrite_result, question_category

    def _get_source_file_names(self):
        """获取所有已处理报告的文件名映射"""
        import json as _json
        source_files = {}
        if self.paths.documents_dir.exists():
            for json_file in self.paths.documents_dir.glob("*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        doc = _json.load(f)
                    metainfo = doc.get("metainfo", {})
                    sha1 = metainfo.get("sha1", "")
                    file_name = metainfo.get("file_name", "")
                    company_name = metainfo.get("company_name", "")
                    if sha1:
                        source_files[sha1] = {
                            "file_name": file_name,
                            "company_name": company_name
                        }
                except Exception as e:
                    print(f"读取文件失败 {json_file.name}: {e}")
        return source_files

    def answer_single_question_stream(self, question: str, kind: str = "string"):
        """
        流式单条问题推理。
        模型配置通过 RunConfig 管理，不再硬编码。
        """
        import json as _json
        import re
        import pandas as pd
        from src.questions_processing import build_metadata_filters
        from src.api_requests import BaseDashscopeProcessor
        from src.retrieval import MetadataFilteredRetriever

        t0 = time.time()

        yield {"type": "status", "content": "正在初始化..."}

        processor = self._create_processor()

        # 步骤1：公司名抽取
        yield {"type": "status", "content": "正在识别公司名称..."}
        t1 = time.time()
        extracted_companies = processor._extract_companies_from_subset(question)
        if len(extracted_companies) == 0:
            yield {"type": "error", "content": "未在问题中找到公司名称"}
            return
        company_name = extracted_companies[0]
        print(f"[计时] 公司名抽取: {time.time()-t1:.2f}s")

        # 步骤2：问题重写 + 问题分类（并行执行）
        yield {"type": "status", "content": "正在重写问题并分析问题类型..."}
        t2 = time.time()
        rewrite_result, question_category = self._rewrite_and_classify_parallel(question)
        print(f"[计时] 问题重写+分类(并行): {time.time()-t2:.2f}s, 类别: {question_category}")
        print(f"[流式-问题重写] 结果: {rewrite_result}")

        # 步骤3：构建元数据过滤条件
        companies_df = getattr(processor, 'companies_df', None)
        if companies_df is None and processor.subset_path:
            try:
                companies_df = pd.read_csv(processor.subset_path, encoding='utf-8')
            except UnicodeDecodeError:
                companies_df = pd.read_csv(processor.subset_path, encoding='gbk')
            processor.companies_df = companies_df

        rewritten_query, metadata_filters = build_metadata_filters(
            question, companies_df, rewrite_result, question_source=""
        )
        print(f"[流式-元数据过滤] rewritten_query: {rewritten_query}")

        # 步骤4：元数据过滤检索
        yield {"type": "status", "content": f"正在检索 {company_name} 的相关文档..."}
        t3 = time.time()

        retriever = MetadataFilteredRetriever(
            vector_db_dir=processor.vector_db_dir,
            documents_dir=processor.documents_dir,
            bm25_db_dir=processor.bm25_db_dir,
            metadata_path=processor.metadata_path,
            alpha=processor.hybrid_bm25_vector_alpha
        )

        retrieval_results = retriever.retrieve(
            rewritten_query=rewritten_query,
            metadata_filters=metadata_filters,
            top_n=self.run_config.top_n_retrieval,
            recall_n=self.run_config.hybrid_bm25_vector_recall_n,
            return_parent_pages=processor.return_parent_pages
        )

        if not retrieval_results:
            yield {"type": "error", "content": "未找到相关文档"}
            return

        print(f"[计时] 检索: {time.time()-t3:.2f}s, 结果数: {len(retrieval_results)}")

        # 步骤5：格式化上下文（完整，不截断）
        rag_context = processor._format_retrieval_results(retrieval_results)
        context_chars = len(rag_context)
        print(f"[流式] 上下文长度: {context_chars} 字符")

        # 步骤6：流式生成
        yield {"type": "status", "content": "正在生成回答..."}

        PROMPT_MAP = {
            "fact_extraction": prompts.AnswerWithRAGContextFactPrompt,
            "analysis_explanation": prompts.AnswerWithRAGContextAnalysisPrompt,
            "prediction_judgment": prompts.AnswerWithRAGContextPredictionPrompt,
            "string": prompts.AnswerWithRAGContextStringPrompt,
        }
        selected_prompt = PROMPT_MAP.get(question_category, prompts.AnswerWithRAGContextStringPrompt)
        system_prompt = selected_prompt.system_prompt
        user_prompt = selected_prompt.user_prompt.format(
            context=rag_context, question=question
        )

        dashscope_processor = BaseDashscopeProcessor()

        yield {"type": "stream_start", "content": ""}

        t4 = time.time()
        first_token = True
        for token in dashscope_processor.send_message_stream(
            model=self.run_config.answering_model,
            system_content=system_prompt,
            human_content=user_prompt
        ):
            if first_token:
                print(f"[计时] LLM首字延迟(TTFT): {time.time()-t4:.2f}s")
                first_token = False
            yield {"type": "token", "content": token}

        # 步骤7：解析完整响应
        full_content = getattr(dashscope_processor, '_stream_full_content', '')

        answer_dict = {"step_by_step_analysis": "", "reasoning_summary": "",
                       "relevant_pages": [], "final_answer": full_content}

        if full_content:
            try:
                content_str = full_content.strip()
                if content_str.startswith('```'):
                    first_backtick = content_str.find('```') + 3
                    next_newline = content_str.find('\n', first_backtick)
                    if next_newline > 0:
                        first_backtick = next_newline + 1
                    last_backtick = content_str.rfind('```')
                    if last_backtick > first_backtick:
                        json_str = content_str[first_backtick:last_backtick].strip()
                    else:
                        json_str = content_str
                else:
                    json_str = content_str

                parsed = _json.loads(json_str)
                if isinstance(parsed, dict):
                    answer_dict = parsed
            except (_json.JSONDecodeError, TypeError):
                pass

        # 步骤8：补充溯源信息
        if processor.new_challenge_pipeline:
            pages = answer_dict.get("relevant_pages", [])
            validated_pages = processor._validate_page_references(pages, retrieval_results)
            answer_dict["relevant_pages"] = validated_pages
            answer_dict["references"] = processor._extract_references_with_traceability(
                validated_pages, company_name, retrieval_results
            )

        source_files = self._get_source_file_names()
        answer_dict["source_files"] = source_files

        t_end = time.time()
        print(f"[计时] 流式回答总耗时: {t_end-t0:.2f}s")

        yield {"type": "done", "content": answer_dict}

preprocess_configs = {"ser_tab": RunConfig(use_serialized_tables=True),
                      "no_ser_tab": RunConfig(use_serialized_tables=False)}

base_config = RunConfig(
    parallel_requests=10,
    submission_file=True,
    pipeline_details="Custom pdf parsing + vDB + Router + SO CoT; llm = GPT-4o-mini",
    config_suffix="_base"
)

parent_document_retrieval_config = RunConfig(
    parent_document_retrieval=True,
    parallel_requests=20,
    submission_file=True,
    pipeline_details="Custom pdf parsing + vDB + Router + Parent Document Retrieval + SO CoT; llm = GPT-4o",
    answering_model="gpt-4o-2024-08-06",
    config_suffix="_pdr"
)

## 这里
max_config = RunConfig(
    use_serialized_tables=False,
    parent_document_retrieval=True,
    llm_reranking=True,
    parallel_requests=4,
    submission_file=True,
    pipeline_details="Custom pdf parsing + vDB + Router + Parent Document Retrieval + reranking + SO CoT; llm = qwen-turbo",
    answering_model="qwen-turbo-latest",
    config_suffix="_qwen_turbo"
)

hybrid_bm25_vector_config = RunConfig(
    use_serialized_tables=False,
    parent_document_retrieval=True,
    use_bm25_db=True,
    hybrid_bm25_vector=True,
    hybrid_bm25_vector_alpha=0.5,
    hybrid_bm25_vector_recall_n=50,      # 第一阶段召回候选数
    top_n_retrieval=5,                   # 最终返回给LLM的检索结果数
    parallel_requests=4,
    submission_file=True,
    use_metadata_filter=True,
    pipeline_details="Custom pdf parsing + BM25+Vector Hybrid + DashScope Rerank + Parent Document Retrieval + SO CoT; llm = kimi-k2.6",
    answering_model="kimi-k2.6",
    rewrite_model="qwen-turbo",
    api_provider="dashscope",
    config_suffix="_hybrid_bm25_vec_rerank_kimi_k26_v2"
)


configs = {"base": base_config,
           "pdr": parent_document_retrieval_config,
           "max": max_config,
           "hybrid_bm25_vector": hybrid_bm25_vector_config}


# 你可以直接在本文件中运行任意方法：
# python .\src\pipeline.py
# 只需取消你想运行的方法的注释即可
# 你也可以修改 run_config 以尝试不同的配置
if __name__ == "__main__":
    root_path = here() / "data" / "stock_data"
    print('root_path:', root_path)
    pipeline = Pipeline(root_path, run_config=hybrid_bm25_vector_config)
    
    # print('4. 将pdf转化为纯markdown文本')
    # pipeline.export_reports_to_markdown('【财报】中芯国际：中芯国际2024年年度报告.pdf')
    # pipeline.export_reports_to_markdown('【东方证券】产能利用率提升，持续推进工艺迭代和产品性能升级.pdf')
    # pipeline.export_reports_to_markdown('【光大证券】中芯国际2025年一季度业绩点评：1Q突发生产问题，2Q业绩有望筑底，自主可控趋势不改.pdf')
    # pipeline.export_reports_to_markdown('【国信证券】工业与汽车触底反弹，良率影响短期营收.pdf')
    # pipeline.export_reports_to_markdown('【华泰证券】中芯国际（688981）：上调港股目标价到63港币，看好DeepSeek推动代工需求强劲增长.pdf')
    # pipeline.export_reports_to_markdown('【上海证券】中芯国际深度研究报告：晶圆制造龙头，领航国产芯片新征程.pdf')
    # pipeline.export_reports_to_markdown('【兴证国际】季度盈利低于预期，看好国产芯片长期空间.pdf')
    # pipeline.export_reports_to_markdown('【中原证券】产能利用率显著提升，持续推进工艺迭代升级——中芯国际(688981)季报点评.pdf')
    # pipeline.export_reports_to_markdown('中芯国际机构调研纪要.pdf')


    # print('5. 将规整后报告分块，便于后续向量化，输出到 databases/chunked_reports')
    # pipeline.chunk_reports() 
    
    # print('6. 从分块报告创建向量数据库，输出到 databases/vector_dbs')
    # pipeline.create_vector_dbs()

    # print('6.5 从分块报告创建BM25数据库，输出到 databases/bm25_dbs')
    # pipeline.create_bm25_db()
    
    print('7. 处理问题并生成答案，具体逻辑取决于 run_config')
    pipeline.process_questions() 
    
    print('完成')
