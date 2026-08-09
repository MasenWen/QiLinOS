"""
Embedding Service — session-pool based text embedding with automatic fallback.

Replaces the shared-session pattern in kylin_embedder.py (which causes ctypes
segfault after 5-6 consecutive C calls on Kylin V11 + Python 3.12.3).

Strategy: per-call create→init→embed→get→destroy lifecycle prevents state corruption.

Fallback chain:
  1. SDK session pool (primary, competition required)
  2. ONNX GTE-base (SDK fails after 3 retries)
  3. DashScope API (ONNX unavailable)
  4. Enhanced BM25 (last resort, no embedding vector)
"""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import List, Optional

import numpy as np

logger = logging.getLogger("memory_engine.embedding_service")


# ============================================================================
# C types — mirrors libkysdk-coreai-embedding.so API
# ============================================================================

class _TextEmbeddingSession(ctypes.Structure):
    pass


class _EmbeddingResult(ctypes.Structure):
    pass


# ============================================================================
# SDK Session Pool (P0 fix: per-call create/destroy)
# ============================================================================

class KylinEmbeddingSessionPool:
    """Session pool that creates a FRESH session per embed call.

    The original KylinEmbedder creates ONE session in __init__() and reuses it
    across ALL embed() calls. On Kylin V11 + Python 3.12.3, this causes ctypes
    state corruption and segfault after ~5-6 consecutive C calls.

    This pool fixes the issue by using the complete lifecycle for EACH call:
        create_session → init_session → text_embedding → get_vector →
        destroy_session

    A semaphore(1) prevents concurrent ctypes calls since the SDK is not
    thread-safe.
    """

    def __init__(self, max_concurrent: int = 1, max_retries: int = 3):
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_retries = max_retries
        self._lib = None
        self._load_lock = threading.Lock()
        self._call_count = 0
        self._error_count = 0
        self._available = True  # becomes False after repeated failures

    # ------------------------------------------------------------------
    # Library loading
    # ------------------------------------------------------------------

    def _load_lib(self):
        if self._lib is not None:
            return self._lib if self._lib is not False else None
        with self._load_lock:
            if self._lib is not None:
                return self._lib if self._lib is not False else None
            try:
                lib = ctypes.cdll.LoadLibrary("libkysdk-coreai-embedding.so.1")
                self._declare_functions(lib)
                self._lib = lib
                logger.info("Kylin embedding SDK library loaded successfully")
                return lib
            except OSError as e:
                logger.warning("Failed to load embedding SDK: %s", e)
                self._lib = False
                return None

    @staticmethod
    def _declare_functions(lib):
        # Session management
        lib.text_embedding_create_session.restype = ctypes.POINTER(_TextEmbeddingSession)

        lib.text_embedding_init_session.argtypes = [ctypes.POINTER(_TextEmbeddingSession)]
        lib.text_embedding_init_session.restype = ctypes.c_int

        lib.text_embedding_destroy_session.argtypes = [
            ctypes.POINTER(ctypes.POINTER(_TextEmbeddingSession)),
        ]

        # Embedding
        lib.text_embedding.argtypes = [
            ctypes.POINTER(_TextEmbeddingSession),
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
        ]
        lib.text_embedding.restype = ctypes.c_bool

        # Result extraction
        lib.embedding_result_get_vector_data.argtypes = [ctypes.POINTER(_EmbeddingResult)]
        lib.embedding_result_get_vector_data.restype = ctypes.POINTER(ctypes.c_float)

        lib.embedding_result_get_vector_length.argtypes = [ctypes.POINTER(_EmbeddingResult)]
        lib.embedding_result_get_vector_length.restype = ctypes.c_int

        lib.embedding_result_get_error_code.argtypes = [ctypes.POINTER(_EmbeddingResult)]
        lib.embedding_result_get_error_code.restype = ctypes.c_int

        lib.embedding_result_get_error_message.argtypes = [ctypes.POINTER(_EmbeddingResult)]
        lib.embedding_result_get_error_message.restype = ctypes.c_char_p

        lib.embedding_result_destroy.argtypes = [
            ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        return self._available and self._load_lib() is not None

    @property
    def stats(self) -> dict:
        return {
            "calls": self._call_count,
            "errors": self._error_count,
            "available": self._available,
            "backend": "openkylin_text_embedding_sdk",
        }

    def embed(self, text: str) -> List[float]:
        """Embed a single text. Returns 768-dim vector."""
        vectors = self.embed_batch([text])
        return vectors[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts with per-call session lifecycle.

        Each text gets its own create→init→embed→get→destroy cycle.
        """
        if not texts:
            return []

        results: List[List[float]] = []
        for text in texts:
            vec = self._embed_one(text)
            results.append(vec)

        # L2 normalization
        arr = np.array(results, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        arr = arr / (norms + 1e-9)
        return arr.tolist()

    def _embed_one(self, text: str) -> List[float]:
        """Full lifecycle embed for ONE text. Session created & destroyed."""
        last_error = None
        for attempt in range(self._max_retries):
            try:
                with self._semaphore:
                    lib = self._load_lib()
                    if lib is None:
                        raise EmbeddingError("SDK library not loaded")

                    session = lib.text_embedding_create_session()
                    if not session:
                        raise EmbeddingError("create_session returned NULL")

                    try:
                        ret = lib.text_embedding_init_session(session)
                        if ret != 0:
                            raise EmbeddingError(f"init_session failed: {ret}")

                        result_ptr = ctypes.POINTER(_EmbeddingResult)()
                        text_bytes = text.encode("utf-8")
                        ok = lib.text_embedding(session, text_bytes, ctypes.byref(result_ptr))

                        if not ok:
                            code = lib.embedding_result_get_error_code(result_ptr)
                            msg_ptr = lib.embedding_result_get_error_message(result_ptr)
                            msg = msg_ptr.decode("utf-8", errors="replace") if msg_ptr else "?"
                            lib.embedding_result_destroy(ctypes.byref(result_ptr))
                            raise EmbeddingError(f"embed failed [{code}]: {msg}")

                        dim = lib.embedding_result_get_vector_length(result_ptr)
                        data = lib.embedding_result_get_vector_data(result_ptr)
                        vec = np.ctypeslib.as_array(data, shape=(dim,)).copy()
                        lib.embedding_result_destroy(ctypes.byref(result_ptr))

                    finally:
                        lib.text_embedding_destroy_session(ctypes.byref(session))

                self._call_count += 1
                return vec.tolist()

            except (EmbeddingError, OSError) as e:
                last_error = e
                self._error_count += 1
                logger.warning(
                    "SDK embed attempt %d/%d failed: %s",
                    attempt + 1, self._max_retries, e,
                )
                continue

        if self._error_count > self._max_retries * 3:
            self._available = False
            logger.error("SDK embedding disabled after %d errors", self._error_count)

        raise EmbeddingError(f"SDK embedding failed after {self._max_retries} retries: {last_error}")


# ============================================================================
# Fallback backends
# ============================================================================

class ONNXEmbeddingBackend:
    """Fallback: ONNX runtime with GTE-base model."""

    backend_id = "onnx_gte_base"

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._available = False
        self._init_lock = threading.Lock()

    @property
    def is_available(self) -> bool:
        if self._model is not None:
            return self._available
        with self._init_lock:
            if self._model is not None:
                return self._available
            try:
                self._init_onnx()
                self._available = True
            except Exception as e:
                logger.warning("ONNX backend unavailable: %s", e)
                self._available = False
        return self._available

    def _init_onnx(self):
        # Try to load from existing rag module
        try:
            from src.rag.kylin_embedding_onnx import KylinEmbeddingONNX
            self._model = KylinEmbeddingONNX()
            self.dim = getattr(self._model, "dim", 768)
        except Exception:
            # Try direct onnxruntime
            import onnxruntime
            import os
            model_path = os.path.expanduser("~/work/vendor/kylin-coreai-embedding/model.onnx")
            if os.path.exists(model_path):
                self._model = onnxruntime.InferenceSession(model_path)
                self.dim = 768
            else:
                raise FileNotFoundError(f"ONNX model not found at {model_path}")

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        from src.rag.kylin_embedding_onnx import KylinEmbeddingONNX
        if isinstance(self._model, KylinEmbeddingONNX):
            return self._model.embed_batch(texts)
        # Direct onnxruntime path
        return self._direct_onnx_embed(texts)

    def _direct_onnx_embed(self, texts: List[str]) -> np.ndarray:
        # Placeholder for direct ONNX inference
        raise NotImplementedError("Direct ONNX inference not implemented")


class DashScopeEmbeddingBackend:
    """Fallback: DashScope text-embedding API."""

    backend_id = "dashscope_text_embedding_v3"

    def __init__(self):
        self._available = False
        self._api_key = None
        self._init_lock = threading.Lock()

    @property
    def is_available(self) -> bool:
        if self._api_key is not None:
            return self._available
        with self._init_lock:
            if self._api_key is not None:
                return self._available
            import os
            self._api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
            self._available = bool(self._api_key)
        return self._available

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        import requests
        if not self._api_key:
            raise EmbeddingError("No API key for DashScope")
        vectors = []
        for text in texts:
            resp = requests.post(
                "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": "text-embedding-v3", "input": {"texts": [text]}},
                timeout=30,
            )
            data = resp.json()
            if data.get("output") and data["output"].get("embeddings"):
                vec = data["output"]["embeddings"][0]["embedding"]
                vectors.append(vec)
            else:
                raise EmbeddingError(f"DashScope API error: {data}")
        return np.array(vectors, dtype=np.float32)


# ============================================================================
# Unified EmbeddingService
# ============================================================================

class EmbeddingError(Exception):
    """Raised when all embedding backends fail."""


class EmbeddingService:
    """Unified embedding interface with automatic fallback chain.

    Usage::

        service = EmbeddingService()
        vectors = service.embed_batch(["hello", "world"])
        # → (2, 768) float32 ndarray

        similarity = service.score(query, documents)
        # → {doc_id: cosine_similarity}
    """

    backend_id = "embedding_service_v1"

    def __init__(self, strategy: str = "auto"):
        self._strategy = strategy
        self._sdk_pool = KylinEmbeddingSessionPool()
        self._onnx_backend: Optional[ONNXEmbeddingBackend] = None
        self._cloud_backend: Optional[DashScopeEmbeddingBackend] = None
        self._active_backend: Optional[str] = None
        self._dim = 768

    @property
    def is_available(self) -> bool:
        return (
            self._sdk_pool.is_available
            or self._get_onnx().is_available
            or self._get_cloud().is_available
        )

    @property
    def active_backend(self) -> str:
        return self._active_backend or "not_initialized"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        return self.embed_batch([text]).tolist()[0]

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)

        # Try SDK first (competition primary)
        if self._sdk_pool.is_available:
            try:
                vectors = self._sdk_pool.embed_batch(texts)
                self._active_backend = "openkylin_sdk_session_pool"
                return np.array(vectors, dtype=np.float32)
            except EmbeddingError as e:
                logger.warning("SDK embedding failed: %s, trying ONNX fallback", e)

        # ONNX fallback
        onnx = self._get_onnx()
        if onnx.is_available:
            try:
                vectors = onnx.embed_batch(texts)
                self._active_backend = onnx.backend_id
                return vectors
            except Exception as e:
                logger.warning("ONNX fallback failed: %s", e)

        # Cloud API fallback
        cloud = self._get_cloud()
        if cloud.is_available:
            try:
                vectors = cloud.embed_batch(texts)
                self._active_backend = cloud.backend_id
                return vectors
            except Exception as e:
                logger.warning("Cloud API fallback failed: %s", e)

        raise EmbeddingError("All embedding backends exhausted")

    def score(
        self,
        query: str,
        documents: List[str],  # or List[StrictMemory]
    ) -> dict:
        """Score documents against query using cosine similarity.

        Compatible with KylinSDKSemanticScorer.score() interface for
        drop-in replacement in strict/retrieval.py.
        """
        from .strict.rendering import render_memory

        if not documents:
            return {}
        if hasattr(documents[0], "memory_id"):
            # StrictMemory objects
            doc_texts = [render_memory(doc) for doc in documents]
            doc_ids = [doc.memory_id for doc in documents]
        else:
            doc_texts = list(documents)
            doc_ids = [str(i) for i in range(len(doc_texts))]

        vectors = self.embed_batch([query] + doc_texts)
        query_vec = vectors[0]
        doc_vecs = vectors[1:]

        from math import sqrt
        scores = {}
        for i, (doc_id, doc_vec) in enumerate(zip(doc_ids, doc_vecs)):
            dot = float((query_vec * doc_vec).sum())
            q_norm = sqrt(float((query_vec * query_vec).sum()))
            d_norm = sqrt(float((doc_vec * doc_vec).sum()))
            if q_norm > 0 and d_norm > 0:
                scores[doc_id] = max(0.0, min(dot / (q_norm * d_norm), 1.0))
            else:
                scores[doc_id] = 0.0
        return scores

    def _get_onnx(self) -> ONNXEmbeddingBackend:
        if self._onnx_backend is None:
            self._onnx_backend = ONNXEmbeddingBackend()
        return self._onnx_backend

    def _get_cloud(self) -> DashScopeEmbeddingBackend:
        if self._cloud_backend is None:
            self._cloud_backend = DashScopeEmbeddingBackend()
        return self._cloud_backend


# ============================================================================
# Module-level singleton
# ============================================================================

_embedding_service: Optional[EmbeddingService] = None
_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    """Get or create the global EmbeddingService singleton."""
    global _embedding_service
    if _embedding_service is None:
        with _lock:
            if _embedding_service is None:
                _embedding_service = EmbeddingService()
    return _embedding_service
