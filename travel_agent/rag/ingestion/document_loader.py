"""Step 1: raw text extraction from a user-provided guide file (.docx/.md/.txt)
into `RawNote`s.

The user's actual guide file (`travel+agent+rag.docx`, confirmed live) already
follows a per-note header-block convention:

    标题：<title>
    目的地：<destination>
    内容类型：<guide_type>
    来源：<source>
    发布时间：<date>
    采集时间：<date>
    <free-text content, possibly many paragraphs, until the next 标题： line>

`_split_into_notes` recognizes this convention (order-independent, so a
reordered or partially-missing header block still splits correctly) and
extracts the header fields directly rather than asking an LLM to re-infer
them -- cheaper, deterministic, and more accurate than guessing. A file
without a single `标题：` line is treated as one whole-file note, left for
`semantic_chunker.py` to split on its own structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from travel_agent.rag.schemas import RawNote

_HEADER_PREFIXES = {
    "标题": "title",
    "目的地": "destination_hint",
    "内容类型": "guide_type_hint",
    "来源": "source_hint",
    "发布时间": "publish_time",
    "采集时间": "collected_time",
}


def _match_header(line: str) -> Optional[tuple[str, str]]:
    stripped = line.strip()
    for prefix, field in _HEADER_PREFIXES.items():
        for sep in ("：", ":"):
            marker = f"{prefix}{sep}"
            if stripped.startswith(marker):
                return field, stripped[len(marker) :].strip()
    return None


def _split_into_notes(lines: List[str], source_file: str) -> List[RawNote]:
    notes: List[RawNote] = []
    current_fields: dict = {}
    current_content: List[str] = []
    note_index = 0

    def _flush() -> None:
        nonlocal current_fields, current_content, note_index
        text = "\n".join(current_content).strip()
        if text or current_fields:
            notes.append(
                RawNote(
                    raw_text=text,
                    title=current_fields.get("title"),
                    destination_hint=current_fields.get("destination_hint"),
                    guide_type_hint=current_fields.get("guide_type_hint"),
                    source_hint=current_fields.get("source_hint"),
                    publish_time=current_fields.get("publish_time"),
                    collected_time=current_fields.get("collected_time"),
                    source_file=source_file,
                    note_index=note_index,
                )
            )
            note_index += 1
        current_fields = {}
        current_content = []

    for line in lines:
        match = _match_header(line)
        if match:
            field, value = match
            if field == "title" and (current_fields or current_content):
                _flush()
            current_fields[field] = value
            continue
        if line.strip():
            current_content.append(line.rstrip())
        elif current_content:
            current_content.append("")  # preserve paragraph breaks inside a note

    _flush()

    if not notes:
        return []
    # If nothing matched a single header line, the whole file was already
    # collapsed into one note by `_flush()` above -- that's the intended
    # generic fallback for header-less files.
    return notes


def load_docx(path: str) -> List[RawNote]:
    from docx import Document  # optional dep, only needed for .docx sources

    document = Document(path)
    lines: List[str] = []
    for para in document.paragraphs:
        lines.append(para.text)
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    return _split_into_notes(lines, source_file=path)


def load_text(path: str) -> List[RawNote]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return _split_into_notes(lines, source_file=path)


def load_file(path: str) -> List[RawNote]:
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return load_docx(path)
    if suffix in (".md", ".txt"):
        return load_text(path)
    raise ValueError(f"不支持的攻略文件类型: {suffix}（仅支持 .docx/.md/.txt）")
