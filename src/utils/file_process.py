
import re
import json
from pydantic import BaseModel, Field
from typing import Dict, Any, Literal, Union
from typing_extensions import TypedDict
from src.agent.llm import get_llm_by_type
import logging
from src.utils.db_manager import log_handler
from werkzeug.utils import secure_filename
from flask import send_from_directory
import uuid
import os
from urllib.parse import quote
from pathlib import Path

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)



# 常见 Office/PDF MIME -> 扩展名 映射（仅当原始名没扩展名时使用）
MIME_EXT_MAP = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}



def get_extension_from_mimetype(mimetype):
    """根据MIME类型返回对应的文件扩展名"""
    extension_map = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'application/pdf': '.pdf',
        'text/plain': '.txt',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.ms-excel': '.xls',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'application/zip': '.zip',
        'audio/mpeg': '.mp3',
        'audio/wav': '.wav',
        'video/mp4': '.mp4',
    }
    return extension_map.get(mimetype, '.png')

def make_stored_filename(original_filename: str, mimetype: str | None) -> str:
    """
    生成安全可存储的文件名：
    1) 拆分原始名：stem + ext
    2) secure 仅作用于 stem；ext 直接保留（含 .）
    3) 若 secure 之后 stem 为空，则用 uuid 顶上
    4) 若原始名没有扩展名，尝试用 mimetype 推断
    """
    original_filename = (original_filename or "").strip() or "unnamed"
    orig_stem, orig_ext = os.path.splitext(original_filename)

    # 统一扩展名为小写
    if orig_ext:
        orig_ext = orig_ext.lower()

    # 如果没有扩展名，尝试用 mimetype 猜一个
    if not orig_ext and mimetype:
        guess = MIME_EXT_MAP.get(mimetype.lower())
        if guess:
            orig_ext = guess

    # 对“主文件名”做 secure；中文会被清空，这里要兜底
    secure_stem = secure_filename(orig_stem)  # 只处理 stem，不处理 ext
    if not secure_stem:
        secure_stem = uuid.uuid4().hex  # 保证一定有可用主文件名

    return f"{secure_stem}{orig_ext}"


def make_safe_filename(original_filename, mimetype, save_directory):
    """
    生成安全的存储文件名，如果存在同名文件则自动添加序号
    
    Args:
        original_filename: 原始文件名
        mimetype: 文件的MIME类型
        save_directory: 文件保存目录
    
    Returns:
        str: 安全的存储文件名
    """
    # 安全化文件名
    # safe_filename = secure_filename(original_filename)
    
    # 分离文件名和扩展名
    name, ext = os.path.splitext(original_filename)

    safe_name = re.sub(r'[^\w\u4e00-\u9fff\-\.]', '_', name)
    
    # 如果处理后名称为空，使用UUID
    if not safe_name or safe_name == '_':
        safe_name = uuid.uuid4().hex
    
    # 如果没有扩展名，尝试从MIME类型推断
    if not ext and mimetype:
        ext = get_extension_from_mimetype(mimetype)
    
    # 生成基础文件名（不带序号）
    base_filename = f"{safe_name}{ext}" if name else f"file{ext}"
    
    # 检查文件是否存在并生成唯一文件名
    counter = 1
    final_filename = base_filename
    file_path = os.path.join(save_directory, final_filename)
    
    # 如果文件已存在，添加序号
    while os.path.exists(file_path):
        name_part = name if name else "file"
        final_filename = f"{name_part}-{counter}{ext}"
        file_path = os.path.join(save_directory, final_filename)
        counter += 1
    
    return final_filename

def remove_uploads_prefix(path):
    """移除 /uploads/ 之前的所有字符串"""
    # 方法1：使用正则表达式
    result = re.sub(r'^.*/uploads/', '', path)
    return result