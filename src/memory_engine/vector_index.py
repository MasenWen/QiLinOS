"""HNSW 向量索引（报告性能优化：替代线性扫描）

基于 MilvusLite（pymilvus MilvusClient）的 HNSW 近似最近邻索引。
检索延迟从 O(n) 线性扫描降到 O(log n)，支撑大记忆池。
"""
from __future__ import annotations

import os
import tempfile
from typing import Iterable, Optional

from pymilvus import MilvusClient, DataType, FieldSchema, CollectionSchema


class HNSWVectorIndex:
    """轻量 HNSW 向量索引封装（MilvusLite 嵌入式）。"""

    def __init__(
        self,
        dim: int = 768,
        metric_type: str = "COSINE",
        m: int = 16,
        ef_construction: int = 200,
        ef: int = 100,
        uri: str | None = None,
    ):
        self.dim = dim
        self.metric_type = metric_type
        self.m = m
        self.ef_construction = ef_construction
        self.ef = ef
        if uri is None:
            fd, path = tempfile.mkstemp(prefix="hnsw_", suffix=".db")
            os.close(fd)
            os.remove(path)  # MilvusLite 需要路径不存在（自行创建）
            uri = path
        self._uri = uri
        self._client = MilvusClient(uri=uri)
        self._collection = "hnsw_vec"
        self._built = False
        self._id_to_text: dict[str, str] = {}

    def build(self, ids: Iterable[str], vectors: Iterable[list[float]], texts: Iterable[str]) -> None:
        """建集合 + HNSW 索引 + 插入向量。"""
        ids = list(ids)
        vectors = list(vectors)
        texts = list(texts)
        if not ids:
            return
        schema = CollectionSchema(
            fields=[
                FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=512, is_primary=True),
                FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
            ]
        )
        self._client.create_collection(
            collection_name=self._collection,
            schema=schema,
            metric_type=self.metric_type,
        )
        ip = self._client.prepare_index_params()
        ip.add_index(
            field_name="vector",
            index_type="HNSW",
            metric_type=self.metric_type,
            params={"M": self.m, "efConstruction": self.ef_construction},
        )
        self._client.create_index(collection_name=self._collection, index_params=ip)
        self._client.insert(
            collection_name=self._collection,
            data=[
                {"id": str(ids[i]), "vector": v, "text": t}
                for i, (v, t) in enumerate(zip(vectors, texts))
            ],
        )
        self._id_to_text = dict(zip(map(str, ids), texts))
        self._built = True

    def search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        """ANN 检索，返回 [(id, 相似度)]。"""
        if not self._built:
            return []
        hits = self._client.search(
            collection_name=self._collection,
            data=[query_vector],
            limit=top_k,
            search_params={"params": {"ef": self.ef}},
            output_fields=["id", "text"],
        )
        out = []
        for item in hits[0]:
            entity = item.get("entity", {})
            out.append((str(entity.get("id", item.get("id", ""))), float(item.get("distance", 0.0))))
        return out

    def search_text(self, query_vector: list[float], top_k: int = 5) -> list[tuple[str, str, float]]:
        """返回 [(id, text, 相似度)]。"""
        out = []
        for nid, score in self.search(query_vector, top_k):
            out.append((nid, self._id_to_text.get(nid, ""), score))
        return out

    @property
    def uri(self) -> str:
        return self._uri

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
        try:
            if os.path.exists(self._uri):
                os.remove(self._uri)
        except Exception:
            pass
