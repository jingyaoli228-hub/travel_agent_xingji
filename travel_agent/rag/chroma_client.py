"""ChromaDB access point: one process-wide `PersistentClient` (embedded,
no server/Docker) plus a get-or-create helper per collection, and the
embedding-function factory.

Graceful degradation, same spirit as `memory/redis_memory.py` and
`memory/episodic_memory.py`: `embedding_model: onnx-minilm` (the default)
downloads a small ONNX model from Chroma's CDN on first use. If that
download fails (offline dev machine, blocked network) we fall back to a
deterministic hashing embedding -- worse recall quality, but the system
keeps running instead of hard-crashing ingestion/retrieval. Callers can
check `using_fallback_embedding()` to know which mode is active.
"""

from __future__ import annotations

import hashlib
import threading
from typing import List, Optional

from travel_agent.config.settings import get_settings
from travel_agent.rag.config import load_rag_config
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.rag.chroma_client")
_fallback_active = False
_fallback_lock = threading.Lock()
_client_lock = threading.Lock()

_HASH_EMBEDDING_DIM = 384  # matches all-MiniLM-L6-v2's output dim, so a
# collection created under one mode has embeddings of a consistent shape.


from chromadb.utils.embedding_functions import register_embedding_function
from chromadb.api.types import EmbeddingFunction


@register_embedding_function
class HashEmbeddingFunction(EmbeddingFunction):
    """Deterministic bag-of-character-ngram hashing embedding. No model
    download, no semantic understanding -- purely a keep-the-lights-on
    fallback so ingestion/retrieval never hard-fail when the real ONNX
    model can't be fetched. Registered with Chroma (`name`/`get_config`/
    `build_from_config`) so a persisted collection using it can be reopened
    across process restarts without the caller re-supplying an instance."""

    def __init__(self, dim: int = _HASH_EMBEDDING_DIM) -> None:
        self._dim = dim

    def __call__(self, input: List[str]) -> List[List[float]]:
        return [self._embed_one(text) for text in input]

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self._dim
        text = text or ""
        for i in range(len(text) - 1):
            gram = text[i : i + 2]
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dim
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm > 0 else vec

    @staticmethod
    def name() -> str:  # chromadb EmbeddingFunction protocol
        return "hash_ngram_fallback"

    def get_config(self) -> dict:
        return {"dim": self._dim}

    @staticmethod
    def build_from_config(config: dict) -> "HashEmbeddingFunction":
        return HashEmbeddingFunction(dim=config.get("dim", _HASH_EMBEDDING_DIM))


def using_fallback_embedding() -> bool:
    return _fallback_active


def _build_embedding_function():
    global _fallback_active
    config = load_rag_config()
    if config.embedding_model == "hash-fallback":
        with _fallback_lock:
            _fallback_active = True
        return HashEmbeddingFunction()

    try:
        from chromadb.utils import embedding_functions

        fn = embedding_functions.ONNXMiniLM_L6_V2()
        # Chroma lazily downloads the model on first `__call__`, not at
        # construction time -- probe with a throwaway string so a network
        # failure surfaces now (during client setup) rather than mid-ingestion.
        fn(["_probe"])
        return fn
    except Exception as exc:  # noqa: BLE001 -- any failure means "degrade", not "crash"
        _logger.warning("rag embedding degraded to hash fallback: %s", exc)
        with _fallback_lock:
            _fallback_active = True
        return HashEmbeddingFunction()


_client_singleton = None
_embedding_function_singleton = None


def _get_client():
    """Double-checked-locking singleton -- `@lru_cache` alone is not a
    thread-safety guarantee for "construct exactly once" (multiple threads
    can all miss the cache on their first concurrent call and race to build
    it). This matters here because `parallel_retriever.py` dispatches all 5
    retrievers concurrently via `asyncio.to_thread`, so the very first
    request in a process can have several threads calling `get_collection()`
    at once -- confirmed live: without the lock this intermittently raised
    "Could not connect to tenant default_tenant" from two threads racing to
    initialize the same `PersistentClient` path."""
    global _client_singleton
    if _client_singleton is None:
        with _client_lock:
            if _client_singleton is None:
                import chromadb

                settings = get_settings()
                if settings.chroma_host:
                    _client_singleton = chromadb.HttpClient(
                        host=settings.chroma_host,
                        port=settings.chroma_port,
                        ssl=settings.chroma_ssl,
                    )
                    _client_singleton.heartbeat()
                else:
                    if settings.require_persistent_services:
                        raise RuntimeError("CHROMA_HOST is required in persistent deployment mode")
                    config = load_rag_config()
                    _client_singleton = chromadb.PersistentClient(path=config.chroma_path)
    return _client_singleton


def _get_embedding_function():
    global _embedding_function_singleton
    if _embedding_function_singleton is None:
        with _client_lock:
            if _embedding_function_singleton is None:
                _embedding_function_singleton = _build_embedding_function()
    return _embedding_function_singleton


def heartbeat() -> int:
    """Check Chroma through the process-wide client.

    Reusing the singleton matters for Docker's frequent readiness probes;
    constructing a new ``HttpClient`` per probe leaves transports open long
    enough to exhaust the small server's file-descriptor limit.
    """
    return _get_client().heartbeat()


def get_collection(name: str, embedding_function: Optional[object] = None):
    """Get-or-create a ChromaDB collection by its configured name (see
    `config/rag.yaml: collections`). `embedding_function` is only needed to
    override the process-wide default (e.g. tests injecting a fake)."""
    client = _get_client()
    ef = embedding_function if embedding_function is not None else _get_embedding_function()
    return client.get_or_create_collection(name=name, embedding_function=ef)
