"""Kylin vector database client for RAG storage."""
import os
import numpy as np
from typing import Optional

from src.memory.kylin_vector_engine_client import open_kylin_vector_client


class KylinVectorDB:
    """Thin wrapper around the Kylin AI vector engine."""

    def __init__(self, collection_name: str = "nex_agent_embeddings", dim: int = 768):
        self.collection_name = collection_name
        self.dim = dim
        self.client: Optional[object] = None

    def connect(self):
        """Connect to the system Kylin vector database service."""
        work_dir = os.path.expanduser("~/.nex-agent/rag_vector_engine")
        self.client = open_kylin_vector_client(path=work_dir)
        print(f"[KylinVectorDB] 麒麟向量引擎服务: {work_dir}")

    def ensure_collection(self, drop_if_exists: bool = False):
        """确保集合存在，不存在则创建"""
        if drop_if_exists and self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)

        if not self.client.has_collection(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                dimension=self.dim,
                metric_type="COSINE",
            )
            print(f"[KylinVectorDB] 已创建集合: {self.collection_name} (dim={self.dim})")

        self.client.load_collection(self.collection_name)

    def insert(self, texts: list[str], embeddings: np.ndarray,
               metadatas: list[dict] = None) -> list:
        """插入文本和向量"""
        data = []
        for i, (text, vec) in enumerate(zip(texts, embeddings)):
            row = {
                "vector": vec.tolist(),
                "text": text,
            }
            if metadatas:
                row.update(metadatas[i])
            data.append(row)

        result = self.client.insert(
            collection_name=self.collection_name,
            data=data,
        )
        return result["ids"]

    def search(self, query_embedding: np.ndarray, top_k: int = 5,
               filter_expr: str = None) -> list:
        """向量相似度搜索"""
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_embedding.tolist()],
            limit=top_k,
            filter=filter_expr,
            output_fields=["text"],
        )
        return results[0]

    def delete_by_filter(self, filter_expr: str):
        """按条件删除数据"""
        self.client.delete(
            collection_name=self.collection_name,
            filter=filter_expr,
        )

    def count(self) -> int:
        """获取集合中的记录数"""
        stats = self.client.get_collection_stats(self.collection_name)
        return stats.get("row_count", 0)

    def close(self):
        """释放连接"""
        if self.client:
            self.client.close()
            print("[KylinVectorDB] 连接已关闭")
