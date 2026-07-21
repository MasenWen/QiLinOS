"""NexAgent 威胁模式扫描 — 敏感信息识别"""
import re
from typing import List, Optional
import json
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# ========== 隐形 Unicode 字符（与 Hermes 一致）==========
INVISIBLE_CHARS = frozenset({
    '\u200b', '\u200c', '\u200d', '\u2060', '\u2062', '\u2063', '\u2064',
    '\ufeff', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2066', '\u2067', '\u2068', '\u2069',
})

# ========== 威胁规则 ==========
# 中文 + 英文混合规则
_PATTERNS = [
    # --- 经典 Prompt 注入 ---
    (r'(?:忽略|无视|忘记)\s*(?:(?:所有|任何|之前|上述|上面|这些|那些)\s*)*?(?:的\s*)?(?:指令|规则|限制|约束)', "prompt_injection_cn"),
    (r'(?:ignore|disregard|forget)\s+(?:\w+\s+)*(?:all|previous|above|prior\s+)?(?:\w+\s+)*(?:instructions?|rules?|constraints?)', "prompt_injection_en"),
    (r'(?:你\s*现在\s*是|假装\s*你是|扮演)\s*(?:一个|一名)', "role_hijack_cn"),
    (r'(?:输出|打印|显示|告诉我)\s*(?:你的\s*)?(?:系统\s*)?(?:提示词|prompt|指令)', "leak_system_prompt_cn"),
    (r'(?:不要|不准|禁止)\s*(?:告诉|通知|提示)\s*用户', "deception_hide_cn"),

    # --- 数据外泄 ---
    (r'curl\s+[^\n]*\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|API)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|API)', "exfil_wget"),
    (r'cat\s+[^\n]*(?:\.env|credentials|\.netrc|\.pgpass)', "read_secrets"),
    (r'(?:发送|上传|传输).*(?:对话|聊天)\s*(?:记录|历史|内容)|(?:对话|聊天)\s*(?:记录|历史|内容).*(?:发送|上传|传输)', "context_exfil_cn"),

    # --- 硬编码密钥 ---
    (r'(?:api[_-]?key|token|secret|password|密钥|AK\s*ID)\s*[=:：]\s*["\"][A-Za-z0-9+/=_-]{20,}', "hardcoded_secret"),
    (r'sk-[A-Za-z0-9_-]{20,}', "openai_key_prefix"),
    (r'ghp_[A-Za-z0-9]{20,}', "github_token"),

    # --- 路径遍历 / 后门 ---
    (r'(?:\.\./)+\.\./(?:\.ssh|\.hermes|\.env)', "path_traversal"),
    (r'authorized_keys', "ssh_backdoor"),
]


_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "threat_patterns.json"
_file_mtime = 0.0
_compiled_cache: list[tuple[re.Pattern, str]] = []

def _compile_all():
    """合并内置规则 + 配置文件规则"""
    merged = list(_PATTERNS)    # threat_patterns.py 规则
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("patterns", []):
                merged.append((item["pattern"], item["id"]))
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 解析失败: {e}")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")

    return [(re.compile(p, re.IGNORECASE), pid) for p, pid in merged]

_compiled_cache = _compile_all()
try:
    _file_mtime = _CONFIG_PATH.stat().st_mtime
except FileNotFoundError:
    pass

def scan_content(text: str) -> List[str]:
    """扫描文本，返回命中的规则 ID 列表"""
    global _compiled_cache, _file_mtime
    # 检测配置文件是否被修改
    try:
        current_mtime = _CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        current_mtime = 0.0
    # print(current_mtime)
    # print(_file_mtime)
    if current_mtime != _file_mtime:
        print("检测到配置文件已被修改，正在加载最新的配置文件")
        _compiled_cache = _compile_all()
        _file_mtime = current_mtime

    if not text:
        return []
    findings = []
    # 隐形字符
    char_set = set(text)
    for ch in char_set & INVISIBLE_CHARS:
        findings.append(f"invisible_unicode_U+{ord(ch):04X}")
    # 正则匹配
    for compiled, pid in _compiled_cache:
        if compiled.search(text):
            findings.append(pid)
    return findings

def is_safe(text: str) -> bool:
    """文本是否安全（无任何威胁命中）"""
    return len(scan_content(text)) == 0


def first_threat(text: str) -> Optional[str]:
    """返回第一条威胁描述，无命中返回 None"""
    findings = scan_content(text)
    if not findings:
        return None
    pid = findings[0]
    if pid.startswith("invisible_unicode_"):
        return f"内容包含隐形 Unicode 字符 {pid.replace('invisible_unicode_', '')}，疑似注入攻击"
    return f"内容匹配威胁模式 '{pid}'，已拦截"