# -*- coding: utf-8 -*-
"""
对象名精确匹配通道（报告 24 优化落地）
=====================================
背景：1 万条记忆库中纯向量检索 R@20=0.053；对象名精确匹配通道 R@20=0.232（+338%）。
原理：query 中的文件名/业务对象名（"客户周报.docx"、"付款申请"）精确出现在
      Gold 记忆文本中，而向量相似度捕获不了这种字符串关联。

本模块提供：
  - extract_objs(query)      : 从 query 提取对象名
  - ObjectIndex              : 记忆文本索引（懒构建 + 增量），支持对象名匹配

用法（mem0_store.search 集成）：
  idx = ObjectIndex.get(vs, user_id)      # 懒加载该用户记忆文本
  hits = idx.match(query)                  # [(mid, strength), ...] 按强度降序
"""
import re
import logging

logger = logging.getLogger(__name__)

# 对象名提取：文件名（.docx/.xlsx/.pptx/.md/.txt/.csv 等）+ 高频业务对象名
OBJ_RE = re.compile(
    r"([一-鿿A-Za-z0-9_（）()-]{2,20}\."
    r"(?:docx|xlsx|pptx|md|txt|csv|pdf|xls|ppt)|"
    r"付款申请|差旅许可|报销|行动项|例会|收件箱|合同|审批|"
    r"客户周报|经营月报|工作总结|出差安排|学习计划|设计评审|"
    r"年度合同|本周行动项|个人汇报|部门例会|邮件收件箱)"
)


def extract_objs(query: str) -> set:
    """从 query 提取对象名集合。"""
    if not query:
        return set()
    return set(OBJ_RE.findall(query))


class ObjectIndex:
    """对象名 → 记忆 的文本索引（每用户懒构建，增量维护）。"""

    _instances = {}  # (db_path, user_id) -> ObjectIndex

    def __init__(self, vs, user_id: str):
        self.vs = vs
        self.user_id = user_id
        self.texts = {}      # mid -> text
        self._loaded = False

    @classmethod
    def get(cls, vs, user_id: str):
        key = (id(vs), user_id)
        inst = cls._instances.get(key)
        if inst is None:
            inst = cls(vs, user_id)
            cls._instances[key] = inst
        return inst

    def _load(self):
        """从向量库拉取该用户全部记忆文本（首次调用）。"""
        if self._loaded:
            return
        try:
            rows = self.vs.client.query(
                collection_name=self.vs.collection_name,
                filter=f'user_id == "{self.user_id}"',
                output_fields=["metadata", "text"],
                limit=20000,
            )
            for r in rows:
                md = r.get("metadata") or {}
                mid = md.get("src_memory_id") or r.get("id", "")
                txt = r.get("text") or md.get("data", "")
                if mid and txt:
                    self.texts[mid] = txt
        except Exception as e:
            logger.warning("[ObjectIndex] 加载失败: %s", e)
        self._loaded = True
        logger.info("[ObjectIndex] %s: 载入 %d 条记忆文本", self.user_id, len(self.texts))

    def add(self, mid: str, text: str):
        """增量添加一条记忆（add 记忆后调用）。"""
        if mid and text:
            self.texts[mid] = text

    def match(self, query: str, top_n: int = 50):
        """对象名匹配：返回 [(mid, strength)] 按强度降序（无对象名返回 []）。"""
        objs = extract_objs(query)
        if not objs:
            return []
        self._load()
        scored = []
        for mid, txt in self.texts.items():
            s = 0
            for o in objs:
                if o in txt:
                    s += 2 if "." in o else 1  # 文件名权重更高
            if s:
                scored.append((mid, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_n]
