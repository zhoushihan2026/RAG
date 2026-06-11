"""
项目业务常量集中定义
将分散在各模块中的硬编码常量统一管理，避免重复定义和遗漏
"""

# 已知券商名列表（用于排除券商名干扰、识别文档类型、提取元数据）
KNOWN_BROKERS = ["东方证券", "光大证券", "国信证券", "上海证券", "中原证券", "兴证国际", "华泰证券"]

# 文档类型识别关键词映射
DOC_TYPE_KEYWORDS = {
    "年报": ["【财报】", "年报"],
    "券商研报": KNOWN_BROKERS,
    "调研纪要": ["调研纪要"],
}

# 按文档类型差异化的分块参数
CHUNK_CONFIG_BY_DOC_TYPE = {
    "年报": {"chunk_size": 800, "chunk_overlap": 100},
    "券商研报": {"chunk_size": 600, "chunk_overlap": 100},
    "调研纪要": {"chunk_size": 600, "chunk_overlap": 100},
}

# 未识别文档类型时的默认分块参数
DEFAULT_CHUNK_CONFIG = {"chunk_size": 300, "chunk_overlap": 50}

# 默认行业（当 subset.csv 中无 industry 列时使用）
DEFAULT_INDUSTRY = "半导体"

# 默认数据路径
DEFAULT_DATA_PATH = "data/stock_data"
