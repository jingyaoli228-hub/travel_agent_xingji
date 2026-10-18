---
name: travel_weather
version: "1.0"
activity_type: weather_advisory
synonyms:
  - 天气
  - 天气预报
  - weather
query_templates: []
tool: weather.get_weather
place_type: null
display_label_cn: 天气
enabled: true
---

# Travel Weather

Reference skill showing a `SKILL.md` that maps onto an *existing* tool
(`travel_agent/tools/weather.py::get_weather`, via the Phase-1 Tool Runtime
registry name `weather.get_weather`) rather than declaring a brand-new
activity type. `query_templates` is intentionally empty: `get_weather` takes
structured `destination`/`travel_date` parameters, not a free-text search
query, so this skill does not participate in Phase 5's query generator --
it's here only to document the tool-name mapping convention for skills that
wrap a non-search tool.
