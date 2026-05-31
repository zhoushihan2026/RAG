#!/bin/bash
# AutoDL GPU服务器 - RAG项目完整部署脚本（含模型下载）
# 使用方法: bash autodl_deploy.sh

set -e

echo "================================================"
echo "  RAG项目 AutoDL 一键部署"
echo "  GPU: RTX 4090 | 预计总耗时: 15-20分钟"
echo "================================================"

# ===== 第1步：配置环境 =====
echo ""
echo "[1/7] 配置Python环境..."
source /etc/profile
conda activate rag 2>/dev/null || {
    conda create -n rag python=3.10 -y
    conda activate rag
}
echo "✓ Python环境就绪"

# ===== 第2步：安装依赖 =====
echo ""
echo "[2/7] 安装依赖包（约2-3分钟）..."
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    aiohttp tiktoken python-dotenv pydantic openai requests tqdm \
    rank-bm25 tabulate docling pyprojroot PyPDF2 pandas faiss-gpu \
    langchain json_repair google-generativeai click httpx --quiet

pip install sentence-transformers transformers torch torchvision \
    --index-url https://download.pytorch.org/whl/cu118 --quiet
echo "✓ 依赖安装完成"

# ===== 第3步：下载Embedding模型 =====
echo ""
echo "[3/7] 下载 Qwen3-Embedding-4B 模型（约8GB，5-10分钟）..."
mkdir -p /root/autodl-tmp/embedding
export HF_ENDPOINT=https://hf-mirror.com

python << 'EOF'
from sentence_transformers import SentenceTransformer
import os
model_path = "/root/autodl-tmp/embedding/Qwen3-Embedding-4B"
if not os.path.exists(os.path.join(model_path, "config.json")):
    model = SentenceTransformer("Qwen/Qwen3-Embedding-4B", cache_folder="/root/autodl-tmp/embedding")
    print(f"✓ Embedding模型已保存到 {model_path}")
else:
    print(f"✓ Embedding模型已存在: {model_path}")
EOF

# ===== 第4步：下载Reranker模型 =====
echo ""
echo "[4/7] 下载 bge-reranker-v2-m3 模型（约2GB，2-3分钟）..."
mkdir -p /root/autodl-tmp/reranker

python << 'EOF'
from huggingface_hub import snapshot_download
import os
model_path = "/root/autodl-tmp/reranker/bge-reranker-v2-m3"
if not os.path.exists(os.path.join(model_path, "config.json")):
    snapshot_download(
        "BAAI/bge-reranker-v2-m3",
        local_dir=model_path,
        local_dir_use_symlinks=False
    )
    print(f"✓ Reranker模型已保存到 {model_path}")
else:
    print(f"✓ Reranker模型已存在: {model_path}")
EOF

# ===== 第5步：验证模型 =====
echo ""
echo "[5/7] 验证模型文件..."
python << 'EOF'
import os
emb_path = "/root/autodl-tmp/embedding/Qwen3-Embedding-4B"
rerank_path = "/root/autodl-tmp/reranker/bge-reranker-v2-m3"

assert os.path.exists(os.path.join(emb_path, "config.json")), "Embedding模型不完整!"
assert os.path.exists(os.path.join(rerank_path, "config.json")), "Reranker模型不完整!"

# 检查GPU
import torch
print(f"\n✓ PyTorch版本: {torch.__version__}")
print(f"✓ CUDA可用: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"✓ GPU名称: {torch.cuda.get_device_name(0)}")
    print(f"✓ 显存大小: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB")
EOF

echo "✓ 模型验证通过"

# ===== 第6步：检查项目代码 =====
echo ""
echo "[6/7] 检查项目代码..."
if [ ! -d "/root/autodl-tmp/RAG-cy/src" ]; then
    echo ""
    echo "⚠️  未找到项目代码！请先上传 RAG-cy.tar.gz 到服务器"
    echo ""
    echo "操作步骤:"
    echo "  1. 在本地PowerShell执行:"
    echo "     cd D:\\"
    echo "     scp RAG-cy.tar.gz root@116.136.52.35:/root/autodl-tmp/"
    echo ""
    echo "  2. 然后在AutoDL终端解压:"
    echo "     cd /root/autodl-tmp"
    echo "     tar -xzvf RAG-cy.tar.gz"
    echo ""
    echo "  3. 最后重新运行此脚本"
    exit 1
fi
echo "✓ 项目代码就绪"

# ===== 第7步：清理旧数据并运行Pipeline =====
echo ""
echo "[7/7] 清理旧数据并启动Pipeline..."
cd /root/autodl-tmp/RAG-cy

rm -rf data/stock_data/databases/chunked_reports/*
rm -rf data/stock_data/databases/vector_dbs/*
rm -rf data/stock_data/databases/bm25_dbs/*
rm -f data/stock_data/answers.json
echo "✓ 旧数据清理完成"

echo ""
echo "================================================"
echo "  开始运行 RAG Pipeline (预计5-10分钟)"
echo "================================================"

python src/pipeline.py

if [ $? -eq 0 ]; then
    echo ""
    echo "================================================"
    echo "  ✓ 部署完成！输出文件:"
    echo "  → data/stock_data/answers.json"
    echo "================================================"
else
    echo ""
    echo "❌ Pipeline执行失败，请检查错误信息"
    exit 1
fi
