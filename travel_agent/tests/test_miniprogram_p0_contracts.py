"""Static contracts for the native mini-program P0 experience.

WeChat WXML cannot be mounted in pytest, but these assertions prevent the
critical product wiring from silently disappearing while backend tests cover
the corresponding APIs and mutations.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_map_first_itinerary_surface_contract():
    wxml = _read("miniprogram/pages/itinerary/index.wxml")
    js = _read("miniprogram/pages/itinerary/index.js")
    sheet = _read("miniprogram/components/xj-bottom-sheet/index.js")

    assert "<map" in wxml
    assert 'include-points="{{includePoints}}"' in wxml
    assert 'bindmarkertap="onMarker"' in wxml
    assert 'bindpoitap="openAddPlace"' in wxml
    assert "<xj-day-tabs" in wxml
    assert "<xj-bottom-sheet" in wxml
    assert "<xj-chat-bar" in wxml
    assert "markers, polyline, includePoints: mapPoints" in js
    assert "const order = ['full', 'half', 'peek']" in sheet


def test_reorder_preview_shows_new_timetable_and_requires_explicit_apply():
    wxml = _read("miniprogram/pages/itinerary/index.wxml")
    js = _read("miniprogram/pages/itinerary/index.js")

    assert "{{reorderPreview.schedule}}" in wxml
    assert "{{reorderPreview.routeSummaries}}" in wxml
    assert "confirmReorderPreview" in wxml
    assert "cancelReorderPreview" in wxml
    assert "api.applyPatch" in js
    assert "wx.showModal" not in js[js.index("async endReorder()") : js.index("async handleWorkspaceError")]


def test_play_card_shows_after_destination_and_unknown_quality_is_not_zero():
    wxml = _read("miniprogram/pages/itinerary/index.wxml")
    badge = _read("miniprogram/components/xj-quality-badge/index.wxml")
    js = _read("miniprogram/pages/itinerary/index.js")

    assert "出来之后" in wxml
    assert "afterText" in js
    assert "state==='unknown'?'—':score" in badge
