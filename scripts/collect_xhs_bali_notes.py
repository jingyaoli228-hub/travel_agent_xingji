"""Bulk-collect Xiaohongshu (小红书) notes about 巴厘岛 for RAG ingestion.

Drives the user's own opencli-backed, already-logged-in Xiaohongshu session --
the same "Agent Reach" style mechanism as `travel_agent/tools/xhs_search.py`
(`opencli xiaohongshu search`), plus `opencli xiaohongshu note <url>` for the
full note body -- across a set of Bali-themed search queries. Candidates are
deduped, filtered to recent + no obvious ad/marketing copy, and ranked by
likes ("更火"). Kept notes are written out using the exact
`标题：/目的地：/内容类型：/来源：/发布时间：/采集时间：` header-block convention that
`travel_agent/rag/ingestion/document_loader.py` expects, so the output file
can be fed straight into `scripts/ingest_travel_guides.py`.

This is a long-running job -- each `opencli` call drives a real browser tab
(roughly 10-20s). Progress is checkpointed to a JSONL cache file after every
kept note, so an interrupted run can be re-launched with the same `--cache`
path and it will skip notes already collected instead of re-fetching them.

Usage:
    python scripts/collect_xhs_bali_notes.py --target 300
    python scripts/collect_xhs_bali_notes.py --target 300   # re-run to resume after an interruption
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to a non-UTF-8 codepage

from travel_agent.tools.xhs_search import XiaohongshuSearcher

_TODAY = datetime.now().strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# Query plan: bucket -> (内容类型 label written into each note's header block,
# search queries feeding that bucket). Buckets intentionally cover distinct
# facets of a Bali trip so 300 unique, non-redundant notes are reachable
# without exhausting any single query's result pool.
# ---------------------------------------------------------------------------
QUERY_BUCKETS: Dict[str, Dict[str, object]] = {
    "region": {
        "guide_type": "区域攻略",
        "queries": [
            "巴厘岛 攻略", "巴厘岛 7天", "巴厘岛 行程", "巴厘岛 环岛",
            "巴厘岛 乌布", "巴厘岛 库塔", "巴厘岛 水明漾", "巴厘岛 苍古",
            "巴厘岛 乌鲁瓦图", "巴厘岛 蓝梦岛", "巴厘岛 佩尼达岛", "巴厘岛 情人崖",
            "巴厘岛 努萨杜瓦", "巴厘岛 金巴兰",
        ],
    },
    "food": {
        "guide_type": "美食攻略",
        "queries": ["巴厘岛 美食", "巴厘岛 咖啡", "巴厘岛 网红餐厅", "巴厘岛 素食"],
    },
    "stay": {
        "guide_type": "住宿攻略",
        "queries": ["巴厘岛 住宿", "巴厘岛 民宿", "巴厘岛 度假村", "巴厘岛 悬崖酒店"],
    },
    "experience": {
        "guide_type": "体验攻略",
        "queries": [
            "巴厘岛 冲浪", "巴厘岛 潜水", "巴厘岛 浮潜", "巴厘岛 瑜伽",
            "巴厘岛 spa", "巴厘岛 火山徒步", "巴厘岛 摩托车", "巴厘岛 梯田",
        ],
    },
    "budget": {
        "guide_type": "省钱攻略",
        "queries": ["巴厘岛 穷游", "巴厘岛 花费", "巴厘岛 避坑", "巴厘岛 落地签", "巴厘岛 签证"],
    },
    "honeymoon": {
        "guide_type": "蜜月攻略",
        "queries": ["巴厘岛 蜜月", "巴厘岛 婚纱照", "巴厘岛 求婚"],
    },
    "family": {
        "guide_type": "亲子攻略",
        "queries": ["巴厘岛 亲子", "巴厘岛 带娃"],
    },
    "lifestyle": {
        "guide_type": "生活方式攻略",
        "queries": ["巴厘岛 数字游民", "巴厘岛 长居", "巴厘岛 体校"],
    },
}

# Sub-region names `canonicalization.py` already recognizes -- if a note's
# title/content names one specifically, use it as 目的地 (matches the existing
# corpus's convention, e.g. an Ubud-only note is filed under 目的地：乌布, not
# the generic 巴厘岛). Anything else (蓝梦岛/努萨杜瓦/... aren't in that table)
# falls back to the destination-level 巴厘岛.
_REGION_KEYWORDS: Dict[str, str] = {
    "乌布": "乌布", "Ubud": "乌布",
    "苍古": "苍古", "Canggu": "苍古",
    "水明漾": "水明漾", "Seminyak": "水明漾",
    "库塔": "库塔", "Kuta": "库塔",
    "乌鲁瓦图": "乌鲁瓦图", "Uluwatu": "乌鲁瓦图",
    "罗威纳": "罗威纳", "Lovina": "罗威纳",
    "图兰本": "图兰本", "Tulamben": "图兰本",
    "佩尼达岛": "佩尼达岛", "佩妮达岛": "佩尼达岛", "帕尼达岛": "佩尼达岛", "Nusa Penida": "佩尼达岛",
}

# Heuristic ad/marketing-copy filter. Deliberately narrow -- only patterns
# that are near-unambiguous commercial solicitation, so genuine short
# avoid-pitfall notes aren't false-positived out (same conservative spirit as
# `rag/ingestion/cleaner.py`'s docstring).
_AD_PATTERNS = [
    re.compile(p)
    for p in (
        r"私信.{0,4}(领取|获取|咨询)",
        r"扫码.{0,4}(领取|进群|咨询)",
        r"加[VvＶ微][信:：]",
        r"[Vv][:：Xx]\s*[A-Za-z0-9_]{4,}",
        r"客服.{0,4}(咨询|下单)",
        r"限时(优惠|折扣|秒杀)",
        r"券后价|拼团价|全网最低",
        r"招商加盟|代运营",
        r"点击.{0,4}(左下角|下方|链接)",
        r"业务合作|商务合作请|接广告|本文为推广",
    )
]
_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
_NOTE_ID_PATTERN = re.compile(r"/(?:explore|search_result)/([0-9a-fA-F]{20,26})")

_MIN_CONTENT_CHARS = 60
_NOTE_CMD_TEMPLATE = 'opencli xiaohongshu note "{url}" -f json'
_NOTE_TIMEOUT_SECONDS = 45


def _parse_count(raw: str) -> int:
    raw = (raw or "").strip().replace(",", "").replace("+", "")
    if not raw:
        return 0
    try:
        if raw.endswith("万"):
            return int(float(raw[:-1]) * 10000)
        if raw[-1] in "kK":
            return int(float(raw[:-1]) * 1000)
        return int(float(raw))
    except ValueError:
        return 0


def _parse_date(raw: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime((raw or "").strip(), fmt)
        except ValueError:
            continue
    return None


def _extract_note_id(url: str) -> Optional[str]:
    match = _NOTE_ID_PATTERN.search(url or "")
    return match.group(1) if match else None


def _is_ad(title: str, content: str) -> bool:
    text = f"{title}\n{content}"
    if _PHONE_PATTERN.search(text):
        return True
    return any(pattern.search(text) for pattern in _AD_PATTERNS)


def _detect_destination(title: str, content: str) -> str:
    text = f"{title} {content}"
    for keyword, canonical in _REGION_KEYWORDS.items():
        if keyword in text:
            return canonical
    return "巴厘岛"


@dataclass
class Candidate:
    note_id: str
    url: str
    title: str
    author: str
    likes: int
    published_at: Optional[str]
    guide_type: str


def collect_candidates(
    searcher: XiaohongshuSearcher, search_limit: int, max_age_days: int, sleep_seconds: float
) -> List[Candidate]:
    """Run every bucket's queries, dedup by note id, drop stale/ad-flagged
    hits, return candidates sorted by likes descending (hottest first)."""
    seen: Dict[str, Candidate] = {}
    cutoff = datetime.now() - timedelta(days=max_age_days)

    for bucket in QUERY_BUCKETS.values():
        guide_type = str(bucket["guide_type"])
        for query in bucket["queries"]:  # type: ignore[union-attr]
            print(f"[search] {query!r} ...", flush=True)
            results = searcher.search(query, limit=search_limit)
            for item in results:
                if item.get("success") is False:
                    print(f"  ! {item.get('error')}")
                    continue
                url = item.get("url") or ""
                note_id = _extract_note_id(url)
                if not note_id or note_id in seen:
                    continue
                title = item.get("title") or ""
                if _is_ad(title, ""):
                    continue
                published = _parse_date(item.get("published_at") or "")
                if published is not None and published < cutoff:
                    continue
                seen[note_id] = Candidate(
                    note_id=note_id,
                    url=url,
                    title=title,
                    author=item.get("author") or "",
                    likes=_parse_count(item.get("likes") or ""),
                    published_at=item.get("published_at"),
                    guide_type=guide_type,
                )
            time.sleep(sleep_seconds)

    return sorted(seen.values(), key=lambda c: c.likes, reverse=True)


def fetch_note_detail(url: str) -> Optional[Dict[str, str]]:
    """`opencli xiaohongshu note <url> -f json` -> {field: value} dict, or
    None on any failure. `url` is opencli's own JSON output, not external
    input, but is still checked for shell-breaking characters before being
    interpolated into the (necessarily shell=True, see xhs_search.py's
    docstring for the Windows .cmd-shim reason) command string."""
    if not url.startswith("https://www.xiaohongshu.com/") or '"' in url or "`" in url:
        return None
    command = _NOTE_CMD_TEMPLATE.format(url=url)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_NOTE_TIMEOUT_SECONDS,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout)
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    return {row.get("field"): row.get("value") for row in rows if isinstance(row, dict)}


def load_cache(cache_path: Path) -> Dict[str, dict]:
    cache: Dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            cache[record["note_id"]] = record
    return cache


def append_cache(cache_path: Path, record: dict) -> None:
    with cache_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def format_note_block(record: dict) -> str:
    return (
        f"标题：{record['title']}\n"
        f"目的地：{record['destination']}\n"
        f"内容类型：{record['guide_type']}\n"
        f"来源：小红书\n"
        f"发布时间：{record.get('published_at') or ''}\n"
        f"采集时间：{record['collected_time']}\n"
        f"{record['content']}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=int, default=300, help="目标笔记数量 (default: 300)")
    parser.add_argument("--output", default="bali_xhs_notes_batch2.md", help="输出文件路径 (.md)")
    parser.add_argument("--cache", default="scripts/.xhs_bali_cache.jsonl", help="断点续爬缓存文件路径")
    parser.add_argument("--search-limit", type=int, default=20, help="每个搜索关键词拉取的结果数上限")
    parser.add_argument("--max-age-days", type=int, default=730, help="只保留最近 N 天内发布的笔记 (更新)")
    parser.add_argument("--min-likes", type=int, default=0, help="点赞数低于此值的候选直接跳过")
    parser.add_argument("--sleep", type=float, default=1.5, help="每次 opencli 调用之间的等待秒数")
    args = parser.parse_args()

    cache_path = Path(args.cache)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)
    kept: List[dict] = list(cache.values())
    print(f"[cache] 已有 {len(kept)} 条缓存笔记 ({cache_path})")

    if len(kept) < args.target:
        searcher = XiaohongshuSearcher()
        candidates = collect_candidates(searcher, args.search_limit, args.max_age_days, args.sleep)
        print(f"[search] 去重、过滤广告/过期后候选 {len(candidates)} 条")

        for cand in candidates:
            if len(kept) >= args.target:
                break
            if cand.note_id in cache:
                continue
            if cand.likes < args.min_likes:
                continue

            print(f"[note] ({len(kept) + 1}/{args.target}) 抓取 {cand.title!r} ...", flush=True)
            fields = fetch_note_detail(cand.url)
            time.sleep(args.sleep)
            if not fields:
                print("  ! 抓取失败，跳过")
                continue

            content = (fields.get("content") or "").strip()
            title = fields.get("title") or cand.title
            if len(content) < _MIN_CONTENT_CHARS:
                print("  ! 正文过短，跳过")
                continue
            if _is_ad(title, content):
                print("  ! 命中广告/营销关键词，跳过")
                continue

            record = {
                "note_id": cand.note_id,
                "title": title,
                "destination": _detect_destination(title, content),
                "guide_type": cand.guide_type,
                "published_at": cand.published_at,
                "collected_time": _TODAY,
                "likes": _parse_count(fields.get("likes") or "") or cand.likes,
                "content": content,
                "url": cand.url,
                "author": fields.get("author") or cand.author,
            }
            append_cache(cache_path, record)
            cache[cand.note_id] = record
            kept.append(record)

    kept.sort(key=lambda r: r.get("likes", 0), reverse=True)
    kept = kept[: args.target]

    blocks = [format_note_block(record) for record in kept]
    Path(args.output).write_text("\n".join(blocks), encoding="utf-8")
    print(f"[done] 共写入 {len(kept)} 条笔记 -> {args.output}")
    print("下一步可运行: python scripts/ingest_travel_guides.py " + args.output)


if __name__ == "__main__":
    main()
