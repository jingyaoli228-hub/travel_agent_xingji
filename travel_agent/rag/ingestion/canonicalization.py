"""Step 3: destination/region name normalization (requirement doc section 9
-- "佩尼达岛/佩妮达岛/帕尼达岛/Nusa Penida must canonicalize to the same
entity"). That exact case appears in the user's real guide file: note titles
use both "佩尼达岛" and "佩妮达岛" for the same island.

Small hand-maintained alias table, same style as
`destination_intelligence/service.py::_KNOWN_COMPLEX_DESTINATIONS` (offline,
no LLM required, LLM fallback can be added later for names not in the table
without changing this function's contract).

`canonical_place_name` intentionally mirrors `canonical_region` here rather
than attempting attraction-level NER (e.g. resolving "Campuhan Ridge Walk"
as its own place) -- that's a separate, harder entity-extraction problem
better left to a future LLM-based pass in `metadata_extractor.py`, not
something to fake with string matching.
"""

from __future__ import annotations

from typing import Dict, List, Optional, TypedDict

_REGION_TABLE: Dict[str, Dict[str, object]] = {
    "乌布": {"canonical": "乌布", "destination": "巴厘岛", "aliases": ["乌布", "Ubud"]},
    "苍古": {"canonical": "苍古", "destination": "巴厘岛", "aliases": ["苍古", "Canggu"]},
    "水明漾": {"canonical": "水明漾", "destination": "巴厘岛", "aliases": ["水明漾", "Seminyak"]},
    "库塔": {"canonical": "库塔", "destination": "巴厘岛", "aliases": ["库塔", "Kuta"]},
    "乌鲁瓦图": {"canonical": "乌鲁瓦图", "destination": "巴厘岛", "aliases": ["乌鲁瓦图", "Uluwatu"]},
    "罗威纳": {"canonical": "罗威纳", "destination": "巴厘岛", "aliases": ["罗威纳", "Lovina"]},
    "图兰本": {"canonical": "图兰本", "destination": "巴厘岛", "aliases": ["图兰本", "Tulamben"]},
    "佩尼达岛": {
        "canonical": "佩尼达岛",
        "destination": "巴厘岛",
        "aliases": ["佩尼达岛", "佩妮达岛", "帕尼达岛", "Nusa Penida"],
    },
}
# Extra alias keys pointing at the same region entry (so a lookup by any
# spelling variant finds it), built once at import time.
for _key, _entry in list(_REGION_TABLE.items()):
    for _alias in _entry["aliases"]:  # type: ignore[union-attr]
        _REGION_TABLE.setdefault(_alias, _entry)
        _REGION_TABLE.setdefault(_alias.lower(), _entry)

_DESTINATION_TABLE: Dict[str, Dict[str, object]] = {
    "巴厘岛": {"canonical": "巴厘岛", "country": "印度尼西亚", "aliases": ["巴厘岛", "巴厘", "Bali"]},
}
for _key, _entry in list(_DESTINATION_TABLE.items()):
    for _alias in _entry["aliases"]:  # type: ignore[union-attr]
        _DESTINATION_TABLE.setdefault(_alias, _entry)
        _DESTINATION_TABLE.setdefault(_alias.lower(), _entry)


class CanonicalizationResult(TypedDict):
    destination_country: Optional[str]
    canonical_destination: Optional[str]
    canonical_region: Optional[str]
    canonical_place_name: Optional[str]
    aliases: List[str]


def canonicalize(destination_hint: Optional[str]) -> CanonicalizationResult:
    hint = (destination_hint or "").strip()
    if not hint:
        return CanonicalizationResult(
            destination_country=None, canonical_destination=None, canonical_region=None,
            canonical_place_name=None, aliases=[],
        )

    region_entry = _REGION_TABLE.get(hint) or _REGION_TABLE.get(hint.lower())
    if region_entry is not None:
        aliases = list(region_entry["aliases"])  # type: ignore[arg-type]
        canonical_region = str(region_entry["canonical"])
        return CanonicalizationResult(
            destination_country="印度尼西亚",
            canonical_destination=str(region_entry["destination"]),
            canonical_region=canonical_region,
            canonical_place_name=canonical_region,
            aliases=aliases,
        )

    dest_entry = _DESTINATION_TABLE.get(hint) or _DESTINATION_TABLE.get(hint.lower())
    if dest_entry is not None:
        return CanonicalizationResult(
            destination_country=str(dest_entry["country"]),
            canonical_destination=str(dest_entry["canonical"]),
            canonical_region=None,
            canonical_place_name=None,
            aliases=list(dest_entry["aliases"]),  # type: ignore[arg-type]
        )

    # Unknown destination: keep the raw hint verbatim rather than dropping it.
    return CanonicalizationResult(
        destination_country=None, canonical_destination=hint, canonical_region=None,
        canonical_place_name=None, aliases=[hint],
    )
