"""
RAG自动化评测脚本
用法：
  1. 评测单个答案文件：
     python run_evaluation.py --answers data/stock_data/answers/answers_hybrid_bm25_vec_rerank_12_19.json

  2. 评测并指定评测模型（默认deepseek-v4-pro）：
     python run_evaluation.py --answers data/stock_data/answers/answers_hybrid_bm25_vec_rerank_12_19.json --model qwen3.6-plus

  3. 对比多个答案文件：
     python run_evaluation.py --answers data/stock_data/answers/answers_hybrid_bm25_vec_rerank_12_19.json data/stock_data/answers/answers_hybrid_bm25_vec_rerank_12_21.json

  4. 指定输出目录（默认与答案文件同目录）：
     python run_evaluation.py --answers data/stock_data/answers/answers_hybrid_bm25_vec_rerank_12_19.json --output-dir data/stock_data/evaluations
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

from src.api_requests import BaseDashscopeProcessor

EVALUATION_PROMPT = """你是一个专业的RAG系统评测专家。请根据以下信息，对RAG系统的回答质量进行评分。

## 问题
{question}

## 标准答案（参考）
{reference_answer}

## RAG系统的回答
{rag_answer}

## 评分标准
对每个问题按以下标准评分：

- **1.0分**：回答正确，关键信息完整且准确。以下情况也视为1.0分：
  - 数据精度略有差异（如578亿 vs 577.96亿）但本质正确
  - 提供了与标准答案不同但同样合理的分析角度（如从利润表数据推导原因，即使推导角度与标准答案不同，只要逻辑自洽且数据准确）
  - 回答比标准答案更详细，包含了额外的正确信息
  - 回答顺序与标准答案不同但信息完整

- **0.5分**：回答部分正确，存在以下问题之一：
  - 漏答了问题中的部分子问题（如问A和B，只答了A）
  - 关键数据有轻微偏差但不影响结论
  - 对某个子问题回答"无法提供/未披露"，但其他子问题回答正确

- **0分**：回答完全错误、严重偏离事实、或对所有关键子问题都回答"无法提供/未披露"

## 重要规则
1. 标准答案仅供参考，RAG回答如果提供了不同但同样合理的分析，应给予满分
2. 不要因为RAG回答比标准答案更详细或角度不同而扣分
3. "无法提供/未披露"只有在所有子问题都无法回答时才给0分；如果部分子问题回答正确，应给0.5分
4. 重点关注：关键数据是否准确、核心问题是否回答、是否存在事实错误

## 输出格式
请严格按以下JSON格式输出：
```json
{{
  "score": 0.0,
  "reasoning": "评分理由，简要说明扣分原因",
  "missing_points": ["缺失的关键点1", "缺失的关键点2"],
  "incorrect_points": ["错误的关键点1"]
}}
```

请直接输出JSON，不要输出其他内容。"""

REFERENCE_ANSWERS = {
    "中芯国际2024年全年营业收入是多少？同比增长多少？毛利率是多少？": {
        "answer": "2024年全年营业收入约578亿元（57,795,570千元），同比增长约27.7%，毛利率约18.6%。",
        "key_points": ["578亿元/577.96亿元", "同比增长27.7%/27.72%", "毛利率18.59%/18.6%"]
    },
    "中芯国际2024年归属于上市公司股东的净利润是多少？同比下降的主要原因是什么？": {
        "answer": "2024年归母净利润约37亿元（3,698,665千元），同比下降约23%。下降原因可从多个角度分析：1）折旧和摊销大幅增加（产能扩张导致固定资产增长）；2）资产减值损失；3）投资收益波动。或者从利润表角度：营业总成本增速（36.8%）显著高于营收增速（27.7%），财务净收益收窄，所得税增加等。两种分析角度都合理。",
        "key_points": ["净利润约37亿元/36.99亿元", "下降原因（折旧摊销/成本增速>收入增速/资产减值/投资收益波动等合理分析均可）"]
    },
    "中芯国际2024年末总资产和折合8英寸月产能分别是多少？": {
        "answer": "2024年末总资产约3,534亿元，折合8英寸标准逻辑月产能达到94.8万片。",
        "key_points": ["总资产3,534亿元", "8英寸月产能94.8万片"]
    },
    "中芯国际2024年分季度的营业收入分别是多少？哪个季度最高？": {
        "answer": "2024年Q1营收约125亿元，Q2约132亿元，Q3约142亿元，Q4约180亿元。Q4最高。注意：分季度数据需要从研报中检索到，若RAG回答'未披露/无法提供'，说明检索未覆盖到相关内容，属于检索缺失，应得0分。",
        "key_points": ["Q1约125亿", "Q2约132亿", "Q3约142亿", "Q4约180亿", "Q4最高"]
    },
    "中芯国际2024年研发投入占营业收入的比例是多少？研发流程主要包括哪几个阶段？": {
        "answer": "研发投入占营业收入比例约9.42%。研发流程主要包括：立项与可行性研究、研发实施与验证、项目结题与成果转化等阶段。",
        "key_points": ["9.42%", "立项与可行性研究", "研发实施与验证", "项目结题与成果转化"]
    },
    "上海证券对中芯国际的首次评级是什么？预计2025-2027年营业收入分别是多少？": {
        "answer": "首次评级为'买入'。预计2025-2027年营业收入分别为706.52亿元、786.39亿元和875.84亿元。",
        "key_points": ["买入", "706.52亿元", "786.39亿元", "875.84亿元"]
    },
    "中芯国际在2024年Q2全球纯晶圆代工企业营收排名中位列第几？": {
        "answer": "此题存在争议。含IDM企业（含三星）时排第3名。排除IDM企业后，不同口径有不同排名（第2名到第5名均有依据）。RAG回答若能区分'含IDM第3'和'排除IDM后的排名'，并给出合理推理，应给1.0分。若只答第3名未区分口径，给0.5分。若完全答错给0分。",
        "key_points": ["区分纯代工vs含IDM口径", "含IDM第3名", "排除IDM后排名（2-5名视口径而定）"]
    },
    "东方证券对中芯国际采用什么估值方法？目标价是多少？WACC和永续增长率假设分别是多少？": {
        "answer": "采用DCF（现金流折现）估值方法。目标价129.48元。WACC为7.92%，永续增长率为3.00%。",
        "key_points": ["DCF", "129.48元", "WACC 7.92%", "永续增长率3.00%"]
    },
    "中芯国际2025年一季度产能利用率是多少？环比提升了多少个百分点？8英寸和12英寸利用率分别有何变化？": {
        "answer": "2025年一季度产能利用率为89.6%，环比提升4.1个百分点。8英寸产能利用率显著回升，上升至12英寸厂的平均水平；12英寸产能利用率保持稳健。注意：若RAG回答漏了89.6%的具体数值但其他信息完整，仍给1.0分（因为环比变化和8/12英寸变化才是核心信息）。",
        "key_points": ["89.6%（可选）", "环比提升4.1pct", "8英寸回升至12英寸水平", "12英寸保持稳健"]
    },
    "中原证券预测中芯国际2025-2027年归母净利润分别是多少？维持什么评级？": {
        "answer": "预计2025-2027年归母净利润分别为50.75亿元、62.28亿元、75.42亿元。维持'买入'评级。",
        "key_points": ["50.75亿元", "62.28亿元", "75.42亿元", "买入(维持)"]
    },
    "中芯国际2025年一季度突发生产问题具体包括哪两个方面？对ASP造成了怎样的影响？": {
        "answer": "两个方面：1）厂务年度维修出现突发状况（影响部分产能）；2）设备验证改进导致良率波动。对ASP的影响：一季度ASP环比下降（受良率影响，部分产品单位成本上升，但公司未主动降价）。注意：RAG若将两个方面混合表述（如'设备量产晶圆良率不达标+一次性维修费用'）但核心意思正确，给0.5分；若清晰区分两个方面且ASP影响正确，给1.0分。",
        "key_points": ["厂务年度维修突发状况", "设备验证改进致良率波动", "ASP环比下降"]
    },
    "光大证券对中芯国际生产问题恢复时间的判断是什么？对三四季度景气度有何预期？": {
        "answer": "恢复时间判断：预计3Q逐步恢复。对三四季度景气度预期：3Q恢复但4Q景气度存在不确定性（需求端可能面临压力）。",
        "key_points": ["3Q逐步恢复", "4Q景气度不确定"]
    },
    "华泰证券将中芯国际港股目标价上调至多少？上调的主要理由是什么？": {
        "answer": "上调港股目标价至63港币。主要理由包括：1）DeepSeek推动AI推理需求爆发，带动代工需求强劲增长；2）国产替代加速；3）产能利用率持续提升；4）4Q24收入及毛利率超指引，ASP改善等。注意：RAG回答若覆盖了目标价63港币和至少2个合理理由，给1.0分；理由表述与标准答案不同但逻辑正确也可。",
        "key_points": ["63港币", "DeepSeek/AI代工需求", "国产替代", "产能利用率提升/ASP改善"]
    },
    "中芯国际2024年四季度中国区收入占比是多少？ASP环比变化如何？": {
        "answer": "2024年四季度中国区收入占比为89.1%。ASP环比上升约6%。",
        "key_points": ["89.1%", "ASP环比+6%"]
    },
    "国信证券预测中芯国际2025-2027年归母净利润分别是多少？一季度哪个应用领域同比增速最高？": {
        "answer": "预计2025-2027年归母净利润分别为5.78亿美元、8.11亿美元、9.47亿美元。一季度同比增速最高的应用领域是工业与汽车，增速达75.2%。",
        "key_points": ["5.78亿美元", "8.11亿美元", "9.47亿美元", "工业与汽车", "75.2%"]
    },
    "兴证国际对中芯国际的评级是什么？预计2025-2027年营业收入分别是多少？": {
        "answer": "评级为'增持'（维持）。预计2025-2027年营业收入分别为92.04亿美元、115.18亿美元、128.80亿美元。",
        "key_points": ["增持(维持)", "92.04亿美元", "115.18亿美元", "128.80亿美元"]
    },
    "中芯国际管理层在调研中如何解释2025年一季度研发开支下降的原因？": {
        "answer": "管理层解释：1）一季度新进设备较多，研发团队重心偏向设备安装与调试；2）客户急单较多，公司将原研发产能临时划归生产产能以保障出货；3）产能利用率提升导致可用于研发测试的出片量受限。管理层强调公司长期坚持营收8%~10%投入研发，后续将恢复正常。注意：RAG若将第2点和第3点合并表述（如'急单增多导致研发出片量下降'），逻辑正确应给1.0分，因为急单转产能和出片受限本质上是因果关系。",
        "key_points": ["设备安装调试", "急单转产能/研发出片受限（二者为因果关系，合并表述即可）", "8%~10%长期投入"]
    },
    "中芯国际管理层对未来3-5年产能扩充节奏的规划是什么？每年预计增加多少12英寸产能？": {
        "answer": "产能扩充保持'匀速直线运动'的稳健节奏，每年预计增加约5万片12英寸产能。年资本开支约75亿美元（约80%用于设备采购）。",
        "key_points": ["匀速直线运动", "每年5万片12英寸", "75亿美元/年"]
    },
    "中芯国际管理层如何理解'一个中芯，全球运营'的发展蓝图？在当前国际形势下的侧重点是什么？": {
        "answer": "核心理解：专注本业、保持定力，'全球运营'不是在全世界建厂，而是支持全球客户与市场。侧重点：推行'local for local'策略（用中国制造产能满足客户在华销售需求），保障产能、质量与价格竞争力，帮助客户在全球扩大份额。坚持国际化视野，不偏废任何市场。",
        "key_points": ["专注本业保持定力", "支持全球客户", "local for local", "保障产能质量价格"]
    },
    "中芯国际2025年一季度各应用领域的收入占比分别是多少？哪个领域环比增长最为显著？": {
        "answer": "收入占比：消费电子41%、智能手机24%、电脑与平板17%、工业与汽车10%、互联与可穿戴8%。环比增长最显著的是工业与汽车领域，环比增长超20%。",
        "key_points": ["消费电子41%", "智能手机24%", "电脑与平板17%", "工业与汽车10%", "互联与可穿戴8%", "工业与汽车环比+20%+"]
    }
}


def load_answers(answers_path):
    with open(answers_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('answers', [])


def evaluate_single_question(processor, question, rag_answer, reference, model):
    prompt = EVALUATION_PROMPT.format(
        question=question,
        reference_answer=reference['answer'],
        rag_answer=rag_answer
    )

    result = processor.send_message(
        model=model,
        temperature=0.1,
        system_content='你是一个专业的RAG系统评测专家，请严格按照评分标准进行评分，直接输出JSON格式结果。',
        human_content=prompt
    )

    if isinstance(result, dict) and 'score' in result:
        return result

    if isinstance(result, str):
        try:
            cleaned = result.strip()
            if cleaned.startswith('```'):
                first_nl = cleaned.find('\n')
                last_backtick = cleaned.rfind('```')
                if first_nl > 0 and last_backtick > first_nl:
                    cleaned = cleaned[first_nl+1:last_backtick].strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    return {
        "score": -1,
        "reasoning": f"评测模型返回格式异常: {str(result)[:200]}",
        "missing_points": [],
        "incorrect_points": []
    }


def evaluate_answers(answers_path, model, output_dir=None):
    print(f"\n{'='*60}")
    print(f"RAG自动化评测")
    print(f"{'='*60}")
    print(f"答案文件: {answers_path}")
    print(f"评测模型: {model}")
    print(f"{'='*60}\n")

    answers = load_answers(answers_path)
    if not answers:
        print("错误：未找到答案数据")
        return

    processor = BaseDashscopeProcessor()

    results = []
    total_score = 0
    valid_count = 0

    for i, answer in enumerate(answers):
        question = answer.get('question_text', '')
        rag_answer = answer.get('value', '')

        reference = REFERENCE_ANSWERS.get(question)
        if not reference:
            print(f"  Q{i+1}: 未找到参考答案，跳过")
            results.append({
                "question_index": i + 1,
                "question": question,
                "score": -1,
                "reasoning": "未找到参考答案",
                "missing_points": [],
                "incorrect_points": []
            })
            continue

        print(f"  Q{i+1}/{len(answers)}: {question[:40]}...")

        eval_result = evaluate_single_question(
            processor, question, rag_answer, reference, model
        )

        score = eval_result.get('score', -1)
        if score >= 0:
            total_score += score
            valid_count += 1

        result_entry = {
            "question_index": i + 1,
            "question": question,
            "rag_answer": rag_answer,
            "reference_answer": reference['answer'],
            "key_points": reference['key_points'],
            "score": score,
            "reasoning": eval_result.get('reasoning', ''),
            "missing_points": eval_result.get('missing_points', []),
            "incorrect_points": eval_result.get('incorrect_points', [])
        }
        results.append(result_entry)

        score_display = f"{score:.1f}" if score >= 0 else "N/A"
        print(f"         得分: {score_display} | {eval_result.get('reasoning', '')[:60]}")

        time.sleep(1)

    avg_score = total_score / valid_count if valid_count > 0 else 0

    report = {
        "evaluation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "answers_file": str(answers_path),
        "evaluation_model": model,
        "total_questions": len(answers),
        "valid_questions": valid_count,
        "total_score": round(total_score, 1),
        "average_score": round(avg_score, 3),
        "score_percentage": f"{avg_score*100:.1f}%",
        "results": results
    }

    if output_dir:
        output_path = Path(output_dir)
    else:
        output_path = Path(answers_path).parent.parent / "evaluations"
    output_path.mkdir(parents=True, exist_ok=True)

    answers_stem = Path(answers_path).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    eval_filename = f"eval_{answers_stem}_{timestamp}.json"
    eval_path = output_path / eval_filename

    with open(eval_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"评测完成!")
    print(f"{'='*60}")
    print(f"总题数: {valid_count}")
    print(f"总得分: {total_score:.1f} / {valid_count}")
    print(f"得分率: {avg_score*100:.1f}%")
    print(f"评测报告: {eval_path}")
    print(f"{'='*60}\n")

    return report


def compare_reports(report_paths):
    print(f"\n{'='*70}")
    print(f"多版本评测对比")
    print(f"{'='*70}")
    print(f"{'版本':<35} {'总分':>6} {'得分率':>8} {'模型':>20}")
    print(f"{'-'*70}")

    for rp in report_paths:
        with open(rp, 'r', encoding='utf-8') as f:
            report = json.load(f)
        stem = Path(rp).stem
        total = report.get('total_score', 0)
        valid = report.get('valid_questions', 0)
        pct = report.get('score_percentage', 'N/A')
        model = report.get('evaluation_model', 'N/A')
        print(f"{stem:<35} {total:>5.1f}/{valid:<3} {pct:>8} {model:>20}")

    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description='RAG自动化评测工具')
    parser.add_argument('--answers', nargs='+', required=True,
                        help='答案文件路径（支持多个文件对比）')
    parser.add_argument('--model', default='deepseek-v4-pro',
                        help='评测使用的模型（默认deepseek-v4-pro）')
    parser.add_argument('--output-dir', default=None,
                        help='评测报告输出目录（默认与答案文件同目录）')
    parser.add_argument('--compare', nargs='+',
                        help='对比已有的评测报告文件')

    args = parser.parse_args()

    if args.compare:
        compare_reports(args.compare)
        return

    for answers_path in args.answers:
        if not os.path.exists(answers_path):
            print(f"错误：文件不存在 - {answers_path}")
            continue
        evaluate_answers(answers_path, args.model, args.output_dir)


if __name__ == '__main__':
    main()
