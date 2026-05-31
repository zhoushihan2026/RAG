"""
将 MinerU 解析后的 full.md 和 content_list.json 合并，
生成带页码标记的 markdown 文件。

策略：以 full.md 为主体内容（保留完整表格、图表等），
利用 content_list.json 的 page_idx 信息定位分页点，
在 full.md 中插入 "---\\n# Page N" 标记。

算法：通过序列对齐，将 content_list 中的每个元素按顺序
匹配到 full.md 的对应行，确定每行的页码归属。
"""
import json
import os
import re
from typing import Optional


def _extract_item_text(item: dict) -> str:
    """
    从 content_list 的单个元素中提取可用于匹配的文本片段。
    """
    item_type = item.get("type", "")

    if item_type == "text":
        return item.get("text", "").strip()

    elif item_type == "list":
        # list 类型在 full.md 中的格式不确定，跳过
        return ""

    elif item_type == "table":
        caption = item.get("table_caption", [])
        if caption and isinstance(caption, list):
            cap_text = "".join(str(c) for c in caption).strip()
            if cap_text:
                return cap_text
        # 尝试从 table_body 提取第一个单元格文本
        body = item.get("table_body", "")
        if body:
            match = re.search(r'<td>([^<]+)</td>', body)
            if match:
                return match.group(1).strip()
        return ""

    elif item_type == "chart":
        # chart 通常在 full.md 中以图片引用或 details 块出现
        # 暂不作为匹配锚点
        return ""

    elif item_type == "image":
        img_path = item.get("img_path", "")
        if img_path:
            # 用图片文件名的一部分作为匹配特征
            return os.path.basename(img_path)
        return ""

    return ""


def _is_match(text1: str, text2: str) -> bool:
    """
    判断两段文本是否匹配。
    去掉 markdown 标题前缀后进行子串匹配。
    """
    clean1 = re.sub(r'^#+\s*', '', text1).strip()
    clean2 = re.sub(r'^#+\s*', '', text2).strip()

    if not clean1 or not clean2:
        return False

    # 子串匹配：任一方是另一方的子串
    if clean1 in clean2 or clean2 in clean1:
        return True

    return False


def insert_page_markers(full_md_text: str, content_list: list) -> str:
    """
    在 full.md 文本中插入页码标记。
    使用序列对齐算法：按顺序将 content_list 的每个元素匹配到 markdown 的对应行，
    确定每行的页码归属，然后在页码变化处插入标记。
    :param full_md_text: full.md 的完整文本
    :param content_list: content_list.json 解析后的列表
    :return: 带页码标记的 markdown 文本
    """
    skip_types = {'header', 'footer', 'page_number'}

    # 1. 从 content_list 提取有序的 (page_idx, text) 序列
    cl_sequence = []
    for item in content_list:
        item_type = item.get("type", "")
        if item_type in skip_types:
            continue
        page_idx = item.get("page_idx", 0)
        text = _extract_item_text(item)
        if text and len(text) >= 2:
            cl_sequence.append((page_idx, text))

    if not cl_sequence:
        return full_md_text

    lines = full_md_text.split('\n')
    line_pages = [None] * len(lines)  # 每行对应的 page_idx，None 表示未分配

    # 2. 序列对齐：贪心匹配
    cl_idx = 0
    for line_idx, line in enumerate(lines):
        if cl_idx >= len(cl_sequence):
            break

        clean_line = re.sub(r'^#+\s*', '', line).strip()
        if not clean_line or len(clean_line) < 2:
            continue

        # 尝试匹配当前 content_list 项
        _, cl_text = cl_sequence[cl_idx]
        if _is_match(cl_text, clean_line):
            # 匹配成功，分配页码
            line_pages[line_idx] = cl_sequence[cl_idx][0]
            cl_idx += 1
        # 如果匹配失败，该行不分配（后续会通过插值分配）

    # 3. 对未分配的行进行插值（使用前后最近已分配行的页码）
    last_page = 0
    for i in range(len(lines)):
        if line_pages[i] is not None:
            last_page = line_pages[i]
        else:
            line_pages[i] = last_page

    # 4. 确定每页的起始行号
    page_start_lines = {}
    for i, page in enumerate(line_pages):
        if page not in page_start_lines:
            page_start_lines[page] = i

    # 5. 从后向前插入页码标记（避免位置偏移）
    result_lines = lines[:]
    for page_idx in sorted(page_start_lines.keys(), reverse=True):
        line_no = page_start_lines[page_idx]
        page_number = page_idx + 1
        marker = f"---\n\n# Page {page_number}\n"
        result_lines.insert(line_no, marker)

    return '\n'.join(result_lines)


def convert_content_list_json_to_markdown(
    json_path: str,
    output_md_path: str,
    full_md_path: Optional[str] = None
) -> str:
    """
    读取 content_list.json，结合 full.md 生成带页码标记的 markdown 文件。
    :param json_path: content_list.json 的路径
    :param output_md_path: 输出 markdown 文件的路径
    :param full_md_path: full.md 的路径，如果为 None 则尝试在同目录下查找
    :return: 生成的 markdown 文本
    """
    with open(json_path, "r", encoding="utf-8") as f:
        content_list = json.load(f)

    # 查找 full.md
    if full_md_path is None:
        json_dir = os.path.dirname(json_path)
        full_md_path = os.path.join(json_dir, "full.md")

    if not os.path.exists(full_md_path):
        print(f"警告：未找到 full.md: {full_md_path}，回退到从 JSON 直接生成")
        return _fallback_convert(content_list, output_md_path)

    # 读取 full.md
    with open(full_md_path, "r", encoding="utf-8") as f:
        full_md_text = f.read()

    # 插入页码标记
    markdown_text = insert_page_markers(full_md_text, content_list)

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_md_path) or ".", exist_ok=True)
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)

    print(f"已生成带页码标记的 markdown: {output_md_path}")
    return markdown_text


def _fallback_convert(content_list: list, output_md_path: str) -> str:
    """
    回退方案：从 content_list.json 直接生成 markdown（可能丢失表格等格式）。
    """
    skip_types = {'header', 'footer', 'page_number'}

    pages = {}
    for item in content_list:
        item_type = item.get("type", "")
        if item_type in skip_types:
            continue
        page_idx = item.get("page_idx", 0)
        if page_idx not in pages:
            pages[page_idx] = []
        pages[page_idx].append(item)

    md_parts = []
    for page_idx in sorted(pages.keys()):
        page_number = page_idx + 1
        md_parts.append("\n---\n\n")
        md_parts.append(f"# Page {page_number}\n")
        for item in pages[page_idx]:
            item_type = item.get("type", "")
            if item_type == "text":
                text = item.get("text", "").strip()
                text_level = item.get("text_level", 0)
                if text_level > 0:
                    prefix = "#" * text_level
                    md_parts.append(f"{prefix} {text}\n")
                else:
                    md_parts.append(f"{text}\n")
            elif item_type == "table":
                table_body = item.get("table_body", "")
                caption = item.get("table_caption", [])
                footnote = item.get("table_footnote", [])
                if caption:
                    md_parts.append("".join(str(c) for c in caption) + "\n\n")
                if table_body:
                    md_parts.append(table_body + "\n")
                if footnote:
                    md_parts.append("".join(str(c) for c in footnote) + "\n")
            elif item_type == "list":
                list_items = item.get("list_items", [])
                for li in list_items:
                    if isinstance(li, str):
                        md_parts.append(f"- {li.strip()}\n")
            elif item_type == "image":
                img_path = item.get("img_idx", "")
                if img_path:
                    md_parts.append(f"![image](images/{img_path})\n")

    markdown_text = "".join(md_parts).strip() + "\n"
    os.makedirs(os.path.dirname(output_md_path) or ".", exist_ok=True)
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)

    print(f"已生成带页码标记的 markdown（回退模式）: {output_md_path}")
    return markdown_text


if __name__ == "__main__":
    # 示例：手动测试
    json_path = r"f654503b-e78b-4f2a-bb00-6149fac0e69e\7a8765bf-32af-46dd-ad0a-d1a79c0a9988_content_list.json"
    full_md = r"f654503b-e78b-4f2a-bb00-6149fac0e69e\full.md"
    output_path = r"test_page_markdown.md"
    convert_content_list_json_to_markdown(json_path, output_path, full_md)
