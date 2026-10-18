"""Tool implementations exposed as LangChain tools.

Real integrations:
- `amap_places.py`    -- AMap POI search / details
- `amap_routes.py`    -- AMap route planning
- `weather.py`        -- AMap short-term city weather
- `search.py`         -- Agent Reach (local CLI): search_travel_guides

`visa.py` remains a mock (out of scope for this round -- no visa API/key
available); every other tool returns `{"success": False, "error": "..."}` on
failure instead of fabricated data.
"""
