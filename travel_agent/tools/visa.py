"""Visa Worker tool: `search_visa_information`.

MOCK IMPLEMENTATION. Out of scope for the current real-data upgrade (no visa
API/key was provided) -- kept as-is so the pipeline still surfaces a visa
note. Replace the body with a call to a real visa-requirement API (e.g.
Sherpa, VisaHQ, or an official government data feed) while keeping the
function signature and return shape unchanged.
"""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.tools import tool

# A tiny mock visa-requirement matrix keyed by (passport_country, destination_country).
_MOCK_VISA_DB: Dict[str, Dict[str, Any]] = {
    ("中国", "日本"): {
        "visa_required": True,
        "visa_type": "旅游签证 (单次/多次)",
        "processing_days": 5,
        "notes": "可通过旅行社代办，或符合条件申请多次往返签证。",
    },
    ("中国", "泰国"): {
        "visa_required": False,
        "visa_type": "落地签/免签",
        "processing_days": 0,
        "notes": "中泰互免签证协议生效期间可免签入境。",
    },
    ("中国", "新加坡"): {
        "visa_required": False,
        "visa_type": "免签",
        "processing_days": 0,
        "notes": "30天内免签入境。",
    },
}

_DEFAULT_VISA = {
    "visa_required": True,
    "visa_type": "旅游签证",
    "processing_days": 7,
    "notes": "暂无该目的地的详细数据，建议出发前至少提前2周查询官方大使馆信息（mock 数据）。",
}


@tool
def search_visa_information(passport_country: str, destination: str) -> Dict[str, Any]:
    """查询指定护照国家前往目的地所需的签证信息 (mock 实现)。

    Args:
        passport_country: 护照签发国家，例如 "中国"。
        destination: 目的地国家或城市，例如 "日本" 或 "东京"。

    Returns:
        包含 visa_required / visa_type / processing_days / notes 以及 source 的字典。
    """
    dest_country = destination
    # crude city->country normalization for the mock data
    city_to_country = {"东京": "日本", "大阪": "日本", "曼谷": "泰国", "新加坡": "新加坡"}
    dest_country = city_to_country.get(destination, destination)

    info = _MOCK_VISA_DB.get((passport_country, dest_country), _DEFAULT_VISA)
    return {
        "passport_country": passport_country,
        "destination_country": dest_country,
        **info,
        "source": {
            "title": f"{dest_country} 签证要求 (mock)",
            "url": f"https://mock-visa-data.example.com/{dest_country}",
            "source_type": "mock",
        },
    }
