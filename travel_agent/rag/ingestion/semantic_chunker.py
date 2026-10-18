"""Step 4: split a cleaned note into `TextChunk`s along its own structure
(blank-line paragraph blocks, short heading-like first lines such as
"🏄 冲浪（苍古）⭐⭐⭐⭐⭐" or "Day1 登岛"), not fixed character counts (requirement
doc section 8). A short single-topic note (e.g. the whole "水明漾citywalk一日游"
note) stays one chunk; a long multi-section note (e.g. the six-activity
"冲浪｜攀岩｜网球｜瑜伽｜徒步｜健身" note, or the two-day Nusa Penida itinerary)
splits at its own section/day boundaries once it crosses `max_tokens`.

Token counting has no tokenizer dependency (none of `tiktoken`/`transformers`
is installed, and this codebase's existing heuristic modules -- e.g.
`evaluation/judge.py::_tokenize` -- already favor cheap regex/heuristics over
new NLP deps): token count is approximated as `len(text) / 1.5`, which is in
the right ballpark for Chinese-heavy text where most tokenizers spend
roughly one token per 1-2 characters. This is an estimate for chunk-sizing
purposes only, not used for any billing/quota calculation.
"""

from __future__ import annotations

import re
from typing import List

from travel_agent.rag.config import ChunkingConfig
from travel_agent.rag.schemas import CleanedNote, TextChunk

_HEADING_MAX_CHARS = 24
_HEADING_HINT = re.compile(r"^(Day\s*\d|D\d|[🏄🧗🥾🎾🏋️🧘🌊🏖️📅💡📍✨💕⭐️🌟])", re.UNICODE)


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 1.5))


def _split_blocks(text: str) -> List[str]:
    blocks = re.split(r"\n\s*\n", text)
    return [b.strip() for b in blocks if b.strip()]


def _block_heading(block: str) -> str | None:
    first_line = block.splitlines()[0].strip()
    if len(first_line) <= _HEADING_MAX_CHARS and (_HEADING_HINT.match(first_line) or len(first_line) <= 12):
        return first_line
    return None


def _overlap_tail(text: str, overlap_tokens: int) -> str:
    overlap_chars = max(0, round(overlap_tokens * 1.5))
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    return text[-overlap_chars:]


def chunk_note(cleaned: CleanedNote, config: ChunkingConfig) -> List[TextChunk]:
    parent_document_id = f"{cleaned.note.source_file}#{cleaned.note.note_index}"
    blocks = _split_blocks(cleaned.cleaned_text)
    if not blocks:
        return []

    chunks: List[TextChunk] = []
    current_blocks: List[str] = []
    current_tokens = 0
    current_heading: str | None = None
    carry_over = ""

    def _flush() -> None:
        nonlocal current_blocks, current_tokens, current_heading, carry_over
        if not current_blocks:
            return
        text = (carry_over + "\n\n" + "\n\n".join(current_blocks)).strip() if carry_over else "\n\n".join(current_blocks)
        chunks.append(
            TextChunk(
                parent_document_id=parent_document_id,
                chunk_index=len(chunks),
                text=text,
                section_heading=current_heading or cleaned.note.title,
                estimated_tokens=_estimate_tokens(text),
            )
        )
        carry_over = _overlap_tail("\n\n".join(current_blocks), config.overlap_tokens)
        current_blocks = []
        current_tokens = 0
        current_heading = None

    for block in blocks:
        block_tokens = _estimate_tokens(block)
        heading = _block_heading(block)

        would_exceed_max = current_tokens + block_tokens > config.max_tokens
        at_natural_boundary = current_tokens >= config.target_tokens and heading is not None

        if current_blocks and (would_exceed_max or at_natural_boundary):
            _flush()

        if current_heading is None and heading is not None:
            current_heading = heading
        current_blocks.append(block)
        current_tokens += block_tokens

    _flush()
    return chunks
