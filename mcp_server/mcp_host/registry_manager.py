from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Dict, List, Optional

_ALLOWED_EXTS = {".py", ".js", ".mjs", ".cjs"}
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class ServerRegistry:
    """管理 servers_registry.json（CRUD + 校验 + 统一绝对路径保存）。"""

    def __init__(self, registry_path: str = "./mcp_server/servers_registry.json", servers_base_dir: str = "./mcp_server/server"):
        self.registry_path = registry_path
        self.servers_base_dir = servers_base_dir
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._ensure_loaded()

    def _ensure_loaded(self):
        if os.path.exists(self.registry_path):
            self._data = self._load_from_disk()
            return

        # 初始种子（不包含 kylin_server）
        seed_list = [
            {"filename": "bdmap_server.py", "description": "提供百度地图相关的地理服务，包括地址坐标转换、地点搜索、路线规划、天气与路况查询等功能。"},
            {"filename": "api_server.py", "description": "提供多种数据接口能力，如天气查询、翻译服务与星座运势查询等。"},
            {"filename": "filesystem_server.py", "description": "提供文件系统管理功能，包括文件与目录的读取、写入、搜索、移动及元信息获取等操作。"},
            {"filename": "gdmap_server.py", "description": "提供高德地图相关功能，包括地理编码、IP定位、天气查询、路径规划及POI搜索等服务。"},
            {"filename": "local_server.py", "description": "提供本地系统信息服务，包括当前时间日期及GPU显存使用情况查询。"},
        ]

        generated: Dict[str, Dict[str, Any]] = {}
        for item in seed_list:
            filename = item["filename"]
            name, _ = os.path.splitext(filename)
            abs_path = os.path.abspath(os.path.join(self.servers_base_dir, filename))
            generated[name] = {
                "description": item.get("description", ""),
                "filename": filename,
                "abs_path": abs_path,
                "auto_start": True,
            }

        self._data = generated
        self._save_to_disk()

    def _load_from_disk(self) -> Dict[str, Dict[str, Any]]:
        with open(self.registry_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_to_disk(self):
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def list_all_servers(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        with self._lock:
            for name, info in self._data.items():
                out.append({
                    "name": name,
                    "description": info.get("description", ""),
                    "abs_path": info.get("abs_path", ""),
                    "filename": info.get("filename", ""),
                    "auto_start": bool(info.get("auto_start", False)),
                })
        return out

    def get_server_info(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._data.get(name)

    def _validate_name(self, name: str):
        if not _NAME_RE.match(name or ""):
            raise ValueError("name 不合法：只能包含字母/数字/_/-，长度<=64")

    def _resolve_path(self, filename: Optional[str], abs_path: Optional[str]) -> tuple[str, str]:
        if abs_path:
            final_path = os.path.abspath(abs_path)
            final_filename = filename or os.path.basename(final_path)
        else:
            if not filename:
                raise ValueError("abs_path 或 filename 至少提供一个")
            final_filename = filename
            final_path = os.path.abspath(os.path.join(self.servers_base_dir, filename))

        ext = os.path.splitext(final_path)[1].lower()
        if ext not in _ALLOWED_EXTS:
            raise ValueError(f"不支持的脚本后缀：{ext}，仅支持：{sorted(_ALLOWED_EXTS)}")
        if not os.path.exists(final_path):
            raise ValueError(f"找不到脚本文件：{final_path}")
        return final_filename, final_path

    def register_server(
        self,
        name: str,
        filename: Optional[str] = None,
        abs_path: Optional[str] = None,
        description: str = "",
        auto_start: bool = False,
        overwrite: bool = False,
    ):
        self._validate_name(name)
        final_filename, final_path = self._resolve_path(filename, abs_path)

        with self._lock:
            if (not overwrite) and name in self._data:
                raise ValueError(f"server '{name}' 已存在；如需覆盖请设置 overwrite=true")

            self._data[name] = {
                "description": description or "",
                "filename": final_filename,
                "abs_path": final_path,
                "auto_start": bool(auto_start),
            }
            self._save_to_disk()

    def update_server(
        self,
        name: str,
        filename: Optional[str] = None,
        abs_path: Optional[str] = None,
        description: Optional[str] = None,
        auto_start: Optional[bool] = None,
    ):
        with self._lock:
            if name not in self._data:
                raise KeyError(name)
            cur = self._data[name].copy()

        if abs_path is not None or filename is not None:
            final_filename, final_path = self._resolve_path(filename or cur.get("filename"), abs_path or cur.get("abs_path"))
            cur["filename"] = final_filename
            cur["abs_path"] = final_path

        if description is not None:
            cur["description"] = description

        if auto_start is not None:
            cur["auto_start"] = bool(auto_start)

        with self._lock:
            self._data[name] = cur
            self._save_to_disk()

    def unregister_server(self, name: str) -> bool:
        with self._lock:
            if name not in self._data:
                return False
            del self._data[name]
            self._save_to_disk()
            return True
