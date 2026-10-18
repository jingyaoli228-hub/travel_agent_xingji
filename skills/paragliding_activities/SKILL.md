---
name: paragliding_activities
version: "1.0"
activity_type: paragliding
synonyms:
  - 滑翔伞
  - 跳伞
  - paragliding
  - paraglide
  - tandem flight
query_templates:
  - "{dest} paragliding 滑翔伞体验"
  - "{dest} 滑翔伞 攻略"
  - "{dest} tandem paragliding tour"
  - "{dest} 悬崖 滑翔伞 日落"
tool: google_places.search_places
place_type: tourist_attraction
display_label_cn: 滑翔伞
enabled: true
---

# Paragliding Activities

Same purpose as `snorkeling_activities/SKILL.md` -- teaches the system a new
activity type (`paragliding`) it has no hardcoded knowledge of, sourced
entirely from this declarative file. Adding a third, fourth, ... activity
type going forward means adding another `skills/<name>/SKILL.md`, not
another code change to `pattern_parser.py` or `research_agent.py`.
