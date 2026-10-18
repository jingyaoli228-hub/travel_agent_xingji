"""Offline tests for the Round-6 Xiaohongshu guide ingestion pipeline
(`travel_agent/rag/ingestion/`). Only the tests touching ChromaDB itself
(`test_embedding_writer_*`, `test_ingest_file_end_to_end_*`) need `chromadb`
installed -- gated with `pytest.importorskip` so the rest of this file (the
heuristic loader/cleaner/canonicalization/chunker/metadata logic, which is
most of what's worth testing) still runs without it. Any Chroma access in
this file uses `HashEmbeddingFunction` (deterministic, no model download),
never the real ONNX embedding, so the suite stays network-free.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from travel_agent.rag.config import ChunkingConfig
from travel_agent.rag.ingestion.canonicalization import canonicalize
from travel_agent.rag.ingestion.cleaner import clean_notes
from travel_agent.rag.ingestion.document_loader import load_text
from travel_agent.rag.ingestion.metadata_extractor import extract_metadata
from travel_agent.rag.ingestion.semantic_chunker import chunk_note
from travel_agent.rag.schemas import CleanedNote, RawNote

_TWO_NOTE_FIXTURE = """\
标题：冲浪｜攀岩｜网球｜瑜伽｜徒步｜健身
目的地：乌布
内容类型：区域攻略
来源：小红书
发布时间：2026-7-13
采集时间：2026-7-22
这次终于自己来体验了一周～这次什么景点都没打卡[笑哭R]

🧘 瑜伽（Yoga Barn）⭐⭐⭐⭐
算是乌布最有名的瑜伽馆了，环境真的很舒服。

标题：水明漾citywalk一日游（推荐）
目的地：水明漾
内容类型：区域攻略
来源：小红书
发布时间：2025-9-10
采集时间：2026-7-22
早上9点出门，晚上8点结束，好吃好买好看。
"""


# ---------------------------------------------------------------------------
# document_loader
# ---------------------------------------------------------------------------

def test_document_loader_splits_notes_by_header_block(tmp_path: Path) -> None:
    path = tmp_path / "guide.txt"
    path.write_text(_TWO_NOTE_FIXTURE, encoding="utf-8")

    notes = load_text(str(path))

    assert len(notes) == 2
    assert notes[0].title == "冲浪｜攀岩｜网球｜瑜伽｜徒步｜健身"
    assert notes[0].destination_hint == "乌布"
    assert notes[0].publish_time == "2026-7-13"
    assert "瑜伽" in notes[0].raw_text
    assert notes[1].title == "水明漾citywalk一日游（推荐）"
    assert notes[1].destination_hint == "水明漾"


def test_document_loader_headerless_file_becomes_one_note(tmp_path: Path) -> None:
    path = tmp_path / "plain.txt"
    path.write_text("没有标题字段的普通文本\n第二行内容", encoding="utf-8")

    notes = load_text(str(path))

    assert len(notes) == 1
    assert notes[0].title is None
    assert "没有标题字段" in notes[0].raw_text


def test_document_loader_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "guide.pdf"
    path.write_text("x", encoding="utf-8")
    from travel_agent.rag.ingestion.document_loader import load_file

    with pytest.raises(ValueError):
        load_file(str(path))


# ---------------------------------------------------------------------------
# cleaner
# ---------------------------------------------------------------------------

def test_cleaner_strips_sticker_markers_and_media_placeholders() -> None:
    note = RawNote(raw_text="好吃好玩[笑哭R][图片]非常推荐", title="t", note_index=0, source_file="x")
    [cleaned] = clean_notes([note])
    assert "[笑哭R]" not in cleaned.cleaned_text
    assert "[图片]" not in cleaned.cleaned_text
    assert "好吃好玩" in cleaned.cleaned_text


def test_cleaner_flags_exact_duplicate_notes() -> None:
    note_a = RawNote(raw_text="完全相同的内容 一模一样", title="A", note_index=0, source_file="x")
    note_b = RawNote(raw_text="完全相同的内容 一模一样", title="B", note_index=1, source_file="x")
    cleaned = clean_notes([note_a, note_b])
    assert cleaned[0].is_duplicate_of is None
    assert cleaned[1].is_duplicate_of == "A"


def test_cleaner_drops_near_empty_untitled_note() -> None:
    note = RawNote(raw_text="短", title=None, note_index=0, source_file="x")
    assert clean_notes([note]) == []


def test_cleaner_keeps_short_note_with_title() -> None:
    note = RawNote(raw_text="短", title="有标题的短笔记", note_index=0, source_file="x")
    cleaned = clean_notes([note])
    assert len(cleaned) == 1


# ---------------------------------------------------------------------------
# canonicalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hint", ["佩尼达岛", "佩妮达岛", "帕尼达岛", "Nusa Penida"])
def test_canonicalization_normalizes_nusa_penida_aliases(hint: str) -> None:
    result = canonicalize(hint)
    assert result["canonical_region"] == "佩尼达岛"
    assert result["canonical_destination"] == "巴厘岛"
    assert result["destination_country"] == "印度尼西亚"
    assert "Nusa Penida" in result["aliases"]


def test_canonicalization_whole_island_destination() -> None:
    result = canonicalize("巴厘岛")
    assert result["canonical_destination"] == "巴厘岛"
    assert result["canonical_region"] is None
    assert result["destination_country"] == "印度尼西亚"


def test_canonicalization_unknown_destination_passthrough() -> None:
    result = canonicalize("某个从未见过的地方")
    assert result["canonical_destination"] == "某个从未见过的地方"
    assert result["canonical_region"] is None
    assert result["destination_country"] is None


def test_canonicalization_empty_hint() -> None:
    result = canonicalize(None)
    assert result["canonical_destination"] is None
    assert result["aliases"] == []


# ---------------------------------------------------------------------------
# semantic_chunker
# ---------------------------------------------------------------------------

def _cleaned_note(text: str, title: str = "t") -> CleanedNote:
    note = RawNote(raw_text=text, title=title, note_index=0, source_file="guide.txt")
    return CleanedNote(note=note, cleaned_text=text, content_hash="h")


def test_chunker_short_note_stays_one_chunk() -> None:
    cleaned = _cleaned_note("乌布适合体验瑜伽、疗愈和舞蹈课程，非常适合年轻旅行者。")
    chunks = chunk_note(cleaned, ChunkingConfig(target_tokens=400, max_tokens=650, overlap_tokens=80))
    assert len(chunks) == 1
    assert chunks[0].parent_document_id == "guide.txt#0"


def test_chunker_splits_long_multi_section_note_at_headings() -> None:
    sections = []
    for i in range(6):
        heading = f"🏄 活动{i}"
        body = "、".join([f"细节{j}" for j in range(80)])  # push each section well past target
        sections.append(f"{heading}\n{body}")
    long_text = "\n\n".join(sections)

    cleaned = _cleaned_note(long_text)
    config = ChunkingConfig(target_tokens=100, max_tokens=180, overlap_tokens=20)
    chunks = chunk_note(cleaned, config)

    # Each section is individually already well past max_tokens, so the
    # chunker cannot help producing over-budget chunks -- what matters is
    # that it still splits at section boundaries (one heading per chunk)
    # instead of merging everything into a single giant chunk.
    assert 1 < len(chunks) <= 6
    headings = [c.section_heading for c in chunks]
    assert len(set(headings)) == len(headings)  # each chunk keeps a distinct section heading
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunker_empty_note_produces_no_chunks() -> None:
    cleaned = _cleaned_note("")
    assert chunk_note(cleaned, ChunkingConfig()) == []


# ---------------------------------------------------------------------------
# metadata_extractor (heuristic path, no LLM)
# ---------------------------------------------------------------------------

def test_metadata_extractor_heuristic_topics_and_canonicalization() -> None:
    path = "guide.txt"
    note = RawNote(
        raw_text="瑜伽 徒步 攀岩",
        title="乌布运动攻略",
        destination_hint="乌布",
        guide_type_hint="区域攻略",
        publish_time="2026-7-13",
        collected_time="2026-7-22",
        note_index=0,
        source_file=path,
    )
    cleaned = CleanedNote(note=note, cleaned_text=note.raw_text, content_hash="h")
    [chunk] = chunk_note(cleaned, ChunkingConfig())
    guide_chunk = extract_metadata(chunk, cleaned)

    assert set(guide_chunk.activity_topics) >= {"瑜伽", "徒步", "攀岩"}
    assert guide_chunk.canonical_region == "乌布"
    assert guide_chunk.canonical_destination == "巴厘岛"
    assert guide_chunk.freshness_level == "fresh"  # 9 days between publish and collected
    assert guide_chunk.guide_type == "区域攻略"
    assert guide_chunk.id == "guide.txt#0::0"


def test_metadata_extractor_freshness_outdated_for_old_publish_date() -> None:
    note = RawNote(
        raw_text="旧内容", title="t", publish_time="2020-1-1", collected_time="2026-7-22",
        note_index=0, source_file="x",
    )
    cleaned = CleanedNote(note=note, cleaned_text=note.raw_text, content_hash="h")
    [chunk] = chunk_note(cleaned, ChunkingConfig())
    guide_chunk = extract_metadata(chunk, cleaned)
    assert guide_chunk.freshness_level == "outdated"


class _FakeStructuredLLM:
    def __init__(self, result: object) -> None:
        self._result = result

    def invoke(self, messages: object) -> object:
        return self._result


class _FakeLLM:
    """Minimal stand-in for a langchain chat model: only
    `with_structured_output(...)` is exercised by `metadata_extractor.py`."""

    def __init__(self, result: object) -> None:
        self._result = result

    def with_structured_output(self, schema: type, method: str = "function_calling") -> _FakeStructuredLLM:
        return _FakeStructuredLLM(schema(**self._result))


def test_metadata_extractor_llm_enrichment_merges_new_topics() -> None:
    note = RawNote(raw_text="瑜伽 相关内容", title="t", note_index=0, source_file="x")
    cleaned = CleanedNote(note=note, cleaned_text=note.raw_text, content_hash="h")
    [chunk] = chunk_note(cleaned, ChunkingConfig())

    fake_llm = _FakeLLM(
        {
            "activity_topics": ["瑜伽", "巴厘舞蹈"],  # "瑜伽" already found heuristically -- must not duplicate
            "travel_styles": ["当地生活"],
            "suitable_for": ["年轻旅行者"],
            "unsuitable_for": [],
        }
    )

    guide_chunk = extract_metadata(chunk, cleaned, llm=fake_llm)

    assert guide_chunk.activity_topics.count("瑜伽") == 1
    assert "巴厘舞蹈" in guide_chunk.activity_topics
    assert "当地生活" in guide_chunk.travel_styles
    assert "年轻旅行者" in guide_chunk.suitable_for


def test_metadata_extractor_llm_failure_falls_back_to_heuristic() -> None:
    class _RaisingLLM:
        def with_structured_output(self, schema: type, method: str = "function_calling") -> object:
            raise RuntimeError("simulated LLM outage")

    note = RawNote(raw_text="瑜伽 攀岩", title="t", note_index=0, source_file="x")
    cleaned = CleanedNote(note=note, cleaned_text=note.raw_text, content_hash="h")
    [chunk] = chunk_note(cleaned, ChunkingConfig())

    guide_chunk = extract_metadata(chunk, cleaned, llm=_RaisingLLM())
    assert set(guide_chunk.activity_topics) >= {"瑜伽", "攀岩"}


# ---------------------------------------------------------------------------
# embedding_writer / ingestion_pipeline (need chromadb; hash embedding, no network)
# ---------------------------------------------------------------------------

@pytest.fixture()
def _temp_chroma_collection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    chromadb = pytest.importorskip("chromadb")
    from travel_agent.rag.chroma_client import HashEmbeddingFunction

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collection = client.get_or_create_collection(name="travel_guides", embedding_function=HashEmbeddingFunction())
    monkeypatch.setattr("travel_agent.rag.ingestion.embedding_writer.get_collection", lambda name: collection)
    return collection


def test_embedding_writer_write_then_update_same_ids(_temp_chroma_collection) -> None:
    from travel_agent.rag.ingestion.embedding_writer import write_chunks
    from travel_agent.rag.schemas import TravelGuideChunk

    def _chunk(content: str) -> TravelGuideChunk:
        return TravelGuideChunk(
            id="doc#0::0", content=content, parent_document_id="doc#0", chunk_index=0,
            collected_time="2026-7-22",
        )

    written, updated = write_chunks([_chunk("第一次写入")])
    assert (written, updated) == (1, 0)

    written, updated = write_chunks([_chunk("重新入库后的更新内容")])
    assert (written, updated) == (0, 1)

    got = _temp_chroma_collection.get(ids=["doc#0::0"])
    assert got["documents"][0] == "重新入库后的更新内容"


def test_ingest_file_end_to_end_against_two_note_fixture(tmp_path: Path, _temp_chroma_collection) -> None:
    from travel_agent.rag.ingestion.ingestion_pipeline import ingest_file

    path = tmp_path / "guide.txt"
    path.write_text(_TWO_NOTE_FIXTURE, encoding="utf-8")

    report = ingest_file(str(path))

    assert report.notes_found == 2
    assert report.notes_after_cleaning == 2
    assert report.chunks_written >= 2
    assert not report.errors

    all_docs = _temp_chroma_collection.get()
    regions = {m.get("canonical_region") for m in all_docs["metadatas"]}
    assert "乌布" in regions
