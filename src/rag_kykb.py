"""麒麟知识库客户端（Kylin Knowledge Base SDK）— 替代 LightRAG 的知识库方案。

接入方式: Gio.DBusProxy 调用 com.kylin.AiBusiness.Knowledgebase（session/system bus）。
接口（D-Bus, JSON 参数）:
  - createKnowledgeBase / deleteKnowledgeBase
  - addTextFiles / getTextFileContents
  - similaritySearch

运行时依赖:
  - 系统包 kylin-ai-knowledge-base-service（已安装）
  - 服务需注册到 D-Bus（当前 SSH 无桌面会话时服务可能未注册 → 调用会抛
    KnowledgeBaseUnavailable，提示需麒麟桌面会话）

用法:
  from src.rag_kykb import KylinKnowledgeBase
  kb = KylinKnowledgeBase()
  kb.create_knowledge_base("test")
  kb.add_text_files("test", "/path/file.txt")
  result = kb.similarity_search("test", "查询内容", top_k=5)
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("rag.kykb")

BUS_NAME = "com.kylin.AiBusiness.Knowledgebase"
OBJECT_PATH = "/com/kylin/AiBusiness/Knowledgebase"
INTERFACE = "com.kylin.AiBusiness.Knowledgebase"

TIMEOUT_MS = 30000  # 30s 调用超时


class KnowledgeBaseUnavailable(RuntimeError):
    """知识库服务不可用（未注册 D-Bus / 无桌面会话）。"""


class KylinKnowledgeBase:
    """麒麟知识库客户端（D-Bus JSON 协议）。"""

    def __init__(self, bus_type: str = "auto"):
        self._bus_type = bus_type  # "auto" | "session" | "system"
        self._proxy = None

    # ---------------- 连接 ----------------
    def _ensure_proxy(self):
        if self._proxy is not None:
            return self._proxy
        # venv 无 gi 时复用系统 python-gi（麒麟系统自带 /usr/lib/python3/dist-packages）
        try:
            import gi  # noqa: F401
        except ImportError:
            import sys as _sys
            for _p in ("/usr/lib/python3/dist-packages", "/usr/lib/python3.12/dist-packages"):
                if _p not in _sys.path and __import__("os").path.isdir(_p):
                    _sys.path.insert(0, _p)
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except Exception as e:
            raise KnowledgeBaseUnavailable(f"缺少 python-gi (Gio): {e}") from e

        candidates = (Gio.BusType.SESSION, Gio.BusType.SYSTEM)
        if self._bus_type == "session":
            candidates = (Gio.BusType.SESSION,)
        elif self._bus_type == "system":
            candidates = (Gio.BusType.SYSTEM,)

        last_err = ""
        for bt in candidates:
            try:
                conn = Gio.bus_get_sync(bt, None)
                # 检查服务名是否有 owner（避免 proxy 建了但服务不在）
                name_owner = conn.call_sync(
                    "org.freedesktop.DBus", "/org/freedesktop/DBus",
                    "org.freedesktop.DBus", "GetNameOwner",
                    GLib.Variant("(s)", (BUS_NAME,)), None,
                    Gio.DBusCallFlags.NONE, 5000, None,
                ).unpack()[0]
                if not name_owner:
                    last_err = f"服务 {BUS_NAME} 无 owner"
                    continue
                proxy = Gio.DBusProxy.new_sync(
                    conn, Gio.DBusProxyFlags.NONE, None,
                    BUS_NAME, OBJECT_PATH, INTERFACE, None)
                self._proxy = proxy
                logger.info("麒麟知识库已连接: %s (%s)", BUS_NAME, bt)
                return proxy
            except Exception as e:
                last_err = str(e)
                continue
        raise KnowledgeBaseUnavailable(
            f"麒麟知识库服务不可用: {last_err}。"
            f"请确认 kylin-ai-knowledge-base-service 已运行且注册到 D-Bus"
            f"（麒麟桌面会话下正常；SSH 无桌面环境可能不注册）。")

    # ---------------- 通用调用 ----------------
    def call(self, method: str, params: dict) -> dict:
        """调用知识库 D-Bus 方法，返回解析后的 JSON dict。"""
        proxy = self._ensure_proxy()
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
            payload = json.dumps(params, ensure_ascii=False)
            result = proxy.call_sync(
                method, GLib.Variant("(s)", (payload,)),
                Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
            text = result.unpack()[0] if result else ""
            return json.loads(text) if text else {}
        except KnowledgeBaseUnavailable:
            raise
        except Exception as e:
            raise KnowledgeBaseUnavailable(f"调用 {method} 失败: {e}") from e

    # ---------------- 业务方法 ----------------
    def create_knowledge_base(self, name: str) -> dict:
        return self.call("createKnowledgeBase", {"knowledgebaseName": name})

    def delete_knowledge_base(self, name: str) -> dict:
        return self.call("deleteKnowledgeBase", {"knowledgeBaseName": name})

    def add_text_files(self, kb_name: str, filepath: str,
                       fileformat: str = "txt") -> dict:
        """添加文本文件到知识库（filepath 需服务器本地路径）。"""
        params = {"knowledgeBaseName": kb_name, "filepath": filepath,
                  "fileformat": fileformat}
        return self.call("addTextFiles", params)

    def add_text_content(self, kb_name: str, content: str,
                         filename: str = "doc.txt") -> dict:
        """文本内容入库（写入临时 txt 文件后 addTextFiles）。"""
        import os, tempfile
        fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="kykb_", dir="/tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            return self.add_text_files(kb_name, tmp, "txt")
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def similarity_search(self, kb_name: str, query: str,
                          top_k: int = 5, threshold: float = 0.0) -> dict:
        """相似度检索。返回 JSON（含命中片段）。"""
        params = {"knowledgeBaseName": kb_name, "query": query,
                  "top_k": top_k, "threshold": threshold}
        return self.call("similaritySearch", params)

    def get_text_file_contents(self, kb_name: str, filepath: str) -> dict:
        return self.call("getTextFileContents", {"knowledgeBaseName": kb_name,
                                                 "filepath": filepath})

    # ---------------- 状态 ----------------
    def available(self) -> bool:
        """探测服务是否可用（不抛异常）。"""
        try:
            self._ensure_proxy()
            return True
        except Exception:
            return False


# 模块级单例
_kb: KylinKnowledgeBase | None = None


def get_kb() -> KylinKnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KylinKnowledgeBase()
    return _kb
