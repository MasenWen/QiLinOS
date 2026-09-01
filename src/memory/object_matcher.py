# -*- coding: utf-8 -*-
"""
对象名精确匹配通道（报告 24/25 优化落地）
=====================================
背景：1 万条记忆库中纯向量检索 R@20=0.053；对象名精确匹配通道 R@20=0.204-0.232。
原理：query 中的文件名/业务对象名（如 客户周报.docx、付款申请）精确出现在
      Gold 记忆文本中，而向量相似度捕获不了这种字符串关联。
"""
import re
import logging

logger = logging.getLogger(__name__)

# 对象名提取：
# 1) 文件名：中文/英文/数字 + 扩展名（要求前面不是字母数字，避免动词带入）
# 2) 高频业务对象名
# 注意：不能用 raw string 写 \u4e00（raw 中不转义），用普通字符串拼接
OBJ_RE = re.compile(
    "(?<![A-Za-z0-9\u4e00-\u9fff])[A-Za-z0-9\u4e00-\u9fff_（）()\-]{2,20}\\."
    "(?:docx|xlsx|pptx|md|txt|csv|pdf|xls|ppt)"
    "|"
    "付款申请|差旅许可|报销|行动项|例会|收件箱|合同|审批"
    "|"
    "客户周报|经营月报|工作总结|出差安排|学习计划|设计评审"
    "|"
    "年度合同|本周行动项|个人汇报|部门例会|邮件收件箱"
)


# 文件名前的常见动词（提取后清洗，避免"处理经营月报.xlsx"与记忆中的"经营月报.xlsx"失配）
_VERB_PREFIXES = [
    "处理", "整理", "继续", "准备", "查看", "修改", "检查", "跟进",
    "接着", "编写", "完成", "打开", "关闭", "保存", "删除", "更新",
    "上传", "下载", "创建", "编辑", "生成", "汇报", "安排", "完成好",
    "把", "先", "做", "写", "弄", "看", "查",
]


def extract_objs(query: str) -> set:
    """从 query 提取对象名集合（清洗动词前缀）。"""
    if not query:
        return set()
    objs = set()
    for o in OBJ_RE.findall(query):
        if "." in o:  # 文件名：剥离动词前缀
            for v in _VERB_PREFIXES:
                if o.startswith(v):
                    o = o[len(v):]
                    break
        if o:
            objs.add(o)
    return objs


class ObjectIndex:
    """对象名 → 记忆 的文本索引（每用户懒构建，增量维护）。"""

    _instances = {}  # (vs_id, user_id) -> ObjectIndex

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
