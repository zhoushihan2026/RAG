# src 目录各模块功能说明

> 本文档简要介绍了 `src` 目录下各主要模块的功能及其在整个RAG数据分析流程中的作用。

---

## 1. api_requests.py
主要负责与各类大模型API进行交互，统一封装了消息发送、结构化输出、重试、计费等逻辑。包含以下处理器：

- **APIProcessor**：统一入口，根据 `api_provider` 参数路由到对应处理器
- **DashscopeProcessor**：调用 DashScope（通义千问）系列模型
- **OpenAIProcessor**：调用 OpenAI 兼容 API
- **Fe8Processor**：调用 fe8.cn 提供的模型（qwen-turbo 用于问题重写/分类、MiniMax-M2.5 用于回答生成）
- **GeminiProcessor**：调用 Google Gemini 模型
- **IBMProcessor**：调用 IBM watsonx 模型

支持流式输出（`_stream_full_content`）、JSON 响应解析（含 markdown 围栏清理）、异步处理和 RAG 上下文问答接口。

## 1.5. constants.py (新增)
集中管理业务常量，消除硬编码重复定义。包含：
- `KNOWN_BROKERS`：已知券商名称列表（用于公司名抽取）
- `DOC_TYPE_KEYWORDS`：文档类型关键词映射（年报/研报/公告等）
- `CHUNK_CONFIG_BY_DOC_TYPE`：按文档类型的分块配置（chunk_size、overlap）
- 其他业务常量

所有模块通过 `from src.constants import XXX` 引用，不再内联魔法值。

## 2. api_request_parallel_processor.py
用于并发、限流地批量处理API请求，支持大规模任务的流式处理、重试、速率控制和日志记录。常用于批量嵌入生成或大规模LLM推理。

## 3. session_manager.py
负责多轮对话的会话管理，包括：

- **会话创建与存储**：内存存储，每个会话包含唯一 ID、标题、消息列表、时间戳
- **对话历史截断**：保留最近 5 轮对话（10 条消息），总字符数不超过 6000，超出时从头部截断
- **会话列表管理**：按最后活跃时间倒序排列，支持重命名、删除
- **自动标题**：首条用户消息的前 20 字自动设为会话标题
- **过期清理**：可清理超过指定天数的过期会话
- **消息上限**：每个会话最多 50 条用户消息

## 4. image_description.py
负责非表格图片的智能描述生成。通过多模态大模型（qwen-vl-plus）先判断图片类型（表格/图表/非表格），仅对非表格图片生成文字描述，并插入到对应markdown文件中。包含图片描述缓存机制，避免重复调用API。

## 5. ingestion.py
包含两大类：
- `BM25Ingestor`：负责将文本块构建为BM25索引，支持传统关键词检索。按文件粒度计算SHA1哈希缓存，仅当文档变动时才全量重建索引（BM25的IDF为全局统计值，无法局部更新）。
- `VectorDBIngestor`：负责将文本块转为向量并建立faiss向量库，支持语义检索。**支持增量追加**：通过按文件哈希对比，仅对新增/变更的文档调用embedding API，然后使用`faiss.IndexFlatIP.add()`追加到已有索引中；首次运行或删除文件时自动回退为全量构建。元数据（chunks_metadata.json）同样支持增量合并。

## 6. merge_json_to_markdown.py
负责将MinerU解析后的JSON结果与markdown文件合并，生成带页码标记的结构化markdown文档，便于后续分块、检索和人工审查。

## 7. parsed_reports_merging.py
负责将复杂的PDF解析结果（JSON）进一步规整为每页文本的结构化列表，并可导出为markdown，便于后续分块、检索和人工审查。

## 8. pdf_mineru.py
MinerU PDF解析工具的基础封装，提供上传、获取解析结果、解压等基础功能。

## 9. pdf_mineru_z.py
MinerU PDF解析工具的增强版本，支持PDF拆分、批量上传解析、结果合并、SHA1缓存校验（避免重复上传）、系统临时目录自动清理等功能。是当前pipeline中实际使用的MinerU解析模块。

## 10. pdf_parsing.py
负责调用Docling等工具对PDF年报进行结构化解析，输出为标准JSON格式。支持并行处理、元数据补全、页码校正等，是数据流的起点。

## 11. pipeline.py
系统主流程调度模块，串联PDF解析、表格序列化、报告规整、分块、向量化、问题处理等各阶段。包含 `RunConfig` 类，集中管理所有可配置参数。

v2 新增功能：
- **多轮对话支持**：`answer_single_question_stream` 接受 `history_messages` 参数，传入对话历史
- **问题重写与分类**：调用 `Fe8Processor`（qwen-turbo）进行问题分类和重写，输出 `completed_question`（补全后的完整问题）、`rewritten_query`（检索用查询）、`doc_type`（文档类型）
- **追问检索增强**：调用 `expand_followup_query` 从前一轮问题中提取财务术语，合并到检索查询
- **历史摘要注入**：调用 `summarize_history_for_rewrite` 将对话历史格式化为问题重写的上下文
- **回答分段**：Prompt 要求 LLM 按要点分段输出 final_answer
- **final_answer 回退**：当 final_answer 为空时，回退使用 step_by_step_analysis 或 _stream_full_content

性能优化：
- **检索器单例缓存**：`MetadataFilteredRetriever.get_instance()` 按参数缓存实例，避免重复加载 FAISS/BM25 索引
- **Pipeline 内处理器复用**：`QuestionsProcessor` 在 Pipeline 实例内缓存复用
- **LLM 处理器按需创建**：每次请求创建新 `Fe8Processor` 实例，避免多线程并发共享 httpx.Client

## 12. prompts.py
集中定义了所有LLM提示词（Prompt）和结构化输出Schema，涵盖问答、重排、表格序列化、比较等多种场景，保证LLM输出的规范性和可解析性。

v2 新增/修改：
- **REWRITE_PROMPT**：问题重写 Prompt，注入历史上下文，要求输出 `completed_question`、`rewritten_query`、`doc_type` 三个字段
- **各回答 Prompt**：final_answer 描述要求 LLM 用空行分隔不同要点，实现分段输出

## 13. questions_processing.py
负责问题的处理与答案生成。包括公司名抽取、检索调用、RAG上下文构建、LLM问答、答案后处理、引用页校验等，是问答主逻辑的实现核心。支持单问、多公司比较等多种场景。

v2 新增功能：
- **expand_followup_query**：追问检索增强，使用财务术语词表从前一轮问题中提取关键信息（如"营业收入"、"毛利率"），合并到当前检索查询中，避免碎片词
- **summarize_history_for_rewrite**：将对话历史格式化为问题重写的上下文，包含角色标记和内容，支持截断
- **parse_llm_json_response**：解析 LLM 返回的 JSON 响应，支持 markdown 围栏清理

## 14. reranking.py
实现了基于DashScope gte-rerank-v2模型的检索结果重排序（Rerank），可结合向量分数和相关性分数加权，提升检索结果的相关性。

## 15. retrieval.py
实现了四种检索器：
- `BM25Retriever`：基于BM25的关键词检索
- `VectorRetriever`：基于faiss向量的语义检索
- `HybridRetriever`：向量检索 + LLM重排的混合检索
- `HybridBM25VectorRetriever`：BM25 + Vector混合召回 + DashScope Rerank精排（无需LLM参与）
- `MetadataFilteredRetriever`（v2 增强）：支持元数据过滤的混合检索器，采用**单例缓存模式**，相同参数只创建一次实例，线程安全

支持按公司名和问题检索相关文本块，并可选用父文档检索返回整页内容。

## 16. tables_serialization.py
负责将PDF解析出的表格内容，结合上下文，通过LLM序列化为结构化信息块，便于后续检索和问答。

## 17. text_splitter.py
负责将规整后的报告文本按Token数进行分块，支持表格内容的特殊处理，生成适合向量化的文本块。

## 18. text_splitter_z.py
text_splitter的增强版本，针对当前项目需求优化了分块逻辑。

## 19. __init__.py
空文件，用于标识src为Python包。

---

# 模块关系与整体流程

## 数据处理流程
1. **PDF解析**：`pdf_mineru_z.py`（MinerU）或 `pdf_parsing.py`（Docling） → 结构化JSON
2. **图片描述**：`image_description.py` → 非表格图片生成文字描述并插入markdown
3. **JSON合并**：`merge_json_to_markdown.py` → 带页码的结构化markdown
4. **表格序列化（可选）**：`tables_serialization.py`
5. **文本分块**：`text_splitter.py` / `text_splitter_z.py`
6. **向量/检索库构建**：`ingestion.py`（BM25索引 + faiss向量库，**支持增量更新**）

## RAG问答流程（v2 多轮对话 + 性能优化）
7. **会话管理**：`session_manager.py` → 创建/获取会话，管理对话历史
8. **问题重写与分类**：`pipeline.py` → 调用 `Fe8Processor`（qwen-turbo），注入历史上下文，输出 `completed_question`、`rewritten_query`、`doc_type`
9. **追问检索增强**：`questions_processing.py` → `expand_followup_query` 从前一轮提取财务术语，合并到检索查询
10. **检索**：`retrieval.py` → `MetadataFilteredRetriever.get_instance()` 单例缓存，BM25 / Vector / Hybrid 四种检索器
11. **重排**：`reranking.py` → DashScope gte-rerank-v2 精排
12. **LLM交互**：`api_requests.py` → `Fe8Processor`（MiniMax-M2.5）生成分段回答
13. **会话持久化**：`api/app.py` → 保存完整详情（thinking、references）到 metadata，刷新后可恢复
14. **前端恢复**：`App.tsx` → sessionStorage 持久化活跃会话ID，刷新后自动加载消息记录

> 以上各环节可通过 `pipeline.py` 的 `RunConfig` 灵活组合，支撑多种RAG问答与数据分析场景。
