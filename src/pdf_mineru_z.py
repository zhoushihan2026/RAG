import requests
import time
import zipfile
import os

from dotenv import load_dotenv
load_dotenv()

# 从环境变量读取API Key
api_key = os.getenv("MINERU_API_KEY")

base_url = "https://mineru.net/api/v4"


def get_headers():
    """构造请求头"""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }


def upload_and_parse(local_pdf_path):
    """
    上传本地PDF并提交解析任务，返回batch_id。
    :param local_pdf_path: 本地PDF文件的完整路径
    :return: batch_id
    """
    file_name = os.path.basename(local_pdf_path)

    # 第1步：获取上传链接
    data = {
        "files": [{"name": file_name}],
        "model_version": "vlm"
    }

    resp = requests.post(f"{base_url}/file-urls/batch", headers=get_headers(), json=data)
    result = resp.json()
    print(f"获取上传链接响应: {result}")

    if result.get("code") != 0:
        raise Exception(f"获取上传链接失败: {result.get('msg')}")

    batch_id = result["data"]["batch_id"]
    file_urls = result["data"]["file_urls"]

    # 第2步：PUT上传本地PDF文件（无须设置Content-Type请求头）
    with open(local_pdf_path, "rb") as f:
        upload_resp = requests.put(file_urls[0], data=f)
    print(f"上传状态: {upload_resp.status_code}")
    if upload_resp.status_code not in (200, 201):
        raise Exception(f"文件上传失败: HTTP {upload_resp.status_code}")

    print(f"文件上传成功，batch_id: {batch_id}")
    return batch_id


def get_result(batch_id, output_dir=None):
    """
    轮询解析结果，完成后下载并解压。
    :param batch_id: 上传时返回的batch_id
    :param output_dir: 下载和解压的目标目录，默认为当前目录
    :return: 解压目录路径（str），失败返回None
    """
    while True:
        resp = requests.get(f"{base_url}/extract-results/batch/{batch_id}", headers=get_headers())
        result = resp.json()
        extract_result = result["data"]["extract_result"]

        all_in_progress = True
        for item in extract_result:
            state = item.get("state")
            err_msg = item.get("err_msg", "")
            file_name = item.get("file_name", "")

            if state in ("pending", "running", "waiting-file", "converting"):
                print(f"文件: {file_name}, 状态: {state}, 等待5秒后重试...")
                continue
            elif err_msg:
                print(f"任务出错: {err_msg}")
                return None
            elif state == "done":
                all_in_progress = False
                full_zip_url = item.get("full_zip_url")
                if full_zip_url:
                    # 确保输出目录存在
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                    local_filename = os.path.join(output_dir or ".", f"{batch_id}.zip")
                    print(f"开始下载: {full_zip_url}")
                    r = requests.get(full_zip_url, stream=True)
                    with open(local_filename, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    print(f"下载完成，已保存到: {local_filename}")
                    extract_dir = unzip_file(local_filename)
                    return extract_dir
                else:
                    print("未找到 full_zip_url，无法下载。")
                    return None
            else:
                print(f"未知状态: {state}")
                return None

        if not all_in_progress:
            return None

        # 所有文件都还在处理中，等待后重试
        time.sleep(5)


def unzip_file(zip_path, extract_dir=None):
    """
    解压指定的zip文件到目标文件夹。
    :param zip_path: zip文件路径
    :param extract_dir: 解压目标文件夹，默认为zip同名目录
    :return: 解压目录路径（str）
    """
    if extract_dir is None:
        extract_dir = zip_path.rstrip(".zip")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)
    print(f"已解压到: {extract_dir}")
    return extract_dir


if __name__ == "__main__":
    # 示例：上传并解析本地PDF
    local_pdf = r"data\stock_data\pdf_reports\【财报】中芯国际：中芯国际2024年年度报告.pdf"
    batch_id = upload_and_parse(local_pdf)
    print("batch_id:", batch_id)
    get_result(batch_id)
