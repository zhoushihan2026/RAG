import json
import tiktoken
import re
from pathlib import Path
from typing import List, Dict, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
import pandas as pd
import os
from src.constants import (KNOWN_BROKERS, DOC_TYPE_KEYWORDS, CHUNK_CONFIG_BY_DOC_TYPE,
                           DEFAULT_CHUNK_CONFIG, DEFAULT_INDUSTRY)


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

    def _identify_indivisible_blocks(self, lines: List[str]) -> List[tuple]:
        """
        识别不可分割的行块，返回每个不可分割块的 (start_line, end_line) 列表。
        包括：
        1. Markdown 管道表格（连续的 |...| 行，含分隔行 |---|）
        2. <table>...</table> 块
        3. <details>...</details> 块
        """
        blocks = []
        i = 0
        total = len(lines)

        while i < total:
            stripped = lines[i].strip()

            # 识别 <table>...</table> 块
            if stripped.startswith('<table'):
                table_start = i
                # 查找 </table>
                j = i + 1
                while j < total:
                    if '</table>' in lines[j]:
                        blocks.append((table_start, j + 1))
                        i = j + 1
                        break
                    j += 1
                else:
                    # 未找到 </table>，将单行视为不可分割
                    blocks.append((table_start, table_start + 1))
                    i = table_start + 1
                continue

            # 识别 <details>...</details> 块
            if stripped.startswith('<details'):
                details_start = i
                j = i + 1
                while j < total:
                    if '</details>' in lines[j]:
                        blocks.append((details_start, j + 1))
                        i = j + 1
                        break
                    j += 1
                else:
                    # 未找到 </details>，将单行视为不可分割
                    blocks.append((details_start, details_start + 1))
                    i = details_start + 1
                continue

            # 识别 Markdown 管道表格
            # 管道表格行特征：以 | 开头（允许前面有空格）
            if re.match(r'^\s*\|', stripped) and '|' in stripped[1:]:
                table_start = i
                j = i + 1
                while j < total:
                    line_stripped = lines[j].strip()
                    # 管道表格行必须包含 | 分隔
                    if re.match(r'^\s*\|', line_stripped) and '|' in line_stripped[1:]:
                        j += 1
                    else:
                        break
                # 整个管道表格是一个不可分割块
                blocks.append((table_start, j))
                i = j
                continue

            i += 1

        return blocks

    def _identify_qa_blocks(self, lines: List[str]) -> List[tuple]:
        """
        识别调研纪要中的Q&A对，返回每个Q&A块的 (start_line, end_line) 列表。
        Q&A对以 **问：** 或 **问:** 开头，以 **答：** 或 **答:** 开始回答部分，
        直到下一个 **问：** 或文件末尾结束。
        """
        blocks = []
        i = 0
        total = len(lines)
        in_answer = False
        qa_start = -1

        while i < total:
            stripped = lines[i].strip()

            if re.match(r'^\*\*问[：:]\*\*', stripped):
                if qa_start >= 0 and in_answer:
                    blocks.append((qa_start, i))
                qa_start = i
                in_answer = False
            elif re.match(r'^\*\*答[：:]\*\*', stripped):
                in_answer = True

            i += 1

        if qa_start >= 0 and in_answer:
            blocks.append((qa_start, total))

        return blocks

    def _extract_broker(self, file_name: str) -> str:
        """从文件名中提取券商名"""
        for broker in sorted(KNOWN_BROKERS, key=len, reverse=True):
            if broker in file_name:
                return broker
        return ""

    def _extract_date(self, file_name: str) -> str:
        """从文件名中提取发布日期"""
        match = re.search(r'(20\d{2})', file_name)
        if match:
            return match.group(1)
        return ""

    def _extract_quarter(self, file_name: str) -> str:
        """从文件名中提取季度信息"""
        match = re.search(r'(20\d{2})年[一二三四]季度', file_name)
        if match:
            year = match.group(1)
            quarter_map = {'一': 'Q1', '二': 'Q2', '三': 'Q3', '四': 'Q4'}
            quarter_char = re.search(r'[一二三四]', match.group()).group()
            return f"{year}{quarter_map.get(quarter_char, '')}"
        match = re.search(r'(20\d{2})Q([1-4])', file_name)
        if match:
            return f"{match.group(1)}Q{match.group(2)}"
        return ""

    def _is_in_indivisible_block(self, line_idx: int, blocks: List[tuple]) -> Optional[tuple]:
        """检查某行是否属于某个不可分割块，如果是则返回该块的 (start, end)"""
        for start, end in blocks:
            if start <= line_idx < end:
                return (start, end)
        return None

    def _find_overlap_start(self, lines: List[str], current_pos: int, chunk_start: int,
                             encoding, chunk_overlap: int,
                             indivisible_blocks: List[tuple] = None) -> int:
        """
        从 current_pos 向前回溯，找到 overlap 的起始位置。
        返回新 chunk 应该开始的行索引。
        如果回溯距离不足则直接从 current_pos 开始。
        如果提供了 indivisible_blocks，回溯不会进入不可分割块内部，
        遇到块边界时停止在块起始位置之前。
        """
        overlap_tokens = 0
        ov_pos = current_pos
        while ov_pos > chunk_start and overlap_tokens < chunk_overlap:
            next_pos = ov_pos - 1
            # 检查下一行是否属于不可分割块内部
            if indivisible_blocks:
                blocked = False
                for b_s, b_e in indivisible_blocks:
                    # next_pos 落在块内部或正好是块开头 -> 阻止进入
                    if b_s <= next_pos < b_e:
                        # 停止在当前 ov_pos（即块开头之后，不包含块内容）
                        return ov_pos
                if blocked:
                    break
            ov_pos = next_pos
            overlap_tokens += len(encoding.encode(lines[ov_pos]))
        return ov_pos

    def split_markdown_file(self, md_path: Path, chunk_size: int = 300, chunk_overlap: int = 50,
                            external_indivisible_blocks: List[tuple] = None):
        """
        按 token 分割 markdown 文件，严格控制在约 chunk_size tokens/chunk。

        核心策略：
        1. 逐行累积 token，达到 ~chunk_size 时输出一个 chunk
        2. 遇到不可分割块（表格、<table>、<details>、Q&A对）时特殊处理：
           - 若 当前已累积文本 + 表格 <= chunk_size * 1.3：合并为一个 chunk
           - 若 表格本身 <= chunk_size：先输出当前文本，表格单独成 chunk
           - 若 表格本身 > chunk_size：先输出当前文本，大表格单独成 chunk
        3. 相邻 chunk 之间有 chunk_overlap tokens 重叠
        4. 不跨页分块

        :param md_path: markdown 文件路径
        :param chunk_size: 每个分块的目标 token 数（约值，允许小幅超出以保证完整性）
        :param chunk_overlap: 分块重叠 token 数
        :param external_indivisible_blocks: 外部传入的不可分割块（如Q&A对），
               格式为 [(start_line, end_line), ...]，行号从0开始
        :return: (分块列表, 行列表, 行页码列表)
        """
        with open(md_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        encoding = tiktoken.get_encoding("o200k_base")

        # 预处理：为每一行确定所属页码
        page_pattern = re.compile(r'^#\s+Page\s+(\d+)\s*$')
        line_pages = []
        current_page = 0
        for line in lines:
            match = page_pattern.match(line.strip())
            if match:
                current_page = int(match.group(1))
            line_pages.append(current_page)

        # 按页面边界分组
        page_groups = []
        if line_pages:
            group_start = 0
            group_page = line_pages[0]
            for i in range(1, len(line_pages)):
                if line_pages[i] != group_page and line_pages[i] > 0:
                    page_groups.append((group_page, group_start, i))
                    group_start = i
                    group_page = line_pages[i]
            page_groups.append((group_page, group_start, len(line_pages)))

        chunks = []

        for page_num, g_start, g_end in page_groups:
            group_lines = lines[g_start:g_end]
            glen = len(group_lines)
            if glen == 0:
                continue

            # 识别不可分割块
            indivisible_blocks = self._identify_indivisible_blocks(group_lines)

            # 合并外部传入的不可分割块（如Q&A对），转换为group内相对行号
            if external_indivisible_blocks:
                for ext_start, ext_end in external_indivisible_blocks:
                    if ext_start >= g_start and ext_start < g_end:
                        rel_start = ext_start - g_start
                        rel_end = min(ext_end, g_end) - g_start
                        if rel_end > rel_start:
                            indivisible_blocks.append((rel_start, rel_end))
                # 去重并排序
                indivisible_blocks = sorted(set(indivisible_blocks), key=lambda x: x[0])

            # 主循环：逐行/逐块累积
            chunk_start = 0      # 当前 chunk 在 group_lines 中的起始位置
            chunk_tokens = 0     # 当前 chunk 已累积的 token 数
            i = 0

            while i < glen:
                # 检查当前位置是否属于不可分割块
                block_range = self._is_in_indivisible_block(i, indivisible_blocks)

                if block_range:
                    b_start, b_end = block_range
                    block_text = ''.join(group_lines[b_start:b_end])
                    block_tokens = len(encoding.encode(block_text))

                    # === 处理不可分割块 ===

                    if chunk_tokens > 0:
                        # 当前 chunk 已有内容，需要决定如何处理这个块
                        combined = chunk_tokens + block_tokens

                        if combined <= chunk_size * 1.3:
                            # 场景A：小表格，可以和前面的文字合在一起
                            # 直接加入当前 chunk，稍后统一输出
                            pass  # 下面会正常加入并检查是否超限
                        elif block_tokens <= chunk_size:
                            # 场景B：中等表格，单独成 chunk
                            # 先输出前面累积的文字
                            text_before = ''.join(group_lines[chunk_start:i])
                            if text_before.strip():
                                chunks.append({
                                    'lines': [g_start + chunk_start + 1, g_start + i],
                                    'text': text_before,
                                    'page': page_num
                                })
                            # 表格单独成 chunk
                            chunks.append({
                                'lines': [g_start + b_start + 1, g_start + b_end],
                                'text': block_text,
                                'page': page_num
                            })
                            # 新 chunk 从表格后开始（无 overlap 到表格内部）
                            chunk_start = b_end
                            chunk_tokens = 0
                            i = b_end
                            continue
                        else:
                            # 场景C：大表格（> chunk_size），必须单独成 chunk
                            # 先输出前面累积的文字
                            text_before = ''.join(group_lines[chunk_start:i])
                            if text_before.strip():
                                chunks.append({
                                    'lines': [g_start + chunk_start + 1, g_start + i],
                                    'text': text_before,
                                    'page': page_num
                                })
                            # 大表格单独成 chunk
                            chunks.append({
                                'lines': [g_start + b_start + 1, g_start + b_end],
                                'text': block_text,
                                'page': page_num
                            })
                            chunk_start = b_end
                            chunk_tokens = 0
                            i = b_end
                            continue
                    else:
                        # 当前 chunk 为空，表格作为第一个内容
                        chunks.append({
                            'lines': [g_start + b_start + 1, g_start + b_end],
                            'text': block_text,
                            'page': page_num
                        })
                        chunk_start = b_end
                        chunk_tokens = 0
                        i = b_end
                        continue

                    # 场景A：将小表格加入当前 chunk
                    chunk_tokens += block_tokens
                    i = b_end

                    # 加入后检查是否需要输出
                    if chunk_tokens >= chunk_size:
                        text_out = ''.join(group_lines[chunk_start:i])
                        if text_out.strip():
                            chunks.append({
                                'lines': [g_start + chunk_start + 1, g_start + i],
                                'text': text_out,
                                'page': page_num
                            })
                        # 新 chunk 带 overlap（不进入表格内部）
                        new_start = self._find_overlap_start(
                            group_lines, i, chunk_start, encoding, chunk_overlap,
                            indivisible_blocks
                        )
                        chunk_start = new_start
                        chunk_tokens = len(encoding.encode(''.join(group_lines[new_start:i])))
                    continue

                # === 处理普通行 ===
                line_tokens = len(encoding.encode(group_lines[i]))

                # 检查加入此行后是否超限
                if chunk_tokens > 0 and chunk_tokens + line_tokens > chunk_size:
                    # 达到上限，先输出当前 chunk
                    text_out = ''.join(group_lines[chunk_start:i])
                    if text_out.strip():
                        chunks.append({
                            'lines': [g_start + chunk_start + 1, g_start + i],
                            'text': text_out,
                            'page': page_num
                        })
                    # 新 chunk 从 overlap 位置开始
                    new_start = self._find_overlap_start(
                        group_lines, i, chunk_start, encoding, chunk_overlap,
                        indivisible_blocks
                    )
                    chunk_start = new_start
                    chunk_tokens = len(encoding.encode(''.join(group_lines[new_start:i])))

                # 加入当前行
                if chunk_tokens == 0:
                    chunk_start = i
                chunk_tokens += line_tokens
                i += 1

            # 处理页面末尾剩余内容
            if chunk_start < glen:
                text_tail = ''.join(group_lines[chunk_start:glen])
                if text_tail.strip():
                    # 避免与最后一个 chunk 完全重复
                    last_text = chunks[-1]['text'] if chunks else ""
                    if text_tail != last_text:
                        chunks.append({
                            'lines': [g_start + chunk_start + 1, g_start + glen],
                            'text': text_tail,
                            'page': page_num
                        })

        # 轻度后处理：仅合并极小的碎片 chunk（< 20 tokens），如 "---\n\n"
        chunks = self._merge_tiny_fragments(chunks)

        return chunks, lines, line_pages

    def _merge_tiny_fragments(self, chunks: list) -> list:
        """
        仅合并极小碎片（< 20 tokens）到前一个 chunk 中。
        这类碎片通常是分隔符 "---\n\n" 或空标题行等，
        合并它们不会导致 chunk 过大。
        """
        if len(chunks) <= 1:
            return chunks

        encoding = tiktoken.get_encoding("o200k_base")
        TINY_LIMIT = 20

        merged = [chunks[0]]
        for i in range(1, len(chunks)):
            curr = chunks[i]
            curr_toks = len(encoding.encode(curr['text']))
            if curr_toks < TINY_LIMIT:
                prev = merged[-1]
                prev['text'] = prev['text'] + '\n' + curr['text']
                prev['lines'][1] = curr['lines'][1]
            else:
                merged.append(curr)
        return merged

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

    def split_markdown_reports(self, all_md_dir: Path, output_dir: Path, chunk_size: int = 300, chunk_overlap: int = 50, subset_csv: Path = None):
        """
        批量处理目录下所有 markdown 文件，按文档类型差异化分块并输出为 json 文件。
        """
        # 建立 file_name（去扩展名）到 company_name、broker、sha1、coverage_start、coverage_end、doc_type、industry 的映射
        file2company = {}
        file2sha1 = {}
        file2broker = {}
        file2coverage_start = {}
        file2coverage_end = {}
        file2doc_type_from_csv = {}
        file2industry = {}
        if subset_csv is not None and os.path.exists(subset_csv):
            try:
                df = pd.read_csv(subset_csv, encoding='utf-8-sig')
            except UnicodeDecodeError:
                try:
                    df = pd.read_csv(subset_csv, encoding='utf-8')
                except UnicodeDecodeError:
                    print('警告：subset.csv 不是 utf-8 编码，自动尝试 gbk 编码...')
                    df = pd.read_csv(subset_csv, encoding='gbk')
            if 'file_name' in df.columns:
                for _, row in df.iterrows():
                    file_no_ext = os.path.splitext(str(row['file_name']))[0]
                    file2company[file_no_ext] = row['company_name']
                    if 'sha1' in row:
                        file2sha1[file_no_ext] = row['sha1']
                    if 'broker' in row and pd.notna(row.get('broker')):
                        file2broker[file_no_ext] = str(row['broker']).strip()
                    if 'coverage_start' in row and pd.notna(row.get('coverage_start')):
                        file2coverage_start[file_no_ext] = str(row['coverage_start']).strip()
                    if 'coverage_end' in row and pd.notna(row.get('coverage_end')):
                        file2coverage_end[file_no_ext] = str(row['coverage_end']).strip()
                    if 'doc_type' in row and pd.notna(row.get('doc_type')):
                        file2doc_type_from_csv[file_no_ext] = str(row['doc_type']).strip()
                    if 'industry' in row and pd.notna(row.get('industry')):
                        file2industry[file_no_ext] = str(row['industry']).strip()
            elif 'sha1' in df.columns:
                for _, row in df.iterrows():
                    file_no_ext = str(row['sha1'])
                    file2company[file_no_ext] = row['company_name']
                    file2sha1[file_no_ext] = row['sha1']
                    if 'broker' in row and pd.notna(row.get('broker')):
                        file2broker[file_no_ext] = str(row['broker']).strip()
                    if 'coverage_start' in row and pd.notna(row.get('coverage_start')):
                        file2coverage_start[file_no_ext] = str(row['coverage_start']).strip()
                    if 'coverage_end' in row and pd.notna(row.get('coverage_end')):
                        file2coverage_end[file_no_ext] = str(row['coverage_end']).strip()
                    if 'doc_type' in row and pd.notna(row.get('doc_type')):
                        file2doc_type_from_csv[file_no_ext] = str(row['doc_type']).strip()
                    if 'industry' in row and pd.notna(row.get('industry')):
                        file2industry[file_no_ext] = str(row['industry']).strip()
            else:
                raise ValueError('subset.csv 缺少 file_name 或 sha1 列，无法建立文件名到公司名的映射')

        all_md_paths = list(all_md_dir.glob("*.md"))
        output_dir.mkdir(parents=True, exist_ok=True)

        for md_path in all_md_paths:
            base_name = md_path.stem

            # ========== 文档类型识别 ==========
            doc_type = "unknown"
            for dtype, keywords in DOC_TYPE_KEYWORDS.items():
                if any(kw in base_name for kw in keywords):
                    doc_type = dtype
                    break

            # 根据文档类型获取分块参数
            chunk_cfg = CHUNK_CONFIG_BY_DOC_TYPE.get(doc_type, DEFAULT_CHUNK_CONFIG)
            actual_chunk_size = chunk_cfg["chunk_size"]
            actual_chunk_overlap = chunk_cfg["chunk_overlap"]

            # ========== 调研纪要：预识别 Q&A 对 ==========
            if doc_type == "调研纪要":
                with open(md_path, 'r', encoding='utf-8') as f:
                    file_lines = f.readlines()
                qa_blocks = self._identify_qa_blocks(file_lines)
            else:
                qa_blocks = None

            # ========== 分块 ==========
            chunks, lines, line_pages = self.split_markdown_file(
                md_path, actual_chunk_size, actual_chunk_overlap,
                external_indivisible_blocks=qa_blocks
            )

            # ========== 附加元数据到每个 chunk ==========
            company_name = file2company.get(base_name, "")
            broker_from_csv = file2broker.get(base_name, "")
            coverage_start = file2coverage_start.get(base_name, "")
            coverage_end = file2coverage_end.get(base_name, "")
            doc_type_from_csv = file2doc_type_from_csv.get(base_name, "")
            # 优先使用CSV中的doc_type，如果没有则使用自动识别的
            final_doc_type = doc_type_from_csv if doc_type_from_csv else doc_type
            for chunk in chunks:
                chunk["company"] = company_name
                chunk["doc_type"] = final_doc_type
                chunk["broker"] = broker_from_csv if broker_from_csv else self._extract_broker(base_name)
                chunk["publish_date"] = self._extract_date(base_name)
                chunk["quarter"] = self._extract_quarter(base_name)
                chunk["coverage_start"] = coverage_start
                chunk["coverage_end"] = coverage_end
                chunk["industry"] = file2industry.get(base_name, DEFAULT_INDUSTRY)
                chunk["source_file"] = md_path.name

            # ========== 输出 ==========
            output_json_path = output_dir / (md_path.stem + ".json")
            sha1 = file2sha1.get(base_name, "")
            metainfo = {"sha1": sha1, "company_name": company_name, "file_name": md_path.name}
            pages = self._extract_pages_from_lines(lines, line_pages)
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump({"metainfo": metainfo, "content": {"pages": pages, "chunks": chunks}},
                          f, ensure_ascii=False, indent=2)
            print(f"已处理: {md_path.name} -> {output_json_path.name}  |  doc_type={doc_type}  |  chunks={len(chunks)}")
        print(f"共分割 {len(all_md_paths)} 个 markdown 文件")


# 独立运行：分块 + 创建向量库
if __name__ == "__main__":
    from pyprojroot import here
    from src.ingestion import VectorDBIngestor

    root_path = here() / "data" / "stock_data"
    reports_markdown_path = root_path / "debug_data" / "02_reports_markdown"
    chunked_reports_path = root_path / "databases" / "chunked_reports"
    vector_db_path = root_path / "databases" / "vector_dbs"
    subset_csv_path = root_path / "subset.csv"

    # 步骤1：分块
    print("=" * 60)
    print("步骤1：按 token 分块（chunk_size=300, chunk_overlap=50）...")
    print("=" * 60)
    splitter = TextSplitter()
    splitter.split_markdown_reports(
        all_md_dir=reports_markdown_path,
        output_dir=chunked_reports_path,
        chunk_size=300,
        chunk_overlap=50,
        subset_csv=subset_csv_path
    )

    # 步骤2：创建向量数据库
    print("=" * 60)
    print("步骤2：创建向量数据库...")
    print("=" * 60)
    vdb_ingestor = VectorDBIngestor()
    vdb_ingestor.process_reports(chunked_reports_path, vector_db_path)
    print(f"向量数据库已保存到 {vector_db_path}")

    print("完成!")
