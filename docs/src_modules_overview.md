# src 目录各模块功能说明

> 本文档简要介绍了 `src` 目录下各主要模块的功能及其在整个RAG数据分析流程中的作用。

---

## 1. api_requests.py
主要负责与各类大模型API（如OpenAI、DashScope等）进行交互，统一封装了消息发送、结构化输出、重试、计费等逻辑。还包含异步处理和RAG上下文问答的接口，是整个系统与LLM交互的核心。

## 2. api_request_parallel_processor.py
用于并发、限流地批量处理API请求，支持大规模任务的流式处理、重试、速率控制和日志记录。常用于批量嵌入生成或大规模LLM推理。

## 3. image_description.py
负责非表格图片的智能描述生成。通过多模态大模型（qwen-vl-plus）先判断图片类型（表格/图表/非表格），仅对非表格图片生成文字描述，并插入到对应markdown文件中。包含图片描述缓存机制，避免重复调用API。

## 4. ingestion.py
包含两大类：
- `BM25Ingestor`：负责将文本块构建为BM25索引，支持传统关键词检索。按文件粒度计算SHA1哈希缓存，仅当文档变动时才全量重建索引（BM25的IDF为全局统计值，无法局部更新）。
- `VectorDBIngestor`：负责将文本块转为向量并建立faiss向量库，支持语义检索。**支持增量追加**：通过按文件哈希对比，仅对新增/变更的文档调用embedding API，然后使用`faiss.IndexFlatIP.add()`追加到已有索引中；首次运行或删除文件时自动回退为全量构建。元数据（chunks_metadata.json）同样支持增量合并。

## 5. merge_json_to_markdown.py
负责将MinerU解析后的JSON结果与markdown文件合并，生成带页码标记的结构化markdown文档，便于后续分块、检索和人工审查。

## 6. parsed_reports_merging.py
负责将复杂的PDF解析结果（JSON）进一步规整为每页文本的结构化列表，并可导出为markdown，便于后续分块、检索和人工审查。

## 7. pdf_mineru.py
MinerU PDF解析工具的基础封装，提供上传、获取解析结果、解压等基础功能。

## 8. pdf_mineru_z.py
MinerU PDF解析工具的增强版本，支持PDF拆分、批量上传解析、结果合并、SHA1缓存校验（避免重复上传）、系统临时目录自动清理等功能。是当前pipeline中实际使用的MinerU解析模块。

## 9. pdf_parsing.py
负责调用Docling等工具对PDF年报进行结构化解析，输出为标准JSON格式。支持并行处理、元数据补全、页码校正等，是数据流的起点。

## 10. pipeline.py
系统主流程调度模块，串联PDF解析、表格序列化、报告规整、分块、向量化、问题处理等各阶段。可按不同配置灵活组合各处理环节。包含 `RunConfig` 类，集中管理所有可配置参数。

## 11. prompts.py
集中定义了所有LLM提示词（Prompt）和结构化输出Schema，涵盖问答、重排、表格序列化、比较等多种场景，保证LLM输出的规范性和可解析性。

## 12. questions_processing.py
负责问题的处理与答案生成。包括公司名抽取、检索调用、RAG上下文构建、LLM问答、答案后处理、引用页校验等，是问答主逻辑的实现核心。支持单问、多公司比较等多种场景。

## 13. reranking.py
实现了基于DashScope gte-rerank-v2模型的检索结果重排序（Rerank），可结合向量分数和相关性分数加权，提升检索结果的相关性。

## 14. retrieval.py
实现了四种检索器：
- `BM25Retriever`：基于BM25的关键词检索
- `VectorRetriever`：基于faiss向量的语义检索
- `HybridRetriever`：向量检索 + LLM重排的混合检索
- `HybridBM25VectorRetriever`：BM25 + Vector混合召回 + DashScope Rerank精排（无需LLM参与）

支持按公司名和问题检索相关文本块，并可选用父文档检索返回整页内容。

## 15. tables_serialization.py
负责将PDF解析出的表格内容，结合上下文，通过LLM序列化为结构化信息块，便于后续检索和问答。

## 16. text_splitter.py
负责将规整后的报告文本按Token数进行分块，支持表格内容的特殊处理，生成适合向量化的文本块。

## 17. text_splitter_z.py
text_splitter的增强版本，针对当前项目需求优化了分块逻辑。

## 18. __init__.py
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

## RAG问答流程
7. **问题处理**：`questions_processing.py` → 公司名抽取、检索调用、答案生成
8. **检索**：`retrieval.py` → BM25 / Vector / Hybrid / HybridBM25Vector 四种检索器
9. **重排**：`reranking.py` → DashScope gte-rerank-v2 精排
10. **LLM交互**：`api_requests.py` → 结构化问答生成
11. **主流程调度**：`pipeline.py` → 统一配置与流程编排

> 以上各环节可通过 `pipeline.py` 的 `RunConfig` 灵活组合，支撑多种RAG问答与数据分析场景。
