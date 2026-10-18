"""Offline tests for the Round-6 Phase 3 retrieval chain: source_decider,
query_rewriter, retrievers/*, parallel_retriever, result_merger, reranker,
context_assembler. Anything touching ChromaDB uses `HashEmbeddingFunction`
(deterministic, no model download) via `pytest.importorskip("chromadb")`,
same as `test_rag_ingestion.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from travel_agent.rag.context_assembler import assemble_context
from travel_agent.rag.query_rewriter import rewrite_query
from travel_agent.rag.reranker import rerank
from travel_agent.rag.result_merger import merge_and_score
from travel_agent.rag.schemas import (
    KnowledgeSourceDecision,
    RerankedChunk,
    RetrievalContext,
    RetrievedChunk,
    RewrittenQuery,
)
from travel_agent.rag.source_decider import decide_source

# ---------------------------------------------------------------------------
# source_decider
# ---------------------------------------------------------------------------

def test_decide_source_web_only_for_time_sensitive_query() -> None:
    decision = decide_source("巴厘岛现在天气怎么样")
    assert decision.mode == "WEB_ONLY"


def test_decide_source_rag_only_for_guide_query() -> None:
    decision = decide_source("乌布有什么小众的避坑攻略")
    assert decision.mode == "RAG_ONLY"


def test_decide_source_rag_and_web_when_both_keywords_present() -> None:
    decision = decide_source("乌布瑜伽课的营业时间是什么，有什么小众体验")
    assert decision.mode == "RAG_AND_WEB"


def test_decide_source_memory_only_for_history_reference() -> None:
    decision = decide_source("我之前说过不喜欢连续寺庙对吧")
    assert decision.mode == "MEMORY_ONLY"


def test_decide_source_no_retrieval_for_greeting() -> None:
    assert decide_source("你好").mode == "NO_RETRIEVAL"
    assert decide_source("").mode == "NO_RETRIEVAL"


def test_decide_source_default_fallback_rag_and_web() -> None:
    decision = decide_source("帮我规划一下这段旅程")
    assert decision.mode == "RAG_AND_WEB"


def test_decide_source_no_retrieval_for_general_conversation_task_type() -> None:
    class _FakeIntent:
        task_type = "GENERAL_CONVERSATION"

    assert decide_source("随便聊聊", intent_result=_FakeIntent()).mode == "NO_RETRIEVAL"


# ---------------------------------------------------------------------------
# query_rewriter (heuristic path)
# ---------------------------------------------------------------------------

def test_heuristic_rewrite_extracts_positive_and_negative_preferences() -> None:
    rewritten = rewrite_query("不要去寺庙了，想要多一些瑜伽和spa")
    assert "寺庙参观" in rewritten.negative_preferences
    assert "瑜伽" in rewritten.positive_preferences
    assert "spa" in rewritten.positive_preferences


def test_heuristic_rewrite_marker_persists_across_a_comma_separated_list() -> None:
    """Confirmed live: "我要瑜伽，跳舞，浮潜，冲浪，spa，看日落" (one marker, then a
    plain list) only extracted the first item when each clause was judged
    for a marker independently -- Chinese list phrasing puts the marker once
    before the list, not on every item, so it must carry forward."""
    rewritten = rewrite_query("我要瑜伽，跳舞，浮潜，冲浪，spa，看日落")
    assert set(rewritten.positive_preferences) == {"瑜伽", "舞蹈体验", "浮潜", "冲浪", "spa", "看日落"}


def test_heuristic_rewrite_marker_switches_mid_list() -> None:
    rewritten = rewrite_query("我要瑜伽，浮潜，不要寺庙，酒吧")
    assert set(rewritten.positive_preferences) == {"瑜伽", "浮潜"}
    assert set(rewritten.negative_preferences) == {"寺庙参观", "夜生活"}


def test_heuristic_rewrite_uses_destination_from_travel_requirement() -> None:
    class _FakeRequirement:
        destination = "乌布"

    rewritten = rewrite_query("有什么瑜伽课推荐", travel_requirement=_FakeRequirement())
    assert rewritten.destination_filters.get("destination") == "乌布"
    assert any("乌布" in q for q in rewritten.keyword_queries)


def test_heuristic_rewrite_empty_query_is_safe() -> None:
    rewritten = rewrite_query("")
    assert rewritten.semantic_query == ""
    assert rewritten.keyword_queries == []


class _FakeStructuredLLM:
    def __init__(self, result: object) -> None:
        self._result = result

    def invoke(self, messages: object) -> object:
        return self._result


class _FakeLLM:
    def __init__(self, result: object) -> None:
        self._result = result

    def with_structured_output(self, schema: type, method: str = "function_calling") -> _FakeStructuredLLM:
        return _FakeStructuredLLM(self._result if isinstance(self._result, schema) else schema(**self._result))


def test_rewrite_query_uses_llm_result_when_given() -> None:
    fake_result = RewrittenQuery(semantic_query="乌布特色非传统体验", keyword_queries=["乌布 瑜伽"], retrieval_mode="RAG_ONLY")
    rewritten = rewrite_query("乌布有什么好玩的", llm=_FakeLLM(fake_result), retrieval_mode="RAG_ONLY")
    assert rewritten.semantic_query == "乌布特色非传统体验"


def test_rewrite_query_llm_failure_falls_back_to_heuristic() -> None:
    class _RaisingLLM:
        def with_structured_output(self, schema: type, method: str = "function_calling") -> object:
            raise RuntimeError("simulated outage")

    rewritten = rewrite_query("我想要瑜伽课推荐", llm=_RaisingLLM())
    assert "瑜伽" in rewritten.positive_preferences


# ---------------------------------------------------------------------------
# retrievers: dense / keyword / metadata (need chromadb; HashEmbeddingFunction)
# ---------------------------------------------------------------------------

@pytest.fixture()
def _travel_guides_with_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("chromadb")
    import chromadb

    from travel_agent.rag.chroma_client import HashEmbeddingFunction
    from travel_agent.rag.schemas import TravelGuideChunk

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collection = client.get_or_create_collection(name="travel_guides", embedding_function=HashEmbeddingFunction())
    # `dense_retriever.py`/`keyword_retriever.py`/`metadata_retriever.py`/`embedding_writer.py`
    # each did `from travel_agent.rag.chroma_client import get_collection`, binding their own
    # module-level name at import time -- patching `chroma_client.get_collection` alone does not
    # reach any of those already-bound names (or ones bound later from a stale cached import), so
    # every consuming module must be patched explicitly (same pattern as test_rag_ingestion.py's
    # `_temp_chroma_collection` fixture).
    fake_get_collection = lambda name, embedding_function=None: collection
    for target in (
        "travel_agent.rag.ingestion.embedding_writer.get_collection",
        "travel_agent.rag.retrievers.dense_retriever.get_collection",
        "travel_agent.rag.retrievers.keyword_retriever.get_collection",
        "travel_agent.rag.retrievers.metadata_retriever.get_collection",
    ):
        monkeypatch.setattr(target, fake_get_collection)

    chunks = [
        TravelGuideChunk(
            id="ubud#0::0", content="乌布最有名的瑜伽馆 Yoga Barn，环境很舒服，还有巴厘舞蹈课程",
            parent_document_id="ubud#0", chunk_index=0, collected_time="2026-7-22",
            canonical_destination="巴厘岛", canonical_region="乌布",
            activity_topics=["瑜伽"], travel_styles=["悠闲慢节奏"], quality_score=0.9, freshness_level="fresh",
        ),
        TravelGuideChunk(
            id="ubud#1::0", content="乌布圣猴森林公园，猴子是绝对主角，很多游客来打卡拍照",
            parent_document_id="ubud#1", chunk_index=0, collected_time="2026-7-22",
            canonical_destination="巴厘岛", canonical_region="乌布",
            activity_topics=["寺庙参观"], quality_score=0.6, freshness_level="recent",
        ),
        TravelGuideChunk(
            id="penida#0::0", content="佩尼达岛精灵坠崖和钻石沙滩，浮潜也很推荐",
            parent_document_id="penida#0", chunk_index=0, collected_time="2026-7-22",
            canonical_destination="巴厘岛", canonical_region="佩尼达岛",
            activity_topics=["浮潜"], quality_score=1.0, freshness_level="recent",
        ),
    ]
    from travel_agent.rag.ingestion.embedding_writer import write_chunks

    write_chunks(chunks)
    return collection


# ---------------------------------------------------------------------------
# build_where_filter: destination-name canonicalization (confirmed live bug --
# see travel_agent/rag/retrievers/base.py's docstring for the full story)
# ---------------------------------------------------------------------------

def test_build_where_filter_resolves_english_alias_to_ingested_chinese_region() -> None:
    from travel_agent.rag.retrievers.base import build_where_filter

    where = build_where_filter({"destination": "Ubud"}, [])
    or_clauses = where["$or"]
    assert {"canonical_region": "乌布"} in or_clauses
    assert {"canonical_region": "Ubud"} in or_clauses  # raw string still matched too


def test_build_where_filter_region_scoped_does_not_leak_into_destination_level() -> None:
    """A region-scoped filter must not also match `canonical_destination`,
    or a "乌布" query would incorrectly pull in 佩尼达岛/苍古/... chunks that
    merely share the same island-level `canonical_destination`."""
    from travel_agent.rag.retrievers.base import build_where_filter

    where = build_where_filter({"destination": "乌布"}, [])
    fields_used = {tuple(clause.items())[0][0] for clause in where["$or"]}
    assert fields_used == {"canonical_region", "destination_region"}


def test_build_where_filter_whole_destination_still_matches_destination_level() -> None:
    from travel_agent.rag.retrievers.base import build_where_filter

    where = build_where_filter({"destination": "巴厘岛"}, [])
    or_clauses = where["$or"]
    assert {"canonical_destination": "巴厘岛"} in or_clauses


def test_build_where_filter_unknown_destination_falls_back_to_raw_string() -> None:
    from travel_agent.rag.retrievers.base import build_where_filter

    where = build_where_filter({"destination": "从未见过的地方"}, [])
    assert where == {
        "$or": [
            {"canonical_destination": "从未见过的地方"},
            {"destination_city": "从未见过的地方"},
            {"canonical_region": "从未见过的地方"},
            {"destination_region": "从未见过的地方"},
        ]
    }


def test_metadata_retriever_finds_region_by_english_alias(_travel_guides_with_data) -> None:
    """End-to-end version of the canonicalization fix: querying by the
    English region name `destination_intelligence/service.py` actually
    produces must find chunks ingested under their Chinese canonical name."""
    from travel_agent.rag.retrievers import metadata_retriever

    context = RetrievalContext(rewritten=RewrittenQuery(semantic_query="", destination_filters={"destination": "Ubud"}), top_k=10)
    results = metadata_retriever.retrieve(context)
    assert len(results) == 2
    assert all(r.metadata.get("canonical_region") == "乌布" for r in results)


def test_dense_retriever_returns_scored_chunks(_travel_guides_with_data) -> None:
    from travel_agent.rag.retrievers import dense_retriever

    context = RetrievalContext(rewritten=RewrittenQuery(semantic_query="乌布瑜伽体验"), top_k=10)
    results = dense_retriever.retrieve(context)
    assert len(results) > 0
    assert all(r.dense_score is not None for r in results)
    assert all(r.source_type == "travel_guide" for r in results)


def test_dense_retriever_empty_query_returns_nothing(_travel_guides_with_data) -> None:
    from travel_agent.rag.retrievers import dense_retriever

    context = RetrievalContext(rewritten=RewrittenQuery(semantic_query=""), top_k=10)
    assert dense_retriever.retrieve(context) == []


def test_keyword_retriever_scores_by_term_overlap(_travel_guides_with_data) -> None:
    from travel_agent.rag.retrievers import keyword_retriever

    context = RetrievalContext(
        rewritten=RewrittenQuery(semantic_query="", keyword_queries=["浮潜"], topic_filters=["浮潜"]), top_k=10
    )
    results = keyword_retriever.retrieve(context)
    assert any("佩尼达" in r.content for r in results)


def test_metadata_retriever_filters_by_destination_region(_travel_guides_with_data) -> None:
    from travel_agent.rag.retrievers import metadata_retriever

    context = RetrievalContext(
        rewritten=RewrittenQuery(semantic_query="", destination_filters={"destination": "乌布"}), top_k=10
    )
    results = metadata_retriever.retrieve(context)
    assert len(results) == 2
    assert all(r.metadata.get("canonical_region") == "乌布" for r in results)


def test_metadata_retriever_no_filters_returns_nothing(_travel_guides_with_data) -> None:
    from travel_agent.rag.retrievers import metadata_retriever

    context = RetrievalContext(rewritten=RewrittenQuery(semantic_query=""), top_k=10)
    assert metadata_retriever.retrieve(context) == []


# ---------------------------------------------------------------------------
# retrievers: episodic / profile (existing JSONL/JSON memory stores)
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_memory_paths(tmp_path, monkeypatch):
    """Isolates both the JSONL/JSON stores (as before) and, since Phase 4
    dual-writes episodic/profile data into ChromaDB too, a temp Chroma
    client. `episodic_memory.py`/`profile_memory.py` both do `from
    travel_agent.rag.chroma_client import get_collection` *inside* their
    methods (not at module import time), so patching
    `travel_agent.rag.chroma_client.get_collection` directly is sufficient
    here -- unlike the top-level-import retrievers in
    `_travel_guides_with_data` above, there's no stale-binding trap."""
    from travel_agent.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("EPISODIC_MEMORY_PATH", str(tmp_path / "episodes.jsonl"))
    monkeypatch.setenv("USER_PROFILE_STORE_PATH", str(tmp_path / "profiles.json"))

    pytest.importorskip("chromadb")
    import chromadb

    from travel_agent.rag.chroma_client import HashEmbeddingFunction

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collections: dict = {}

    def _fake_get_collection(name, embedding_function=None):
        if name not in collections:
            collections[name] = client.get_or_create_collection(name=name, embedding_function=HashEmbeddingFunction())
        return collections[name]

    monkeypatch.setattr("travel_agent.rag.chroma_client.get_collection", _fake_get_collection)

    yield
    get_settings.cache_clear()


def test_episodic_retriever_wraps_existing_memory_store(isolated_memory_paths) -> None:
    from travel_agent.memory.episodic_memory import EpisodicMemory
    from travel_agent.rag.retrievers import episodic_retriever
    from travel_agent.schemas.memory import TripEpisode

    EpisodicMemory().add_episode(
        TripEpisode(user_id="user-1", session_id="s1", destination="东京", tags=["music"], feedback=["寺庙太多了"])
    )
    context = RetrievalContext(rewritten=RewrittenQuery(semantic_query="x", topic_filters=["music"]), user_id="user-1")
    results = episodic_retriever.retrieve(context)
    assert len(results) == 1
    assert results[0].source_type == "episodic_memory"
    assert "东京" in results[0].content


def test_episodic_retriever_without_user_id_returns_nothing(isolated_memory_paths) -> None:
    from travel_agent.rag.retrievers import episodic_retriever

    context = RetrievalContext(rewritten=RewrittenQuery(semantic_query="x"), user_id="")
    assert episodic_retriever.retrieve(context) == []


def test_profile_retriever_wraps_existing_profile_store(isolated_memory_paths) -> None:
    from travel_agent.memory.profile_memory import ProfileMemory
    from travel_agent.rag.retrievers import profile_retriever

    ProfileMemory().upsert("user-1", travel_style="悠闲", interest_preference=["瑜伽"])
    context = RetrievalContext(rewritten=RewrittenQuery(semantic_query="x"), user_id="user-1")
    results = profile_retriever.retrieve(context)
    # One RetrievedChunk per preference dimension since Phase 4 (travel_style + interest_preference).
    assert len(results) == 2
    assert any("悠闲" in r.content for r in results)


def test_profile_retriever_missing_profile_returns_nothing(isolated_memory_paths) -> None:
    from travel_agent.rag.retrievers import profile_retriever

    context = RetrievalContext(rewritten=RewrittenQuery(semantic_query="x"), user_id="no-such-user")
    assert profile_retriever.retrieve(context) == []


# ---------------------------------------------------------------------------
# parallel_retriever
# ---------------------------------------------------------------------------

def test_retrieve_all_sync_isolates_errors_between_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    from travel_agent.rag.retrievers import parallel_retriever

    def _ok(context: RetrievalContext) -> List[RetrievedChunk]:
        return [
            RetrievedChunk(chunk_id="a", source_type="travel_guide", content="ok", metadata_score=1.0)
        ]

    def _boom(context: RetrievalContext) -> List[RetrievedChunk]:
        raise RuntimeError("retriever exploded")

    monkeypatch.setitem(parallel_retriever._RETRIEVER_TOOLS, "dense", ("rag.dense_retriever", _ok))
    monkeypatch.setitem(parallel_retriever._RETRIEVER_TOOLS, "keyword", ("rag.keyword_retriever", _boom))

    result = parallel_retriever.retrieve_all_sync(
        RetrievalContext(rewritten=RewrittenQuery(semantic_query="x")), sources=["dense", "keyword"]
    )

    stats_by_source = {s.source: s for s in result.stats}
    assert len(result.chunks) == 1
    assert stats_by_source["dense"].error is None
    assert stats_by_source["keyword"].error is not None


# ---------------------------------------------------------------------------
# result_merger
# ---------------------------------------------------------------------------

def test_merge_combines_scores_for_same_chunk_id() -> None:
    chunks = [
        RetrievedChunk(chunk_id="c1", source_type="travel_guide", retriever="dense", content="text", dense_score=0.8),
        RetrievedChunk(chunk_id="c1", source_type="travel_guide", retriever="keyword", content="text", keyword_score=0.5),
    ]
    merged = merge_and_score(chunks)
    assert len(merged) == 1
    assert merged[0].dense_score == 0.8
    assert merged[0].keyword_score == 0.5


def test_merge_renormalizes_weights_for_single_source_chunk() -> None:
    dense_only = RetrievedChunk(chunk_id="dense-only", source_type="travel_guide", content="a", dense_score=0.8)
    episodic_only = RetrievedChunk(chunk_id="episodic-only", source_type="episodic_memory", content="b", metadata_score=1.0)
    merged = merge_and_score([dense_only, episodic_only])
    by_id = {c.chunk_id: c for c in merged}
    # Renormalized: a chunk with only one score component populated should score
    # close to that component's own value, not be diluted by the other 4 missing weights.
    assert by_id["dense-only"].combined_score == pytest.approx(0.8, abs=1e-6)
    assert by_id["episodic-only"].combined_score == pytest.approx(1.0, abs=1e-6)


def test_merge_drops_near_duplicate_content() -> None:
    chunks = [
        RetrievedChunk(chunk_id="c1", source_type="travel_guide", content="乌布最有名的瑜伽馆，环境很舒服，很推荐大家来体验", dense_score=0.9),
        RetrievedChunk(chunk_id="c2", source_type="travel_guide", content="乌布最有名的瑜伽馆，环境很舒服，超推荐大家来体验", dense_score=0.5),
    ]
    merged = merge_and_score(chunks)
    assert len(merged) == 1
    assert merged[0].chunk_id == "c1"  # higher-scored duplicate wins


def test_merge_applies_diversity_cap_per_parent() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id=f"c{i}", source_type="travel_guide", content=f"完全不同的内容第{i}条 abcdefg{i}",
            dense_score=1.0 - i * 0.01, metadata={"parent_document_id": "same_note"},
        )
        for i in range(5)
    ]
    merged = merge_and_score(chunks, max_per_parent=2)
    assert len(merged) == 2


def test_merge_empty_input() -> None:
    assert merge_and_score([]) == []


# ---------------------------------------------------------------------------
# reranker (heuristic path)
# ---------------------------------------------------------------------------

def test_heuristic_rerank_selects_top_n_by_combined_score() -> None:
    chunks = [
        RetrievedChunk(chunk_id=f"c{i}", source_type="travel_guide", content="x", combined_score=1.0 - i * 0.1)
        for i in range(5)
    ]
    reranked = rerank("query", chunks)
    selected = [r for r in reranked if r.selected]
    assert len(selected) <= 5
    assert {r.chunk_id for r in selected}.issuperset({"c0"})  # highest-scored chunk always kept


def test_rerank_empty_candidates() -> None:
    assert rerank("query", []) == []


def test_rerank_llm_path_caps_overselection() -> None:
    class _OverselectingLLM:
        def with_structured_output(self, schema: type, method: str = "function_calling"):
            class _S:
                def invoke(self, messages: object) -> object:
                    return schema(
                        items=[
                            RerankedChunk(chunk_id="c0", relevance_score=0.9, selected=True),
                            RerankedChunk(chunk_id="c1", relevance_score=0.8, selected=True),
                            RerankedChunk(chunk_id="c2", relevance_score=0.95, selected=True),
                        ]
                    )
            return _S()

    candidates = [RetrievedChunk(chunk_id=f"c{i}", source_type="travel_guide", content="x") for i in range(3)]
    reranked = rerank("query", candidates, llm=_OverselectingLLM())
    # rerank_top_k default is 8, well above 3 candidates -- nothing should be capped away here,
    # this just exercises the LLM path end-to-end and confirms chunk_id fidelity.
    assert {r.chunk_id for r in reranked} == {"c0", "c1", "c2"}


def test_rerank_llm_failure_falls_back_to_heuristic() -> None:
    class _RaisingLLM:
        def with_structured_output(self, schema: type, method: str = "function_calling") -> object:
            raise RuntimeError("simulated outage")

    candidates = [RetrievedChunk(chunk_id="c0", source_type="travel_guide", content="x", combined_score=0.7)]
    reranked = rerank("query", candidates, llm=_RaisingLLM())
    assert reranked[0].chunk_id == "c0"
    assert reranked[0].selected is True


# ---------------------------------------------------------------------------
# context_assembler
# ---------------------------------------------------------------------------

def test_assemble_context_builds_expected_sections() -> None:
    lookup = {
        "p1": RetrievedChunk(chunk_id="p1", source_type="user_profile", content="偏好小众体验"),
        "e1": RetrievedChunk(chunk_id="e1", source_type="episodic_memory", content="曾拒绝连续寺庙"),
        "g1": RetrievedChunk(chunk_id="g1", source_type="travel_guide", content="乌布瑜伽馆推荐", metadata={}),
    }
    reranked = [
        RerankedChunk(chunk_id="p1", relevance_score=1.0, selected=True),
        RerankedChunk(chunk_id="e1", relevance_score=1.0, selected=True),
        RerankedChunk(chunk_id="g1", relevance_score=1.0, selected=True),
    ]
    result = assemble_context(reranked, lookup, KnowledgeSourceDecision(mode="RAG_AND_WEB"))
    assert "[USER PROFILE]" in result.text
    assert "[EPISODIC MEMORY]" in result.text
    assert "[TRAVEL GUIDE]" in result.text
    assert "[LIVE WEB]" in result.text
    assert result.evidence_count == 3


def test_assemble_context_flags_time_sensitive_chunks_for_live_verification() -> None:
    lookup = {
        "g1": RetrievedChunk(
            chunk_id="g1", source_type="travel_guide", content="课程在10:00开始，价格¥100",
            metadata={"source_title": "瑜伽课攻略"},
        ),
    }
    reranked = [RerankedChunk(chunk_id="g1", relevance_score=1.0, selected=True)]
    result = assemble_context(reranked, lookup, KnowledgeSourceDecision(mode="RAG_AND_WEB"))
    assert "瑜伽课攻略" in result.needs_live_verification


def test_assemble_context_omits_live_web_when_rag_only() -> None:
    lookup = {"g1": RetrievedChunk(chunk_id="g1", source_type="travel_guide", content="一般描述")}
    reranked = [RerankedChunk(chunk_id="g1", relevance_score=1.0, selected=True)]
    result = assemble_context(reranked, lookup, KnowledgeSourceDecision(mode="RAG_ONLY"))
    assert "[LIVE WEB]" not in result.text


def test_assemble_context_ignores_unselected_chunks() -> None:
    lookup = {"g1": RetrievedChunk(chunk_id="g1", source_type="travel_guide", content="内容")}
    reranked = [RerankedChunk(chunk_id="g1", relevance_score=0.1, selected=False)]
    result = assemble_context(reranked, lookup, KnowledgeSourceDecision(mode="RAG_ONLY"))
    assert result.text == ""
    assert result.evidence_count == 0
