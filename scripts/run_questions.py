import sys
sys.path.insert(0, '.')
from src.pipeline import Pipeline, hybrid_bm25_vector_config
from pathlib import Path

root_path = Path('data/stock_data')
pipeline = Pipeline(root_path, run_config=hybrid_bm25_vector_config)

print('8. 处理问题，生成答案...')
pipeline.process_questions()

print('完成!')
