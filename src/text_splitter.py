import json
import tiktoken
from pathlib import Path
from typing import List, Dict, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
import pandas as pd
import os

# 文本分块工具类，支持按页分块、表格插入、token统计等
class TextSplitter():
    def _get_serialized_tables_by_page(self, tables: List[Dict]) -> Dict[int, List[Dict]]:
        """按页分组已序列化表格，便于后续插入到对应页面分块中"""
        tables_by_page = {}
        for table in tables:
            if 'serialized' not in table:
                continue
                
            page = table['page']
            if page not in tables_by_page:
                tables_by_page[page] = []
            
            table_text = "\n".join(
                block["information_block"] 
                for block in table["serialized"]["information_blocks"]
            )
            
            tables_by_page[page].append({
                "page": page,
                "text": table_text,
                "table_id": table["table_id"],
                "length_tokens": self.count_tokens(table_text)
            })
            
        return tables_by_page

    def _split_report(self, file_content: Dict[str, any], serialized_tables_report_path: Optional[Path] = None) -> Dict[str, any]:
        """将报告按页分块，保留markdown表格内容，可选插入序列化表格块。"""
        chunks = []
        chunk_id = 0
        
        tables_by_page = {}
        if serialized_tables_report_path is not None:
            # 加载序列化表格，按页分组
            with open(serialized_tables_report_path, 'r', encoding='utf-8') as f:
                parsed_report = json.load(f)
            tables_by_page = self._get_serialized_tables_by_page(parsed_report.get('tables', []))
        
        for page in file_content['content']['pages']:
            # 普通文本分块
            page_chunks = self._split_page(page)
            for chunk in page_chunks:
                chunk['id'] = chunk_id
                chunk['type'] = 'content'
                chunk_id += 1
                chunks.append(chunk)
            
            # 插入序列化表格分块
            if tables_by_page and page['page'] in tables_by_page:
                for table in tables_by_page[page['page']]:
                    table['id'] = chunk_id
                    table['type'] = 'serialized_table'
                    chunk_id += 1
                    chunks.append(table)
        
        file_content['content']['chunks'] = chunks
        return file_content

    def count_tokens(self, string: str, encoding_name="o200k_base"):
        # 统计字符串的token数，支持自定义编码
        encoding = tiktoken.get_encoding(encoding_name)
        tokens = encoding.encode(string)
        token_count = len(tokens)
        return token_count

    def _split_page(self, page: Dict[str, any], chunk_size: int = 300, chunk_overlap: int = 50) -> List[Dict[str, any]]:
        """将单页文本分块，保留原始markdown表格。"""
        text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            model_name="gpt-4o",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        chunks = text_splitter.split_text(page['text'])
        chunks_with_meta = []
        for chunk in chunks:
            chunks_with_meta.append({
                "page": page['page'],
                "length_tokens": self.count_tokens(chunk),
                "text": chunk
            })
        return chunks_with_meta

    #对 json 文件分块，输出还是 json
    def split_all_reports(self, all_report_dir: Path, output_dir: Path, serialized_tables_dir: Optional[Path] = None):
        """
        批量处理目录下所有报告（json文件），对每个报告进行文本分块，并输出到目标目录。
        如果提供了序列化表格目录，会尝试将表格内容插入到对应页面的分块中。
        主要用于后续向量化和检索的预处理。
        参数：
            all_report_dir: 存放待处理报告json的目录
            output_dir: 分块后输出的目标目录
            serialized_tables_dir: （可选）存放序列化表格的目录
        """
        # 获取所有报告文件路径
        all_report_paths = list(all_report_dir.glob("*.json"))
        
        # 遍历每个报告文件
        for report_path in all_report_paths:
            serialized_tables_path = None
            # 如果提供了表格序列化目录，查找对应表格文件
            if serialized_tables_dir is not None:
                serialized_tables_path = serialized_tables_dir / report_path.name
                if not serialized_tables_path.exists():
                    print(f"警告：未找到 {report_path.name} 的序列化表格报告")
                
            # 读取报告内容
            with open(report_path, 'r', encoding='utf-8') as file:
                report_data = json.load(file)
                
            # 分块处理，插入表格分块（如有）
            updated_report = self._split_report(report_data, serialized_tables_path)
            # 确保输出目录存在
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # 写入分块后的报告到目标目录
            with open(output_dir / report_path.name, 'w', encoding='utf-8') as file:
                json.dump(updated_report, file, indent=2, ensure_ascii=False)
                
        # 输出处理文件数统计
        print(f"已分块处理 {len(all_report_paths)} 个文件")

    def split_markdown_file(self, md_path: Path, chunk_size: int = 30, chunk_overlap: int = 5):
        """
        按行分割 markdown 文件，每个分块记录起止行号、内容和页码。
        识别 "# Page N" 标记，为每个 chunk 添加 page 字段。
        在页面边界处强制断开，确保 chunk 不跨页。
        :param md_path: markdown 文件路径
        :param chunk_size: 每个分块的最大行数
        :param chunk_overlap: 分块重叠行数
        :return: (分块列表, 行列表, 行页码列表)
        """
        import re
        with open(md_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 预处理：为每一行确定所属页码
        page_pattern = re.compile(r'^#\s+Page\s+(\d+)\s*$')
        line_pages = []  # 每行对应的页码
        current_page = 0
        for line in lines:
            match = page_pattern.match(line.strip())
            if match:
                current_page = int(match.group(1))
            line_pages.append(current_page)

        # 按页面边界分组：将所有行分成若干"页面段"，每段内行都属于同一页
        page_groups = []  # [(page_number, group_start, group_end), ...]
        if line_pages:
            group_start = 0
            group_page = line_pages[0]
            for i in range(1, len(line_pages)):
                if line_pages[i] != group_page and line_pages[i] > 0:
                    page_groups.append((group_page, group_start, i))
                    group_start = i
                    group_page = line_pages[i]
            page_groups.append((group_page, group_start, len(line_pages)))

        # 在每个页面段内部进行分块（不跨页）
        chunks = []
        for page_num, g_start, g_end in page_groups:
            group_lines = lines[g_start:g_end]
            group_len = len(group_lines)
            if group_len == 0:
                continue
            i = 0
            while i < group_len:
                start = i
                end = min(i + chunk_size, group_len)
                chunk_text = ''.join(group_lines[start:end])
                chunks.append({
                    'lines': [g_start + start + 1, g_start + end],  # 行号从1开始
                    'text': chunk_text,
                    'page': page_num
                })
                if end >= group_len:
                    break
                i += chunk_size - chunk_overlap

        return chunks, lines, line_pages

    def _extract_pages_from_chunks(self, chunks: list) -> list:
        """
        从 chunks 中提取去重的 pages 列表，每个 page 包含页码和该页所有文本合并后的内容。
        用于父文档检索（return_parent_pages）。
        :param chunks: 分块列表
        :return: pages 列表，格式 [{"page": 1, "text": "..."}, ...]
        """
        page_texts = {}
        for chunk in chunks:
            page = chunk.get('page', 0)
            if page == 0:
                continue
            if page not in page_texts:
                page_texts[page] = []
            page_texts[page].append(chunk.get('text', ''))
        pages = []
        for page_num in sorted(page_texts.keys()):
            pages.append({
                'page': page_num,
                'text': '\n'.join(page_texts[page_num])
            })
        return pages

    def _extract_pages_from_lines(self, lines: list, line_pages: list) -> list:
        """
        直接按行号-页码映射提取每页文本，避免跨页chunk导致的内容串页问题。
        :param lines: markdown 文件的所有行（含换行符）
        :param line_pages: 每行对应的页码列表
        :return: pages 列表，格式 [{"page": 1, "text": "..."}, ...]
        """
        page_texts = {}
        for i, page in enumerate(line_pages):
            if page <= 0:
                continue
            if page not in page_texts:
                page_texts[page] = []
            page_texts[page].append(lines[i])

        pages = []
        for page_num in sorted(page_texts.keys()):
            pages.append({
                'page': page_num,
                'text': ''.join(page_texts[page_num]).strip()
            })
        return pages

    def split_markdown_reports(self, all_md_dir: Path, output_dir: Path, chunk_size: int = 30, chunk_overlap: int = 5, subset_csv: Path = None):
        """
        批量处理目录下所有 markdown 文件，分块并输出为 json 文件到目标目录。
        :param all_md_dir: 存放 .md 文件的目录
        :param output_dir: 输出 .json 文件的目录
        :param chunk_size: 每个分块的最大行数
        :param chunk_overlap: 分块重叠行数
        :param subset_csv: subset.csv 路径，用于建立 file_name 到 company_name 的映射
        """
        # 建立 file_name（去扩展名）到 company_name 的映射
        file2company = {}
        file2sha1 = {}
        if subset_csv is not None and os.path.exists(subset_csv):
            # 优先尝试 utf-8，失败则尝试 gbk
            try:
                df = pd.read_csv(subset_csv, encoding='utf-8')
            except UnicodeDecodeError:
                print('警告：subset.csv 不是 utf-8 编码，自动尝试 gbk 编码...')
                df = pd.read_csv(subset_csv, encoding='gbk')
            # 自动识别主键列
            if 'file_name' in df.columns:
                for _, row in df.iterrows():
                    file_no_ext = os.path.splitext(str(row['file_name']))[0]
                    file2company[file_no_ext] = row['company_name']
                    if 'sha1' in row:
                        file2sha1[file_no_ext] = row['sha1']
            elif 'sha1' in df.columns:
                for _, row in df.iterrows():
                    file_no_ext = str(row['sha1'])
                    file2company[file_no_ext] = row['company_name']
                    file2sha1[file_no_ext] = row['sha1']
            else:
                raise ValueError('subset.csv 缺少 file_name 或 sha1 列，无法建立文件名到公司名的映射')
        
        all_md_paths = list(all_md_dir.glob("*.md"))
        output_dir.mkdir(parents=True, exist_ok=True)
        for md_path in all_md_paths:
            chunks, lines, line_pages = self.split_markdown_file(md_path, chunk_size, chunk_overlap)
            output_json_path = output_dir / (md_path.stem + ".json")
            # 查找 company_name 和 sha1
            file_no_ext = md_path.stem
            company_name = file2company.get(file_no_ext, "")
            sha1 = file2sha1.get(file_no_ext, "")
            # metainfo 只保留 sha1、company_name、file_name 字段
            metainfo = {"sha1": sha1, "company_name": company_name, "file_name": md_path.name}
            # 直接从行级页码映射提取 pages，避免跨页chunk导致的内容串页
            pages = self._extract_pages_from_lines(lines, line_pages)
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump({"metainfo": metainfo, "content": {"pages": pages, "chunks": chunks}}, f, ensure_ascii=False, indent=2)
            print(f"已处理: {md_path.name} -> {output_json_path.name}")
        print(f"共分割 {len(all_md_paths)} 个 markdown 文件")
