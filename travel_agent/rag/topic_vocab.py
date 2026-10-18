"""Shared activity-topic/travel-style keyword vocabulary, used on both sides
of the RAG pipeline: `ingestion/metadata_extractor.py` tags chunks with it at
write time, `query_rewriter.py` uses the same table to extract
`topic_filters`/positive/negative preferences at query time, so a query like
"想要瑜伽" and a chunk tagged `activity_topics=["瑜伽"]` actually line up.

Requirement doc section 6 is explicit that `activity_topics` is *not* a
fixed global enum -- an LLM (ingestion's optional enrichment pass, or a
future query-side LLM rewrite) can always add topics beyond this table.
This is only the offline, no-LLM-required baseline vocabulary.
"""

from __future__ import annotations

TOPIC_KEYWORDS = {
    "冲浪": "冲浪", "攀岩": "攀岩", "徒步": "徒步", "网球": "网球", "健身": "健身",
    "瑜伽": "瑜伽", "spa": "spa", "SPA": "spa", "按摩": "spa", "潜水": "潜水",
    "浮潜": "浮潜", "日落": "看日落", "跳岛": "跳岛", "citywalk": "citywalk",
    "逛街": "逛街", "滑翔伞": "滑翔伞", "海滩": "海滩", "沙滩": "海滩",
    "梯田": "梯田观光", "咖啡": "咖啡文化", "寺庙": "寺庙参观", "夜生活": "夜生活",
    "酒吧": "夜生活", "美食": "美食", "餐厅": "美食", "摩托": "摩托出行",
    "跳舞": "舞蹈体验", "舞蹈": "舞蹈体验", "音乐": "音乐现场", "livehouse": "音乐现场",
}

STYLE_KEYWORDS = {
    "避坑": "避坑指南", "悠闲": "悠闲慢节奏", "精简": "高效精简", "小众": "小众体验",
    "人少": "小众体验", "包车": "包车出行", "自由行": "自由行",
}
