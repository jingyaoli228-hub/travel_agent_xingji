"""Unit tests for travel_agent/intent/embedding_router.py.

Uses the real seeded intent_data/*.jsonl (small, checked-in, deterministic)
-- no network/embedding-API calls are made by this local cosine engine.
"""

from __future__ import annotations

from travel_agent.intent.embedding_router import EmbeddingIntentRetriever


def test_exact_match_recovers_source_intent():
    result = EmbeddingIntentRetriever().retrieve("确认")
    assert result.intent_candidates
    assert result.intent_candidates[0].intent == "CONFIRM_REQUIREMENT"
    assert result.intent_candidates[0].score > 0.9


def test_exact_match_weather_query():
    result = EmbeddingIntentRetriever().retrieve("东京明天天气怎么样")
    assert result.intent_candidates[0].intent == "QUERY_WEATHER"


def test_feedback_candidate_wellness():
    result = EmbeddingIntentRetriever().retrieve("我想多安排一些瑜伽")
    assert result.feedback_candidates
    assert result.feedback_candidates[0].feedback_type == "PREFERS_WELLNESS"


def test_negative_example_exact_match_is_nearest():
    result = EmbeddingIntentRetriever().retrieve("你好")
    assert result.nearest_examples
    assert result.nearest_examples[0].text == "你好"


def test_empty_message_returns_empty_result():
    result = EmbeddingIntentRetriever().retrieve("")
    assert result.intent_candidates == []
    assert result.confidence == 0.0


def test_paraphrase_near_ubud_yoga_example():
    result = EmbeddingIntentRetriever().retrieve("乌布附近再多加两节瑜伽课，其他天先不动")
    top_intents = {c.intent for c in result.intent_candidates[:3]}
    assert "ADD_ACTIVITY" in top_intents or "REPLAN_PARTIAL_DAY" in top_intents
