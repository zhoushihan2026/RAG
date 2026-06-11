## 一句话目标
> 将 MetadataFilteredRetriever 和 QuestionsProcessor 改为单例缓存，避免每次请求重复加载索引和初始化处理器，将首次请求后的检索准备时间从 ~15s 降到 <1s。

## 数据模型

### 缓存键
| 字段 | 类型 | 说明 |
|---|---|---|
| vector_db_dir | str | 向量库目录路径 |
| documents_dir | str | 文档目录路径 |
| bm25_db_dir | str | BM25索引目录路径 |
| metadata_path | str | 元数据文件路径 |
| alpha | float | 混合检索权重 |

缓存键 = (vector_db_dir, documents_dir, bm25_db_dir, metadata_path, alpha)，相同键复用同一实例。

### 缓存实例
| 类 | 缓存位置 | 生命周期 |
|---|---|---|
| MetadataFilteredRetriever | 模块级全局变量 | 进程生命周期 |
| QuestionsProcessor | RAGPipeline 实例属性 | Pipeline 实例生命周期 |

## 接口变更

### MetadataFilteredRetriever
| 动作 | 输入 | 成功返回 | 失败情况 |
|---|---|---|---|
| get_instance (类方法) | vector_db_dir, documents_dir, bm25_db_dir, metadata_path, alpha | 缓存的或新创建的实例 | 路径不存在时抛 FileNotFoundError |
| clear_cache (类方法) | 无 | None | - |

### QuestionsProcessor
| 动作 | 输入 | 成功返回 | 失败情况 |
|---|---|---|---|
| _create_processor | 同现有 | 缓存的或新创建的实例 | - |

### _get_llm_processor
| 动作 | 输入 | 成功返回 | 失败情况 |
|---|---|---|---|
| 获取LLM处理器 | api_provider | 每次创建新实例 | - |

> **v2 修订**: 不缓存 LLM 处理器，每次请求创建新实例。
> 原因：`_rewrite_and_classify_parallel` 会同时持有两个 LLM 处理器引用做并发调用（classify + rewrite）。
> 若缓存为同一实例，两个线程共享同一个 OpenAI client（底层 httpx.Client 不支持多线程同步并发），
> 会造成线程竞争，请求挂起或超时。创建 Fe8Processor 仅初始化 OpenAI client，耗时可忽略。

## 行为规则

1. **MetadataFilteredRetriever 单例**：相同参数只创建一次，后续请求直接返回缓存实例。
2. **QuestionsProcessor 复用**：Pipeline 实例内复用同一个 QuestionsProcessor，不重复创建。
3. **LLM处理器不缓存**：每次调用创建新实例，避免多线程并发共享 httpx.Client 导致线程竞争。
4. **首次调用正常初始化**：缓存为空时，行为与修改前完全一致。
5. **clear_cache 可重置**：调用后下次 get_instance 会重新加载索引（用于数据更新场景）。
6. **线程安全**：缓存读写需加锁，防止并发请求时重复创建。

## 边界

- 首次请求：缓存为空，需完整加载，行为不变
- 参数不同：不同参数组合应创建不同实例
- 数据更新后：需手动调用 clear_cache 才能加载新数据
- 并发请求：多个请求同时到达时，只创建一个实例
- 进程重启：缓存自动清空，下次请求重新加载

## 明确不做

- 不做自动检测数据变更并刷新缓存
- 不做缓存过期时间（TTL）
- 不做分布式缓存
- 不修改 retrieve 方法本身的逻辑
- 不修改前端代码
