"""Mem0 VectorStoreBase adapter backed by Kylin AI vector engine."""
import logging
import os
from typing import Dict, Optional

from pydantic import BaseModel
from mem0.vector_stores.base import VectorStoreBase

from src.memory.kylin_vector_engine_client import open_kylin_vector_client

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.expanduser("~/.nex-agent/mem0_vector_engine")


class OutputData(BaseModel):
    id: Optional[str]
    score: Optional[float]
    payload: Optional[Dict]


class KylinMem0Adapter(VectorStoreBase):
    """Mem0 vector store using the Kylin system vector database."""

    def __init__(self, collection_name: str, embedding_model_dims: int, **kwargs):
        db_path = kwargs.get("path", DEFAULT_DB_PATH)
        uri = kwargs.get("uri")
        self.collection_name = collection_name
        self.embedding_model_dims = embedding_model_dims
        self.client = open_kylin_vector_client(path=db_path, uri=uri, timeout=30)
        self.create_col(collection_name, embedding_model_dims)

    # ---- 集合 ----
    def create_col(self, name, vector_size, distance=None):
        if self.client.has_collection(name):
            self.client.load_collection(name)
            return
        self.client.create_collection(
            collection_name=name,
            dimension=vector_size,
            metric_type="COSINE",
        )
        logger.info("创建 Mem0 集合: %s (dim=%d)", name, vector_size)

    # ---- 写入 ----
    def insert(self, vectors, payloads=None, ids=None):
        data = []
        for i, vec in enumerate(vectors):
            row = {"vector": vec}
            if ids and i < len(ids):
                row["id"] = str(ids[i])
            if payloads and i < len(payloads):
                row["metadata"] = payloads[i]
                row["text"] = payloads[i].get("data", "")
            data.append(row)

        self.client.insert(collection_name=self.collection_name, data=data)

    # ---- 检索 ----
    def search(self, query, vectors, top_k=5, filters=None):
        expr = self._build_filter(filters) if filters else None
        hits = self.client.search(
            collection_name=self.collection_name,
            data=[vectors],
            limit=top_k,
            filter=expr,
            output_fields=["id", "text", "metadata"],
        )
        result = []
        for item in hits[0]:
            entity = item.get("entity", {})
            # Milvus COSINE search returns similarity as "distance"; higher is closer.
            result.append(OutputData(
                id=entity.get("id", item.get("id", "")),
                score=round(item.get("distance", 0), 4),
                payload=entity.get("metadata", {}),
            ))
        return result

    def keyword_search(self, query, top_k=5, filters=None):
        return None

    # ---- 删除 ----
    def delete(self, vector_id):
        self.client.delete(
            collection_name=self.collection_name,
            ids=[str(vector_id)],
        )

    # ---- 更新 ----
    def update(self, vector_id, vector=None, payload=None):
        data = {"id": str(vector_id), "vector": vector, "metadata": payload or {}}
        if payload and payload.get("data"):
            data["text"] = payload["data"]
        self.client.upsert(collection_name=self.collection_name, data=[data])

    # ---- 查询 ----
    def get(self, vector_id):
        result = self.client.get(
            collection_name=self.collection_name,
            ids=[str(vector_id)],
            output_fields=["id", "text", "metadata"],
        )
        if not result:
            return None
        r = result[0]
        return OutputData(id=r.get("id"), score=None, payload=r.get("metadata"))

    def list_cols(self):
        return self.client.list_collections()

    def delete_col(self):
        self.client.drop_collection(collection_name=self.collection_name)

    def col_info(self):
        return self.client.get_collection_stats(collection_name=self.collection_name)

    def list(self, filters=None, top_k=None):
        expr = self._build_filter(filters) if filters else None
        result = self.client.query(
            collection_name=self.collection_name,
            filter=expr,
            limit=top_k or 100,
            output_fields=["id", "text", "metadata"],
        )
        return [[OutputData(
            id=r.get("id"), score=None, payload=r.get("metadata"),
        ) for r in result]]

    def reset(self):
        self.delete_col()
        self.create_col(self.collection_name, self.embedding_model_dims)

    # ---- 辅助 ----
    def _build_filter(self, filters: dict) -> Optional[str]:
        if not filters:
            return None
        parts = []
        for k, v in filters.items():
            if isinstance(v, str):
                parts.append(f'(metadata["{k}"] == "{v}")')
            else:
                parts.append(f'(metadata["{k}"] == {v})')
        return " and ".join(parts)
