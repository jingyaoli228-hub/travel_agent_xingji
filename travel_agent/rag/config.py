"""Loads `config/rag.yaml`. Mirrors `travel_agent/evaluation/config.py`
exactly: pydantic model tree, `@lru_cache` keyed on `(path, mtime)`,
all-defaults if the file is missing.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict

import yaml
from pydantic import BaseModel


class ChunkingConfig(BaseModel):
    target_tokens: int = 400
    max_tokens: int = 650
    overlap_tokens: int = 80


class CollectionsConfig(BaseModel):
    travel_guides: str = "travel_guides"
    episodic_memory: str = "episodic_memory"
    user_profile: str = "user_profile"


class RetrievalConfig(BaseModel):
    dense_top_k: int = 20
    rerank_top_k: int = 8
    max_context_chunks: int = 6
    distance_threshold: float = 0.45
    episodic_top_k: int = 5
    profile_top_k: int = 6


class FusionWeights(BaseModel):
    dense: float = 0.45
    keyword: float = 0.20
    metadata: float = 0.15
    source_quality: float = 0.10
    freshness: float = 0.10


class RagConfig(BaseModel):
    chroma_path: str = "./data/chroma"
    embedding_model: str = "onnx-minilm"
    chunking: ChunkingConfig = ChunkingConfig()
    collections: CollectionsConfig = CollectionsConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    fusion_weights: FusionWeights = FusionWeights()


def _default_config_path() -> str:
    return "./config/rag.yaml"


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime: float) -> RagConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}
    return RagConfig(**raw)


def load_rag_config(path: str | None = None) -> RagConfig:
    resolved_path = path or _default_config_path()
    try:
        mtime = os.path.getmtime(resolved_path)
        config = _load_cached(resolved_path, mtime)
    except OSError:
        config = RagConfig()

    # Test isolation, same convention as `EPISODIC_MEMORY_PATH`/
    # `USER_PROFILE_STORE_PATH` (see `Settings`): without this, every test
    # that writes an episode/profile statement or runs `graph/nodes.py`'s
    # memory-context wiring dual-writes into this *same* real `./data/chroma`
    # directory `config/rag.yaml` points at by default -- confirmed live,
    # this silently grew the real `episodic_memory`/`user_profile`
    # collections from test runs before this override existed.
    override = os.environ.get("RAG_CHROMA_PATH")
    if override:
        config = config.model_copy(update={"chroma_path": override})
    return config
