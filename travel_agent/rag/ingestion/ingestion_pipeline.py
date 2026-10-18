"""Orchestrates the six ingestion steps: document_loader -> cleaner ->
semantic_chunker -> metadata_extractor (canonicalization happens inside it)
-> embedding_writer. `scripts/ingest_travel_guides.py` is the CLI wrapper.
"""

from __future__ import annotations

from typing import Any, List, Optional

from travel_agent.rag.config import load_rag_config
from travel_agent.rag.ingestion.cleaner import clean_notes
from travel_agent.rag.ingestion.document_loader import load_file
from travel_agent.rag.ingestion.embedding_writer import write_chunks
from travel_agent.rag.ingestion.metadata_extractor import extract_metadata
from travel_agent.rag.ingestion.semantic_chunker import chunk_note
from travel_agent.rag.schemas import IngestionReport, TravelGuideChunk
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.rag.ingestion.pipeline")


def ingest_file(path: str, llm: Optional[Any] = None) -> IngestionReport:
    report = IngestionReport(source_file=path)

    try:
        notes = load_file(path)
    except Exception as exc:  # noqa: BLE001 -- report the failure, don't crash the CLI
        report.errors.append(str(exc))
        return report
    report.notes_found = len(notes)

    cleaned = clean_notes(notes)
    report.notes_after_cleaning = len(cleaned)
    report.duplicates_skipped = sum(1 for c in cleaned if c.is_duplicate_of is not None)

    config = load_rag_config()
    all_chunks: List[TravelGuideChunk] = []
    for c in cleaned:
        if c.is_duplicate_of is not None:
            continue
        try:
            for text_chunk in chunk_note(c, config.chunking):
                all_chunks.append(extract_metadata(text_chunk, c, llm=llm))
        except Exception as exc:  # noqa: BLE001 -- one bad note shouldn't abort the whole file
            label = c.note.title or f"note#{c.note.note_index}"
            report.errors.append(f"{label}: {exc}")
            _logger.error("ingestion failed for %s: %s", label, exc)

    written, updated = write_chunks(all_chunks)
    report.chunks_written = written
    report.chunks_updated = updated
    return report
