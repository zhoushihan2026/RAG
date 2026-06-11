import sys
sys.path.insert(0, '.')
import os
from src.pipeline import Pipeline, hybrid_bm25_vector_config
from src.constants import DEFAULT_DATA_PATH
from pathlib import Path

root_path = Path(os.getenv("RAG_DATA_PATH", DEFAULT_DATA_PATH))
pipeline = Pipeline(root_path, run_config=hybrid_bm25_vector_config)

print('5. 重新分块...')
pipeline.chunk_reports()

print('6. 重建向量库...')
pipeline.create_vector_dbs()

print('7. 重建BM25索引...')
pipeline.create_bm25_db()

print('完成!')
