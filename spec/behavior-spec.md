# RAG-cy 行为 Spec（现状锁定）

> 生成日期: 2026-06-05
> 原则: 只描述当前行为，不判断合理性，不包含重构方案

---

## S-1 文本分块 (`text_splitter_z.py`)

### S-1.1 不可分割块识别

- `_identify_indivisible_blocks(lines)`: 识别 Markdown 管道表格（`|...|`行）和 `<table>...</table>` 块、`<details>...</details>` 块，返回 `[(start_line, end_line), ...]`
- 管道表格: 连续的 `|` 开头行视为一个块，直到遇到非 `|` 行
- `<table>` 块: 从 `<table` 开始到 `</table>` 结束（含）
- `<details>` 块: 从 `<details` 开始到 `</details>` 结束（含）

### S-1.2 Q&A 块识别

- `_identify_qa_blocks(lines)`: 识别以 `**问：**` 或 `**问:**` 开头的 Q&A 对
- 每个 Q&A 对从 `**问：**` 行开始，到下一个 `**问：**` 行之前结束
- 最后一个 Q&A 对到文件末尾结束
- 只有出现了 `**答：**` 的 Q&A 对才会被收录

### S-1.3 券商名提取

- `_extract_broker(file_name)`: 从文件名中提取已知券商名
- 已知券商列表: `["东方证券", "光大证券", "国信证券", "上海证券", "中原证券", "兴证国际", "华泰证券"]`
- 按长度降序匹配（长名优先），返回第一个匹配到的券商名
- 无匹配返回空字符串

### S-1.4 日期/季度提取

- `_extract_date(file_name)`: 提取第一个 `20XX` 格式的年份，无匹配返回空字符串
- `_extract_quarter(file_name)`: 优先匹配 `20XX年X季度`，其次匹配 `20XXQX`，无匹配返回空字符串

### S-1.5 Markdown 分块 (`split_markdown_file`)

- 按 token 分块，默认 `chunk_size=300`, `chunk_overlap=50`
- 使用 `o200k_base` 编码计算 token
- **不跨页分块**: 以 `# Page N` 标记分页，每页独立分块
- 不可分割块处理:
  - 小块（当前累积 + 块 <= chunk_size * 1.3）: 合入当前 chunk
  - 中等块（块 <= chunk_size）: 先输出当前文本，块单独成 chunk
  - 大块（块 > chunk_size）: 先输出当前文本，大块单独成 chunk
- overlap 回溯不进入不可分割块内部
- **现状**: `_find_overlap_start` 中 `blocked` 变量赋值后未使用，`if blocked: break` 缺失
- 后处理: 合并 < 20 tokens 的极小碎片到前一个 chunk
- 返回: `(chunks_list, lines_list, line_pages_list)`

### S-1.6 批量分块 (`split_markdown_reports`)

- 读取 subset.csv 获取 company_name/broker/sha1/coverage_start/coverage_end/doc_type 映射
- CSV 读取编码优先级: utf-8-sig -> utf-8 -> gbk
- 输出 JSON 格式: `{"metainfo": {...}, "content": {"chunks": [...], "pages": [...]}}`
- 每个 chunk 包含: `text`, `page`, `source_file`, `company_name`, `broker`, `sha1`, `doc_type`, `coverage_start`, `coverage_end`

---

## S-2 MinerU 结果合并 (`merge_json_to_markdown.py`)

### S-2.1 页码标记插入 (`insert_page_markers`)

- 输入: full.md 文本 + content_list.json 列表
- 跳过类型: `header`, `footer`, `page_number`
- 序列对齐: 贪心匹配，按顺序将 content_list 元素匹配到 markdown 行
- 匹配规则: 去掉 `#` 前缀后子串匹配（任一方是另一方子串）
- 匹配文本最小长度: 2 字符
- 未匹配行: 使用前后最近已分配行的页码插值
- 页码标记格式: `---\n\n# Page {page_number}`（page_number = page_idx + 1，1-based）
- 从后向前插入标记（避免位置偏移）
- 无可匹配内容时: 原样返回 full_md_text

### S-2.2 回退模式 (`_fallback_convert`)

- 当 full.md 不存在时使用
- 按 page_idx 分组，每组输出 `---\n\n# Page N` 标记
- text 类型: 有 text_level 时加 `#` 前缀
- table 类型: 输出 caption + table_body + footnote
- list 类型: 每项加 `- ` 前缀
- image 类型: 输出 `![image](images/{img_idx})`

### S-2.3 PDF 拆分合并 (`pipeline._split_pdf` / `_merge_mineru_results`)

- 超过 200 页的 PDF 自动拆分
- content_list.json 的 page_idx 按起始页码偏移修正
- full.md 直接拼接（用 `\n\n` 连接）

---

## S-3 缓存/增量逻辑

### S-3.1 MinerU 文件缓存

- 缓存文件: `debug_data/01_mineru_json/file_cache.json`
- 键: 文件 base_name
- 值: `{"pdf_sha1": "...", "status": "completed"}`
- PDF SHA1 未变时跳过上传
- PDF SHA1 变动时: 删除旧 md/json/images，重新上传

### S-3.2 向量库增量

- 缓存文件: `databases{suffix}/vector_dbs/embedding_cache.json`
- 键: 文件 base_name
- 值: `{"sha1": "...", "vector_count": N}`
- 新增文件: 只对新文件调 embedding API，追加到已有 FAISS 索引
- 删除文件: 全量重建
- 变动文件: 全量重建

### S-3.3 BM25 缓存

- 缓存文件: `databases{suffix}/bm25_dbs/bm25_cache.json`
- 逻辑同向量库缓存

### S-3.4 分块缓存

- 缓存文件: `databases{suffix}/chunking_cache.json`
- 键: 输入目录路径
- 值: 输入目录内容的 SHA1 哈希
- 哈希未变时跳过分块

### S-3.5 SHA1 计算

- 使用 `hashlib.sha1` 计算文件哈希
- 分块读取（8192 字节），避免大文件内存溢出

---

## S-4 检索行为 (`retrieval.py`)

### S-4.1 MetadataFilteredRetriever 硬过滤

- 过滤条件: company（必须）、broker（可选）、doc_type（可选）
- `soft_doc_type` 不参与硬过滤，仅用于软加权
- 匹配规则: `str(meta.get(key)).strip() == str(value).strip()`

### S-4.2 分级回退

- 层级0: company + broker + doc_type（原始条件，不含 soft_doc_type）
- 层级1: company + broker（去掉 doc_type）
- 层级2: company（去掉 broker）
- 层级3: 全空（触发软过滤模式）
- 最低结果数阈值: `MIN_RESULTS = 3`
- 某层级结果 >= MIN_RESULTS 时使用该层级

### S-4.3 软加权

- 匹配一个元数据字段: 权重 +0.3
- 匹配 N 个字段: 权重 1.0 + 0.3 * N
- `soft_doc_type` 映射到 chunk 的 `doc_type` 字段

### S-4.4 混合检索融合

- BM25 分数归一化: higher_is_better=True（越高越好）
- Vector 分数归一化: higher_is_better=False（距离越小越好，归一化后反转）
- 加权: `hybrid_score = alpha * vector_score + (1-alpha) * bm25_score`（再乘以 boost）
- 默认 alpha=0.5

### S-4.5 父文档检索

- 按 `(page, source_file)` 联合匹配，避免不同 PDF 同页码冲突
- 同一页只返回一次（去重）

### S-4.6 DashScopeReranker（现状: 第二个定义生效）

- 使用原生 HTTP API: `POST https://dashscope.aliyuncs.com/api/v1/services/rerank`
- 模型: `qwen3-rerank`
- 返回: 按 relevance_score 降序排列

### S-4.7 VectorRetriever/BM25Retriever 分库模式（现状: 不可用）

- VectorRetriever 期望 `{company_name}.faiss` 格式索引
- BM25Retriever 期望 `{company_name}.pkl` 格式索引
- 但 Ingestor 只生成 `all_docs.faiss` / `all_docs.pkl`
- **现状**: 使用这两种检索器会因找不到文件而报错

---

## S-5 问答处理 (`questions_processing.py`)

### S-5.1 公司名提取

- `new_challenge_pipeline=True`: 从 subset.csv 公司名列表匹配（按长度降序，排除券商名干扰）
- `new_challenge_pipeline=False`: `re.findall(r'"([^"]*)"', question)` 提取引号内内容

### S-5.2 问题分类

- LLM 分类为: `fact_extraction` / `analysis_explanation` / `prediction_judgment`
- 不在以上三类的归为 `string`

### S-5.3 问题重写

- LLM 返回: `{"rewritten_query": "...", "doc_type": "..."}`
- doc_type 可选值: `年报` / `券商研报` / `调研纪要`

### S-5.4 元数据过滤构建 (`build_metadata_filters`)

- 公司名: 从问题文本中匹配 subset.csv 公司名（排除券商名干扰）
- 券商名: 优先从 `question_source` 的【】内解析，其次从问题文本匹配
- doc_type:
  - source 标注的: 硬过滤（`filters["doc_type"]`）
  - LLM 推断的: 仅软加权（`filters["soft_doc_type"]`）
- source 解析规则:
  - `【财报】` -> doc_type="年报"
  - `【券商名】` -> broker=券商名, doc_type="券商研报"
  - 含"调研纪要" -> doc_type="调研纪要"

### S-5.5 页码校验 (`_validate_page_references`)

- 过滤: 只保留检索结果中存在的页码
- 补充: 不足 `min_pages=2` 时从检索结果按顺序补充
- **现状**: 补充的页可能与答案无关

### S-5.6 引用提取

- `_extract_references_with_traceability`: 含 source_file 溯源
- sha1 匹配: 从 subset.csv 的 file_name 与 chunk 的 source_file 做核心部分匹配
- N/A 答案时 references 清空为 []

### S-5.7 比较类问题

- 先将比较问题重写为单公司问题
- 并行处理每个公司
- 去重引用（按 pdf_sha1 + page_index 去重）

### S-5.8 答案输出格式

- `new_challenge_pipeline=True`: `{"question_text", "kind", "value", "references", "answer_details"}`
- `new_challenge_pipeline=False`: `{"question", "schema", "answer", "answer_details"}`

---

## S-6 JSON 解析行为 (`api_requests.py`)

### S-6.1 Markdown 代码块剥离

- 检测 ``` 开头: 找到第一个 ``` 后的换行，到最后一个 ``` 之间的内容
- 4 处实现（send_message, _send_message_openai_compat, send_message_stream 后处理, answer_single_question_stream 后处理）
- **现状**: 4 处实现略有差异但核心逻辑相同

### S-6.2 JSON 解析失败兜底

- 解析失败时返回: `{"final_answer": content, "step_by_step_analysis": "", "reasoning_summary": "", "relevant_pages": []}`

### S-6.3 response_data 副作用

- `self.response_data` 在每次 API 调用后更新
- **现状**: 多线程环境下存在竞态条件

---

## S-7 公司名提取（Pipeline 层）

### S-7.1 文件名提取规则

- 有【】时: 取【】内内容
  - 如果【】内是"财报"等词: 取】和：之间的内容作为公司名
  - 如果【】内是券商名: 取】和：之间的内容作为公司名
- 无【】时: 从已有公司名列表匹配（按长度降序）
- 无匹配时: 整个文件名（去扩展名）作为 company_name

### S-7.2 subset.csv 操作

- 新文件: 生成 `stock_{5位随机hex}` 格式 sha1
- 已存在文件: 跳过，返回已有 sha1
- 写入编码: utf-8-sig（带 BOM）
- 读取编码: utf-8 -> gbk 降级

---

## S-8 图片描述 (`image_description.py`)

### S-8.1 表格/图表判断

- `is_table_or_chart(image_path)`: 调用多模态模型判断
- 返回 True 时跳过描述生成

### S-8.2 描述生成

- 非表格图表图片: 调用多模态模型生成描述
- 在 markdown 中将图片引用替换为 `**[图片描述: {desc}]**`

### S-8.3 缓存

- 缓存文件: `image_desc_cache.json`
- 键: 报告名
- 值: `{"status": "completed"/"no_images"/"partial", "described_count": N, "total_count": M}`
- status 为 completed 或 no_images 时跳过

---

## S-9 DashScopeReranker 同名覆盖（现状）

- `reranking.py` 中定义了两个 `DashScopeReranker` 类
- 第二个覆盖第一个
- 第一个: OpenAI 兼容接口 `client.rerank.create()`
- 第二个: 原生 HTTP API `requests.post()`
- **当前生效的是第二个定义**

---

## S-10 Pipeline 流式问答内联（现状）

- `answer_single_question_stream` 在 Pipeline 中重新实现了完整问答流程
- 未复用 QuestionsProcessor
- 差异: 问题重写+分类并行执行（QuestionsProcessor 中串行）
- Prompt 选择: 按 question_category 选择（fact/analysis/prediction/string）
