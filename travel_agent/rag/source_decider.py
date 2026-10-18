"""Knowledge Source Decision (requirement doc section 4): decide whether a
query should hit the `travel_guides` RAG knowledge base, live web tools
(`xhs_search`/`google_places`/...), both, memory only, or neither, *before*
running any retrieval. Not every question should trigger a knowledge-base
query.

Rule-based, keyword-driven -- same "offline table first" style as
`destination_intelligence/service.py`'s known-destination lookup. No LLM
fallback: unlike destination complexity assessment (open-ended, needs an
LLM to reason about an unknown destination), this is a five-way
classification over a small, enumerable set of query shapes, and the rule
table + a safe default (`RAG_AND_WEB`, since a research-stage query is
rarely harmed by having both subjective guide content and a live-fact
check available) already covers every case without an LLM call.

Deliberately decoupled from `travel_agent.intent`: `intent_result` is
accessed via `getattr(..., default)` rather than importing `IntentResult`,
so this module has no import-time dependency on the intent pipeline and can
be unit-tested with plain dicts/namespaces.
"""

from __future__ import annotations

from typing import Any, Optional

from travel_agent.rag.schemas import KnowledgeSourceDecision

_WEB_ONLY_KEYWORDS = [
    "天气", "机票", "航班", "汇率", "路况", "签证政策", "签证要求", "实时",
    "营业时间", "开放时间", "闭馆", "门票价格", "票价", "现在几点", "今天开门",
]
_RAG_ONLY_KEYWORDS = [
    "攻略", "玩法", "体验感", "小众", "避坑", "拍照", "怎么玩", "有什么好玩",
    "本地人", "私藏", "值不值得", "节奏建议", "游玩感受",
]
_MEMORY_ONLY_KEYWORDS = ["我之前", "我说过", "我上次", "我的偏好", "我一直", "还记得"]
_NO_RETRIEVAL_TASK_TYPES = {"GENERAL_CONVERSATION"}
_NO_RETRIEVAL_GREETINGS = ["你好", "谢谢", "好的", "嗯嗯", "ok", "OK", "收到"]


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def decide_source(
    raw_query: str,
    intent_result: Optional[Any] = None,
    travel_requirement: Optional[Any] = None,
) -> KnowledgeSourceDecision:
    text = (raw_query or "").strip()

    task_type = getattr(intent_result, "task_type", None)
    if task_type in _NO_RETRIEVAL_TASK_TYPES or text in _NO_RETRIEVAL_GREETINGS:
        return KnowledgeSourceDecision(mode="NO_RETRIEVAL", reason="通用寒暄/闲聊，无需检索")

    if not text:
        return KnowledgeSourceDecision(mode="NO_RETRIEVAL", reason="空查询")

    if _contains_any(text, _MEMORY_ONLY_KEYWORDS):
        return KnowledgeSourceDecision(mode="MEMORY_ONLY", reason="用户在询问自己过去说过的偏好/历史")

    is_web = _contains_any(text, _WEB_ONLY_KEYWORDS)
    is_rag = _contains_any(text, _RAG_ONLY_KEYWORDS)

    if is_web and is_rag:
        return KnowledgeSourceDecision(mode="RAG_AND_WEB", reason="既包含主观体验类关键词，也包含强时效性关键词")
    if is_web:
        return KnowledgeSourceDecision(mode="WEB_ONLY", reason="命中强时效性关键词（天气/票价/营业时间等）")
    if is_rag:
        return KnowledgeSourceDecision(mode="RAG_ONLY", reason="命中攻略/体验类关键词")

    requires_research = bool(getattr(intent_result, "requires_research", False))
    if requires_research:
        return KnowledgeSourceDecision(mode="RAG_AND_WEB", reason="意图标记为需要研究，攻略经验+实时验证并用")

    return KnowledgeSourceDecision(mode="RAG_AND_WEB", reason="默认：无法明确归类时，攻略经验与实时验证都取")
