"""Context Assembly (requirement doc section 15): the final step before the
Research Orchestrator Agent -- format the reranker's `selected` chunks into
the four-section text block ([USER PROFILE]/[EPISODIC MEMORY]/[TRAVEL
GUIDE]/[LIVE WEB]), capped at `retrieval.max_context_chunks` so the prompt
doesn't grow unbounded.

[LIVE WEB] is not a retrieved section -- live web search is the existing
`xhs_search`/`google_places` tools' job (`agents/research_agent.py`), not
this module's. When `source_decision.mode` calls for web verification, this
just flags *which* travel-guide chunks contain concrete, time-sensitive
details (times/prices) that the Research Agent should confirm live, so a
subjective guide claim ("阿育吠陀油疗60-90min") doesn't get treated as an
already-verified fact.
"""

from __future__ import annotations

import re
from typing import Dict, List

from travel_agent.rag.config import load_rag_config
from travel_agent.rag.schemas import AssembledContext, KnowledgeSourceDecision, RerankedChunk, RetrievedChunk

_TIME_OR_PRICE_PATTERN = re.compile(r"\d{1,2}[:：]\d{2}|[¥￥]|(?:元|万|k\b)", re.IGNORECASE)

_SECTION_TITLES = {
    "user_profile": "[USER PROFILE]",
    "episodic_memory": "[EPISODIC MEMORY]",
    "travel_guide": "[TRAVEL GUIDE]",
}


def assemble_context(
    reranked: List[RerankedChunk],
    chunk_lookup: Dict[str, RetrievedChunk],
    source_decision: KnowledgeSourceDecision,
) -> AssembledContext:
    max_chunks = load_rag_config().retrieval.max_context_chunks
    selected = [r for r in reranked if r.selected][:max_chunks]

    sections: Dict[str, List[str]] = {"user_profile": [], "episodic_memory": [], "travel_guide": []}
    needs_live_verification: List[str] = []

    for reranked_chunk in selected:
        chunk = chunk_lookup.get(reranked_chunk.chunk_id)
        if chunk is None:
            continue
        sections.setdefault(chunk.source_type, []).append(f"- {chunk.content.strip()}")
        if chunk.source_type == "travel_guide" and _TIME_OR_PRICE_PATTERN.search(chunk.content):
            label = chunk.metadata.get("source_title") or chunk.chunk_id
            if label not in needs_live_verification:
                needs_live_verification.append(label)

    blocks: List[str] = []
    for key in ("user_profile", "episodic_memory", "travel_guide"):
        if sections.get(key):
            blocks.append(_SECTION_TITLES[key] + "\n" + "\n".join(sections[key]))

    if source_decision.mode in ("WEB_ONLY", "RAG_AND_WEB"):
        if needs_live_verification:
            note = f"以下内容涉及具体时间/价格，需要实时验证后再采用：{'、'.join(needs_live_verification)}"
        else:
            note = "具体地点、时间、价格和可用性需要实时验证。"
        blocks.append("[LIVE WEB]\n" + note)

    return AssembledContext(
        text="\n\n".join(blocks),
        source_decision=source_decision,
        evidence_count=len(selected),
        needs_live_verification=needs_live_verification,
    )
