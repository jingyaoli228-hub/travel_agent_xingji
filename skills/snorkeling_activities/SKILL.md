---
name: snorkeling_activities
version: "1.0"
activity_type: snorkeling
synonyms:
  - 浮潜
  - 潜水
  - 珊瑚礁
  - snorkel
  - snorkeling
  - diving
query_templates:
  - "{dest} snorkeling spot 浮潜"
  - "{dest} 浮潜 攻略"
  - "{dest} coral reef snorkeling tour"
  - "{dest} 出海浮潜 一日游"
tool: google_places.search_places
place_type: tourist_attraction
display_label_cn: 浮潜
enabled: true
---

# Snorkeling Activities

Teaches the Research Orchestrator's dynamic query generator (Phase 5) how to
find snorkeling/diving spots and tour operators for a destination, without
requiring `snorkeling` to be a pre-registered entry in
`schemas/experience.py::EXPERIENCE_TYPES` or `research_agent.py`'s static
`_TAG_QUERY_MAP`.

Also feeds `intent/pattern_parser.py`'s keyword matching: any of the
`synonyms` above appearing near an ADD/REPLACE verb in user feedback (e.g.
"我想浮潜") now resolves to `activity_type: snorkeling` instead of being
silently dropped.
