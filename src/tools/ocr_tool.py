import subprocess
import time
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from .decorators import log_io
import logging
from typing import Annotated
import os
from src.utils.db_manager import log_handler, node_state

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)

@tool
@log_io
def ocr_tool(image_path: Annotated[str, "File path of the image that requires text recognition"]) -> str:
    """
    调用OCR可执行文件并获取输出
    """
    image_path = os.path.abspath(image_path.strip())
    logger.info(f"{node_state}-=-文本识别员===待识别的文件路径：{image_path}")

    # 路径校验
    if not os.path.isfile(image_path):
        return f"错误: 图片文件不存在: {image_path}，请检查路径是否正确（注意路径中不要有多余空格）"
    if not image_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')):
        return f"错误: 不支持的文件格式: {image_path}，支持的格式: png, jpg, jpeg, bmp, tiff, webp"

    try:
        # 运行可执行文件
        result = subprocess.run(
            ["ocr_tool", image_path],  # 假设可执行文件在当前目录
            capture_output=True,
            text=True,
            timeout=60  # 设置超时时间
        )
        
        # 检查返回码
        if result.returncode == 0:
            logger.info(f"{node_state}-=-文本识别员===识别成功！")
            print("输出内容:")
            print(result.stdout)
            return f"文本识别结果：\n{result.stdout}"
        else:
            print(f"识别失败，错误码: {result.returncode}")
            print(f"错误信息: {result.stderr}")
            return f"识别失败，错误码: {result.returncode}, 错误信息: {result.stderr}"

    except FileNotFoundError:
        logger.info(f"{node_state}-=-文本识别员===错误: 找不到可执行文件")
        return "错误: 找不到 OCR 可执行文件，请确认 ocr_tool 已正确安装"
    except subprocess.TimeoutExpired:
        logger.info(f"{node_state}-=-文本识别员===错误: 处理超时")
        return "错误: OCR 处理超时"
    except Exception as e:
        logger.info(f"{node_state}-=-文本识别员===未知错误: {e}")
        return f"错误: {e}"
