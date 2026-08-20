"""轻量知识图谱记忆（报告第 9 章）

节点(NODES) + 边(EDGE, AYES 肯定 / DENIES 否定)，支持 STRONG/weak 记忆判定、
强相关节点群发现、边权 = stronger matching → stronger EDGE。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Iterable, Mapping

STRONG_THRESHOLD = 0.7   # 强度 ≥ 阈值 → 强记忆
WEAK_THRESHOLD = 0.3     # 强度 < 阈值 → 弱记忆（接近 denies）


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _nid(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


class EdgeType:
    AYES = "AYES"      # 肯定：事实成立
    DENIES = "DENIES"  # 否定：事实被否认


@dataclass
class KGNode:
    id: str
    label: str
    text: str = ""
    strength: float = 0.5
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class KGEdge:
    source: str
    target: str
    type: str = EdgeType.AYES
    weight: float = 0.5
    last_updated: str = field(default_factory=_now)


class KnowledgeGraph:
    """内存版知识图谱：节点 + 边 + 强弱记忆 + 群组。"""

    def __init__(self):
        self._nodes: dict[str, KGNode] = {}
        self._edges: list[KGEdge] = []

    # ---- 节点 ----
    def add_node(self, label: str, text: str = "", strength: float = 0.5) -> KGNode:
        nid = _nid(text or label)
        node = self._nodes.get(nid)
        if node:
            node.strength = strength
            node.updated_at = _now()
            return node
        node = KGNode(id=nid, label=label, text=text, strength=strength)
        self._nodes[nid] = node
        return node

    def get_node(self, nid: str) -> KGNode | None:
        return self._nodes.get(nid)

    # ---- 边 ----
    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str = EdgeType.AYES,
        weight: float | None = None,
    ) -> KGEdge:
        """边权遵循 stronger matching → stronger EDGE：未显式给权时由两端强度均值决定。"""
        src = self._nodes.get(source) or self.add_node(source, source)
        tgt = self._nodes.get(target) or self.add_node(target, target)
        if weight is None:
            weight = round((src.strength + tgt.strength) / 2, 4)
        edge = KGEdge(source=source, target=target, type=edge_type, weight=weight)
        self._edges.append(edge)
        # 边影响节点强度：AYES 强化，DENIES 衰减
        delta = 0.05 if edge_type == EdgeType.AYES else -0.05
        src.strength = round(min(1.0, max(0.0, src.strength + delta)), 4)
        tgt.strength = round(min(1.0, max(0.0, tgt.strength + delta)), 4)
        src.updated_at = tgt.updated_at = _now()
        return edge

    # ---- 查询 ----
    def neighbors(self, nid: str) -> list[tuple[str, str, float]]:
        """返回 (对方节点id, 边类型, 边权)。"""
        out = []
        for e in self._edges:
            if e.source == nid:
                out.append((e.target, e.type, e.weight))
            elif e.target == nid:
                out.append((e.source, e.type, e.weight))
        return out

    def query(self, label: str = "", top_k: int = 10) -> list[KGNode]:
        nodes = [n for n in self._nodes.values() if not label or n.label == label]
        nodes.sort(key=lambda n: n.strength, reverse=True)
        return nodes[:top_k]

    # ---- 强弱记忆 ----
    def strong_memories(self) -> list[KGNode]:
        return [n for n in self._nodes.values() if n.strength >= STRONG_THRESHOLD]

    def weak_memories(self) -> list[KGNode]:
        return [n for n in self._nodes.values() if n.strength < WEAK_THRESHOLD]

    # ---- 强相关节点群（简单连通分量聚类）----
    def related_groups(self, min_group: int = 2) -> list[list[str]]:
        adj: dict[str, set[str]] = {nid: set() for nid in self._nodes}
        for e in self._edges:
            if e.type == EdgeType.AYES:
                adj[e.source].add(e.target)
                adj[e.target].add(e.source)
        seen: set[str] = set()
        groups: list[list[str]] = []
        for nid in self._nodes:
            if nid in seen:
                continue
            stack, group = [nid], []
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                group.append(cur)
                stack.extend(adj[cur] - seen)
            if len(group) >= min_group:
                groups.append(group)
        return groups

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return {
            "nodes": [asdict(n) for n in self._nodes.values()],
            "edges": [asdict(e) for e in self._edges],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, path: str) -> None:
        """持久化知识图谱到 JSON 文件（原子写）。"""
        import os as _os
        _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        _os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "KnowledgeGraph":
        """从 JSON 恢复知识图谱；文件缺失或损坏时返回空图。"""
        kg = cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            nodes = data.get("nodes", []) if isinstance(data, dict) else []
            edges = data.get("edges", []) if isinstance(data, dict) else []
            for nd in nodes:
                nid = nd.get("id", "")
                if not nid:
                    continue
                kg._nodes[nid] = KGNode(
                    id=nid,
                    label=nd.get("label", ""),
                    text=nd.get("text", ""),
                    strength=float(nd.get("strength", 0.5)),
                    created_at=nd.get("created_at", ""),
                    updated_at=nd.get("updated_at", ""),
                )
            for ed in edges:
                kg._edges.append(KGEdge(
                    source=ed.get("source", ""),
                    target=ed.get("target", ""),
                    type=ed.get("type", EdgeType.AYES),
                    weight=float(ed.get("weight", 0.5)),
                    last_updated=ed.get("last_updated", ""),
                ))
        except Exception:
            pass
        return kg

    def __len__(self) -> int:
        return len(self._nodes)
