"""Loads `config/intent_fusion.yaml` -- fusion weights, confidence
thresholds, embedding Top-K, and per-branch timeouts. Nothing in
`fusion_resolver.py`/`interpreter.py` hardcodes a weight or threshold; every
tunable number is read from here so weights can be adjusted from evaluation
data without a code change (per the design doc's "权重可配置；不能硬编码在
业务逻辑中").

Cached by (path, mtime) so editing the YAML during a long-running process
(e.g. a dev server) picks up without a restart, while repeated calls in a
hot loop don't re-parse the file.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict

import yaml
from pydantic import BaseModel, Field

from travel_agent.config.settings import get_settings


class IntentFusionWeights(BaseModel):
    llm_weight: float = 0.60
    embedding_weight: float = 0.25
    pattern_weight: float = 0.15

    agreement_bonus: float = 0.08
    workflow_invalid_penalty: float = 0.50
    ambiguity_penalty: float = 0.20

    high_confidence_threshold: float = 0.82
    medium_confidence_threshold: float = 0.65


class FastPathConfig(BaseModel):
    confidence_threshold: float = 0.75


class EmbeddingConfig(BaseModel):
    top_k: int = 5
    negative_penalty: float = 0.3


class TimeoutConfig(BaseModel):
    embedding_seconds: float = 3.0
    llm_seconds: float = 45.0


class IntentFusionConfig(BaseModel):
    intent_fusion: IntentFusionWeights = Field(default_factory=IntentFusionWeights)
    fast_path: FastPathConfig = Field(default_factory=FastPathConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)


def _default_config_path() -> str:
    return get_settings().intent_fusion_config_path


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime: float) -> IntentFusionConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}
    return IntentFusionConfig(**raw)


def load_fusion_config(path: str | None = None) -> IntentFusionConfig:
    """Return the (cached, mtime-aware) fusion config, or defaults if the
    file is missing -- the pipeline must still run with sane values even
    before `config/intent_fusion.yaml` is deployed to an environment."""
    resolved_path = path or _default_config_path()
    try:
        mtime = os.path.getmtime(resolved_path)
    except OSError:
        return IntentFusionConfig()
    return _load_cached(resolved_path, mtime)
