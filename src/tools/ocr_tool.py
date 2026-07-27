"""
OCR 文字识别工具 — 使用麒麟 AI Vision SDK 替代外部 ocr_tool 二进制。

之前: subprocess.run(["ocr_tool", image_path], timeout=60)
现在: src.sdk.ai_vision.recognize_text(image_path)
"""
import os
import logging
from typing import Annotated
from langchain_core.tools import tool
from .decorators import log_io
from src.utils.db_manager import log_handler, node_state
from src.sdk.ai_vision import recognize_text, TextRecognitionError, is_available

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)


@tool
@log_io
def ocr_tool(image_path: Annotated[str, "File path of the image that requires text recognition"]) -> str:
    """
    使用麒麟 AI SDK 对图片进行文字识别（OCR）。

    支持格式: PNG, JPG, JPEG, BMP, TIFF, WebP
    """
    image_path = os.path.abspath(image_path.strip())
    logger.info(f"{node_state}-=-文本识别员===待识别的文件路径：{image_path}")

    # 路径校验
    if not os.path.isfile(image_path):
        return f"错误: 图片文件不存在: {image_path}，请检查路径是否正确（注意路径中不要有多余空格）"
    if not image_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')):
        return f"错误: 不支持的文件格式: {image_path}，支持的格式: png, jpg, jpeg, bmp, tiff, webp"

    # 检查 SDK 是否可用
    if not is_available():
        return (
            "错误: Kylin AI Vision SDK (libkysdk-coreai-vision) 不可用。"
            "请在 Kylin 服务器上确认已安装: sudo apt install libkysdk-coreai-vision-dev"
        )

    try:
        text = recognize_text(image_path, timeout=60.0)
        if text:
            logger.info(f"{node_state}-=-文本识别员===识别成功！")
            return f"文本识别结果：\n{text}"
        else:
            logger.info(f"{node_state}-=-文本识别员===识别完成但未获取到文本内容")
            return "文本识别完成，但未识别到文字内容（图片可能为空白或不包含文字）"
    except TextRecognitionError as e:
        logger.error(f"{node_state}-=-文本识别员===SDK 错误: {e}")
        return f"OCR 识别失败: {e}"
    except FileNotFoundError as e:
        logger.info(f"{node_state}-=-文本识别员===文件不存在: {e}")
        return f"错误: {e}"
    except Exception as e:
        logger.error(f"{node_state}-=-文本识别员===未知错误: {e}")
        return f"OCR 识别出错: {e}"
