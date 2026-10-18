"""Xiaohongshu guide ingestion pipeline.

    document_loader -> cleaner -> canonicalization -> semantic_chunker
        -> metadata_extractor -> embedding_writer

`ingestion_pipeline.ingest_file()` runs all six steps; `scripts/
ingest_travel_guides.py` is the CLI entry point.
"""
