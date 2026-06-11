import json
from typing import Union, Dict, List, Optional
import re
from pathlib import Path
from src.retrieval import (VectorRetriever, BM25Retriever, HybridRetriever,
                           HybridBM25VectorRetriever, MetadataFilteredRetriever)
from src.api_requests import APIProcessor
from src import prompts
from src.constants import KNOWN_BROKERS
from tqdm import tqdm
import pandas as pd
import threading
import concurrent.futures
import time
import datetime


def _parse_question_time(question_text: str):
    """从问题文本中提取时间范围，返回 (start_date, end_date)"""
    import datetime

    # 匹配 "2025年一季度"、"2024年四季度" 等
    quarter_match = re.search(r'(20\d{2})年[一二三四]季度', question_text)
    if quarter_match:
        year = int(quarter_match.group(1))
        quarter_map = {'一': 1, '二': 2, '三': 3, '四': 4}
        quarter_char = re.search(r'[一二三四]', quarter_match.group()).group()
        quarter = quarter_map.get(quarter_char, 1)
        # 计算季度起始和结束月份
        start_month = (quarter - 1) * 3 + 1
        end_month = quarter * 3
        start_date = datetime.date(year, start_month, 1)
        # 计算月末日期
        if end_month == 12:
            end_date = datetime.date(year, 12, 31)
        else:
            end_date = datetime.date(year, end_month + 1, 1) - datetime.timedelta(days=1)
        return start_date, end_date

    # 匹配 "2024年"（整年）
    year_match = re.search(r'(20\d{2})年', question_text)
    if year_match:
        year = int(year_match.group(1))
        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 12, 31)
        return start_date, end_date

    return None, None


def _check_time_coverage(companies_df: pd.DataFrame, question_start: datetime.date,
                         question_end: datetime.date, doc_type: str) -> bool:
    """
    检查指定doc_type的文档是否能覆盖问题的时间范围。
    返回 True 如果该doc_type能覆盖，False 如果不能覆盖。
    """
    if companies_df is None or 'coverage_start' not in companies_df.columns:
        return True  # 没有时间信息，默认可以覆盖

    import datetime

    # 筛选指定doc_type的文档
    type_docs = companies_df[companies_df.get('doc_type', '') == doc_type]
    if type_docs.empty:
        return True  # 该类型文档不存在，不限制

    for _, row in type_docs.iterrows():
        try:
            if pd.notna(row.get('coverage_start')) and pd.notna(row.get('coverage_end')):
                doc_start = datetime.datetime.strptime(str(row['coverage_start']), '%Y-%m-%d').date()
                doc_end = datetime.datetime.strptime(str(row['coverage_end']), '%Y-%m-%d').date()
                # 如果文档时间范围与问题时间范围有重叠，则认为可以覆盖
                if doc_start <= question_end and doc_end >= question_start:
                    return True
        except (ValueError, TypeError):
            continue

    return False  # 该doc_type没有任何文档能覆盖问题时间范围


def build_metadata_filters(question_text: str, companies_df: pd.DataFrame,
                           rewrite_result: dict, question_source: str = "") -> tuple:
    """
    根据问题文本和LLM重写结果，构建元数据过滤条件。
    返回: (rewritten_query, metadata_filters)

    策略：
    1. 始终提取 company（被分析公司）
    2. 优先从 question_source 解析券商名；若没有则从问题文本推断
    3. 优先从 question_source 解析 doc_type；若没有则由 LLM 推断
    """
    rewritten_query = rewrite_result.get("rewritten_query", question_text)
    doc_type = rewrite_result.get("doc_type")

    filters = {}

    # 提取被分析公司名（排除券商名干扰）
    clean_question = question_text
    for broker in sorted(KNOWN_BROKERS, key=len, reverse=True):
        clean_question = clean_question.replace(broker, '')

    if companies_df is not None:
        company_names = sorted(companies_df['company_name'].unique(), key=len, reverse=True)
        for company in company_names:
            if company in clean_question:
                filters["company"] = company
                break

    # 从 question_source 中解析券商名和文档类型
    source_broker = None
    source_doc_type = None
    if question_source:
        bracket_match = re.match(r'【([^】]+)】', question_source)
        if bracket_match:
            bracket_content = bracket_match.group(1)
            if bracket_content == "财报":
                source_doc_type = "年报"
                print(f"[元数据过滤] 从source解析: doc_type=年报 (财报)")
            elif bracket_content in KNOWN_BROKERS:
                source_broker = bracket_content
                source_doc_type = "券商研报"
                print(f"[元数据过滤] 从source解析: broker={source_broker}, doc_type=券商研报")
        elif "调研纪要" in question_source:
            source_doc_type = "调研纪要"
            print(f"[元数据过滤] 从source解析: doc_type=调研纪要")

    # 券商过滤：优先使用从 source 解析到的券商名，其次从问题文本推断
    specified_broker = None
    if source_broker:
        filters["broker"] = source_broker
        specified_broker = source_broker
        print(f"[元数据过滤] 使用source中的券商: {source_broker}")
    else:
        for broker in sorted(KNOWN_BROKERS, key=len, reverse=True):
            if broker in question_text:
                filters["broker"] = broker
                specified_broker = broker
                break

    # 文档类型过滤：优先使用 source 解析结果，其次使用 LLM 推断
    if source_doc_type:
        doc_type = source_doc_type
        print(f"[元数据过滤] 使用source中的doc_type: {doc_type}")

    # 文档类型过滤策略：
    # - source字段明确标注的doc_type：硬过滤（确定性高）
    # - LLM推断的doc_type：仅软加权（不确定性高，避免误排除）
    if doc_type and doc_type in ("年报", "券商研报", "调研纪要"):
        if source_doc_type:
            filters["doc_type"] = doc_type
            print(f"[元数据过滤] doc_type={doc_type}（source标注，硬过滤）")
        else:
            filters["soft_doc_type"] = doc_type
            print(f"[元数据过滤] doc_type={doc_type}（LLM推断，仅软加权）")

    return rewritten_query, filters


# ========== 多轮对话相关工具函数 ==========


def extract_company_from_history(history_messages: list[dict], companies_df) -> str | None:
    """
    从历史消息中提取公司名称。
    当当前问题中无法提取到公司名时，回退到历史消息中查找。

    参数：
        history_messages: 对话历史消息列表
        companies_df: subset.csv 的 DataFrame，包含 company_name 列
    返回：
        找到的公司名，或 None
    """
    if not history_messages or companies_df is None:
        return None

    company_names = sorted(companies_df['company_name'].unique(), key=len, reverse=True)
    # 已知券商名，排除干扰

    # 遍历历史中的用户消息（从最近到最早），找到第一个包含公司名的
    user_msgs = [m for m in history_messages if m["role"] == "user"]
    for msg in reversed(user_msgs):
        clean_text = msg["content"]
        for broker in sorted(KNOWN_BROKERS, key=len, reverse=True):
            clean_text = clean_text.replace(broker, '')
        for company in company_names:
            if company in clean_text:
                return company
    return None

# 中文停用词集合，用于追问关键词扩展时过滤无意义词
FOLLOWUP_STOPWORDS = {
    "是", "多少", "有", "了", "在", "和", "与", "或", "及", "等", "中", "为",
    "到", "从", "被", "把", "让", "向", "对", "这", "那", "一", "个", "不",
    "也", "都", "还", "又", "就", "才", "已", "所", "其", "之", "而", "则",
    "且", "但", "如", "若", "因", "故", "会", "能", "可", "要", "将", "上",
    "下", "里", "外", "前", "后", "时", "年", "月", "日",
}


def expand_followup_query(rewritten_query: str, history_messages: list[dict]) -> str:
    """
    追问场景：将前一轮用户问题的核心词合并到检索查询中，扩大召回范围。
    解决追问"同比下降的原因"时检索不到相关文档的问题。

    参数：
        rewritten_query: 当前重写后的检索查询
        history_messages: 对话历史消息列表
    返回：
        扩展后的检索查询
    """
    import re

    if not history_messages:
        return rewritten_query

    prev_user_msgs = [m for m in history_messages if m["role"] == "user"]
    if not prev_user_msgs:
        return rewritten_query

    prev_question = prev_user_msgs[-1]["content"]

    # 从前一轮问题中提取有意义的中文词组
    # 使用常见财务/业务指标词表匹配，避免滑动窗口产生碎片
    FINANCIAL_TERMS = {
        "营业收入", "营收", "收入", "净利润", "利润", "毛利率", "净利率",
        "研发费用", "研发投入", "营业成本", "成本", "现金流", "资产负债",
        "产能利用率", "产能", "产量", "销量", "出货量", "产能扩张",
        "折旧", "摊销", "减值", "资产减值", "投资收益",
        "目标价", "评级", "盈利预测", "估值",
        "同比增长", "同比", "环比增长", "环比", "增长", "下降",
        "占比", "比重", "份额", "比例",
        "原因", "因素", "驱动", "影响",
    }

    prev_tokens = set()
    # 1. 匹配已知财务术语（优先长词，避免短词覆盖长词）
    for term in sorted(FINANCIAL_TERMS, key=len, reverse=True):
        if term in prev_question:
            prev_tokens.add(term)

    # 2. 提取数字+单位组合（如"2024年"、"578亿元"）
    for m in re.finditer(r'\d+[年月日季度%％亿元万美元港元]', prev_question):
        prev_tokens.add(m.group())

    # 当前 rewritten_query 中已有的词
    curr_tokens = set(rewritten_query.split())
    # 从 rewritten_query 中也提取中文片段做匹配
    for seg in re.findall(r'[\u4e00-\u9fff]+', rewritten_query):
        for length in (2, 3, 4):
            for i in range(len(seg) - length + 1):
                curr_tokens.add(seg[i:i+length])

    extra_words = prev_tokens - curr_tokens
    # 过滤停用词
    extra_words = {w for w in extra_words if w not in FOLLOWUP_STOPWORDS}
    if extra_words:
        rewritten_query = rewritten_query + " " + " ".join(sorted(extra_words))
        print(f"[追问扩展] 合并前一轮关键词: {extra_words}")

    return rewritten_query


def summarize_history_for_rewrite(history_messages: list[dict], max_rounds: int = 3) -> str:
    """
    将历史消息格式化为问题重写用的摘要。
    只取最近 max_rounds 轮（1轮 = 1个user + 1个assistant）。
    assistant 内容截取前 100 字。

    参数：
        history_messages: 对话历史消息列表
        max_rounds: 保留的最大轮数
    返回：
        格式化的历史摘要文本
    """
    recent = history_messages[-(max_rounds * 2):]
    lines = []
    for msg in recent:
        role_label = "用户" if msg["role"] == "user" else "助手"
        content = msg["content"]
        if role_label == "助手" and len(content) > 100:
            content = content[:100] + "..."
        lines.append(f"{role_label}: {content}")
    return "\n".join(lines)


def parse_llm_json_response(response) -> dict:
    """
    解析 LLM 返回的 JSON 响应。
    支持纯 JSON 字符串和被 ``` 包裹的代码块格式。

    参数：
        response: LLM 返回的响应（str 或 dict）
    返回：
        解析后的字典，解析失败返回空字典
    """
    import json as _json

    if isinstance(response, dict):
        return response

    if isinstance(response, str):
        try:
            resp_str = response.strip()
            if resp_str.startswith("```"):
                resp_str = re.sub(r'^```\w*\n?', '', resp_str)
                resp_str = re.sub(r'\n?```$', '', resp_str)
            return _json.loads(resp_str)
        except (_json.JSONDecodeError, TypeError):
            return {}

    return {}


def parse_classify_result(response) -> str:
    """
    解析问题分类结果。

    参数：
        response: LLM 返回的分类响应
    返回：
        分类字符串：fact_extraction / analysis_explanation / prediction_judgment / string
    """
    result = parse_llm_json_response(response)
    category = result.get("category", "string") if isinstance(result, dict) else "string"
    if category not in ("fact_extraction", "analysis_explanation", "prediction_judgment"):
        category = "string"
    return category


class QuestionsProcessor:
    def __init__(
        self,
        vector_db_dir: Union[str, Path] = './vector_dbs',
        documents_dir: Union[str, Path] = './documents',
        questions_file_path: Optional[Union[str, Path]] = None,
        new_challenge_pipeline: bool = False,
        subset_path: Optional[Union[str, Path]] = None,
        parent_document_retrieval: bool = False,
        use_vector_dbs: bool = True,
        use_bm25_db: bool = False,
        llm_reranking: bool = False,
        llm_reranking_sample_size: int = 5,
        hybrid_bm25_vector: bool = False,
        hybrid_bm25_vector_alpha: float = 0.5,
        hybrid_bm25_vector_recall_n: int = 30,
        bm25_db_dir: Union[str, Path] = None,
        top_n_retrieval: int = 10,
        parallel_requests: int = 10,
        api_provider: str = "dashscope",
        answering_model: str = "deepseek-v4-pro",
        rewrite_model: str = "qwen-turbo",
        full_context: bool = False,
        metadata_path: Optional[Union[str, Path]] = None,
        use_metadata_filter: bool = False
    ):
        # 初始化问题处理器，配置检索、模型、并发等参数
        self.questions = self._load_questions(questions_file_path)
        self.documents_dir = Path(documents_dir)
        self.vector_db_dir = Path(vector_db_dir)
        self.subset_path = Path(subset_path) if subset_path else None
        
        self.new_challenge_pipeline = new_challenge_pipeline
        self.return_parent_pages = parent_document_retrieval
        self.use_vector_dbs = use_vector_dbs
        self.use_bm25_db = use_bm25_db
        self.llm_reranking = llm_reranking
        self.llm_reranking_sample_size = llm_reranking_sample_size
        self.hybrid_bm25_vector = hybrid_bm25_vector
        self.hybrid_bm25_vector_alpha = hybrid_bm25_vector_alpha
        self.hybrid_bm25_vector_recall_n = hybrid_bm25_vector_recall_n
        self.bm25_db_dir = Path(bm25_db_dir) if bm25_db_dir else None
        self.top_n_retrieval = top_n_retrieval
        self.answering_model = answering_model
        self.rewrite_model = rewrite_model
        self.parallel_requests = parallel_requests
        self.api_provider = api_provider
        self.openai_processor = APIProcessor(provider=api_provider)
        self.full_context = full_context
        self.metadata_path = Path(metadata_path) if metadata_path else None
        self.use_metadata_filter = use_metadata_filter

        self.answer_details = []
        self.detail_counter = 0
        self._lock = threading.Lock()

    def _load_questions(self, questions_file_path: Optional[Union[str, Path]]) -> List[Dict[str, str]]:
        # 加载问题文件，返回问题列表
        if questions_file_path is None:
            return []
        with open(questions_file_path, 'r', encoding='utf-8') as file:
            return json.load(file)

    def _format_retrieval_results(self, retrieval_results) -> str:
        """将检索结果格式化为RAG上下文字符串，包含溯源信息"""
        if not retrieval_results:
            return ""
        
        context_parts = []
        for result in retrieval_results:
            page_number = result['page']
            text = result['text']
            source_file = result.get('file_name', '')
            if source_file:
                context_parts.append(f'Text retrieved from page {page_number} of {source_file}: \n"""\n{text}\n"""')
            else:
                context_parts.append(f'Text retrieved from page {page_number}: \n"""\n{text}\n"""')
            
        return "\n\n---\n\n".join(context_parts)

    def _extract_references(self, pages_list: list, company_name: str) -> list:
        # 根据公司名和页码列表，提取引用信息
        if self.subset_path is None:
            raise ValueError("subset_path is required for new challenge pipeline when processing references.")
        # 优先尝试 utf-8，失败则尝试 gbk
        try:
            self.companies_df = pd.read_csv(self.subset_path, encoding='utf-8')
        except UnicodeDecodeError:
            print('警告：subset.csv 不是 utf-8 编码，自动尝试 gbk 编码...')
            self.companies_df = pd.read_csv(self.subset_path, encoding='gbk')

        # Find the company's SHA1 from the subset CSV
        matching_rows = self.companies_df[self.companies_df['company_name'] == company_name]
        if matching_rows.empty:
            company_sha1 = ""
        else:
            company_sha1 = matching_rows.iloc[0]['sha1']

        refs = []
        for page in pages_list:
            refs.append({"pdf_sha1": company_sha1, "page_index": page})
        return refs

    def _validate_page_references(self, claimed_pages: list, retrieval_results: list, min_pages: int = 2, max_pages: int = 8) -> list:
        """
        校验LLM答案中引用的页码是否真实存在于检索结果中。
        若不足最小页数，则补充检索结果中的top页。
        """
        if claimed_pages is None:
            claimed_pages = []
        
        retrieved_pages = [result['page'] for result in retrieval_results]
        
        validated_pages = [page for page in claimed_pages if page in retrieved_pages]
        
        if len(validated_pages) < len(claimed_pages):
            removed_pages = set(claimed_pages) - set(validated_pages)
            print(f"Warning: Removed {len(removed_pages)} hallucinated page references: {removed_pages}")
        
        if len(validated_pages) < min_pages and retrieval_results:
            existing_pages = set(validated_pages)
            
            for result in retrieval_results:
                page = result['page']
                if page not in existing_pages:
                    validated_pages.append(page)
                    existing_pages.add(page)
                    
                    if len(validated_pages) >= min_pages:
                        break
        
        if len(validated_pages) > max_pages:
            print(f"Trimming references from {len(validated_pages)} to {max_pages} pages")
            validated_pages = validated_pages[:max_pages]
        
        return validated_pages

    def get_answer_for_company(self, company_name: str, question: str, schema: str) -> dict:
        # 针对单个公司，检索上下文并调用LLM生成答案
        t0 = time.time()
        # 根据配置选择检索器，优先级：hybrid_bm25_vector > llm_reranking > 单独检索
        if self.hybrid_bm25_vector:
            if not self.use_vector_dbs or not self.use_bm25_db:
                print("警告: hybrid_bm25_vector需要use_vector_dbs和use_bm25_db同时为True，已自动启用")
            retriever = HybridBM25VectorRetriever(
                vector_db_dir=self.vector_db_dir,
                documents_dir=self.documents_dir,
                bm25_db_dir=self.bm25_db_dir,
                alpha=self.hybrid_bm25_vector_alpha
            )
        elif self.llm_reranking:
            if not self.use_vector_dbs:
                print("警告: llm_reranking需要use_vector_dbs为True，已自动启用")
            retriever = HybridRetriever(
                vector_db_dir=self.vector_db_dir,
                documents_dir=self.documents_dir
            )
        elif self.use_vector_dbs and self.use_bm25_db:
            # 同时启用向量检索和BM25检索，但未启用混合检索，默认使用向量检索
            print("提示: 同时启用了use_vector_dbs和use_bm25_db，但未启用hybrid_bm25_vector，默认使用向量检索")
            retriever = VectorRetriever(
                vector_db_dir=self.vector_db_dir,
                documents_dir=self.documents_dir
            )
        elif self.use_bm25_db:
            # 仅使用BM25检索
            retriever = BM25Retriever(
                bm25_db_dir=self.bm25_db_dir,
                documents_dir=self.documents_dir
            )
        elif self.use_vector_dbs:
            # 仅使用向量检索
            retriever = VectorRetriever(
                vector_db_dir=self.vector_db_dir,
                documents_dir=self.documents_dir
            )
        else:
            raise ValueError("至少需要启用一种检索方式: use_vector_dbs 或 use_bm25_db")
        t1 = time.time()
        print(f"[计时] [get_answer_for_company] 检索器初始化耗时: {t1-t0:.2f} 秒")
        if self.full_context:
            retrieval_results = retriever.retrieve_all(company_name)
        else:           
            t2 = time.time()
            if self.hybrid_bm25_vector:
                retrieval_results = retriever.retrieve_by_company_name(
                    company_name=company_name,
                    query=question,
                    top_n=self.top_n_retrieval,
                    recall_n=self.hybrid_bm25_vector_recall_n,
                    return_parent_pages=self.return_parent_pages
                )
            elif self.llm_reranking:
                retrieval_results = retriever.retrieve_by_company_name(
                    company_name=company_name,
                    query=question,
                    llm_reranking_sample_size=self.llm_reranking_sample_size,
                    top_n=self.top_n_retrieval,
                    return_parent_pages=self.return_parent_pages
                )
            else:
                retrieval_results = retriever.retrieve_by_company_name(
                    company_name=company_name,
                    query=question,
                    top_n=self.top_n_retrieval,
                    return_parent_pages=self.return_parent_pages
                )
            t3 = time.time()
            print(f"[计时] [get_answer_for_company] 检索耗时: {t3-t2:.2f} 秒")
        if not retrieval_results:
            raise ValueError("No relevant context found")
        t4 = time.time()
        rag_context = self._format_retrieval_results(retrieval_results)
        t5 = time.time()
        print(f"[计时] [get_answer_for_company] 构建rag_context耗时: {t5-t4:.2f} 秒")
        answer_dict = self.openai_processor.get_answer_from_rag_context(
            question=question,
            rag_context=rag_context,
            schema=schema,
            model=self.answering_model
        )
        t6 = time.time()
        print(f"[计时] [get_answer_for_company] LLM调用耗时: {t6-t5:.2f} 秒")
        self.response_data = self.openai_processor.response_data
        if self.new_challenge_pipeline:
            pages = answer_dict.get("relevant_pages", [])
            validated_pages = self._validate_page_references(pages, retrieval_results)
            answer_dict["relevant_pages"] = validated_pages
            answer_dict["references"] = self._extract_references(validated_pages, company_name)
        print(f"[计时] [get_answer_for_company] 总耗时: {t6-t0:.2f} 秒")
        return answer_dict

    def _rewrite_question(self, question: str) -> dict:
        """调用LLM重写问题：关键词扩展 + 文档类型推断。使用rewrite_model加速"""
        system_prompt = prompts.QUESTION_REWRITE_SYSTEM_PROMPT
        user_prompt = f"请分析以下问题：\n{question}"
        try:
            result = self.openai_processor.send_message(
                model=self.rewrite_model,
                system_content=system_prompt,
                human_content=user_prompt,
                is_structured=False
            )
            if isinstance(result, str):
                result = result.strip()
                if result.startswith("```"):
                    result = re.sub(r'^```\w*\n?', '', result)
                    result = re.sub(r'\n?```$', '', result)
                return json.loads(result)
            return result if isinstance(result, dict) else {}
        except Exception as e:
            print(f"问题重写失败: {e}")
            return {}

    def _classify_question(self, question: str) -> str:
        """调用LLM分类问题类型，返回 fact_extraction/analysis_explanation/prediction_judgment/string"""
        try:
            result = self.openai_processor.send_message(
                model=self.rewrite_model,
                system_content=prompts.QUESTION_CLASSIFICATION_SYSTEM_PROMPT,
                human_content=f"请分类以下问题：\n{question}",
                is_structured=False
            )
            if isinstance(result, str):
                result = result.strip()
                if result.startswith("```"):
                    result = re.sub(r'^```\w*\n?', '', result)
                    result = re.sub(r'\n?```$', '', result)
                classify_result = json.loads(result)
                category = classify_result.get("category", "string")
            elif isinstance(result, dict):
                category = result.get("category", "string")
            else:
                category = "string"
            if category not in ("fact_extraction", "analysis_explanation", "prediction_judgment"):
                category = "string"
            print(f"[问题分类] 问题: {question[:30]}... -> 类别: {category}")
            return category
        except Exception as e:
            print(f"问题分类失败: {e}, 回退到string")
            return "string"

    def _extract_companies_from_subset(self, question_text: str) -> list[str]:
        """从问题文本中提取被分析公司名（排除券商名干扰），匹配subset文件中的公司"""
        if not hasattr(self, 'companies_df'):
            if self.subset_path is None:
                raise ValueError("subset_path must be provided to use subset extraction")
            # 优先尝试 utf-8，失败则尝试 gbk
            try:
                self.companies_df = pd.read_csv(self.subset_path, encoding='utf-8')
            except UnicodeDecodeError:
                print('警告：subset.csv 不是 utf-8 编码，自动尝试 gbk 编码...')
                self.companies_df = pd.read_csv(self.subset_path, encoding='gbk')

        # 先排除问题中的券商名，避免误匹配
        clean_question = question_text
        for broker in sorted(KNOWN_BROKERS, key=len, reverse=True):
            clean_question = clean_question.replace(broker, '')

        found_companies = []
        company_names = sorted(self.companies_df['company_name'].unique(), key=len, reverse=True)

        for company in company_names:
            # 在清理后的问题中匹配公司名
            if company in clean_question:
                found_companies.append(company)
                clean_question = clean_question.replace(company, '')

        return found_companies

    def get_answer_with_metadata_filter(self, rewritten_query: str, metadata_filters: dict,
                                         schema: str, company_name: str) -> dict:
        """使用元数据过滤检索器获取答案"""
        t0 = time.time()
        retriever = MetadataFilteredRetriever(
            vector_db_dir=self.vector_db_dir,
            documents_dir=self.documents_dir,
            bm25_db_dir=self.bm25_db_dir,
            metadata_path=self.metadata_path,
            alpha=self.hybrid_bm25_vector_alpha
        )
        t1 = time.time()
        print(f"[计时] [元数据检索] 检索器初始化耗时: {t1-t0:.2f} 秒")

        retrieval_results = retriever.retrieve(
            rewritten_query=rewritten_query,
            metadata_filters=metadata_filters,
            top_n=self.top_n_retrieval,
            recall_n=self.hybrid_bm25_vector_recall_n,
            return_parent_pages=self.return_parent_pages
        )
        t2 = time.time()
        print(f"[计时] [元数据检索] 检索耗时: {t2-t1:.2f} 秒")

        if not retrieval_results:
            raise ValueError("元数据过滤检索未找到相关内容")

        rag_context = self._format_retrieval_results(retrieval_results)
        answer_dict = self.openai_processor.get_answer_from_rag_context(
            question=rewritten_query,
            rag_context=rag_context,
            schema=schema,
            model=self.answering_model
        )
        t3 = time.time()
        print(f"[计时] [元数据检索] LLM调用耗时: {t3-t2:.2f} 秒")
        self.response_data = self.openai_processor.response_data

        # 添加溯源信息
        if self.new_challenge_pipeline:
            pages = answer_dict.get("relevant_pages", [])
            validated_pages = self._validate_page_references(pages, retrieval_results)
            answer_dict["relevant_pages"] = validated_pages
            answer_dict["references"] = self._extract_references_with_traceability(
                validated_pages, company_name, retrieval_results
            )

        print(f"[计时] [元数据检索] 总耗时: {t3-t0:.2f} 秒")
        return answer_dict

    def _extract_references_with_traceability(self, pages_list: list, company_name: str,
                                               retrieval_results: list) -> list:
        """提取引用信息，包含溯源（来源PDF文件名+页码）"""
        if self.subset_path is None:
            raise ValueError("subset_path is required for reference extraction.")

        if not hasattr(self, 'companies_df'):
            try:
                self.companies_df = pd.read_csv(self.subset_path, encoding='utf-8')
            except UnicodeDecodeError:
                self.companies_df = pd.read_csv(self.subset_path, encoding='gbk')

        matching_rows = self.companies_df[self.companies_df['company_name'] == company_name]
        company_sha1 = matching_rows.iloc[0]['sha1'] if not matching_rows.empty else ""

        # 建立 page -> file_name 映射，同时建立 file_name -> doc_sha1 映射
        page_to_file = {}
        file_to_sha1 = {}
        for result in retrieval_results:
            page = result.get('page')
            file_name = result.get('file_name', '')
            if page is not None and page not in page_to_file:
                page_to_file[page] = file_name

        # 从 subset.csv 构建 source_file -> sha1 的映射（每个文件对应唯一的 sha1）
        for _, row in self.companies_df.iterrows():
            csv_file_name = row.get('file_name', '')
            csv_sha1 = row.get('sha1', '')
            if csv_file_name and csv_sha1:
                # subset.csv 的 file_name 是 PDF 原名，chunk 的 source_file 是 .md 转换后名称，需要匹配核心部分
                file_to_sha1[csv_file_name] = csv_sha1

        refs = []
        for page in pages_list:
            source_file = page_to_file.get(page, "")
            ref_pdf_sha1 = company_sha1
            if source_file:
                # 根据实际 source_file 查找对应的文档级 sha1
                for csv_fname, csv_sha1 in file_to_sha1.items():
                    core = csv_fname.replace('.pdf', '').replace('.PDF', '')
                    if core in source_file or source_file in core:
                        ref_pdf_sha1 = csv_sha1
                        break
            ref = {"pdf_sha1": ref_pdf_sha1, "page_index": page}
            if source_file:
                ref["source_file"] = source_file
            refs.append(ref)
        return refs

    def process_question(self, question: str, schema: str):
        # 处理单个问题，支持多公司比较
        if self.new_challenge_pipeline:
            extracted_companies = self._extract_companies_from_subset(question)
        else:
            extracted_companies = re.findall(r'"([^"]*)"', question)
        
        if len(extracted_companies) == 0:
            raise ValueError("No company name found in the question.")
        
        if len(extracted_companies) == 1:
            company_name = extracted_companies[0]
            answer_dict = self.get_answer_for_company(company_name=company_name, question=question, schema=schema)
            return answer_dict
        else:
            return self.process_comparative_question(question, extracted_companies, schema)
    
    def _create_answer_detail_ref(self, answer_dict: dict, question_index: int) -> str:
        """创建答案详情的引用ID，并存储详细内容"""
        ref_id = f"#/answer_details/{question_index}"
        with self._lock:
            self.answer_details[question_index] = {
                "step_by_step_analysis": answer_dict['step_by_step_analysis'],
                "reasoning_summary": answer_dict['reasoning_summary'],
                "relevant_pages": answer_dict['relevant_pages'],
                "response_data": self.response_data,
                "self": ref_id
            }
        return ref_id

    def _calculate_statistics(self, processed_questions: List[dict], print_stats: bool = False) -> dict:
        """统计处理结果，包括总数、错误数、N/A数、成功数"""
        total_questions = len(processed_questions)
        error_count = sum(1 for q in processed_questions if "error" in q)
        na_count = sum(1 for q in processed_questions if (q.get("value") if "value" in q else q.get("answer")) == "N/A")
        success_count = total_questions - error_count - na_count
        if print_stats:
            print(f"\nFinal Processing Statistics:")
            print(f"Total questions: {total_questions}")
            print(f"Errors: {error_count} ({(error_count/total_questions)*100:.1f}%)")
            print(f"N/A answers: {na_count} ({(na_count/total_questions)*100:.1f}%)")
            print(f"Successfully answered: {success_count} ({(success_count/total_questions)*100:.1f}%)\n")
        
        return {
            "total_questions": total_questions,
            "error_count": error_count,
            "na_count": na_count,
            "success_count": success_count
        }

    def process_questions_list(self, questions_list: List[dict], output_path: str = None, submission_file: bool = False, pipeline_details: str = "") -> dict:
        # 批量处理问题列表，支持并行与断点保存，返回处理结果和统计信息
        total_questions = len(questions_list)
        # 给每个问题加索引，便于后续答案详情定位
        questions_with_index = [{**q, "_question_index": i} for i, q in enumerate(questions_list)]
        self.answer_details = [None] * total_questions  # 预分配答案详情列表
        processed_questions = []
        parallel_threads = self.parallel_requests

        if parallel_threads <= 1:
            # 单线程顺序处理
            for question_data in tqdm(questions_with_index, desc="Processing questions"):
                processed_question = self._process_single_question(question_data)
                processed_questions.append(processed_question)
                if output_path:
                    self._save_progress(processed_questions, output_path, submission_file=submission_file, pipeline_details=pipeline_details)
        else:
            # 多线程并行处理
            with tqdm(total=total_questions, desc="Processing questions") as pbar:
                for i in range(0, total_questions, parallel_threads):
                    batch = questions_with_index[i : i + parallel_threads]
                    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_threads) as executor:
                        # executor.map 保证结果顺序与输入一致
                        batch_results = list(executor.map(self._process_single_question, batch))
                    processed_questions.extend(batch_results)
                    
                    if output_path:
                        self._save_progress(processed_questions, output_path, submission_file=submission_file, pipeline_details=pipeline_details)
                    pbar.update(len(batch_results))
        
        statistics = self._calculate_statistics(processed_questions, print_stats = True)
        
        return {
            "questions": processed_questions,
            "answer_details": self.answer_details,
            "statistics": statistics
        }

    def _process_single_question(self, question_data: dict) -> dict:
        question_index = question_data.get("_question_index", 0)
        
        if self.new_challenge_pipeline:
            question_text = question_data.get("text")
            schema = question_data.get("kind")
        else:
            question_text = question_data.get("question")
            schema = question_data.get("schema")

        # 当schema为string时，自动分类问题类型
        if schema == "string":
            schema = self._classify_question(question_text)

        try:
            if self.use_metadata_filter and self.metadata_path:
                # 新流程：问题重写 + 元数据过滤检索 + 答案溯源
                # 步骤1：确定性提取公司名和来源信息
                question_source = question_data.get("source", "")
                extracted_companies = self._extract_companies_from_subset(question_text) if self.new_challenge_pipeline else re.findall(r'"([^"]*)"', question_text)
                if not extracted_companies:
                    raise ValueError("No company name found in the question.")
                company_name = extracted_companies[0]

                # 步骤2：LLM问题重写
                rewrite_result = self._rewrite_question(question_text)
                print(f"[问题重写] 原始: {question_text}")
                print(f"[问题重写] 结果: {rewrite_result}")

                # 步骤3：构建元数据过滤条件
                companies_df = getattr(self, 'companies_df', None)
                if companies_df is None and self.subset_path:
                    try:
                        companies_df = pd.read_csv(self.subset_path, encoding='utf-8')
                    except UnicodeDecodeError:
                        companies_df = pd.read_csv(self.subset_path, encoding='gbk')
                    self.companies_df = companies_df
                rewritten_query, metadata_filters = build_metadata_filters(
                    question_text, companies_df, rewrite_result, question_source=question_source
                )
                print(f"[元数据过滤] rewritten_query: {rewritten_query}")
                print(f"[元数据过滤] metadata_filters: {metadata_filters}")

                # 步骤4：使用元数据过滤检索
                answer_dict = self.get_answer_with_metadata_filter(rewritten_query, metadata_filters, schema, company_name)

                # 步骤5：构建答案（含溯源信息）
                detail_ref = self._create_answer_detail_ref(answer_dict, question_index)
                if self.new_challenge_pipeline:
                    return {
                        "question_text": question_text,
                        "kind": schema,
                        "value": answer_dict.get("final_answer"),
                        "references": answer_dict.get("references", []),
                        "answer_details": {"$ref": detail_ref}
                    }
                else:
                    return {
                        "question": question_text,
                        "schema": schema,
                        "answer": answer_dict.get("final_answer"),
                        "answer_details": {"$ref": detail_ref},
                    }
            else:
                # 原有流程
                answer_dict = self.process_question(question_text, schema)
            
            if "error" in answer_dict:
                detail_ref = self._create_answer_detail_ref({
                    "step_by_step_analysis": None,
                    "reasoning_summary": None,
                    "relevant_pages": None
                }, question_index)
                if self.new_challenge_pipeline:
                    return {
                        "question_text": question_text,
                        "kind": schema,
                        "value": None,
                        "references": [],
                        "error": answer_dict["error"],
                        "answer_details": {"$ref": detail_ref}
                    }
                else:
                    return {
                        "question": question_text,
                        "schema": schema,
                        "answer": None,
                        "error": answer_dict["error"],
                        "answer_details": {"$ref": detail_ref},
                    }
            detail_ref = self._create_answer_detail_ref(answer_dict, question_index)
            if self.new_challenge_pipeline:
                return {
                    "question_text": question_text,
                    "kind": schema,
                    "value": answer_dict.get("final_answer"),
                    "references": answer_dict.get("references", []),
                    "answer_details": {"$ref": detail_ref}
                }
            else:
                return {
                    "question": question_text,
                    "schema": schema,
                    "answer": answer_dict.get("final_answer"),
                    "answer_details": {"$ref": detail_ref},
                }
        except Exception as err:
            return self._handle_processing_error(question_text, schema, err, question_index)

    def _handle_processing_error(self, question_text: str, schema: str, err: Exception, question_index: int) -> dict:
        """
        处理问题处理过程中的异常。
        记录错误详情并返回包含错误信息的字典。
        """
        import traceback
        error_message = str(err)
        tb = traceback.format_exc()
        error_ref = f"#/answer_details/{question_index}"
        error_detail = {
            "error_traceback": tb,
            "self": error_ref
        }
        
        with self._lock:
            self.answer_details[question_index] = error_detail
        
        print(f"Error encountered processing question: {question_text}")
        print(f"Error type: {type(err).__name__}")
        print(f"Error message: {error_message}")
        print(f"Full traceback:\n{tb}\n")
        
        if self.new_challenge_pipeline:
            return {
                "question_text": question_text,
                "kind": schema,
                "value": None,
                "references": [],
                "error": f"{type(err).__name__}: {error_message}",
                "answer_details": {"$ref": error_ref}
            }
        else:
            return {
                "question": question_text,
                "schema": schema,
                "answer": None,
                "error": f"{type(err).__name__}: {error_message}",
                "answer_details": {"$ref": error_ref},
            }

    def _post_process_submission_answers(self, processed_questions: List[dict]) -> List[dict]:
        """
        提交格式后处理：
        1. 页码从1-based转为0-based
        2. N/A答案清空引用
        3. 格式化为比赛提交schema
        4. 包含step_by_step_analysis
        """
        submission_answers = []
        
        for q in processed_questions:
            question_text = q.get("question_text") or q.get("question")
            kind = q.get("kind") or q.get("schema")
            value = "N/A" if "error" in q else (q.get("value") if "value" in q else q.get("answer"))
            references = q.get("references", [])
            
            answer_details_ref = q.get("answer_details", {}).get("$ref", "")
            step_by_step_analysis = None
            if answer_details_ref and answer_details_ref.startswith("#/answer_details/"):
                try:
                    index = int(answer_details_ref.split("/")[-1])
                    if 0 <= index < len(self.answer_details) and self.answer_details[index]:
                        step_by_step_analysis = self.answer_details[index].get("step_by_step_analysis")
                except (ValueError, IndexError):
                    pass
            
            # Clear references if value is N/A
            if value == "N/A":
                references = []
            else:
                # 使用1-based页码输出（与实际页码一致），并保留source_file信息
                references = [
                    {
                        "pdf_sha1": ref["pdf_sha1"],
                        "page_index": ref["page_index"],
                        "source_file": ref.get("source_file", "")
                    }
                    for ref in references
                ]
            
            submission_answer = {
                "question_text": question_text,
                "kind": kind,
                "value": value,
                "references": references,
            }
            
            if step_by_step_analysis:
                submission_answer["reasoning_process"] = step_by_step_analysis
            
            submission_answers.append(submission_answer)
        
        return submission_answers

    def _save_progress(self, processed_questions: List[dict], output_path: Optional[str], submission_file: bool = False, pipeline_details: str = ""):
        if output_path:
            statistics = self._calculate_statistics(processed_questions)
            
            # Prepare debug content
            result = {
                "questions": processed_questions,
                "answer_details": self.answer_details,
                "statistics": statistics
            }
            output_file = Path(output_path)
            debug_file = output_file.with_name(output_file.stem + "_debug" + output_file.suffix)
            with open(debug_file, 'w', encoding='utf-8') as file:
                json.dump(result, file, ensure_ascii=False, indent=2)
            
            if submission_file:
                # Post-process answers for submission
                submission_answers = self._post_process_submission_answers(processed_questions)
                submission = {
                    "answers": submission_answers,
                    "details": pipeline_details
                }
                with open(output_file, 'w', encoding='utf-8') as file:
                    json.dump(submission, file, ensure_ascii=False, indent=2)

    def process_all_questions(self, output_path: str = 'questions_with_answers.json', submission_file: bool = False, pipeline_details: str = ""):
        result = self.process_questions_list(
            self.questions,
            output_path,
            submission_file=submission_file,
            pipeline_details=pipeline_details
        )
        return result

    def process_comparative_question(self, question: str, companies: List[str], schema: str) -> dict:
        """
        处理多公司比较类问题：
        1. 先将比较问题重写为单公司问题
        2. 并行处理每个公司
        3. 汇总结果并生成最终比较答案
        """
        # Step 1: Rephrase the comparative question
        rephrased_questions = self.openai_processor.get_rephrased_questions(
            original_question=question,
            companies=companies
        )
        
        individual_answers = {}
        aggregated_references = []
        
        # Step 2: Process each individual question in parallel
        def process_company_question(company: str) -> tuple[str, dict]:
            """Helper function to process one company's question and return (company, answer)"""
            sub_question = rephrased_questions.get(company)
            if not sub_question:
                raise ValueError(f"Could not generate sub-question for company: {company}")
            
            answer_dict = self.get_answer_for_company(
                company_name=company, 
                question=sub_question, 
                schema="number"
            )
            return company, answer_dict

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_company = {
                executor.submit(process_company_question, company): company 
                for company in companies
            }
            
            for future in concurrent.futures.as_completed(future_to_company):
                try:
                    company, answer_dict = future.result()
                    individual_answers[company] = answer_dict
                    
                    company_references = answer_dict.get("references", [])
                    aggregated_references.extend(company_references)
                except Exception as e:
                    company = future_to_company[future]
                    print(f"Error processing company {company}: {str(e)}")
                    raise
        
        # Remove duplicate references
        unique_refs = {}
        for ref in aggregated_references:
            key = (ref.get("pdf_sha1"), ref.get("page_index"))
            unique_refs[key] = ref
        aggregated_references = list(unique_refs.values())
        
        # Step 3: Get the comparative answer using all individual answers
        comparative_answer = self.openai_processor.get_answer_from_rag_context(
            question=question,
            rag_context=individual_answers,
            schema="comparative",
            model=self.answering_model
        )
        self.response_data = self.openai_processor.response_data
        
        comparative_answer["references"] = aggregated_references
        return comparative_answer

    def process_single_question(self, question: str, kind: str = "string"):
        """
        单条问题推理，返回结构化答案。
        kind: 支持 'string'、'number'、'boolean'、'names' 等
        """
        t0 = time.time()
        print("[计时] [单问] 开始公司名抽取 ...")
        # 公司名抽取
        if self.new_challenge_pipeline:
            extracted_companies = self._extract_companies_from_subset(question)
        else:
            extracted_companies = re.findall(r'"([^"]*)"', question)
        t1 = time.time()
        print(f"[计时] [单问] 公司名抽取耗时: {t1-t0:.2f} 秒")
        if len(extracted_companies) == 0:
            raise ValueError("No company name found in the question.")
        if len(extracted_companies) == 1:
            company_name = extracted_companies[0]
            print("[计时] [单问] 开始检索与LLM推理 ...")
            t2 = time.time()
            answer_dict = self.get_answer_for_company(company_name=company_name, question=question, schema=kind)
            t3 = time.time()
            print(f"[计时] [单问] 检索+LLM推理耗时: {t3-t2:.2f} 秒")
            print(f"[计时] [单问] 总耗时: {t3-t0:.2f} 秒")
            return answer_dict
        else:
            print("[计时] [单问] 开始多公司比较 ...")
            t2 = time.time()
            answer_dict = self.process_comparative_question(question, extracted_companies, kind)
            t3 = time.time()
            print(f"[计时] [单问] 多公司比较耗时: {t3-t2:.2f} 秒")
            print(f"[计时] [单问] 总耗时: {t3-t0:.2f} 秒")
            return answer_dict
    