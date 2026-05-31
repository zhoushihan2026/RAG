#!/bin/bash

# AutoDL GPU服务器 - RAG项目一键部署脚本
# 使用方法: bash deploy_on_autodl.sh

set -e  # 遇到错误立即退出

echo "=========================================="
echo "  RAG项目 AutoDL 部署脚本"
echo "  GPU: RTX 4090 | 内存: 120GB"
echo "=========================================="

# ===== 第1步: 配置环境 =====
echo ""
echo "[1/6] 配置Python环境..."
conda activate rag || conda create -n rag python=3.10 -y && conda activate rag

# ===== 第2步: 安装依赖 =====
echo ""
echo "[2/6] 安装项目依赖..."
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
pip install faiss-gpu sentence-transformers transformers torch torchvision --index-url https://download.pytorch.org/whl/cu118 --quiet

# ===== 第3步: 解压模型 =====
echo ""
echo "[3/6] 解压模型文件..."
cd /root/autodl-tmp

if [ ! -d "embedding/Qwen3-Embedding-4B" ]; then
    echo "错误: 未找到 embedding 目录，请先上传 models.tar.gz"
    exit 1
fi

if [ ! -d "reranker/bge-reranker-v2-m3" ]; then
    echo "错误: 未找到 reranker 目录，请先上传 models.tar.gz"
    exit 1
fi

echo "✓ 模型文件验证通过"

# ===== 第4步: 清理旧数据 =====
echo ""
echo "[4/6] 清理旧的中间数据..."
cd /root/autodl-tmp/RAG-cy
rm -rf data/stock_data/databases/chunked_reports/*
rm -rf data/stock_data/databases/vector_dbs/*
rm -rf data/stock_data/databases/bm25_dbs/*
rm -f data/stock_data/answers.json
echo "✓ 旧数据清理完成"

# ===== 第5步: 验证GPU环境 =====
echo ""
echo "[5/6] 验证GPU环境..."
python -c "
import torch
print(f'PyTorch版本: {torch.__version__}')
print(f'CUDA可用: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU名称: {torch.cuda.get_device_name(0)}')
    print(f'显存大小: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB')
"

# ===== 第6步: 运行Pipeline =====
echo ""
echo "[6/6] 启动RAG Pipeline..."
echo "预计耗时: 5-10分钟（RTX 4090加速）"
echo ""

python src/pipeline.py

echo ""
echo "=========================================="
echo "  ✓ Pipeline执行完成！"
echo "  输出文件: data/stock_data/answers.json"
echo "=========================================="
