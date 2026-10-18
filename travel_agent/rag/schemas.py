"""RAG schemas. Phase 2 scope: `TravelGuideChunk` (the unit stored in the
`travel_guides` ChromaDB collection) plus the intermediate shapes the
ingestion pipeline passes between its steps. Phase 3 (below the ingestion
schemas) adds the retrieval-chain shapes: `KnowledgeSourceDecision`,
`RewrittenQuery`, `RetrievedChunk`, `RerankedChunk`, `AssembledContext`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TravelGuideChunk(BaseModel):
    """One retrievable unit in the `travel_guides` collection. Field set is
    per docs/round6_rag_memory_eval_design.md section 4 (== requirement
    doc section 6), plus the canonicalization fields from section 9."""

    id: str

    content: str
    summary: Optional[str] = None

    destination_country: Optional[str] = None
    destination_city: Optional[str] = None
    destination_region: Optional[str] = None

    guide_type: str = ""
    activity_topics: List[str] = Field(default_factory=list)
    travel_styles: List[str] = Field(default_factory=list)

    suitable_for: List[str] = Field(default_factory=list)
    unsuitable_for: List[str] = Field(default_factory=list)

    source_type: str = "小红书"
    source_title: Optional[str] = None
    source_author: Optional[str] = None
    source_url: Optional[str] = None

    publish_time: Optional[str] = None
    collected_time: str = ""

    freshness_level: Optional[str] = None
    quality_score: Optional[float] = None

    parent_document_id: str
    chunk_index: int

    # Canonicalization (requirement doc section 9) -- not in the original
    # schema sketch (section 6) but required by section 9's normalization
    # rules, so it lives on the same record rather than a side table.
    canonical_destination: Optional[str] = None
    canonical_region: Optional[str] = None
    canonical_place_name: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)


class RawNote(BaseModel):
    """One raw note as extracted from a source file, before cleaning. If the
    source file uses the `标题：/目的地：/内容类型：/来源：/发布时间：/采集时间：`
    header-block convention (see `ingestion/document_loader.py`), those
    fields are already split out here; a source file without that structure
    leaves them empty and the whole note is treated as one blob for the
    chunker/metadata_extractor to work with."""

    raw_text: str
    title: Optional[str] = None
    destination_hint: Optional[str] = None
    guide_type_hint: Optional[str] = None
    source_hint: Optional[str] = None
    publish_time: Optional[str] = None
    collected_time: Optional[str] = None
    source_file: str = ""
    note_index: int = 0


class CleanedNote(BaseModel):
    """A `RawNote` post `cleaner.py`: junk stripped, dedup-checked."""

    note: RawNote
    cleaned_text: str
    content_hash: str
    is_duplicate_of: Optional[str] = None


class TextChunk(BaseModel):
    """One chunk out of `semantic_chunker.py`, pre metadata-extraction."""

    parent_document_id: str
    chunk_index: int
    text: str
    section_heading: Optional[str] = None
    estimated_tokens: int = 0


class IngestionReport(BaseModel):
    source_file: str
    notes_found: int = 0
    notes_after_cleaning: int = 0
    duplicates_skipped: int = 0
    chunks_written: int = 0
    chunks_updated: int = 0
    errors: List[str] = Field(default_factory=list)


# ===========================================================================
# Phase 3: retrieval chain
# ===========================================================================

SourceMode = Literal["RAG_ONLY", "WEB_ONLY", "RAG_AND_WEB", "MEMORY_ONLY", "NO_RETRIEVAL"]


class KnowledgeSourceDecision(BaseModel):
    """Output of `source_decider.py` -- requirement doc section 4."""

    mode: SourceMode
    reason: str = ""


class RewrittenQuery(BaseModel):
    """Output of `query_rewriter.py` -- requirement doc section 10, field set
    unchanged from the spec's sketch."""

    semantic_query: str
    keyword_queries: List[str] = Field(default_factory=list)
    sub_queries: List[str] = Field(default_factory=list)

    destination_filters: Dict[str, Any] = Field(default_factory=dict)
    topic_filters: List[str] = Field(default_factory=list)

    positive_preferences: List[str] = Field(default_factory=list)
    negative_preferences: List[str] = Field(default_factory=list)

    retrieval_mode: SourceMode = "RAG_ONLY"


class RetrievalContext(BaseModel):
    """What `parallel_retriever.py` hands to every individual retriever.
    A single shared shape (rather than a different kwarg set per retriever)
    keeps `ToolManager.call(...)` dispatch uniform across all 5 retrievers."""

    rewritten: RewrittenQuery
    user_id: str = ""
    top_k: int = 20


class RetrievedChunk(BaseModel):
    """Unified output shape every retriever in `rag/retrievers/` returns,
    regardless of which collection/store it came from."""

    chunk_id: str
    source_type: Literal["travel_guide", "episodic_memory", "user_profile"]
    retriever: str = ""
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    dense_score: Optional[float] = None
    keyword_score: Optional[float] = None
    metadata_score: Optional[float] = None
    source_quality_score: Optional[float] = None
    freshness_score: Optional[float] = None
    combined_score: float = 0.0


class SourceRetrievalStats(BaseModel):
    """Per-retriever observability (requirement doc section 11: "记录每路延迟
    和命中数")."""

    source: str
    hit_count: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None


class ParallelRetrievalResult(BaseModel):
    chunks: List[RetrievedChunk] = Field(default_factory=list)
    stats: List[SourceRetrievalStats] = Field(default_factory=list)


class RerankedChunk(BaseModel):
    """Output of `reranker.py` -- requirement doc section 14."""

    chunk_id: str
    relevance_score: float
    personalization_score: float = 0.0
    actionability_score: float = 0.0
    freshness_score: float = 0.0
    reason: str = ""
    selected: bool = True


class AssembledContext(BaseModel):
    """Output of `context_assembler.py`: the formatted, four-section text
    block handed to the Research Orchestrator Agent, plus bookkeeping."""

    text: str
    source_decision: KnowledgeSourceDecision
    evidence_count: int = 0
    needs_live_verification: List[str] = Field(default_factory=list)
