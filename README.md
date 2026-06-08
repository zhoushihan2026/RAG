# RAG-zsh 企业知识库问答系统

基于大语言模型的 RAG（检索增强生成）智能问答系统，专注于证券研报与企业年报的文档解析、混合检索与精准问答。

## 核心功能

- **PDF 文档解析**：集成 MinerU（主）与 Docling 两种解析引擎，支持表格、图表、图片的结构化提取
- **多路混合检索**：BM25 关键词检索 + FAISS 向量语义检索 + DashScope Rerank 精排
- **LLM 智能问答**：支持 OpenAI / DashScope（通义千问）/ Gemini / fe8.cn（GPT 系列）等多种大模型
- **多轮对话记忆**：支持追问、代词消解、问题重写，自动补全歧义追问的上下文
- **对话历史管理**：侧边栏会话列表，支持新建、切换、重命名、删除会话
- **React + FastAPI Web 界面**：侧边栏 + 对话区布局，SSE 流式输出，思考动画 + 打字机效果
- **灵活配置系统**：通过 RunConfig 可自由组合不同检索策略和模型

## 技术架构

### 系统组件关系图

展示各模块之间的依赖与数据流向：

![技术架构图](docs/architecture.png)

### 系统全流程图

包含**知识入库流程**（离线/增量）和**用户提问流程**（在线/实时）两条主线：

![全流程图](docs/flowchart.png)


## 快速开始

### 环境准备

```bash
# 克隆项目
git clone <your-repo-url>
cd RAG-zsh

# 创建虚拟环境
python -m venv venv
venv\Scripts\Activate.ps1   # Windows (PowerShell)

# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖
cd web
npm install
cd ..
```

### 配置 API Key

复制 `.env.example` 为 `.env`，并填入你的 API 密钥：

```bash
cp .env.example .env
# 然后编辑 .env 文件，填入真实的 API Key
```

必填项：
- `FE8_API_KEY`：fe8.cn API Key（用于 GPT-3.5-turbo 问题重写 + GPT-4-turbo 回答生成）
- `DASHSCOPE_API_KEY`：DashScope API Key（用于 Embedding 向量化 + Rerank 重排序）

### 运行方式

#### 方式一：Web 界面（推荐）

```bash
# 启动后端（终端 1）
uvicorn api.app:app --host 127.0.0.1 --port 8000

# 启动前端（终端 2）
cd web
npm run dev
```

浏览器打开 http://127.0.0.1:5173 即可使用。

#### 方式二：CLI 命令行

```bash
# 查看所有可用命令
python main.py --help

# 下载 Docling 模型
python main.py download-models

# 解析 PDF 报告（支持并行）
python main.py parse-pdfs --parallel --chunk-size 2 --max-workers 10

# 序列化表格
python main.py serialize-tables

# 处理报告（分块+向量化）
python main.py process-reports --config no_ser_tab

# 批量回答问题
python main.py process-questions --config hybrid_bm25_vector
```

#### 方式三：直接运行 pipeline

编辑 `src/pipeline.py` 底部的 `__main__` 部分，取消注释需要执行的步骤：

```bash
python src/pipeline.py
```

## 项目结构

```
RAG-zsh/
├── api/                       # FastAPI 后端
│   └── app.py                 # API 路由（SSE 流式问答、会话管理、文件上传、知识库状态）
│
├── web/                       # React 前端
│   ├── src/
│   │   ├── App.tsx            # 主应用组件（含侧边栏布局）
│   │   ├── api/index.ts       # API 调用封装（含会话管理 API）
│   │   ├── components/        # UI 组件
│   │   │   ├── Sidebar.tsx    # 侧边栏（会话列表、新建/重命名/删除）
│   │   │   ├── AssistantMessage.tsx  # 助手消息（分段渲染）
│   │   │   ├── InputBar.tsx   # 输入栏
│   │   │   └── ...            # 其他组件
│   │   └── types/index.ts     # TypeScript 类型定义
│   ├── vite.config.ts         # Vite 配置（含代理）
│   └── package.json
│
├── main.py                    # CLI 命令行入口
├── setup.py                   # 包安装配置
├── requirements.txt           # Python 依赖
│
├── scripts/                   # 运行脚本与部署脚本
│   ├── run_evaluation.py     # 运行评估
│   ├── run_questions.py      # 运行问答
│   ├── run_rebuild.py        # 重建索引
│   └── autodl_deploy.sh      # AutoDL 部署脚本
│
├── src/                       # 核心源代码
│   ├── pipeline.py           # 主流程调度与配置管理
│   ├── api_requests.py       # LLM API 统一封装（OpenAI/DashScope/Gemini/fe8）
│   ├── api_request_parallel_processor.py  # 并发请求处理器
│   ├── session_manager.py    # 会话管理（创建、历史截断、过期清理）
│   ├── retrieval.py          # 四种检索器实现
│   ├── reranking.py          # DashScope Rerank 重排序
│   ├── ingestion.py          # 向量库与 BM25 索引构建
│   ├── questions_processing.py  # 问答核心逻辑（含追问扩展、历史摘要）
│   ├── pdf_mineru_z.py       # MinerU PDF 解析（增强版）
│   ├── pdf_parsing.py        # Docling PDF 解析
│   ├── text_splitter_z.py    # 文本分块（增强版）
│   ├── tables_serialization.py  # 表格序列化
│   ├── image_description.py  # 图片智能描述
│   ├── merge_json_to_markdown.py  # JSON 转 Markdown
│   ├── parsed_reports_merging.py  # 报告规整
│   └── prompts.py            # Prompt 与 Schema 定义（含历史重写、分段输出）
│
├── data/                     # 数据目录
│   └── stock_data/           # 证券研报数据集
│       ├── pdf_reports/      # 原始 PDF 文件
│       ├── questions.json    # 待回答的问题列表
│       ├── answers/          # 生成的答案
│       ├── databases/        # 检索索引（FAISS向量库/BM25，支持增量更新）
│       └── debug_data/       # 调试中间数据
│
├── tests/                    # 测试
│   ├── api/                  # API 端点测试
│   ├── chunking/             # 分块测试
│   ├── image/                # 图片描述测试
│   ├── pipeline/             # Pipeline 测试
│   ├── qa/                   # 问答逻辑测试
│   ├── retrieval/            # 检索测试
│   └── session/              # 会话管理测试
│
├── spec/                     # 设计规范文档
│   ├── api-spec.md           # API 契约规范
│   ├── frontend-spec.md      # 前端交互规范
│   ├── behavior-spec.md      # 行为规范
│   ├── legacy-audit.md       # 遗留代码审计
│   └── v2-spec.md            # v2 多轮对话规格说明
│
├── docs/                     # 文档与图表
│   ├── src_modules_overview.md  # 模块详细说明
│   ├── architecture.drawio      # 技术架构图（draw.io 源文件）
│   └── flowchart.drawio         # 系统全流程图（draw.io 源文件）
└── reference/                # 参考代码
```

## v2 新增功能

### 多轮对话记忆

- 用户可以追问（如"它的毛利率呢？"），系统自动补全上下文（"中芯国际2024年全年的毛利率是多少？"）
- 对话历史注入问题重写，实现代词消解和省略补全
- 追问检索增强：从前一轮问题中提取财务术语关键词，合并到检索查询中
- 历史截断策略：保留最近 5 轮对话，总字符数不超过 6000

### 对话历史管理

- 侧边栏会话列表，按最后活跃时间倒序排列
- 新建对话、切换会话、重命名标题、删除会话
- 首条用户消息自动设置会话标题（前 20 字）
- 会话上限 50 条用户消息，过期会话可清理

### 模型配置

| 用途 | 模型 | API 提供方 |
|------|------|-----------|
| 问题重写 + 分类 | gpt-3.5-turbo | fe8.cn |
| 查询向量化 | text-embedding-v4 | DashScope |
| 检索结果重排 | qwen3-rerank | DashScope |
| 生成最终回答 | gpt-4-turbo | fe8.cn |

### 回答分段

所有回答按要点分段输出，不同指标、核心结论与补充说明分别成段，提升可读性。

## 可用配置 (RunConfig)

| 配置名 | 说明 | 特点 |
|--------|------|------|
| `base` | 基础配置 | 向量检索 + GPT-4o-mini |
| `pdr` | 父文档检索 | 检索 chunk 后返回整页内容 |
| `max` | 全功能配置 | 父文档检索 + LLM 重排 |
| `hybrid_bm25_vector` | BM25 + 向量混合召回 + DashScope Rerank | |
| `hybrid_bm25_vec_rerank_fe8_gpt4` | **v2 推荐配置** | BM25 + 向量混合 + Rerank + fe8 GPT 模型 |

## 数据集说明

当前内置数据集为 **中芯国际证券研报与年报**，包含：
- 8 份 PDF 研报/年报（上海证券、东方证券、光大证券等）
- 覆盖营收、利润、产能、研发等多维度问题

可通过修改 `data/stock_data/questions.json` 自定义问题。

## 主要依赖

### 后端 (Python)

- `fastapi` - Web API 框架
- `uvicorn` - ASGI 服务器
- `faiss-cpu` - 向量相似度检索
- `rank-bm25` - BM25 关键词检索
- `dashscope` - 通义千问 API + Embedding + Rerank
- `openai` - OpenAI 兼容 API（fe8.cn）
- `sentence-transformers` - 句子向量化
- `PyPDF2` - PDF 处理工具

### 前端 (TypeScript)

- `react` - UI 框架
- `vite` - 构建工具
- `tailwindcss` - CSS 框架
- `shadcn/ui` - UI 组件库

## 版本历史

| 版本 | Tag | 说明 |
|------|-----|------|
| v1 | `v1` | 单轮对话，无记忆，居中单栏布局 |
| v2 | - | 多轮对话记忆 + 侧边栏会话管理 + fe8 GPT 模型 |

## License

MIT
