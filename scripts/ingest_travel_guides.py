"""CLI for the Xiaohongshu guide ingestion pipeline (Round-6 Phase 2).

Default: heuristic-only metadata extraction (offline, no LLM key needed --
keyword/regex tagging in `rag/ingestion/metadata_extractor.py`). Pass
`--with-llm` to additionally run the LLM enrichment pass for richer,
dynamically-generated `activity_topics`/`travel_styles` (needs a configured
`DEEPSEEK_API_KEY`/`KIMI_API`; expect it to be slower, one call per chunk).

Usage:
    python scripts/ingest_travel_guides.py "travel+agent+rag.docx"
    python scripts/ingest_travel_guides.py "travel+agent+rag.docx" --with-llm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to a non-UTF-8 codepage

from travel_agent.config.llm import get_llm
from travel_agent.rag.ingestion.ingestion_pipeline import ingest_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Guide file to ingest (.docx/.md/.txt)")
    parser.add_argument("--with-llm", action="store_true", help="Also run LLM metadata enrichment (slower)")
    args = parser.parse_args()

    llm = get_llm(role="research", tier="fast") if args.with_llm else None
    if args.with_llm and llm is None:
        print("警告：--with-llm 已指定，但未检测到可用的 LLM 配置，将回退到纯启发式抽取。")

    report = ingest_file(args.path, llm=llm)

    print(f"文件: {report.source_file}")
    print(f"  发现笔记: {report.notes_found}")
    print(f"  清洗后剩余: {report.notes_after_cleaning}")
    print(f"  跳过的重复笔记: {report.duplicates_skipped}")
    print(f"  新写入片段: {report.chunks_written}")
    print(f"  更新片段: {report.chunks_updated}")
    if report.errors:
        print(f"  错误 ({len(report.errors)}):")
        for err in report.errors:
            print(f"    - {err}")


if __name__ == "__main__":
    main()
