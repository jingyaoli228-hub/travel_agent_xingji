"""Deterministic implementation of TripCraft's four separate metrics."""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Optional, Protocol, Sequence

import numpy as np
from pydantic import BaseModel, Field
try:  # SciPy is the production implementation; NumPy/math keep degraded installs importable.
    from scipy.linalg import inv
    from scipy.special import factorial
except ImportError:  # pragma: no cover - exercised only before requirements are installed
    inv = np.linalg.inv
    factorial = math.factorial

from travel_agent.evaluation.attraction_duration_config import ATTRACTION_DURATION_HOURS
from travel_agent.evaluation.tripcraft_parameters import (
    ATTRACTION_PARAMETERS, MEAL_PARAMETERS, METRIC_THRESHOLDS, SPATIAL_D0_METERS,
    SPATIAL_LAMBDA, nearest_duration_bucket,
)
from travel_agent.schemas.constraints import ConstraintValidationReport
from travel_agent.schemas.itinerary import Itinerary


class TripCraftMetricReport(BaseModel):
    temporal_meal_score: Optional[float] = None
    temporal_attraction_score: Optional[float] = None
    spatial_score: Optional[float] = None
    persona_score: Optional[float] = None
    persona_score_multilingual: Optional[float] = None
    metric_coverage: dict[str, Any] = Field(default_factory=dict)
    metric_missing_data: list[dict[str, Any]] = Field(default_factory=list)
    constraint_passed: bool = False
    hard_violations: list[dict[str, Any]] = Field(default_factory=list)
    commonsense_violations: list[dict[str, Any]] = Field(default_factory=list)
    low_score_dimensions: list[str] = Field(default_factory=list)
    engineering_adaptations: list[str] = Field(default_factory=list)


class Embedder(Protocol):
    def __call__(self, texts: Sequence[str]) -> np.ndarray: ...


def meal_score(midpoint_hour: float, duration_hour: float, parameters: tuple[float, float, float, float, float]) -> float:
    mean_t, mean_d, std_t, std_d, beta = parameters
    delta = np.array([midpoint_hour - mean_t, duration_hour - mean_d], dtype=float)
    covariance = np.array([[std_t ** 2, beta * std_t * std_d], [beta * std_t * std_d, std_d ** 2]])
    return float(np.exp(-.5 * delta @ inv(covariance) @ delta))


def attraction_score(duration: float, category: str, count: int, traveler_type: str, parameters: dict[str, float]) -> float:
    lam = parameters[f"{traveler_type}_lambda"]
    base = ATTRACTION_DURATION_HOURS[category]
    if traveler_type == "adventurous":
        expected = base - parameters["k"] * (count - parameters["n_min"])
    else:
        expected = base + parameters["k"] * (parameters["n_max"] - count)
    gaussian = math.exp(-((duration - expected) ** 2) / (2 * parameters["sigma"] ** 2))
    try:
        denominator = factorial(count, exact=True)
    except TypeError:  # math.factorial fallback
        denominator = factorial(count)
    poisson = (lam ** count) * math.exp(-lam) / float(denominator)
    return gaussian * poisson


def spatial_point_score(distance_meters: float, d0: float = SPATIAL_D0_METERS, decay: float = SPATIAL_LAMBDA) -> float:
    if distance_meters < 0:
        raise ValueError("distance must be non-negative")
    return 1 - .5 * distance_meters / d0 if distance_meters <= d0 else .5 * math.exp(-decay * (distance_meters - d0))


def persona_cosine_score(profile_texts: Sequence[str], poi_names: Sequence[str], embedder: Embedder) -> Optional[float]:
    if len(profile_texts) != 4 or not poi_names:
        return None
    vectors = np.asarray(embedder([*profile_texts, *poi_names]), dtype=float)
    profile_vectors, poi_vectors = vectors[:4], vectors[4:]
    norms = np.linalg.norm(profile_vectors, axis=1)[:, None] * np.linalg.norm(poi_vectors, axis=1)[None, :]
    similarities = np.divide(profile_vectors @ poi_vectors.T, norms, out=np.zeros_like(norms), where=norms != 0)
    return float(similarities.mean())


class BertMeanPoolEmbedder:
    """Lazy strict-reproduction embedder: bert-base-uncased + attention-mask mean pooling."""
    model_name = "bert-base-uncased"

    def __init__(self) -> None:
        self._tokenizer = self._model = None

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        import torch
        from transformers import AutoModel, AutoTokenizer
        if self._tokenizer is None:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, local_files_only=True)
            self._model = AutoModel.from_pretrained(self.model_name, local_files_only=True)
            self._model.eval()
        tokens = self._tokenizer(list(texts), padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            hidden = self._model(**tokens).last_hidden_state
        mask = tokens["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
        return ((hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)).cpu().numpy()


class TripCraftMetricEvaluator:
    def __init__(self, embedder: Optional[Embedder] = None, thresholds: Optional[dict[str, float]] = None) -> None:
        self.embedder = embedder
        self.thresholds = thresholds or METRIC_THRESHOLDS

    def evaluate(self, itinerary: Itinerary, persona: dict[str, Any], constraints: ConstraintValidationReport) -> TripCraftMetricReport:
        days = max(len(itinerary.days), 1)
        bucket, adapted = nearest_duration_bucket(days)
        adaptations = [f"{days} 天使用最近的 {bucket} 天参数桶（工程适配，非论文新公式）"] if adapted else []
        meals, attractions, distances, poi_names, missing = [], [], [], [], []
        transit_total = 0
        for day in itinerary.days:
            day_attractions = [item for item in day.items if item.activity == "attraction"]
            n = len(day_attractions)
            for item in day.items:
                start = self._hour(item.time)
                duration = item.duration_minutes / 60
                meal_kind = item.activity if item.activity in ("breakfast", "lunch", "dinner") else None
                if meal_kind and start is not None:
                    meals.append(meal_score(start + duration / 2, duration, MEAL_PARAMETERS[bucket][meal_kind]))
                if item.activity == "attraction":
                    poi_names.append(item.location)
                    category = getattr(item, "primary_category", None)
                    planned = getattr(item, "planned_duration_hours", None) or duration
                    if not category or category not in ATTRACTION_DURATION_HOURS:
                        missing.append({"metric": "temporal_attraction", "day": day.day_number, "poi": item.location, "field": "primary_category"})
                    else:
                        traveler = str(persona.get("traveler_type") or "laidback").replace("laid-back", "laidback")
                        if traveler == "mixed":
                            weight = float(persona.get("adventurous_weight", .5))
                            value = weight * attraction_score(planned, category, n, "adventurous", ATTRACTION_PARAMETERS[bucket]) + (1-weight) * attraction_score(planned, category, n, "laidback", ATTRACTION_PARAMETERS[bucket])
                            adaptations.append("mixed 画像按 adventurous/laidback 加权（工程扩展）")
                        else:
                            traveler = traveler if traveler in ("adventurous", "laidback") else "laidback"
                            value = attraction_score(planned, category, n, traveler, ATTRACTION_PARAMETERS[bucket])
                        attractions.append(value)
                    transit_total += 1
                    distance = getattr(item, "nearest_transit_distance_meters", None)
                    if distance is None:
                        missing.append({"metric": "spatial", "day": day.day_number, "poi": item.location, "field": "nearest_transit_distance_meters"})
                    else:
                        distances.append(spatial_point_score(float(distance)))
        profile_texts = self._persona_texts(persona)
        persona_value = None
        if self.embedder is not None and profile_texts:
            persona_value = persona_cosine_score(profile_texts, poi_names, self.embedder)
        elif not profile_texts:
            missing.append({"metric": "persona", "field": "four_persona_components"})
        else:
            missing.append({"metric": "persona", "field": "bert-base-uncased-local-model"})
        scores = {
            "temporal_meal": float(np.mean(meals)) if meals else None,
            "temporal_attraction": float(np.mean(attractions)) if attractions else None,
            "spatial": float(np.mean(distances)) if distances else None,
            "persona": persona_value,
        }
        low = [name for name, value in scores.items() if value is not None and value < self.thresholds[name]]
        return TripCraftMetricReport(
            temporal_meal_score=scores["temporal_meal"], temporal_attraction_score=scores["temporal_attraction"],
            spatial_score=scores["spatial"], persona_score=scores["persona"],
            metric_coverage={"meal": {"scored": len(meals)}, "attraction": {"scored": len(attractions), "total": len(poi_names)}, "spatial_metric_coverage": len(distances) / transit_total if transit_total else 0.0, "missing_transit_distance_count": transit_total - len(distances), "persona_components": 4 if profile_texts else 0},
            metric_missing_data=missing, constraint_passed=constraints.passed,
            hard_violations=[v.model_dump() for v in constraints.hard_violations], commonsense_violations=[v.model_dump() for v in constraints.commonsense_violations],
            low_score_dimensions=low, engineering_adaptations=list(dict.fromkeys(adaptations)),
        )

    @staticmethod
    def _hour(value: str) -> Optional[float]:
        try:
            h, m = value.split(":")[:2]
            return int(h) + int(m) / 60
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _persona_texts(persona: dict[str, Any]) -> list[str]:
        keys = ("traveler_type", "travel_purposes", "spending_preference", "location_preferences")
        if any(persona.get(key) in (None, "", []) for key in keys):
            return []
        return [", ".join(map(str, persona[key])) if isinstance(persona[key], list) else str(persona[key]) for key in keys]
