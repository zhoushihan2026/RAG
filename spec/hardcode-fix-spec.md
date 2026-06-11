# RAG-cy 硬编码修复规格

> 审计日期: 2026-06-08
> 审计范围: `src/`, `api/`, `scripts/`, `app_streamlit.py`, `.env`, `.gitignore`
> 原则: 每个问题给出现状分析、是否真风险、推荐方案

---

## 审计修正说明

初次审计中有以下误判，已从问题列表中移除：

1. **`.env` 中 API Key 明文** — `.env` 已在 `.gitignore` 第118行排除，且项目有 `.env.example` 模板。Key 不会进入版本控制，不属于硬编码风险。

2. **`BaseOpenaiProcessor` 的 `base_url` fallback `"https://api.fe8.cn/v1"`** — 该类是遗留代码，当前主流程通过 `APIProcessor(provider=...)` 路由到 `Fe8Processor` 或 `BaseDashscopeProcessor`，`BaseOpenaiProcessor` 仅在 `provider="openai"` 时使用，而主流程不选此 provider。fallback 值在非预期场景下才会触发，属于低优先级。

3. **`BaseIBMAPIProcessor` 的 `base_url = "https://rag.timetoact.at/ibm"`** — 同上，IBM processor 是实验性功能，不在主流程中使用。且该 URL 是 IBM API 的唯一入口，不存在"换环境"的场景，硬编码合理。

4. **`JinaReranker` 的 `url = 'https://api.jina.ai/v1/rerank'`** — JinaReranker 是遗留代码，当前主流程使用 `DashScopeReranker`/`LocalReranker`。且 API URL 是服务唯一入口，硬编码合理。

5. **`DashScopeReranker` 的 `url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/..."`** — DashScope API 的固定端点，不存在多环境切换需求，硬编码合理。同理 `DashScopeEmbedding` 和 `BaseDashscopeProcessor` 中的 `base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"` 也是固定端点。

6. **`pdf_mineru_z.py` 的 `base_url = "https://mineru.net/api/v4"`** — MinerU 云服务的固定端点，硬编码合理。

7. **`FOLLOWUP_STOPWORDS` 和 `FINANCIAL_TERMS` 集合** — 领域知识词表，与业务逻辑强耦合，不适合外部配置。硬编码合理。

8. **`MINERU_MAX_PAGES = 200`** — MinerU API 的硬性限制，不是可调参数。作为类属性已合理。

9. **`encoding="utf-8"` / `encoding="gbk"`** — 文件读写的编码声明，不是配置项。硬编码合理。

10. **`o200k_base` 编码名** — tiktoken 的编码名，由使用的模型决定（GPT-4o 系列），不是可配置项。

---

## 确认的硬编码问题及修复方案

### HC-01: KNOWN_BROKERS 列表重复定义 4 次

**现状**:
```python
# questions_processing.py:97, :178, :626
# text_splitter_z.py:234
KNOWN_BROKERS = ["东方证券", "光大证券", "国信证券", "上海证券", "中原证券", "兴证国际", "华泰证券"]
```
同一列表在 4 个位置独立定义。新增券商需改 4 处，极易遗漏导致元数据提取不一致。

**风险**: 新增券商时遗漏某处 -> 券商名被误识别为公司名 -> 元数据过滤失效 -> 检索结果错误

**推荐方案**: 新建 `src/constants.py`，集中定义所有业务常量：

```python
# src/constants.py
KNOWN_BROKERS = ["东方证券", "光大证券", "国信证券", "上海证券", "中原证券", "兴证国际", "华泰证券"]

DOC_TYPE_KEYWORDS = {
    "年报": ["【财报】", "年报"],
    "券商研报": KNOWN_BROKERS,
    "调研纪要": ["调研纪要"],
}

DEFAULT_INDUSTRY = "半导体"
```

4 处引用改为 `from src.constants import KNOWN_BROKERS`。同时 `text_splitter_z.py` 中 `split_markdown_reports` 方法里按券商名判断 doc_type 的逻辑（第638-647行）也改为引用 `DOC_TYPE_KEYWORDS`。

**影响范围**: `questions_processing.py`, `text_splitter_z.py`
**兼容性**: 纯重构，行为不变

---

### HC-02: industry="半导体" 硬编码

**现状**:
```python
# text_splitter_z.py:683
chunk["industry"] = "半导体"
```
行业字段写死为"半导体"，换行业场景需改源码。且该字段当前未被检索/过滤使用，仅作为元数据存储。

**风险**: 低。当前仅影响元数据完整性，不影响检索逻辑。但扩展到其他行业时会出错。

**推荐方案**: 从 `subset.csv` 中读取行业信息。如果 CSV 中无 industry 列，则使用 `constants.py` 中的 `DEFAULT_INDUSTRY`。

```python
# text_splitter_z.py split_markdown_reports() 中
file2industry = {}
if 'industry' in df.columns:
    for _, row in df.iterrows():
        file_no_ext = str(row.get('file_name', '')).rsplit('.', 1)[0]
        file2industry[file_no_ext] = str(row['industry']).strip()

# 赋值时
chunk["industry"] = file2industry.get(base_name, DEFAULT_INDUSTRY)
```

**影响范围**: `text_splitter_z.py`, `constants.py`
**兼容性**: 无 industry 列时回退到默认值"半导体"，行为不变

---

### HC-03: 分块参数按文档类型硬编码

**现状**:
```python
# text_splitter_z.py:638-647
if "【财报】" in base_name or "年报" in base_name:
    actual_chunk_size = 800
    actual_chunk_overlap = 100
elif any(broker in base_name for broker in [...]):
    actual_chunk_size = 600
    actual_chunk_overlap = 100
elif "调研纪要" in base_name:
    actual_chunk_size = 600
    actual_chunk_overlap = 100
```
分块参数与文档类型判断逻辑耦合在分块函数内部，无法通过配置调整。

**风险**: 中。调参需要改源码，且文档类型判断逻辑与 HC-01 的 KNOWN_BROKERS 重复。

**推荐方案**: 在 `constants.py` 中定义文档类型到分块参数的映射：

```python
# constants.py
CHUNK_CONFIG_BY_DOC_TYPE = {
    "年报": {"chunk_size": 800, "chunk_overlap": 100},
    "券商研报": {"chunk_size": 600, "chunk_overlap": 100},
    "调研纪要": {"chunk_size": 600, "chunk_overlap": 100},
}
DEFAULT_CHUNK_CONFIG = {"chunk_size": 300, "chunk_overlap": 50}
```

分块函数中根据 `doc_type` 查表获取参数，不再硬编码 if-elif。

**影响范围**: `text_splitter_z.py`, `constants.py`
**兼容性**: 参数值与当前完全一致，行为不变

---

### HC-04: CORS origins 硬编码 8 个 localhost 地址

**现状**:
```python
# api/app.py:73-80
allow_origins=[
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:5174", "http://127.0.0.1:5174",
    "http://localhost:5178", "http://127.0.0.1:5178",
    "http://localhost:5180", "http://127.0.0.1:5180",
]
```
开发端口硬编码，生产部署需手动修改源码。

**风险**: 中。生产环境忘记改 -> CORS 拦截前端请求 -> 功能不可用。且当前列表缺少常见部署端口（如 80、443、8080）。

**推荐方案**: 从环境变量读取，开发环境有合理默认值：

```python
# api/app.py
import os

cors_origins_str = os.getenv("CORS_ORIGINS", "")
if cors_origins_str:
    allow_origins = [origin.strip() for origin in cors_origins_str.split(",")]
else:
    # 开发环境默认值
    allow_origins = [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://localhost:5178", "http://127.0.0.1:5178",
        "http://localhost:5180", "http://127.0.0.1:5180",
    ]
```

`.env.example` 中添加：
```
# CORS 允许的前端来源（逗号分隔，留空则使用开发默认值）
# CORS_ORIGINS=http://localhost:5173,http://localhost:5174
```

**影响范围**: `api/app.py`, `.env.example`
**兼容性**: 无 CORS_ORIGINS 环境变量时行为完全一致

---

### HC-05: RAG_DATA_PATH 默认值硬编码

**现状**:
```python
# api/app.py:89
root_path = Path(os.getenv("RAG_DATA_PATH", "data/stock_data"))
```
默认路径 `data/stock_data` 硬编码。同理 `app_streamlit.py:6`, `scripts/run_questions.py:6`, `scripts/run_rebuild.py:6` 中也有 `Path('data/stock_data')`。

**风险**: 低。`app.py` 已支持环境变量覆盖，但脚本中未支持。且 `data/stock_data` 是项目约定路径，不太会变。

**推荐方案**: 脚本中也使用环境变量，统一默认值到 `constants.py`：

```python
# constants.py
DEFAULT_DATA_PATH = "data/stock_data"
```

```python
# scripts/run_questions.py, run_rebuild.py, app_streamlit.py
from src.constants import DEFAULT_DATA_PATH
root_path = Path(os.getenv("RAG_DATA_PATH", DEFAULT_DATA_PATH))
```

**影响范围**: `constants.py`, `app_streamlit.py`, `scripts/run_questions.py`, `scripts/run_rebuild.py`
**兼容性**: 默认值不变，行为不变

---

### HC-06: session_manager 中截断阈值硬编码在函数体内

**现状**:
```python
# session_manager.py:73-74
MAX_CHARS = 6000   # 约 4000 tokens
SINGLE_MSG_MAX = 3000  # 约 2000 tokens
```
这两个值定义在 `get_history_messages` 方法内部，无法从外部配置。

**风险**: 低。当前值合理，但调参需改源码。

**推荐方案**: 提升为 `SessionManager` 的初始化参数：

```python
class SessionManager:
    def __init__(self, max_user_messages_per_session=50, max_history_rounds=5,
                 max_history_chars=6000, single_msg_max_chars=3000):
        self.max_user_messages = max_user_messages_per_session
        self.max_history_rounds = max_history_rounds
        self.max_history_chars = max_history_chars
        self.single_msg_max_chars = single_msg_max_chars
```

`app.py` 中创建 `SessionManager` 时可传入自定义值。

**影响范围**: `session_manager.py`, `api/app.py`
**兼容性**: 默认参数值与当前一致

---

### HC-07: Embedding 维度 dimensions=1024 硬编码

**现状**:
```python
# retrieval.py:54
response = DashScopeEmbedding._client.embeddings.create(
    model=self._model_name,
    input=batch,
    dimensions=1024
)
```
Embedding 维度与模型绑定（text-embedding-v4 支持 512/1024/2048），当前硬编码为 1024。

**风险**: 低。换模型或换维度时需改源码，但 Embedding 模型切换频率极低，且维度变更需要全量重建向量库。

**推荐方案**: 将维度作为 `DashScopeEmbedding` 的类属性，与模型名放在一起：

```python
class DashScopeEmbedding:
    _client = None
    _model_name = "text-embedding-v4"
    _dimensions = 1024

    def encode(self, texts, ...):
        ...
        response = DashScopeEmbedding._client.embeddings.create(
            model=self._model_name,
            input=batch,
            dimensions=self._dimensions
        )
```

如果未来需要切换维度，只需改一处。

**影响范围**: `retrieval.py`
**兼容性**: 行为不变

---

### HC-08: Embedding batch_size=4 硬编码

**现状**:
```python
# ingestion.py:117
embeddings = self.model.encode(
    text_chunks,
    normalize_embeddings=True,
    show_progress_bar=True,
    batch_size=4
)
```
批量大小硬编码，DashScope API 限流策略变化时需改源码。

**风险**: 低。当前值经过实测稳定，但 API 限流策略可能调整。

**推荐方案**: 将 batch_size 提升为 `VectorDBIngestor` 的初始化参数：

```python
class VectorDBIngestor:
    def __init__(self, embedding_batch_size=4):
        self.model = DashScopeEmbedding()
        self.embedding_batch_size = embedding_batch_size
```

**影响范围**: `ingestion.py`
**兼容性**: 默认值不变

---

### HC-09: Linux 绝对路径作为默认参数（残留死代码）

**现状**:
```python
# ingestion.py:94
def __init__(self, model_path: str = "/root/autodl-tmp/embedding/Qwen/Qwen3-Embedding-4B"):
    self.model = DashScopeEmbedding()  # model_path 未使用！

# retrieval.py:146
EMBEDDING_MODEL_PATH = "/root/autodl-tmp/embedding/Qwen/Qwen3-Embedding-4B"  # 从未引用

# reranking.py:349
def __init__(self, model_path: str = "/root/autodl-tmp/rerank/BAAI/bge-reranker-v2-m3"):
    # model_path 未使用，实际初始化 DashScopeReranker
```
三处 Linux 绝对路径均为**死代码**：项目已从本地模型切换到 DashScope API，这些路径参数从未被使用。`EMBEDDING_MODEL_PATH` 是模块级变量，无任何代码引用。

**风险**: 低（不影响运行），但造成困惑：新开发者看到这些路径会以为需要本地部署模型。

**推荐方案**: 清理死代码：

1. `ingestion.py:94` -- 移除 `model_path` 参数，构造函数改为 `def __init__(self):`
2. `retrieval.py:146` -- 删除 `EMBEDDING_MODEL_PATH = "..."` 整行
3. `reranking.py:349` -- 移除 `model_path` 参数，构造函数改为 `def __init__(self):`

同时清理 `tests/pipeline/test_cache_ingestion.py:200` 中的 `VectorDBIngestor(model_path="/custom/path/to/model")` 测试调用。

**影响范围**: `ingestion.py`, `retrieval.py`, `reranking.py`, `tests/`
**兼容性**: 移除未使用参数，无功能影响

---

### HC-10: 各 Processor 的 default_model 硬编码

**现状**:
```python
# api_requests.py
BaseOpenaiProcessor.default_model = 'gpt-4o-2024-08-06'       # 遗留，主流程不用
BaseIBMAPIProcessor.default_model = 'meta-llama/llama-3-3-70b-instruct'  # 遗留
BaseGeminiProcessor.default_model = 'gemini-2.0-flash-001'    # 遗留
BaseDashscopeProcessor.default_model = 'qwen-turbo-latest'    # 主流程用
Fe8Processor.default_model = 'gpt-3.5-turbo'                  # 主流程用
```
模型名硬编码在各 Processor 类中。但主流程通过 `RunConfig.answering_model` 和 `RunConfig.rewrite_model` 覆盖了默认值，`default_model` 仅在未指定 model 参数时作为 fallback。

**风险**: 低。主流程已通过配置覆盖，默认值仅影响直接调用 Processor 的场景（如测试、脚本）。

**推荐方案**: 不做修改。原因：
1. 主流程已通过 `RunConfig` 控制模型选择，`default_model` 不影响线上行为
2. 每个 Provider 有自己的模型生态（DashScope 用 Qwen、fe8 用 GPT），默认值与 Provider 匹配是合理的
3. 如果强行统一到配置文件，反而增加了 Provider 与模型名不匹配的风险

---

### HC-11: temperature 默认值不统一

**现状**:
```python
# api_requests.py
BaseOpenaiProcessor.send_message(temperature=0.5)      # 遗留
BaseIBMAPIProcessor.send_message(temperature=0.5)      # 遗留
BaseGeminiProcessor.send_message(temperature=0.5)      # 遗留
BaseDashscopeProcessor.send_message(temperature=0.1)   # 主流程
Fe8Processor.send_message(temperature=0.1)             # 主流程
```
遗留 Processor 用 0.5，主流程 Processor 用 0.1，不一致。

**风险**: 低。主流程的 temperature 由调用方显式传入，默认值不影响。

**推荐方案**: 不做修改。原因同 HC-10：主流程已通过调用方控制，默认值仅影响非主流程场景。且遗留 Processor 不在主流程中使用。

---

### HC-12: Gemini seed=12345 硬编码

**现状**:
```python
# api_requests.py:361
seed=12345,  # For back compatibility
```
Gemini Processor 的 seed 硬编码，影响可复现性。但 Gemini Processor 是遗留代码，不在主流程中使用。

**风险**: 极低。遗留代码，不影响主流程。

**推荐方案**: 不做修改。Gemini Processor 属于实验性功能，不在主流程路径上。

---

### HC-13: DashScope Embedding 每批 6 条硬编码

**现状**:
```python
# retrieval.py:60
for i in range(0, len(texts), 6):
    batch = texts[i:i+6]
```
Embedding API 每批处理 6 条，硬编码在循环中。DashScope text-embedding-v4 的限制是每批最多 25 条。

**风险**: 低。当前值保守但稳定，未充分利用 API 吞吐。

**推荐方案**: 将批大小提升为 `DashScopeEmbedding` 的类属性：

```python
class DashScopeEmbedding:
    _model_name = "text-embedding-v4"
    _dimensions = 1024
    _batch_size = 6  # DashScope text-embedding-v4 每批最大 25 条

    def encode(self, texts, ...):
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            ...
```

**影响范围**: `retrieval.py`
**兼容性**: 行为不变

---

## 修复优先级排序

| 优先级 | 编号 | 问题 | 理由 |
|--------|------|------|------|
| P0 | HC-09 | Linux 绝对路径死代码清理 | 零风险，消除困惑，5分钟完成 |
| P0 | HC-01 | KNOWN_BROKERS 重复 4 次 | 最容易出错的硬编码，新增券商必漏 |
| P1 | HC-03 | 分块参数硬编码 | 与 HC-01 联动，一起改 |
| P1 | HC-04 | CORS origins 硬编码 | 生产部署必踩坑 |
| P2 | HC-02 | industry 硬编码 | 当前不影响功能，扩展时才需要 |
| P2 | HC-05 | RAG_DATA_PATH 默认值 | 影响范围小，已有环境变量覆盖 |
| P2 | HC-06 | session 截断阈值 | 调参需求低，但提升可配置性 |
| P3 | HC-07 | Embedding 维度 | 换模型频率极低 |
| P3 | HC-08 | Embedding batch_size | 当前值稳定 |
| P3 | HC-13 | Embedding 每批条数 | 当前值保守但稳定 |
| 不修 | HC-10 | default_model | 主流程已通过配置覆盖 |
| 不修 | HC-11 | temperature 不统一 | 主流程已通过调用方控制 |
| 不修 | HC-12 | Gemini seed | 遗留代码，不影响主流程 |

---

## 实施计划

### 第一步: 新建 constants.py + 清理死代码（HC-01 + HC-09）

1. 创建 `src/constants.py`，集中定义 `KNOWN_BROKERS`、`DOC_TYPE_KEYWORDS`、`CHUNK_CONFIG_BY_DOC_TYPE`、`DEFAULT_CHUNK_CONFIG`、`DEFAULT_INDUSTRY`、`DEFAULT_DATA_PATH`
2. 4 处 `KNOWN_BROKERS` 改为 `from src.constants import KNOWN_BROKERS`
3. 删除 `retrieval.py:146` 的 `EMBEDDING_MODEL_PATH`
4. 移除 `ingestion.py:94` 和 `reranking.py:349` 的 `model_path` 参数
5. 清理测试中的对应调用

### 第二步: 分块参数配置化（HC-03）

1. `text_splitter_z.py` 的 `split_markdown_reports` 方法中，用 `CHUNK_CONFIG_BY_DOC_TYPE` 查表替代 if-elif
2. 文档类型判断逻辑也改用 `DOC_TYPE_KEYWORDS`

### 第三步: CORS 配置化（HC-04）

1. `api/app.py` 从环境变量读取 CORS origins
2. `.env.example` 添加 `CORS_ORIGINS` 说明

### 第四步: 其余低优先级项（HC-02, HC-05, HC-06, HC-07, HC-08, HC-13）

按需逐步推进，每项独立，互不依赖。
