"""Step 5: fill in the `TravelGuideChunk` metadata fields not already known
from the source file's header block or canonicalization.

Dual-path, same convention as `evaluation/judge.py` / `destination_intelligence
/service.py`: a keyword/regex heuristic that needs no LLM (so ingestion works
offline and deterministically, matching this project's general preference for
an offline-runnable pipeline), and an optional LLM-enrichment pass when a
client is given. The LLM path is what requirement doc section 6 actually
wants long-term (`activity_topics` freely generated, not a fixed enum) --
the heuristic path only recognizes topics that literally appear as keywords
in the text, which is a strict subset of what a real note might describe.

`llm` is passed in per-call, never constructed here -- same rule as every
other module in this codebase (`ReviewerAgent`, `DestinationIntelligenceService`,
`LLMJudge`).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Optional

from travel_agent.rag.ingestion.canonicalization import canonicalize
from travel_agent.rag.schemas import CleanedNote, TextChunk, TravelGuideChunk
from travel_agent.rag.topic_vocab import STYLE_KEYWORDS, TOPIC_KEYWORDS
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.rag.ingestion.metadata_extractor")

_TIME_PATTERN = re.compile(r"\d{1,2}[:：]\d{2}")
_PRICE_PATTERN = re.compile(r"[¥￥]|(?:rmb|元|万|k\b)", re.IGNORECASE)


def _extract_keywords(text: str, table: dict[str, str]) -> List[str]:
    found = []
    for keyword, tag in table.items():
        if keyword in text and tag not in found:
            found.append(tag)
    return found


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _freshness_level(publish_time: Optional[str], collected_time: Optional[str]) -> Optional[str]:
    published = _parse_date(publish_time)
    collected = _parse_date(collected_time) or datetime.now()
    if published is None:
        return None
    age_days = (collected - published).days
    if age_days <= 90:
        return "fresh"
    if age_days <= 365:
        return "recent"
    return "outdated"


def _quality_score(text: str) -> float:
    score = 0.5
    if _TIME_PATTERN.search(text):
        score += 0.15
    if _PRICE_PATTERN.search(text):
        score += 0.15
    if len(text) >= 200:
        score += 0.1
    if "⭐" in text or "推荐" in text:
        score += 0.1
    return round(min(score, 1.0), 2)


def extract_metadata(
    chunk: TextChunk, cleaned: CleanedNote, llm: Optional[Any] = None
) -> TravelGuideChunk:
    note = cleaned.note
    canon = canonicalize(note.destination_hint)

    activity_topics = _extract_keywords(chunk.text, TOPIC_KEYWORDS)
    travel_styles = _extract_keywords(chunk.text, STYLE_KEYWORDS)
    suitable_for: List[str] = []
    unsuitable_for: List[str] = []

    if llm is not None:
        _enrich_with_llm(chunk, activity_topics, travel_styles, suitable_for, unsuitable_for, llm)

    chunk_id = f"{chunk.parent_document_id}::{chunk.chunk_index}"
    return TravelGuideChunk(
        id=chunk_id,
        content=chunk.text,
        summary=chunk.section_heading,
        destination_country=canon["destination_country"],
        destination_city=canon["canonical_destination"],
        destination_region=canon["canonical_region"],
        guide_type=note.guide_type_hint or "",
        activity_topics=activity_topics,
        travel_styles=travel_styles,
        suitable_for=suitable_for,
        unsuitable_for=unsuitable_for,
        source_type=note.source_hint or "小红书",
        source_title=note.title,
        source_author=None,
        source_url=None,
        publish_time=note.publish_time,
        collected_time=note.collected_time or "",
        freshness_level=_freshness_level(note.publish_time, note.collected_time),
        quality_score=_quality_score(chunk.text),
        parent_document_id=chunk.parent_document_id,
        chunk_index=chunk.chunk_index,
        canonical_destination=canon["canonical_destination"],
        canonical_region=canon["canonical_region"],
        canonical_place_name=canon["canonical_place_name"],
        aliases=canon["aliases"],
    )


def _enrich_with_llm(
    chunk: TextChunk,
    activity_topics: List[str],
    travel_styles: List[str],
    suitable_for: List[str],
    unsuitable_for: List[str],
    llm: Any,
) -> None:
    """Best-effort LLM enrichment: append any additional topics/styles the
    LLM notices beyond the keyword heuristic. Mutates the lists in place;
    never raises -- ingestion must keep working if the LLM call fails."""
    try:
        from pydantic import BaseModel, Field

        class _TopicSuggestion(BaseModel):
            activity_topics: List[str] = Field(default_factory=list)
            travel_styles: List[str] = Field(default_factory=list)
            suitable_for: List[str] = Field(default_factory=list)
            unsuitable_for: List[str] = Field(default_factory=list)

        structured_llm = llm.with_structured_output(_TopicSuggestion, method="function_calling")
        prompt = (
            "阅读下面的小红书旅行攻略片段，提取其中的活动主题(activity_topics，自由生成，"
            "不受固定分类限制，可以是瑜伽/巴厘舞蹈/黑胶店等具体活动)、旅行风格(travel_styles)、"
            "适合人群(suitable_for)和不适合人群(unsuitable_for)。\n\n" + chunk.text
        )
        result = structured_llm.invoke([("human", prompt)])
        if isinstance(result, _TopicSuggestion):
            for topic in result.activity_topics:
                if topic not in activity_topics:
                    activity_topics.append(topic)
            for style in result.travel_styles:
                if style not in travel_styles:
                    travel_styles.append(style)
            for tag in result.suitable_for:
                if tag not in suitable_for:
                    suitable_for.append(tag)
            for tag in result.unsuitable_for:
                if tag not in unsuitable_for:
                    unsuitable_for.append(tag)
    except Exception as exc:  # noqa: BLE001 -- enrichment is optional, never fatal
        _logger.warning("metadata_extractor LLM enrichment failed, keeping heuristic tags: %s", exc)
