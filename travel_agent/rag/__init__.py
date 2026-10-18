"""Travel RAG: Xiaohongshu guide ingestion + retrieval (see docs/round6_rag_memory_eval_design.md).

Phase 2 (current): `ingestion/` -- turns a user-curated guide file (docx/md/txt)
into `TravelGuideChunk` records in the `travel_guides` ChromaDB collection.
Phase 3 will add `retrievers/`, `query_rewriter.py`, `result_merger.py`,
`reranker.py`, `context_assembler.py` on top of this.
"""
