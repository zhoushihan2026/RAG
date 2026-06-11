import sys
sys.path.insert(0, '.')
import os
from src.pipeline import Pipeline, hybrid_bm25_vector_config
from src.constants import DEFAULT_DATA_PATH
from pathlib import Path

root_path = Path(os.getenv("RAG_DATA_PATH", DEFAULT_DATA_PATH))
pipeline = Pipeline(root_path, run_config=hybrid_bm25_vector_config)

print('8. 处理问题，生成答案...')
pipeline.process_questions()

print('完成!')
