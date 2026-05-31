"""
图片描述模块：使用多模态大模型为MinerU无法处理的图片生成文字描述。

对于content_list.json中type为"image"且content为空的条目，
先判断图片是否为非表格图表图片，如果不是表格图表图片则交给多模态大模型生成描述，
最后将描述插入到markdown文件中。
"""
import base64
import json
import os
import time

import dashscope
from dotenv import load_dotenv

load_dotenv()
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

CLASSIFICATION_PROMPT = """请判断这张图片是否为表格、图表或数据可视化图形（如折线图、柱状图、饼图、散点图、面积图等）。
只需回答"是"或"否"。"是"表示这是表格/图表/数据可视化，"否"表示不是。"""

DESCRIPTION_PROMPT = """请详细描述这张图片的内容。这是一份金融/证券研究报告中的图片。
请重点关注：
1. 图片展示的核心内容或信息
2. 关键数据或文字信息（如有）
3. 图片的标题或说明（如有）
请用简洁、准确的中文描述，不超过200字。"""


def _encode_image_to_base64(image_path):
    """将图片编码为base64字符串"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_image_mime_type(image_path):
    """根据文件扩展名获取MIME类型"""
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    return mime_map.get(ext, "image/jpeg")


def _call_vision_model(image_path, prompt, model="qwen-vl-plus"):
    """
    调用DashScope多模态大模型
    :param image_path: 图片文件的完整路径
    :param prompt: 提示词
    :param model: 模型名称
    :return: 模型返回的文本内容，失败返回空字符串
    """
    img_base64 = _encode_image_to_base64(image_path)
    mime_type = _get_image_mime_type(image_path)

    messages = [
        {
            "role": "user",
            "content": [
                {"image": f"data:{mime_type};base64,{img_base64}"},
                {"text": prompt},
            ],
        }
    ]

    response = dashscope.MultiModalConversation.call(
        model=model, messages=messages
    )

    if response.status_code == 200:
        result = response.output.choices[0].message.content
        if isinstance(result, list):
            text_parts = [
                item["text"] for item in result if isinstance(item, dict) and "text" in item
            ]
            return "".join(text_parts)
        elif isinstance(result, str):
            return result
        else:
            return str(result)
    else:
        print(f"多模态API调用失败: {response.code} - {response.message}")
        return ""


def is_table_or_chart(image_path, model="qwen-vl-plus"):
    """
    判断图片是否为表格或图表
    :param image_path: 图片文件的完整路径
    :param model: 模型名称
    :return: True表示是表格/图表，False表示不是
    """
    result = _call_vision_model(image_path, CLASSIFICATION_PROMPT, model)
    return "是" in result.strip()


def describe_image(image_path, model="qwen-vl-plus"):
    """
    为图片生成文字描述
    :param image_path: 图片文件的完整路径
    :param model: 模型名称
    :return: 图片的中文描述
    """
    return _call_vision_model(image_path, DESCRIPTION_PROMPT, model)


def _find_images_dir_for_report(report_name, mineru_images_dir):
    """
    在永久图片目录中查找指定报告对应的图片目录。
    :param report_name: 报告名称（不含扩展名）
    :param mineru_images_dir: 01_mineru_images根目录
    :return: 图片目录路径（包含images子目录的目录），未找到返回None
    """
    report_images_dir = os.path.join(mineru_images_dir, report_name)
    if os.path.isdir(os.path.join(report_images_dir, "images")):
        return report_images_dir
    return None


def _load_image_desc_cache(cache_dir):
    """加载图片描述缓存"""
    cache_path = os.path.join(cache_dir, "image_desc_cache.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_image_desc_cache(cache_dir, cache):
    """保存图片描述缓存"""
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "image_desc_cache.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def process_report_images(
    content_list_path,
    images_base_dir,
    markdown_path,
    model="qwen-vl-plus",
    skip_classification=False,
):
    """
    处理报告中的图片：判断是否为非表格图表图片，如果是则生成描述并更新markdown。

    :param content_list_path: content_list.json的路径
    :param images_base_dir: 图片文件所在的基础目录（该目录下有images子目录）
    :param markdown_path: 要更新的markdown文件路径
    :param model: 使用的多模态模型名称
    :param skip_classification: 是否跳过分类步骤，直接为所有图片生成描述
    :return: 处理的图片数量
    """
    # 缓存目录与content_list.json同目录
    cache_dir = os.path.dirname(content_list_path)
    cache = _load_image_desc_cache(cache_dir)
    base_name = os.path.splitext(os.path.basename(markdown_path))[0]

    # 检查缓存：如果之前已处理过（无论是否有图片），直接跳过
    cached_record = cache.get(base_name)
    if cached_record and cached_record.get("status") in ("no_images", "completed"):
        print(f"缓存记录显示图片描述已处理（{cached_record['status']}），跳过: {base_name}")
        return 0

    with open(content_list_path, "r", encoding="utf-8") as f:
        content_list = json.load(f)

    image_entries = []
    for item in content_list:
        item_type = item.get("type", "")
        has_content = bool(item.get("content", "").strip())
        if item_type == "image" and not has_content:
            image_entries.append(item)
        elif item_type == "chart" and not has_content:
            image_entries.append(item)

    if not image_entries:
        print("没有需要处理的非表格图表图片")
        # 保存缓存：该报告无待处理图片
        cache[base_name] = {
            "status": "no_images",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        _save_image_desc_cache(cache_dir, cache)
        return 0

    print(f"发现 {len(image_entries)} 个待处理的图片条目")

    with open(markdown_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    processed_count = 0

    for entry in image_entries:
        img_path = entry.get("img_path", "")
        if not img_path:
            continue

        img_filename = os.path.basename(img_path)
        img_ref = f"![]({img_path})"

        # 检查markdown中是否已有该图片的描述，避免重复调用多模态模型
        if img_ref in md_content:
            # 查找图片引用后面是否已有[图片描述]标记
            ref_idx = md_content.find(img_ref)
            after_ref = md_content[ref_idx + len(img_ref):ref_idx + len(img_ref) + 50]
            if "[图片描述]" in after_ref:
                print(f"已有图片描述，跳过: {img_filename}")
                continue

        full_img_path = os.path.join(images_base_dir, img_path)
        if not os.path.exists(full_img_path):
            print(f"图片文件不存在，跳过: {full_img_path}")
            continue

        print(f"正在处理图片: {img_filename}")

        if not skip_classification:
            if is_table_or_chart(full_img_path, model):
                print(f"  -> 识别为表格/图表图片，跳过: {img_filename}")
                continue

        description = describe_image(full_img_path, model)
        if not description:
            print(f"  -> 描述生成失败，跳过: {img_filename}")
            continue

        if img_ref in md_content:
            description_block = f"\n\n**[图片描述]** {description}"
            md_content = md_content.replace(img_ref, img_ref + description_block, 1)
            processed_count += 1
            print(f"  -> 已添加描述: {img_filename}")
        else:
            print(f"  -> 未在markdown中找到图片引用: {img_ref}")

    if processed_count > 0:
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"已更新markdown文件，共处理 {processed_count} 张图片: {markdown_path}")
    else:
        print("没有图片需要添加描述")

    # 保存缓存：该报告图片描述已处理完成
    cache[base_name] = {
        "status": "completed",
        "processed_count": processed_count,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    _save_image_desc_cache(cache_dir, cache)

    return processed_count


def process_all_reports_images(
    mineru_json_dir,
    mineru_markdown_dir,
    mineru_images_dir,
    model="qwen-vl-plus",
    skip_classification=False,
):
    """
    批量处理所有报告的图片描述。
    遍历01_mineru_json目录中的JSON文件，找到对应的图片和markdown文件，
    为非表格图表图片生成描述并更新markdown。

    :param mineru_json_dir: 01_mineru_json目录路径
    :param mineru_markdown_dir: 01_mineru_markdown目录路径
    :param mineru_images_dir: 01_mineru_images根目录路径（包含图片文件）
    :param model: 使用的多模态模型名称
    :param skip_classification: 是否跳过分类步骤
    :return: 总处理的图片数量
    """
    total_processed = 0

    if not os.path.exists(mineru_json_dir):
        print(f"JSON目录不存在: {mineru_json_dir}")
        return 0

    for json_filename in os.listdir(mineru_json_dir):
        if not json_filename.endswith(".json"):
            continue

        base_name = os.path.splitext(json_filename)[0]
        json_path = os.path.join(mineru_json_dir, json_filename)
        md_path = os.path.join(mineru_markdown_dir, f"{base_name}.md")

        if not os.path.exists(md_path):
            print(f"对应的markdown文件不存在，跳过: {md_path}")
            continue

        images_base_dir = _find_images_dir_for_report(base_name, mineru_images_dir)
        if not images_base_dir:
            print(f"未找到图片目录，跳过: {base_name}")
            continue

        print(f"\n{'='*60}")
        print(f"处理报告: {base_name}")
        print(f"{'='*60}")

        count = process_report_images(
            content_list_path=json_path,
            images_base_dir=images_base_dir,
            markdown_path=md_path,
            model=model,
            skip_classification=skip_classification,
        )
        total_processed += count

    print(f"\n所有报告处理完成，共处理 {total_processed} 张图片")
    return total_processed
