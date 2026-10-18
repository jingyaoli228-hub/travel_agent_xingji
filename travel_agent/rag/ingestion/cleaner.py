"""Step 2: strip non-informative filler from a `RawNote` and flag exact
duplicates. Deliberately conservative -- this project's actual guide notes
are curated by the user already (not raw social-media spam), so the rules
here only remove things with zero information value (image/video
placeholders, Xiaohongshu sticker markers) and near-empty notes, rather than
trying to detect "exaggerated marketing tone" heuristically, which would risk
false-positive drops on legitimate short avoid-pitfall tips. Anything
subtler (dated info, unsupported claims) is `quality_score`'s job in
`metadata_extractor.py`, not a hard filter here.
"""

from __future__ import annotations

import hashlib
import re
from typing import List

from travel_agent.rag.schemas import CleanedNote, RawNote

_STICKER_MARKER = re.compile(r"\[[^\[\]]{1,10}R\]")  # e.g. "[笑哭R]", "[星R]" -- xhs custom-emoji placeholders
_MEDIA_PLACEHOLDER = re.compile(r"\[(图片|视频|链接)\]")
_MIN_CONTENT_CHARS = 15


def _strip_filler(text: str) -> str:
    text = _STICKER_MARKER.sub("", text)
    text = _MEDIA_PLACEHOLDER.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", "", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def clean_notes(notes: List[RawNote]) -> List[CleanedNote]:
    cleaned: List[CleanedNote] = []
    seen_hashes: dict[str, str] = {}  # content_hash -> first note's identifying string

    for note in notes:
        text = _strip_filler(note.raw_text)
        if len(text) < _MIN_CONTENT_CHARS and not note.title:
            continue  # near-empty and no title to justify keeping it as a stub

        digest = _content_hash(text)
        duplicate_of = seen_hashes.get(digest)
        if duplicate_of is None:
            seen_hashes[digest] = note.title or f"{note.source_file}#{note.note_index}"

        cleaned.append(CleanedNote(note=note, cleaned_text=text, content_hash=digest, is_duplicate_of=duplicate_of))

    return cleaned
