# RAG-cy 遗留代码审计报告

> 审计日期: 2026-06-05
> 审计范围: `src/`, `main.py`, `app_streamlit.py`, `scripts/`
> 审计原则: 只描述现状，不给重构方案，不修 bug

---

## 1. Public API / 入口清单

### 1.1 CLI 入口 (`main.py`)

| 命令 | 下游依赖的调用面 | 说明 |
|------|-----------------|------|
| `download_models` | `Pipeline.download_docling_models()` | 下载 Docling 模型 |
| `parse_pdfs` | `Pipeline.parse_pdf_reports(parallel, chunk_size, max_workers)` | 解析 PDF |
| `serialize_tables` | `Pipeline.serialize_tables(max_workers)` | 表格序列化 |
| `process_reports` | `Pipeline.process_parsed_reports()` | 分块+建库 |
| `process_questions` | `Pipeline.process_questions()` | 问答处理 |

### 1.2 Streamlit 入口 (`app_streamlit.py`)

| 入口 | 下游依赖的调用面 | 说明 |
|------|-----------------|------|
| 用户提问 | `Pipeline.answer_single_question_stream(question, kind="string")` | 流式问答 |
| 文件上传 | `Pipeline.process_single_pdf_file(file_path, original_filename)` | 单文件入库 |

### 1.3 脚本入口 (`scripts/`)

| 脚本 | 下游依赖的调用面 | 说明 |
|------|-----------------|------|
| `run_questions.py` | `Pipeline.process_questions()` | 批量问答 |
| `run_rebuild.py` | `Pipeline.chunk_reports()` + `create_vector_dbs()` + `create_bm25_db()` | 重建索引 |
| `run_evaluation.py` | (评估相关) | 评估 |
| `test_rerank.py` | (Rerank 测试) | Rerank 测试 |

### 1.4 Pipeline 核心 Public 方法 (`src/pipeline.py`)

| 方法 | 被谁调用 | 说明 |
|------|---------|------|
| `Pipeline.__init__(root_path, run_config)` | 所有入口 | 初始化 |
| `Pipeline.parse_pdf_reports(parallel, chunk_size, max_workers)` | CLI | PDF 解析调度 |
| `Pipeline.export_reports_to_markdown(file_name)` | 内部 | 单文件 MinerU 解析 |
| `Pipeline.describe_report_images(file_name)` | 内部 | 图片描述 |
| `Pipeline.chunk_reports()` | CLI/脚本 | 文本分块 |
| `Pipeline.create_vector_dbs()` | CLI/脚本 | 建向量库 |
| `Pipeline.create_bm25_db()` | CLI/脚本 | 建 BM25 索引 |
| `Pipeline.process_parsed_reports()` | CLI | 分块+建库 |
| `Pipeline.process_questions()` | CLI/脚本 | 批量问答 |
| `Pipeline.process_single_pdf_file(file_path, original_filename)` | Streamlit | 单文件完整入库 |
| `Pipeline.answer_single_question_stream(question, kind)` | Streamlit | 流式单条问答 |

### 1.5 QuestionsProcessor 核心 Public 方法 (`src/questions_processing.py`)

| 方法 | 被谁调用 | 说明 |
|------|---------|------|
| `QuestionsProcessor.__init__(...)` | Pipeline | 初始化（约 20 个参数） |
| `process_all_questions(output_path, submission_file, pipeline_details)` | Pipeline | 批量处理 |
| `process_single_question(question, kind)` | Pipeline | 单条问答 |
| `get_answer_for_company(company_name, question, schema)` | 内部 | 单公司检索+LLM |
| `get_answer_with_metadata_filter(rewritten_query, filters, schema, company_name)` | 内部 | 元数据过滤检索+LLM |

### 1.6 检索层 Public 方法 (`src/retrieval.py`)

| 类/方法 | 被谁调用 | 说明 |
|---------|---------|------|
| `DashScopeEmbedding.encode(texts, ...)` | VectorDBIngestor, VectorRetriever, MetadataFilteredRetriever | 文本向量化 |
| `BM25Retriever.retrieve_by_company_name(...)` | QuestionsProcessor | BM25 检索 |
| `VectorRetriever.retrieve_by_company_name(...)` | QuestionsProcessor, HybridRetriever, HybridBM25VectorRetriever | 向量检索 |
| `VectorRetriever.retrieve_all(company_name)` | QuestionsProcessor | 全量上下文 |
| `HybridRetriever.retrieve_by_company_name(...)` | QuestionsProcessor | 向量+LLM重排 |
| `HybridBM25VectorRetriever.retrieve_by_company_name(...)` | QuestionsProcessor | BM25+向量+Rerank |
| `MetadataFilteredRetriever.retrieve(...)` | Pipeline.answer_single_question_stream | 元数据过滤检索 |

### 1.7 API 请求层 Public 方法 (`src/api_requests.py`)

| 类/方法 | 被谁调用 | 说明 |
|---------|---------|------|
| `APIProcessor.__init__(provider)` | QuestionsProcessor | 初始化 |
| `APIProcessor.send_message(...)` | QuestionsProcessor | 统一消息发送 |
| `APIProcessor.get_answer_from_rag_context(...)` | QuestionsProcessor | RAG 问答 |
| `BaseDashscopeProcessor.send_message(...)` | Pipeline | DashScope 消息 |
| `BaseDashscopeProcessor.send_message_stream(...)` | Pipeline | DashScope 流式消息 |
| `BaseOpenaiProcessor.send_message(...)` | TableSerializer | OpenAI 消息 |

---

## 2. 职责板块拆分

### 2.1 PDF 解析板块

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| Docling 解析 | `src/pdf_parsing.py` (PDFParser, JsonReportProcessor) | 本地 Docling 解析，已基本弃用 |
| MinerU 解析（URL模式） | `src/pdf_mineru.py` | 旧版 MinerU，通过 URL 上传，已弃用 |
| MinerU 解析（本地文件模式） | `src/pdf_mineru_z.py` | 当前使用的 MinerU，本地文件上传 |
| PDF 拆分（大文件） | `src/pipeline.py` `_split_pdf()` | 超过 200 页拆分 |
| MinerU 结果合并 | `src/pipeline.py` `_merge_mineru_results()` | 多部分结果合并 |
| JSON+Markdown 合并 | `src/merge_json_to_markdown.py` | content_list.json + full.md -> 带页码 markdown |
| 图片描述 | `src/image_description.py` | 多模态模型为非表格图表图片生成描述 |
| 报告规整（Docling后处理） | `src/parsed_reports_merging.py` (PageTextPreparation) | Docling JSON -> 清洗后页面文本 |

### 2.2 文本分块板块

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| 按页分块（Docling格式） | `src/text_splitter.py` (TextSplitter) | 旧版，基于 JSON 页面数据分块 |
| 按行分块（Markdown格式） | `src/text_splitter_z.py` (TextSplitter) | 当前使用，基于 Markdown 按行+token 分块 |
| 表格序列化 | `src/tables_serialization.py` (TableSerializer) | LLM 将表格 HTML 转为独立信息块 |

### 2.3 索引构建板块

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| 向量库构建 | `src/ingestion.py` (VectorDBIngestor) | FAISS 索引，支持增量追加 |
| BM25 索引构建 | `src/ingestion.py` (BM25Ingestor) | rank_bm25 索引 |
| 缓存/增量判断 | `src/ingestion.py` + `src/pipeline.py` | 文件 SHA1 哈希对比 |

### 2.4 检索板块

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| 向量检索 | `src/retrieval.py` (VectorRetriever) | FAISS + DashScope Embedding |
| BM25 检索 | `src/retrieval.py` (BM25Retriever) | rank_bm25 |
| 混合检索（LLM重排） | `src/retrieval.py` (HybridRetriever) | 向量 + LLM 重排 |
| 混合检索（Rerank精排） | `src/retrieval.py` (HybridBM25VectorRetriever) | BM25+向量+DashScope Rerank |
| 元数据过滤检索 | `src/retrieval.py` (MetadataFilteredRetriever) | 硬过滤+软加权+分级回退 |
| 父文档检索 | 各 Retriever 的 `return_parent_pages` 参数 | chunk -> 完整页面 |

### 2.5 重排板块

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| DashScope Rerank（OpenAI兼容） | `src/reranking.py` (DashScopeReranker, 第一个定义) | OpenAI 兼容接口 qwen3-rerank |
| DashScope Rerank（原生API） | `src/reranking.py` (DashScopeReranker, 第二个定义) | 原生 HTTP API qwen3-rerank |
| Jina Rerank | `src/reranking.py` (JinaReranker) | Jina API |
| LLM 重排 | `src/reranking.py` (LLMReranker) | OpenAI/DashScope LLM 打分 |
| LocalReranker | `src/reranking.py` (LocalReranker) | 委托给 DashScopeReranker |

### 2.6 LLM 调用板块

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| OpenAI 处理器 | `src/api_requests.py` (BaseOpenaiProcessor) | OpenAI 兼容接口 |
| IBM 处理器 | `src/api_requests.py` (BaseIBMAPIProcessor) | IBM watsonx |
| Gemini 处理器 | `src/api_requests.py` (BaseGeminiProcessor) | Google Gemini |
| DashScope 处理器 | `src/api_requests.py` (BaseDashscopeProcessor) | DashScope Qwen |
| API 路由器 | `src/api_requests.py` (APIProcessor) | 按 provider 分发 |
| 并行请求处理器 | `src/api_request_parallel_processor.py` | 异步批量 API 调用 |

### 2.7 问答处理板块

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| 问题分类 | `src/questions_processing.py` `_classify_question()` | LLM 分类为 fact/analysis/prediction |
| 问题重写 | `src/questions_processing.py` `_rewrite_question()` | LLM 关键词扩展+文档类型推断 |
| 元数据过滤构建 | `src/questions_processing.py` `build_metadata_filters()` | 公司名+券商+文档类型过滤 |
| 答案生成 | `src/questions_processing.py` `get_answer_for_company()` | 检索+LLM 生成 |
| 页码校验 | `src/questions_processing.py` `_validate_page_references()` | 过滤幻觉页码 |
| 引用提取 | `src/questions_processing.py` `_extract_references()` / `_extract_references_with_traceability()` | 溯源信息 |
| 比较类问题 | `src/questions_processing.py` `process_comparative_question()` | 多公司比较 |
| 流式问答 | `src/pipeline.py` `answer_single_question_stream()` | Pipeline 内实现 |

### 2.8 Prompt 管理

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| 所有 Prompt 定义 | `src/prompts.py` | 约 760 行，包含所有 Prompt 类和常量 |

### 2.9 配置管理

| 功能 | 散落位置 | 说明 |
|------|---------|------|
| 路径配置 | `src/pipeline.py` (PipelineConfig) | 所有目录路径 |
| 运行配置 | `src/pipeline.py` (RunConfig) | 检索/模型/流程参数 |
| 预设配置 | `src/pipeline.py` (configs, preprocess_configs, hybrid_bm25_vector_config) | 硬编码的配置预设 |

---

## 3. 状态地图

### 3.1 数据库（持久化存储）

| 存储 | 路径 | 格式 | 读写方 | 说明 |
|------|------|------|--------|------|
| FAISS 向量索引 | `databases{suffix}/vector_dbs/all_docs.faiss` | FAISS binary | VectorDBIngestor写, VectorRetriever/MetadataFilteredRetriever读 | 统一向量库 |
| BM25 索引 | `databases{suffix}/bm25_dbs/all_docs.pkl` | Pickle | BM25Ingestor写, BM25Retriever/MetadataFilteredRetriever读 | 统一BM25索引 |
| 分块文档 | `databases{suffix}/chunked_reports/*.json` | JSON | TextSplitter写, 各Retriever读 | 每个报告一个JSON |
| 元数据 | `databases{suffix}/chunks_metadata.json` | JSON | VectorDBIngestor写, MetadataFilteredRetriever读 | 全量chunk元数据 |
| Embedding 缓存 | `databases{suffix}/vector_dbs/embedding_cache.json` | JSON | VectorDBIngestor读写 | 文件级SHA1哈希 |
| BM25 缓存 | `databases{suffix}/bm25_dbs/bm25_cache.json` | JSON | BM25Ingestor读写 | 文件级SHA1哈希 |
| 分块缓存 | `databases{suffix}/chunking_cache.json` | JSON | Pipeline读写 | 输入目录哈希 |
| MinerU 缓存 | `debug_data/01_mineru_json/file_cache.json` | JSON | Pipeline读写 | PDF文件SHA1 |
| 图片描述缓存 | `debug_data/01_mineru_json/image_desc_cache.json` | JSON | image_description读写 | 报告级状态 |
| 答案文件 | `data/stock_data/answers/answers{suffix}.json` | JSON | QuestionsProcessor写 | 问答结果 |
| 答案调试文件 | `data/stock_data/answers/answers{suffix}_debug.json` | JSON | QuestionsProcessor写 | 含详情 |
| subset.csv | `data/stock_data/subset.csv` | CSV | Pipeline读写 | 文件-公司映射 |
| questions.json | `data/stock_data/questions.json` | JSON | QuestionsProcessor读 | 问题列表 |

### 3.2 全局变量 / 类变量（单例状态）

| 变量 | 位置 | 说明 |
|------|------|------|
| `DashScopeEmbedding._client` | `src/retrieval.py` | 类级单例，DashScope OpenAI 客户端 |
| `DashScopeEmbedding._model_name` | `src/retrieval.py` | 类级常量 "text-embedding-v4" |
| `VectorRetriever._model` | `src/retrieval.py` | 类级单例，DashScopeEmbedding 实例 |
| `LocalReranker._model` | `src/reranking.py` | 类级单例，DashScopeReranker 实例 |
| `LocalReranker._model_available` | `src/reranking.py` | 类级标志，是否初始化成功 |
| `DashScopeReranker._client` | `src/reranking.py` (第一个定义) | 类级单例，DashScope OpenAI 客户端 |
| `EMBEDDING_MODEL_PATH` | `src/retrieval.py` | 模块级常量 "/root/autodl-tmp/..."（未使用） |
| `dashscope.api_key` | `src/api_requests.py`, `src/image_description.py` | 模块级全局变量 |

### 3.3 环境变量 / 配置

| 变量 | 使用位置 | 说明 |
|------|---------|------|
| `DASHSCOPE_API_KEY` | retrieval.py, reranking.py, api_requests.py, image_description.py | DashScope API 密钥 |
| `OPENAI_API_KEY` | api_requests.py | OpenAI API 密钥 |
| `OPENAI_BASE_URL` | api_requests.py | OpenAI 基础 URL（默认 https://api.fe8.cn/v1） |
| `MINERU_API_KEY` | pdf_mineru.py, pdf_mineru_z.py | MinerU API 密钥 |
| `IBM_API_KEY` | api_requests.py | IBM API 密钥 |
| `GEMINI_API_KEY` | api_requests.py | Gemini API 密钥 |
| `JINA_API_KEY` | reranking.py | Jina API 密钥 |

### 3.4 隐式输入输出

| 类型 | 位置 | 说明 |
|------|------|------|
| 文件系统状态 | Pipeline 多处 | 通过 `os.path.exists()` 判断是否跳过步骤 |
| SHA1 哈希对比 | Pipeline, Ingestor | 判断文件是否变动，决定是否跳过/增量 |
| `self.response_data` | BaseOpenaiProcessor, APIProcessor, QuestionsProcessor | 副作用式传递 token 用量 |
| `self.companies_df` | QuestionsProcessor | 惰性加载，首次使用时从 subset.csv 读取 |
| `self._stream_full_content` | BaseDashscopeProcessor | 流式结束后保存完整内容 |
| `self.answer_details` | QuestionsProcessor | 线程安全的答案详情列表 |
| `self._lock` | QuestionsProcessor | 线程锁 |
| `message_queue` | tables_serialization.py | 模块级日志队列 |
| print 语句 | 全项目 | 大量 print 作为日志输出 |

---

## 4. 现存多套实现 / 多套规则

### 4.1 PDF 解析：两套 MinerU + 一套 Docling

| 实现 | 文件 | 状态 |
|------|------|------|
| `pdf_mineru.py` | URL 模式上传 | **已弃用**（pipeline.py 中被注释 `from src import pdf_mineru_z as pdf_mineru`） |
| `pdf_mineru_z.py` | 本地文件上传 | **当前使用** |
| `pdf_parsing.py` | Docling 本地解析 | **仅 `download_models` 命令使用**，主流程已不用 |

### 4.2 文本分块：两套 TextSplitter

| 实现 | 文件 | 分块策略 | 状态 |
|------|------|---------|------|
| `text_splitter.py` | TextSplitter | 按页 RecursiveCharacterTextSplitter + 按行分块 Markdown | **旧版**，pipeline.py 中被注释 |
| `text_splitter_z.py` | TextSplitter | 按 token 分块 Markdown，支持不可分割块（表格/Q&A），不跨页 | **当前使用** |

### 4.3 DashScopeReranker：同名类定义两次

| 实现 | 位置 | 接口 |
|------|------|------|
| `DashScopeReranker` (第一个) | `reranking.py` 第 10-45 行 | OpenAI 兼容接口 `client.rerank.create()` |
| `DashScopeReranker` (第二个) | `reranking.py` 第 200-260 行 | 原生 HTTP API `requests.post()` |

**第二个定义覆盖了第一个**。`LocalReranker` 内部使用的是第二个定义。

### 4.4 检索器：5 种并存

| 检索器 | 触发条件 | 说明 |
|--------|---------|------|
| `BM25Retriever` | `use_bm25_db=True, use_vector_dbs=False` | 纯 BM25 |
| `VectorRetriever` | `use_vector_dbs=True, use_bm25_db=False, llm_reranking=False` | 纯向量 |
| `HybridRetriever` | `llm_reranking=True` | 向量 + LLM 重排 |
| `HybridBM25VectorRetriever` | `hybrid_bm25_vector=True` | BM25+向量+DashScope Rerank |
| `MetadataFilteredRetriever` | `use_metadata_filter=True` | 元数据过滤+BM25+向量+Rerank |

前 4 种按 `company_name` 分库检索，第 5 种使用统一全库 + 元数据过滤。

### 4.5 LLM 处理器：4 种并存

| 处理器 | Provider | 状态 |
|--------|----------|------|
| `BaseOpenaiProcessor` | openai | 活跃（TableSerializer 使用） |
| `BaseIBMAPIProcessor` | ibm | 实验性 |
| `BaseGeminiProcessor` | gemini | 实验性 |
| `BaseDashscopeProcessor` | dashscope | **主流程使用** |

### 4.6 公司名提取：两套规则

| 实现 | 位置 | 规则 |
|------|------|------|
| 正则提取 | `QuestionsProcessor.process_question()` | `re.findall(r'"([^"]*)"', question)` |
| subset 匹配 | `QuestionsProcessor._extract_companies_from_subset()` | 从 subset.csv 公司名列表匹配 |

`new_challenge_pipeline=True` 时使用 subset 匹配，否则使用正则。

### 4.7 引用提取：两套实现

| 实现 | 位置 | 说明 |
|------|------|------|
| `_extract_references()` | QuestionsProcessor | 简单版，按公司名查 sha1 |
| `_extract_references_with_traceability()` | QuestionsProcessor | 增强版，包含 source_file 溯源 |

### 4.8 报告规整：两套路径

| 路径 | 说明 | 状态 |
|------|------|------|
| Docling -> PageTextPreparation -> text_splitter.py | 旧版流程 | 已弃用 |
| MinerU -> merge_json_to_markdown -> text_splitter_z.py | 当前流程 | 活跃 |

### 4.9 问答 Prompt：按问题类型多套

| Prompt 类 | 问题类型 |
|-----------|---------|
| `AnswerWithRAGContextNamePrompt` | name |
| `AnswerWithRAGContextNumberPrompt` | number |
| `AnswerWithRAGContextBooleanPrompt` | boolean |
| `AnswerWithRAGContextNamesPrompt` | names |
| `AnswerWithRAGContextFactPrompt` | fact_extraction（流式使用） |
| `AnswerWithRAGContextAnalysisPrompt` | analysis_explanation（流式使用） |
| `AnswerWithRAGContextPredictionPrompt` | prediction_judgment（流式使用） |
| `AnswerWithRAGContextStringPrompt` | string（流式兜底） |
| `ComparativeAnswerPrompt` | 比较类 |

### 4.10 配置预设：多套硬编码

| 预设名 | 位置 | 说明 |
|--------|------|------|
| `preprocess_configs['ser_tab']` | pipeline.py | 使用序列化表格 |
| `preprocess_configs['no_ser_tab']` | pipeline.py | 不使用序列化表格 |
| `configs['base']` | pipeline.py | 基础配置 |
| `configs['pdr']` | pipeline.py | 父文档检索 |
| `configs['max']` | pipeline.py | 最大配置 |
| `configs['max_no_ser_tab']` | pipeline.py | 最大配置无序列化表格 |
| `configs['max_nst_o3m']` | pipeline.py | o3-mini 模型 |
| `configs['max_st_o3m']` | pipeline.py | o3-mini + 序列化表格 |
| `configs['ibm_llama70b']` | pipeline.py | IBM Llama 70B |
| `configs['ibm_llama8b']` | pipeline.py | IBM Llama 8B |
| `configs['gemini_thinking']` | pipeline.py | Gemini Thinking |
| `hybrid_bm25_vector_config` | pipeline.py | 混合检索配置（Streamlit 使用） |

---

## 5. 可疑行为清单

> 以下行为看起来像 bug 或有风险，但重构前必须先原样锁住。

### 5.1 DashScopeReranker 同名类覆盖

**位置**: `src/reranking.py`
**现象**: 文件中定义了两个 `DashScopeReranker` 类，第二个覆盖了第一个。第一个使用 OpenAI 兼容接口，第二个使用原生 HTTP API。
**风险**: 如果有人意图使用第一个定义的接口，实际运行的是第二个。两个类的 `rerank()` 方法签名和返回格式不同。
**锁定**: 当前 `LocalReranker` 使用的是第二个定义，行为已被隐式锁定。

### 5.2 VectorRetriever 按公司名分库 vs MetadataFilteredRetriever 统一全库

**位置**: `src/retrieval.py`
**现象**: `VectorRetriever` 按 `company_name` 分组加载 FAISS 索引（每个公司一个 `.faiss` 文件），而 `MetadataFilteredRetriever` 加载 `all_docs.faiss` 统一索引。两套索引结构不同。
**风险**: `VectorDBIngestor` 只生成 `all_docs.faiss` 统一索引，不生成按公司分组的索引。如果使用 `VectorRetriever`，会因为找不到 `{company_name}.faiss` 而报错。
**锁定**: 当前主流程使用 `MetadataFilteredRetriever`，`VectorRetriever` 的按公司分库逻辑实际已不可用。

### 5.3 BM25Retriever 同样按公司名分库

**位置**: `src/retrieval.py`
**现象**: `BM25Retriever` 期望 `{company_name}.pkl` 格式的 BM25 索引，但 `BM25Ingestor` 只生成 `all_docs.pkl` 统一索引。
**风险**: 同 5.2，`BM25Retriever` 的按公司分库逻辑不可用。

### 5.4 `_compute_file_sha1` 使用 SHA1 而非 SHA256

**位置**: `src/pipeline.py`, `src/ingestion.py`
**现象**: 文件哈希使用 SHA1 算法。
**风险**: SHA1 有碰撞风险，但对于缓存判断场景影响极小。
**锁定**: 所有缓存逻辑依赖 SHA1，修改会导致缓存失效。

### 5.5 `export_reports_to_markdown` 中的缓存跳过逻辑有死代码

**位置**: `src/pipeline.py` 第 327-345 行
**现象**: 当 PDF 文件变动时，删除旧文件后进入 `if os.path.exists(existing_md) or os.path.exists(existing_json)` 分支，但此时文件已被删除，条件为 False，进入 else 分支为空（只有 `pass` 语义）。然后代码继续到"再次检查"部分。中间的 if/else 分支实际上什么都不做。
**风险**: 逻辑上不会出错（因为后面有再次检查），但代码意图不清晰。

### 5.6 `_add_file_to_subset_csv` 中 company_name 提取规则脆弱

**位置**: `src/pipeline.py`
**现象**: 从文件名提取公司名的正则逻辑：先取【】内内容，如果是"财报"等词则取】和：之间的内容。没有【】时从已有公司名列表匹配。
**风险**: 文件名格式变化会导致公司名提取错误。例如文件名不含【】且不匹配已有公司名时，整个文件名作为 company_name。

### 5.7 `QuestionsProcessor` 构造函数约 20 个参数

**位置**: `src/questions_processing.py`
**现象**: 构造函数参数极多，且大部分直接透传自 `RunConfig`。
**风险**: 参数传递链路长，容易遗漏或顺序错误。

### 5.8 `BaseDashscopeProcessor.send_message` 的 JSON 解析逻辑重复

**位置**: `src/api_requests.py`
**现象**: 剥离 markdown 代码块标记 + JSON 解析的逻辑在 `send_message`、`_send_message_openai_compat`、`send_message_stream`、`answer_single_question_stream` 中各写了一遍，且实现略有差异。
**风险**: 一处修了另一处没修，导致行为不一致。

### 5.9 `self.response_data` 副作用传递

**位置**: 多处
**现象**: `BaseOpenaiProcessor`、`APIProcessor`、`BaseDashscopeProcessor` 都通过 `self.response_data` 传递 token 用量，调用方需要在调用后立即读取，否则会被下一次调用覆盖。在多线程环境下存在竞态条件。
**风险**: `QuestionsProcessor` 中 `self.response_data` 被多线程共享，可能读到错误值。

### 5.10 `Pipeline.answer_single_question_stream` 直接内联了 QuestionsProcessor 的逻辑

**位置**: `src/pipeline.py` 第 1100-1400 行
**现象**: 流式问答没有复用 `QuestionsProcessor`，而是在 Pipeline 中重新实现了公司名抽取、问题重写、元数据过滤、检索、LLM 调用、页码校验、引用提取的完整流程。
**风险**: 两套实现的行为可能不一致（如 Prompt 选择逻辑、重写+分类并行执行等）。

### 5.11 `text_splitter_z.py` 中 `_find_overlap_start` 的 `blocked` 变量赋值后未使用

**位置**: `src/text_splitter_z.py`
**现象**: `blocked = False` 赋值后，在 for 循环内可能设为 True，但循环结束后 `if blocked: break` 被注释掉或缺失。
**风险**: 不可分割块回溯保护可能不生效。

### 5.12 `pdf_mineru.py` 中 API Key 检查在模块加载时执行

**位置**: `src/pdf_mineru.py` 第 5-6 行
**现象**: `api_key = os.getenv("MINERU_API_KEY")` + `if not api_key: raise ValueError(...)` 在模块顶层执行。
**风险**: 即使不使用 `pdf_mineru.py`（当前已被 `pdf_mineru_z.py` 替代），import 时也会触发检查。不过当前代码中 `pdf_mineru.py` 已不被 import。

### 5.13 `EMBEDDING_MODEL_PATH` 常量未使用

**位置**: `src/retrieval.py` 第 280 行
**现象**: `EMBEDDING_MODEL_PATH = "/root/autodl-tmp/embedding/Qwen/Qwen3-Embedding-4B"` 定义但未被任何代码引用。`VectorDBIngestor.__init__` 的 `model_path` 参数也未使用。
**风险**: 死代码，可能误导维护者。

### 5.14 `VectorDBIngestor` 构造函数的 `model_path` 参数未使用

**位置**: `src/ingestion.py`
**现象**: `VectorDBIngestor.__init__(self, model_path: str = "...")` 接受 `model_path` 但内部直接创建 `DashScopeEmbedding()`，忽略该参数。
**风险**: 调用方传入 `model_path` 不会生效。

### 5.15 `process_single_pdf_file` 中的 subset.csv 写入使用 utf-8-sig 编码

**位置**: `src/pipeline.py`
**现象**: `_add_file_to_subset_csv` 使用 `utf-8-sig` 编码写入 CSV，但读取时先尝试 `utf-8` 再尝试 `gbk`。
**风险**: `utf-8-sig` 带 BOM，`utf-8` 读取时可能将 BOM 作为首列内容的一部分。

### 5.16 `_validate_page_references` 的 min_pages 补充逻辑可能引入不相关页

**位置**: `src/questions_processing.py`
**现象**: 当 LLM 声称的页码不足 `min_pages=2` 时，从检索结果中按顺序补充。但检索结果排序是按相似度，补充的页可能与答案无关。
**锁定**: 此行为可能是有意设计（确保引用页数足够），但需注意。

### 5.17 `build_metadata_filters` 中 KNOWN_BROKERS 硬编码

**位置**: `src/questions_processing.py` 和 `src/text_splitter_z.py`
**现象**: 券商名单 `["东方证券", "光大证券", "国信证券", "上海证券", "中原证券", "兴证国际", "华泰证券"]` 在多处硬编码。
**风险**: 新增券商需改多处代码。

---

## 6. 第一批应补的特征测试

> 以下测试应在重构前编写，用于锁定现有行为。

### 6.1 文本分块行为测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-CHUNK-01 | 包含 Markdown 管道表格的页面分块 | 表格不被拆断 |
| T-CHUNK-02 | 包含 `<table>...</table>` 的页面分块 | HTML 表格不被拆断 |
| T-CHUNK-03 | 包含 `<details>...</details>` 的页面分块 | details 块不被拆断 |
| T-CHUNK-04 | 包含 Q&A 对（**问：**/**答：**）的调研纪要分块 | Q&A 对不被拆断 |
| T-CHUNK-05 | 跨页边界处分块 | 不跨页分块 |
| T-CHUNK-06 | 大表格（> chunk_size tokens）分块 | 大表格单独成 chunk |
| T-CHUNK-07 | chunk_overlap 行为 | 相邻 chunk 有重叠 |

### 6.2 MinerU 结果合并测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-MERGE-01 | 拆分 PDF 后 content_list.json 的 page_idx 偏移修正 | page_idx 正确偏移 |
| T-MERGE-02 | 拆分 PDF 后 markdown 拼接 | 各部分 markdown 正确拼接 |
| T-MERGE-03 | 不需拆分的 PDF（<=200页） | 直接复制，不拆分 |

### 6.3 缓存/增量逻辑测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-CACHE-01 | 文件未变动时跳过 MinerU 上传 | 跳过，使用缓存 |
| T-CACHE-02 | 文件变动时重新上传 | 删除旧缓存，重新解析 |
| T-CACHE-03 | 向量库增量追加（新增文件） | 只对新文件调 embedding |
| T-CACHE-04 | 向量库全量重建（删除文件） | 全量重建 |
| T-CACHE-05 | BM25 缓存命中 | 跳过索引构建 |
| T-CACHE-06 | 分块缓存命中 | 跳过分块 |

### 6.4 检索行为测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-RET-01 | MetadataFilteredRetriever 硬过滤（company+broker+doc_type） | 只返回匹配 chunk |
| T-RET-02 | MetadataFilteredRetriever 分级回退（层级0->1->2->3） | 逐级放宽过滤 |
| T-RET-03 | MetadataFilteredRetriever 软加权（soft_doc_type） | 匹配 chunk 权重 +0.3 |
| T-RET-04 | HybridBM25VectorRetriever 分数归一化 | BM25 和 Vector 分数归一化到 0-1 |
| T-RET-05 | HybridBM25VectorRetriever 加权融合 | alpha=0.5 时两路等权 |
| T-RET-06 | 父文档检索（return_parent_pages=True） | 返回完整页面文本 |
| T-RET-07 | DashScope Rerank 精排 | 按 relevance_score 降序 |

### 6.5 问答处理测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-QA-01 | 问题分类（fact_extraction/analysis_explanation/prediction_judgment） | 返回正确类别 |
| T-QA-02 | 问题重写（关键词扩展+doc_type推断） | 保留原始关键词，扩展同义词 |
| T-QA-03 | 元数据过滤构建（从 source 字段解析券商和 doc_type） | 正确解析 |
| T-QA-04 | 页码校验（过滤幻觉页码+补充不足页码） | 只保留检索结果中存在的页码 |
| T-QA-05 | 引用提取（含 source_file 溯源） | 正确关联 PDF 文件名 |
| T-QA-06 | 比较类问题处理（多公司拆分+汇总） | 每个公司独立检索后比较 |
| T-QA-07 | N/A 答案时清空引用 | references 为空列表 |

### 6.6 JSON 解析行为测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-JSON-01 | LLM 返回带 ```json``` 包裹的响应 | 正确剥离代码块标记 |
| T-JSON-02 | LLM 返回非 JSON 字符串 | 返回 `{"final_answer": content, ...}` 兜底格式 |
| T-JSON-03 | LLM 返回有效 JSON | 正确解析为 dict |

### 6.7 公司名提取测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-COMP-01 | 从【券商名】文件名提取公司名 | 取】和：之间的内容（如"财报"类型） |
| T-COMP-02 | 从【券商名】文件名提取券商名 | 取【】内内容 |
| T-COMP-03 | 无【】的文件名匹配已有公司名 | 按长度降序匹配 |
| T-COMP-04 | 从问题文本中提取公司名（排除券商名干扰） | 不把券商名当作被分析公司 |

### 6.8 subset.csv 操作测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-SUBSET-01 | 新文件添加到 subset.csv | 生成 stock_XXXXX 格式 sha1 |
| T-SUBSET-02 | 已存在文件不重复添加 | 跳过，返回已有 sha1 |
| T-SUBSET-03 | 多编码读取（utf-8/gbk） | 自动降级 |

### 6.9 图片描述测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-IMG-01 | 表格/图表图片跳过描述 | is_table_or_chart 返回 True 时跳过 |
| T-IMG-02 | 非表格图表图片生成描述 | 插入 **[图片描述]** 标记 |
| T-IMG-03 | 已有描述的图片跳过 | 不重复调用多模态模型 |
| T-IMG-04 | 缓存命中时跳过 | status 为 completed/no_images 时跳过 |

### 6.10 merge_json_to_markdown 测试

| 测试 ID | 测试内容 | 锁定行为 |
|---------|---------|---------|
| T-MD-01 | 页码标记插入位置 | 在页码变化处插入 `---\n\n# Page N` |
| T-MD-02 | 无 full.md 时回退到 JSON 直接生成 | 使用 _fallback_convert |
| T-MD-03 | 序列对齐匹配 | content_list 与 markdown 行正确对应 |
