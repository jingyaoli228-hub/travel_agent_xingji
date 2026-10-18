"""Query Rewrite (requirement doc section 10): turn a raw user message into
a `RewrittenQuery` -- a raw message is not fit for direct vector search.

Dual-path, same convention as `evaluation/judge.py`/`metadata_extractor.py`:
LLM structured output when a client is given, deterministic keyword
heuristic otherwise (uses the same `topic_vocab.py` table
`metadata_extractor.py` used to tag chunks at ingestion time, so the
heuristic path's `topic_filters` actually line up with real chunk metadata).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from travel_agent.rag.schemas import RewrittenQuery, SourceMode
from travel_agent.rag.topic_vocab import TOPIC_KEYWORDS
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.rag.query_rewriter")

_POSITIVE_MARKERS = ["想要", "希望", "增加", "多安排", "想", "喜欢", "要"]
_NEGATIVE_MARKERS = ["不要", "减少", "太多了", "别再", "不喜欢", "少一点"]
# `is_negative` is checked before `is_positive` in `_extract_preferences`
# (negative wins on overlap), so adding the bare "要" here is safe even
# though "不要"/negative clauses also contain it as a substring -- this is
# what makes plain "我要瑜伽" register as a positive preference, not just
# the more formal "想要"/"希望".
_SPLIT_PATTERN = re.compile(r"[，,。！!？?、\s]+")


def _extract_preferences(text: str) -> tuple[list[str], list[str]]:
    """Heuristic positive/negative preference extraction.

    The marker's sign *persists* across subsequent comma-separated clauses
    until a new marker appears -- confirmed live: "我要瑜伽，跳舞，浮潜，冲浪，
    spa，看日落" (a marker once, then a plain list) only extracted "瑜伽" when
    each clause was judged independently, since "跳舞"/"浮潜"/... on their own
    carry no marker at all. Chinese list-of-things phrasing puts the marker
    once before the list, not on every item, so the sign has to carry
    forward rather than reset every clause."""
    positive, negative = [], []
    current_sign: Optional[str] = None
    for clause in _SPLIT_PATTERN.split(text):
        if not clause:
            continue
        if any(marker in clause for marker in _NEGATIVE_MARKERS):
            current_sign = "negative"
        elif any(marker in clause for marker in _POSITIVE_MARKERS):
            current_sign = "positive"
        for keyword, topic in TOPIC_KEYWORDS.items():
            if keyword not in clause:
                continue
            if current_sign == "negative" and topic not in negative:
                negative.append(topic)
            elif current_sign == "positive" and topic not in positive:
                positive.append(topic)
    return positive, negative


def _heuristic_rewrite(
    raw_query: str, travel_requirement: Optional[Any], retrieval_mode: SourceMode
) -> RewrittenQuery:
    text = raw_query or ""
    positive, negative = _extract_preferences(text)
    topic_filters = sorted(set(positive) | {t for t in TOPIC_KEYWORDS.values() if t in text})

    destination = getattr(travel_requirement, "destination", None)
    destination_filters: Dict[str, Any] = {"destination": destination} if destination else {}

    tokens = [t for t in _SPLIT_PATTERN.split(text) if len(t) >= 2]
    keyword_queries = []
    if destination:
        for token in tokens[:3]:
            query = f"{destination} {token}".strip()
            if query not in keyword_queries:
                keyword_queries.append(query)
    if not keyword_queries:
        keyword_queries = [text] if text else []

    return RewrittenQuery(
        semantic_query=text,
        keyword_queries=keyword_queries,
        sub_queries=[],
        destination_filters=destination_filters,
        topic_filters=list(topic_filters),
        positive_preferences=positive,
        negative_preferences=negative,
        retrieval_mode=retrieval_mode,
    )


def rewrite_query(
    raw_query: str,
    intent_result: Optional[Any] = None,
    travel_requirement: Optional[Any] = None,
    current_plan: Optional[Dict[str, Any]] = None,
    user_profile: Optional[Any] = None,
    destination_profile: Optional[Any] = None,
    retrieval_mode: SourceMode = "RAG_ONLY",
    llm: Optional[Any] = None,
) -> RewrittenQuery:
    if llm is not None:
        rewritten = _rewrite_with_llm(
            raw_query, intent_result, travel_requirement, current_plan, user_profile, destination_profile,
            retrieval_mode, llm,
        )
        if rewritten is not None:
            return rewritten
    return _heuristic_rewrite(raw_query, travel_requirement, retrieval_mode)


def _rewrite_with_llm(
    raw_query: str,
    intent_result: Optional[Any],
    travel_requirement: Optional[Any],
    current_plan: Optional[Dict[str, Any]],
    user_profile: Optional[Any],
    destination_profile: Optional[Any],
    retrieval_mode: SourceMode,
    llm: Any,
) -> Optional[RewrittenQuery]:
    try:
        structured_llm = llm.with_structured_output(RewrittenQuery, method="function_calling")

        def _dump(obj: Any) -> str:
            if obj is None:
                return "无"
            if hasattr(obj, "model_dump"):
                return str(obj.model_dump())
            return str(obj)

        prompt = (
            "请把用户请求改写为适合向量检索/关键词检索的查询。输出 semantic_query（语义查询，"
            "完整通顺的一句话）、keyword_queries（若干关键词组合）、sub_queries（子查询）、"
            "destination_filters（目的地过滤条件）、topic_filters（涉及的活动主题）、"
            "positive_preferences（用户想要的）、negative_preferences（用户想减少/不要的）、"
            f"retrieval_mode 固定填写 '{retrieval_mode}'。\n\n"
            f"用户原始请求: {raw_query}\n"
            f"意图理解结果: {_dump(intent_result)}\n"
            f"结构化旅行需求: {_dump(travel_requirement)}\n"
            f"当前行程: {_dump(current_plan)}\n"
            f"用户画像: {_dump(user_profile)}\n"
            f"目的地画像: {_dump(destination_profile)}\n"
        )
        result = structured_llm.invoke([("human", prompt)])
        if isinstance(result, RewrittenQuery):
            result.retrieval_mode = retrieval_mode
            return result
    except Exception as exc:  # noqa: BLE001 -- fall back to heuristic, never raise
        _logger.warning("query_rewriter LLM path failed, using heuristic: %s", exc)
    return None
