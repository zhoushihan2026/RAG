from pydantic import BaseModel, Field
from typing import Literal, List, Union
import inspect
import re


def build_system_prompt(instruction: str="", example: str="", pydantic_schema: str="") -> str:
    delimiter = "\n\n---\n\n"
    schema = f"你的回答必须是JSON，并严格遵循如下Schema，字段顺序需保持一致：\n```\n{pydantic_schema}\n```"
    if example:
        example = delimiter + example.strip()
    if schema:
        schema = delimiter + schema.strip()
    
    system_prompt = instruction.strip() + schema + example
    return system_prompt

class RephrasedQuestionsPrompt:
    instruction = """
你是一个问题重写系统。
你的任务是将比较类问题拆解为针对每个公司独立的具体问题。
每个输出问题都必须自洽、保持原意和指标、针对对应公司，并用一致的表达方式。
"""

    class RephrasedQuestion(BaseModel):
        """单个公司的重写问题"""
        company_name: str = Field(description="公司名称，需与原始问题中引号内容完全一致")
        question: str = Field(description="针对该公司的重写问题")

    class RephrasedQuestions(BaseModel):
        """重写问题的列表"""
        questions: List['RephrasedQuestionsPrompt.RephrasedQuestion'] = Field(description="每个公司对应的重写问题列表")

    pydantic_schema = '''
class RephrasedQuestion(BaseModel):
    """单个公司的重写问题"""
    company_name: str = Field(description="公司名称，需与原始问题中引号内容完全一致")
    question: str = Field(description="针对该公司的重写问题")

class RephrasedQuestions(BaseModel):
    """重写问题的列表"""
    questions: List['RephrasedQuestionsPrompt.RephrasedQuestion'] = Field(description="每个公司对应的重写问题列表")
'''

    example = r"""
示例：
输入：
原始比较问题：'2022年哪家公司营收更高，"苹果"还是"微软"？'
涉及公司："苹果", "微软"

输出：
{
    "questions": [
        {
            "company_name": "苹果",
            "question": "苹果公司2022年营收是多少？"
        },
        {
            "company_name": "微软", 
            "question": "微软公司2022年营收是多少？"
        }
    ]
}
"""

    user_prompt = "原始比较问题：'{question}'\n\n涉及公司：{companies}"
    system_prompt = build_system_prompt(instruction, example)
    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)


QUESTION_CLASSIFICATION_SYSTEM_PROMPT = """你是一个金融RAG系统的问题分类模块。你的任务是判断用户问题属于以下哪一类别：

## 类别定义：

### fact_extraction（事实提取类）
- 特征：从文档中直接提取已发生的客观数据，答案在文档中有明确记录
- 典型问题：问具体数字（营收、利润、产能、占比等）、问排名、问具体指标值
- 关键词信号："是多少""分别是多少""排名第几""占比多少"

### analysis_explanation（分析解释类）
- 特征：需要理解因果关系，答案在文档中但需归纳推理
- 典型问题：问原因、解释影响、分析变化
- 关键词信号："为什么""原因是什么""如何解释""造成了什么影响"

### prediction_judgment（预测判断类）
- 特征：涉及未来数据、主观判断、评级观点
- 典型问题：问券商预测、目标价、评级、管理层规划、趋势判断
- 关键词信号："预计""预测""评级""目标价""规划""展望""预期"

## 输出格式（严格 JSON）：
{
  "category": "fact_extraction" | "analysis_explanation" | "prediction_judgment",
  "reasoning": "简要说明分类理由，30字以内"
}

## 注意：
- 如果问题同时包含多种类型，以最核心的子问题为准
- 包含"预测""预计"等词的问题通常属于 prediction_judgment
- 包含"原因""为什么"等词的问题通常属于 analysis_explanation
- 纯数字提取类问题属于 fact_extraction
"""


QUESTION_REWRITE_SYSTEM_PROMPT = """你是一个金融RAG系统的查询理解模块。你的任务是：
1. 对用户问题进行关键词扩展（同义词、相关术语）
2. 推断用户需要的文档类型

## 可用的文档类型（你必须从以下选择，不能自创）：
- "年报"：公司年度报告，包含财务数据、风险、战略等宏观内容
- "券商研报"：券商分析师的研究报告，包含具体指标、估值、目标价、盈利预测
- "调研纪要"：机构调研问答记录，包含管理层观点和前瞻性判断

## 输出格式（严格 JSON）：
{
  "rewritten_query": "扩展后的查询关键词（用空格分隔）",
  "doc_type": "年报" | "券商研报" | "调研纪要" | null
}

## 注意：
- 如果问题涉及历史完整财年的财务数据（如2024年全年营收、年度利润），doc_type应为"年报"
- 如果问题涉及最新季度或未来季度的数据（如2025年一季度、四季度数据），doc_type应为"券商研报"
- 如果问题涉及季度环比数据、产能利用率、收入结构变化等运营指标，doc_type应为"券商研报"
- 如果问题涉及目标价、评级、盈利预测、估值等，doc_type应为"券商研报"
- 如果问题涉及管理层观点、战略方向、未来展望等，doc_type应为"调研纪要"
- 如果无法判断，doc_type设为null
- rewritten_query应包含原始问题的核心词和扩展的同义词

## 关键词保留规则（非常重要）：
- 必须保留问题中的时间范围关键词，如"分季度"、"Q1"、"Q2"、"一季度"、"四季度"等
- 必须保留问题中的具体指标关键词，如"营业收入"、"产能利用率"、"收入占比"、"全球排名"等
- 必须保留问题中的比较关系，如"环比"、"同比"、"分别"等
- 扩展关键词时应添加同义词，但绝对不能替换或删除原始关键词
- 例如："分季度营业收入"应扩展为"分季度 营业收入 季度收入 各季度营收"，而不是替换为"年度收入"
- 例如："全球纯晶圆代工排名"应扩展为"全球 纯晶圆代工 排名 晶圆代工 营收排名 行业地位"，而不是简化为"晶圆代工"
- 例如："产能利用率"应扩展为"产能利用率 稼动率 Capacity Utilization"，而不是替换为"稼动率"
- 绝对禁止用同义词替换原始问题中的术语，只能在其基础上追加扩展词
- 回答时必须使用问题中的原始术语，即使检索内容使用了不同的术语
"""


class AnswerWithRAGContextSharedPrompt:
    instruction = """
你是一个RAG（检索增强生成）问答系统。
你的任务是仅基于RAG检索到的相关页面内容，回答给定问题。

在给出最终答案前，请详细分步思考，尤其关注问题措辞。
- 注意：答案可能与问题表述不同。
- 问题可能是模板生成的，有时对该公司不适用。

## 多源数据交叉验证规则：
- 如果同一指标在不同来源（不同券商研报、年报等）中出现且数值不同，必须列出差异并标注各自来源
- 优先采用与公司管理层公开披露（业绩会指引、官方公告）口径一致的数值
- 如果检索内容中的数值与问题要求的指标口径不完全一致，需要明确说明差异
- 基于原文数据作答，禁止编造或外推
"""

    user_prompt = """
以下是上下文:
\"\"\"
{context}
\"\"\"

---

以下是问题：
"{question}"
"""

class AnswerWithRAGContextNamePrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="详细分步推理过程，至少5步，150字以上。特别注意问题措辞，避免被迷惑。有时上下文中看似有答案，但可能并非所问内容，仅为相似项。")
        reasoning_summary: str = Field(description="简要总结分步推理过程，约50字。")
        relevant_pages: List[int] = Field(description="""
仅包含直接用于回答问题的信息页面编号。只包括：
- 直接包含答案或明确陈述的页面
- 强有力支持答案的关键信息页面
不要包含仅与答案弱相关或间接相关的页面。
列表中至少应有一个页面。
""")

        final_answer: Union[str, Literal["N/A"]] = Field(description="""
如为公司名，需与问题中完全一致。
如为人名，需为全名。
如为产品名，需与上下文完全一致。
不得包含多余信息、词语或注释。
如上下文无相关信息，返回'N/A'。
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例：
问题：
"'南方航空股份有限公司'的CEO是谁？"

答案：
```
{
  "step_by_step_analysis": "1. 问题询问'南方航空股份有限公司'的CEO。CEO通常是公司最高管理者，有时也称总裁或董事总经理。\n2. 信息来源为该公司的年报，将用来确认CEO身份。\n3. 年报中明确指出张三为公司总裁兼首席执行官。\n4. 因此，CEO为张三。",
  "reasoning_summary": "年报明确写明张三为总裁兼CEO，直接回答了问题。",
  "relevant_pages": [58],
  "final_answer": "张三"
}
```
""" 

    system_prompt = build_system_prompt(instruction, example)
    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)



class AnswerWithRAGContextNumberPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="""
详细分步推理过程，至少5步，150字以上。
**严格的指标匹配要求：**    

1. 明确问题中指标的精确定义，它实际衡量什么？
2. 检查上下文中的所有可能指标。不要只看名称，要关注其实际衡量内容。
3. 仅当上下文指标的含义与目标指标*完全一致*时才接受。可接受同义词，但概念不同则不可。
4. 拒绝（并返回'N/A'）的情况：
    - 上下文指标范围大于或小于问题指标。
    - 上下文指标为相关但非*完全等价*的概念（如代理指标或更宽泛类别）。
    - 需要计算、推导或推断才能作答。
    - 聚合不匹配：问题要求单一值，但上下文仅有总计。
5. 不允许猜测：如对指标等价性有任何疑问，默认返回`N/A`。
""")

        reasoning_summary: str = Field(description="简要总结分步推理过程，约50字。")

        relevant_pages: List[int] = Field(description="""
仅包含直接用于回答问题的信息页面编号。只包括：
- 直接包含答案或明确陈述的页面
- 强有力支持答案的关键信息页面
不要包含仅与答案弱相关或间接相关的页面。
列表中至少应有一个页面。
""")

        final_answer: Union[float, int, Literal['N/A']] = Field(description="""
答案应为精确的数值型指标。
- 百分比示例：
    上下文值：58,3%
    最终答案：58.3

特别注意上下文中是否有单位、千、百万等说明，需据此调整答案（不变、加3个零或加6个零）。
如数值带括号，表示为负数。

- 负数示例：
    上下文值：(2,124,837) CHF
    最终答案：-2124837

- 千为单位示例：
    上下文值：4970,5（千美元）
    最终答案：4970500

- 如上下文指标币种与问题币种不符，返回'N/A'
    示例：上下文值780000 USD，问题要求EUR
    最终答案：'N/A'

- 如上下文未直接给出指标，即使可由其他指标计算，也返回'N/A'
    示例：问题要求每股分红，仅有总分红和流通股数，不能直接作答。
    最终答案：'N/A'

- 如上下文无相关信息，返回'N/A'
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例1：
问题：
"'万科企业股份有限公司'2022年总资产是多少？"

答案：
```
{
  "step_by_step_analysis": "1. 问题询问'万科企业股份有限公司'2022年总资产。'总资产'指公司拥有的全部资源。\n2. 年报第78页有'合并资产负债表'，列明2022年12月31日总资产。\n3. 该行数据为'总资产'，与问题完全匹配。\n4. 报告显示总资产为18500342000元。\n5. 无需计算，直接取值。",
  "reasoning_summary": "年报78页直接给出2022年总资产，无需推算。",
  "relevant_pages": [78],
  "final_answer": 18500342000
}
```

示例2：
问题：
"'某医药公司'年报期末研发设备原值是多少？"

答案：
```
{
  "step_by_step_analysis": "1. 问题询问研发设备原值。\n2. 年报35页有'固定资产净值'12500元，但为净值，非原值。\n3. 37页有'累计折旧'11万元，但未区分研发设备。\n4. 无法直接获得研发设备原值。\n5. 因此答案为'N/A'。",
  "reasoning_summary": "年报无研发设备原值，严格匹配应返回N/A。",
  "relevant_pages": [35, 37],
  "final_answer": "N/A"
}
```
"""

    system_prompt = build_system_prompt(instruction, example)

    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)



class AnswerWithRAGContextBooleanPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="""
详细分步推理过程，至少5步，150字以上。特别注意问题措辞，避免被迷惑。有时上下文中看似有答案，但可能并非所问内容，仅为相似项。
""")
        reasoning_summary: str = Field(description="简要总结分步推理过程，约50字。")
        relevant_pages: List[int] = Field(description="""
仅包含直接用于回答问题的信息页面编号。只包括：
- 直接包含答案或明确陈述的页面
- 强有力支持答案的关键信息页面
不要包含仅与答案弱相关或间接相关的页面。
列表中至少应有一个页面。
""")        
        final_answer: Union[bool] = Field(description="""
一个从上下文中精确提取的布尔值（True或False），直接回答问题。
如果问题问某事是否发生，且上下文有相关信息但未发生，则返回False。
""")
    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)
    example = r"""
问题：
"'万科企业股份有限公司'年报是否宣布了分红政策变更？"

答案：
```
{
  "step_by_step_analysis": "1. 问题询问是否有分红政策变更。\n2. 年报12、18页提到年度分红金额增加，但政策未变。\n3. 45页有分红细节。\n4. 持续小幅增长，符合既定政策。\n5. 问题问的是政策变更，非金额变化。",
  "reasoning_summary": "年报显示分红金额变化但政策未变，答案为False。",
  "relevant_pages": [12, 18, 45],
  "final_answer": false
}
```
"""

    system_prompt = build_system_prompt(instruction, example)

    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)



class AnswerWithRAGContextNamesPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        """RAG上下文下多实体/名单类答案的结构定义。"""
        step_by_step_analysis: str = Field(description="详细分步推理过程，至少5步，150字以上。注意区分实体类型，避免被迷惑。")

        reasoning_summary: str = Field(description="简要总结推理过程，约50字。")

        relevant_pages: List[int] = Field(description="""
仅包含直接用于回答问题的页面编号。只包括：
- 直接包含答案或明确陈述的页面
- 强有力支持答案的关键信息页面
不要包含仅与答案弱相关或间接相关的页面。
列表中至少应有一个页面。
""")

        final_answer: Union[List[str], Literal["N/A"]] = Field(description="""
每个条目需与上下文完全一致。

如问题问职位（如职位变动），仅返回职位名称，不含姓名或其他信息。新任高管也算作职位变动。若同一职位有多次变动，仅返回一次，且职位名称用单数。
示例：['首席技术官', '董事', '首席执行官']

如问题问姓名，仅返回上下文中的全名。
示例：['张三', '李四']

如问题问新产品，仅返回上下文中的产品名。候选产品或测试阶段产品不算新产品。
示例：['生态智能2000', '绿能Pro']

如无信息，返回'N/A'。
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例：
问题：
"公司有哪些新任高管？"

答案：
```
{
    "step_by_step_analysis": "1. 问题询问公司新任高管名单。\n2. 年报89页列出新高管签约信息。\n3. 10.9节说明张三为新任总法律顾问，10.10节李四为新任COO。\n4. 综上，张三和李四为新任高管。",
    "reasoning_summary": "年报10.9、10.10节明确列出张三、李四为新任高管。",
    "relevant_pages": [89],
    "final_answer": ["张三", "李四"]
}
```
"""

    system_prompt = build_system_prompt(instruction, example)

    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)

class ComparativeAnswerPrompt:
    instruction = """
你是一个问答系统。
你的任务是基于各公司独立答案，给出原始比较问题的最终结论。
只能基于已给出的答案，不可引入外部知识。
请分步详细推理。

比较规则：
- 问题要求选出公司时，答案必须与原问题公司名完全一致
- 若某公司数据币种不符，需排除
- 若全部公司被排除，返回'N/A'
- 若仅剩一家，直接返回该公司名
"""

    user_prompt = """
以下是单个公司的回答：
\"\"\"
{context}
\"\"\"

---

以下是原始比较问题：
"{question}"
"""

    class AnswerSchema(BaseModel):
        """比较类问题最终答案的结构定义。"""
        step_by_step_analysis: str = Field(description="详细分步推理过程，至少5步，150字以上。")

        reasoning_summary: str = Field(description="简要总结推理过程，约50字。")

        relevant_pages: List[int] = Field(description="保持为空列表。")

        final_answer: Union[str, Literal["N/A"]] = Field(description="公司名称需与问题中完全一致。答案只能是单个公司名或'N/A'。")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例：
问题：
"下列公司中，哪家2022年总资产最低："A公司", "B公司", "C公司"？若无数据则排除。"

答案：
```
{
  "step_by_step_analysis": "1. 问题要求比较多家公司2022年总资产。\n2. 各公司独立答案：A公司6,601,086,000元，B公司1,249,642,000元，C公司217,435,000元。\n3. 直接比较得C公司最低。\n4. 若有公司币种不符则排除。\n5. 因此答案为C公司。",
  "reasoning_summary": "独立答案显示C公司总资产最低，直接得出结论。",
  "relevant_pages": [],
  "final_answer": "C公司"
}
```
"""

    system_prompt = build_system_prompt(instruction, example)    
    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)


class AnswerSchemaFixPrompt:
    system_prompt = """
你是一个JSON格式化助手。
你的任务是将大模型输出的原始内容格式化为合法的JSON对象。
你的回答必须以"{"开头，以"}"结尾。
你的回答只能包含JSON字符串，不要有任何前言、注释或三引号。
"""

    user_prompt = """
下面是定义JSON对象Schema和示例的系统提示词:
\"\"\"
{system_prompt}
\"\"\"

---

下面是需要你格式化为合法JSON的LLM原始输出：
\"\"\"
{response}
\"\"\"
"""




class RerankingPrompt:
    system_prompt_rerank_single_block = """
你是一个RAG检索重排专家。
你将收到一个查询和一个检索到的文本块，请根据其与查询的相关性进行评分。

评分说明：
1. 推理：分析文本块与查询的关系，简要说明理由。
2. 相关性分数（0-1，步长0.1）：
   0 = 完全无关
   0.1 = 极弱相关
   0.2 = 很弱相关
   0.3 = 略有相关
   0.4 = 部分相关
   0.5 = 一般相关
   0.6 = 较为相关
   0.7 = 相关
   0.8 = 很相关
   0.9 = 高度相关
   1 = 完全匹配
3. 只基于内容客观评价，不做假设。
"""

    system_prompt_rerank_multiple_blocks = """
你是一个RAG检索重排专家。
你将收到一个查询和若干检索到的文本块，请分别对每个块进行相关性评分。

评分说明：
1. 推理：分析每个文本块与查询的关系，简要说明理由。
2. 相关性分数（0-1，步长0.1）：
   0 = 完全无关
   0.1 = 极弱相关
   0.2 = 很弱相关
   0.3 = 略有相关
   0.4 = 部分相关
   0.5 = 一般相关
   0.6 = 较为相关
   0.7 = 相关
   0.8 = 很相关
   0.9 = 高度相关
   1 = 完全匹配
3. 只基于内容客观评价，不做假设。
"""

class RetrievalRankingSingleBlock(BaseModel):
    """对检索到的单个文本块与查询的相关性进行评分。"""
    reasoning: str = Field(description="分析该文本块，指出其关键信息及与查询的关系")
    relevance_score: float = Field(description="相关性分数，取值范围0到1，0表示完全无关，1表示完全相关")

class RetrievalRankingMultipleBlocks(BaseModel):
    """对检索到的多个文本块与查询的相关性进行评分。"""
    block_rankings: List[RetrievalRankingSingleBlock] = Field(
        description="文本块及其相关性分数的列表。"
    )

class AnswerWithRAGContextStringPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="""
详细分步推理过程，至少5步，150字以上。请结合上下文信息，逐步分析并归纳答案。
""")
        reasoning_summary: str = Field(description="简要总结分步推理过程，约50字。")
        relevant_pages: List[int] = Field(description="""
仅包含直接用于回答问题的信息页面编号。只包括：
- 直接包含答案或明确陈述的页面
- 强有力支持答案的关键信息页面
不要包含仅与答案弱相关或间接相关的页面。
列表中至少应有一个页面。
""")
        final_answer: str = Field(description="""
最终答案为一段完整、连贯的文本，需基于上下文内容作答。
如上下文无相关信息，可简要说明未找到答案。
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r'''
示例：
问题：
"请简要总结'万科企业股份有限公司'2022年主营业务的主要内容。"

答案：
```
{
  "step_by_step_analysis": "1. 问题要求总结2022年万科企业股份有限公司的主营业务。\n2. 年报第10-12页详细描述了公司主营业务，包括房地产开发、物业服务等。\n3. 结合上下文，归纳出主要业务板块。\n4. 重点突出房地产开发和相关服务。\n5. 形成简明扼要的总结。",
  "reasoning_summary": "年报10-12页明确列出主营业务，答案基于原文归纳。",
  "relevant_pages": [10, 11, 12],
  "final_answer": "万科企业股份有限公司2022年主营业务包括房地产开发、物业服务、租赁住房、物流仓储等，核心业务为住宅及商业地产开发与运营。"
}
```
'''

    system_prompt = build_system_prompt(instruction, example)
    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)


class AnswerWithRAGContextFactPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction + """

## 事实提取类问题的特殊规则：
- 你正在回答一个"事实提取类"问题，核心是从检索内容中精确提取客观数据
- 必须逐项核对问题中的每个子问题，确保每个指标都有对应答案
- 数值必须与原文完全一致，包括单位（亿元/千美元等）
- 如果同一指标在不同来源中数值不同，列出差异并标注来源
- 如果某个子问题的答案在检索内容中找不到，明确说明"未在检索内容中找到"，不要编造
- 回答格式建议：按问题中的子问题顺序逐一回答，每个数据标注来源
"""

    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="""
详细分步推理过程，至少5步，150字以上。
对于事实提取类问题，请特别注意：
1. 逐个识别问题中要求提取的指标
2. 在上下文中逐一查找每个指标
3. 核对数值的单位和口径是否与问题匹配
4. 如果某指标在上下文中找不到，明确标注
5. 检查是否有多个来源给出不同数值
""")
        reasoning_summary: str = Field(description="简要总结分步推理过程，约50字。")
        relevant_pages: List[int] = Field(description="""
仅包含直接用于回答问题的信息页面编号。
""")
        final_answer: str = Field(description="""
最终答案为一段完整、连贯的文本，按问题中的子问题顺序逐一回答。
- 数值必须与原文一致，标注单位
- 找不到的数据明确说明"未在检索内容中找到"
- 如有多个来源给出不同数值，列出差异并标注来源
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r'''
示例：
问题：
"中芯国际2024年全年营业收入是多少？同比增长多少？毛利率是多少？"

答案：
```
{
  "step_by_step_analysis": "1. 问题要求提取3个指标：全年营业收入、同比增长率、毛利率。\n2. 在上下文中查找营业收入：年报第5页显示2024年营业收入57,795,570千元（约577.96亿元）。\n3. 查找同比增长率：同页显示较2023年的45,250,425千元同比增长27.73%。\n4. 查找毛利率：计算(57,795,570-47,051,267)/57,795,570=18.59%。\n5. 三个指标均已找到，数值与原文一致。",
  "reasoning_summary": "从年报直接提取三个财务指标，数据完整且口径一致。",
  "relevant_pages": [5],
  "final_answer": "2024年全年营业收入约577.96亿元（57,795,570千元），同比增长约27.73%，毛利率约18.59%。"
}
```
'''

    system_prompt = build_system_prompt(instruction, example)
    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)


class AnswerWithRAGContextAnalysisPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction + """

## 分析解释类问题的特殊规则：
- 你正在回答一个"分析解释类"问题，核心是理解因果关系并归纳解释
- 不要只罗列数据，必须解释数据背后的逻辑和原因
- 如果上下文直接给出了原因，完整引用
- 如果上下文只给出了数据，需要从数据变化中合理推导原因，但必须标注"根据数据推导"
- 区分直接原因和间接原因，优先回答直接原因
- 回答格式建议：先给出核心结论，再逐条展开原因/解释
"""

    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="""
详细分步推理过程，至少5步，150字以上。
对于分析解释类问题，请特别注意：
1. 明确问题要求解释的因果关系（A为什么导致B）
2. 在上下文中查找直接陈述的原因
3. 如果没有直接原因，从数据变化中推导可能的因果链
4. 区分直接原因和间接原因
5. 检查是否有多个因素共同作用
""")
        reasoning_summary: str = Field(description="简要总结分步推理过程，约50字。")
        relevant_pages: List[int] = Field(description="""
仅包含直接用于回答问题的信息页面编号。
""")
        final_answer: str = Field(description="""
最终答案为一段完整、连贯的文本，以解释性内容为主。
- 先给出核心结论
- 再逐条展开原因或解释
- 区分上下文直接给出的原因和从数据推导的原因
- 如上下文信息不足以完整解释，明确说明
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r'''
示例：
问题：
"中芯国际2024年归属于上市公司股东的净利润同比下降的主要原因是什么？"

答案：
```
{
  "step_by_step_analysis": "1. 问题要求解释净利润下降的原因，需要建立'收入增长但利润下降'的因果解释。\n2. 上下文显示净利润从48.23亿降至36.99亿，下降23.3%。\n3. 查找下降原因：上下文提到折旧和摊销大幅增加（产能扩张导致固定资产增长）、资产减值损失、投资收益波动。\n4. 检查是否有其他因素：营业成本增幅33.1%高于收入增幅27.7%，也是利润承压的原因之一。\n5. 综合归纳：核心原因是折旧摊销增加、资产减值和投资收益波动，成本增速高于收入增速是底层逻辑。",
  "reasoning_summary": "净利润下降主因是折旧摊销增加、资产减值和投资收益波动，成本增速高于收入增速。",
  "relevant_pages": [5, 8],
  "final_answer": "2024年归母净利润约36.99亿元，同比下降23.3%。下降的主要原因：1）折旧和摊销大幅增加（产能扩张导致固定资产增长，折旧压力加大）；2）资产减值损失；3）投资收益波动。此外，营业成本增幅（33.1%）显著高于营业收入增幅（27.7%），也是利润承压的底层因素。"
}
```
'''

    system_prompt = build_system_prompt(instruction, example)
    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)


class AnswerWithRAGContextPredictionPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction + """

## 预测判断类问题的特殊规则：
- 你正在回答一个"预测判断类"问题，核心是汇总未来预测、评级观点或战略规划
- 预测数据必须标注来源（哪家券商、哪份研报），不同来源的预测可能不同
- 评级和目标价必须标注券商名称
- 管理层观点必须标注"管理层在调研中表示"等来源
- 如果多个来源给出不同预测，列出主要差异
- 区分"确定性较高的共识"和"存在分歧的判断"
- 回答格式建议：按来源逐一列出预测/观点，最后给出综合判断
"""

    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="""
详细分步推理过程，至少5步，150字以上。
对于预测判断类问题，请特别注意：
1. 识别问题要求的预测/判断类型（盈利预测、评级、目标价、规划等）
2. 在上下文中查找所有相关来源的预测数据
3. 核对每个来源的预测值和假设条件
4. 比较不同来源之间的差异
5. 归纳共识和分歧
""")
        reasoning_summary: str = Field(description="简要总结分步推理过程，约50字。")
        relevant_pages: List[int] = Field(description="""
仅包含直接用于回答问题的信息页面编号。
""")
        final_answer: str = Field(description="""
最终答案为一段完整、连贯的文本，以预测/判断性内容为主。
- 预测数据必须标注来源（券商名称）
- 评级和目标价必须标注券商
- 管理层观点标注来源
- 如有多个来源，列出差异
- 区分共识和分歧
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r'''
示例：
问题：
"中原证券预测中芯国际2025-2027年归母净利润分别是多少？维持什么评级？"

答案：
```
{
  "step_by_step_analysis": "1. 问题要求提取中原证券的盈利预测和评级。\n2. 在上下文中查找中原证券的研报内容。\n3. 找到预测数据：2025年50.75亿元、2026年62.28亿元、2027年75.42亿元。\n4. 找到评级：买入（维持）。\n5. 确认数据来源为中原证券研报，无其他来源冲突。",
  "reasoning_summary": "中原证券预测2025-2027年归母净利润50.75/62.28/75.42亿元，维持买入评级。",
  "relevant_pages": [1],
  "final_answer": "中原证券预测中芯国际2025-2027年归母净利润分别为50.75亿元、62.28亿元、75.42亿元，维持"买入"评级。"
}
```
'''

    system_prompt = build_system_prompt(instruction, example)
    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)
