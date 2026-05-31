"""
测试DashScope Rerank API是否正常工作
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到sys.path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

def test_rerank_api():
    """测试DashScope Rerank API"""
    print("=" * 60)
    print("测试1：检查环境变量")
    print("=" * 60)

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if api_key:
        print(f"[OK] DASHSCOPE_API_KEY 已设置 (长度: {len(api_key)})")
        print(f"   Key前缀: {api_key[:10]}...")
    else:
        print("[FAIL] DASHSCOPE_API_KEY 未设置！")
        return False

    print("\n" + "=" * 60)
    print("测试2：导入LocalReranker并初始化")
    print("=" * 60)

    try:
        from src.reranking import LocalReranker
        print("[OK] 成功导入 LocalReranker")

        reranker = LocalReranker()
        print(f"[OK] LocalReranker 初始化成功")
        print(f"   _model_available: {LocalReranker._model_available}")

        if not LocalReranker._model_available:
            print("\n[!!!] 关键发现：Reranker 未成功初始化！")
            print("   这意味着所有检索结果都没有经过精排！")
            return False

    except Exception as e:
        print(f"[FAIL] LocalReranker 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("测试3：实际调用Rerank API")
    print("=" * 60)

    test_query = "中芯国际2024年营业收入"
    test_docs = [
        {"text": "中芯国际2024年营业收入为577.96亿元", "page": 10},
        {"text": "公司总资产为3534亿元", "page": 5},
        {"text": "产能利用率达到89.6%", "page": 3},
        {"text": "研发投入占收入比例", "page": 20},
    ]

    try:
        results = reranker.rerank(
            query=test_query,
            documents=test_docs,
            top_n=2
        )

        print(f"[OK] Rerank API 调用成功！")
        print(f"\n查询: {test_query}")
        print(f"\n重排结果:")
        for i, doc in enumerate(results, 1):
            score = doc.get('relevance_score', doc.get('rerank_score', 'N/A'))
            text = doc['text'][:50] + "..." if len(doc['text']) > 50 else doc['text']
            print(f"  {i}. [score={score}] {text}")

        # 验证排序是否合理
        if len(results) > 0:
            first_score = results[0].get('relevance_score', results[0].get('rerank_score', 0))
            if first_score > 0:
                print(f"\n[!!!] Rerank 正常工作！分数 > 0 说明进行了有效重排")
                return True
        else:
            print(f"\n[WARN] Rerank 返回的分数都是0或不存在，可能未真正执行重排")
            return False

    except Exception as e:
        print(f"[FAIL] Rerank API 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_rerank_api()

    print("\n" + "=" * 60)
    print("最终结论")
    print("=" * 60)

    if success:
        print("[OK] Rerank 功能正常，系统应该能获得更好的检索质量")
        print("\n如果得分仍然不高，需要从其他方面优化：")
        print("  1. 元数据过滤策略")
        print("  2. chunk_size配置")
        print("  3. 问题重写Prompt")
        print("  4. top_n_retrieval数量")
    else:
        print("[!!!] Rerank 功能异常！这就是得分低的主要原因！")
        print("\n影响：")
        print("  - 系统只使用了 BM25+Vector 混合检索的粗排结果")
        print("  - 缺少了最关键的精排步骤")
        print("  - 导致返回给LLM的上下文相关性不够高")
        print("\n解决方案：")
        print("  1. 检查 DASHSCOPE_API_KEY 环境变量是否正确设置")
        print("  2. 检查网络连接是否能访问 dashscope.aliyuncs.com")
        print("  3. 检查 API 账户余额和配额")
        print("  4. 检查 reranking.py 中的模型名称是否正确")
