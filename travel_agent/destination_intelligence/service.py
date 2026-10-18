"""`DestinationIntelligenceService`: two entry points sharing the same
known-destination lookup + LLM-prompt-building logic.

- `assess_region_split(destination)` -- whole-destination, trip-creation-time
  (moved here verbatim from `RequirementAgent.assess_destination_complexity`,
  a refactor not a rewrite: same known-destination table, same LLM prompt
  shape, same confirmation-message text, so existing callers/tests see
  identical output).
- `profile_region(destination, region_name, focus_hint=...)` -- new: an
  ad-hoc, single-region lookup for a region the trip's original split never
  covered (e.g. a mid-trip "swap Ubud for Nusa Penida" request naming a
  region nobody confirmed at trip-creation time). `focus_hint` (e.g.
  `["snorkeling", "paragliding"]`) is injected into the LLM prompt so the
  profile is need-aware, not generic.

The LLM client is passed in per-call (`llm=...`), never constructed or
cached here -- callers (RequirementAgent, and from Phase 5 onward
AgentRouter) own their own `get_llm(role=...)` call, same "no module
constructs its own client" rule as every agent. This also means this
service needs no entry in `tests/conftest.py::no_llm` -- there is no
module-level client for that fixture to zero out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from travel_agent.schemas.destination import DestinationComplexityAssessment, RegionCandidate

# Stage-2: known multi-region destinations, used as the offline fallback (no
# LLM key required). Keyed by any alias that might appear in a user's
# message. Moved here from requirement_agent.py, unchanged.
_KNOWN_COMPLEX_DESTINATIONS: Dict[str, List[Dict[str, Any]]] = {
    "巴厘岛": [
        {"name": "Ubud", "highlights": ["文化", "瑜伽", "梯田"], "typical_experience_types": ["culture", "nature", "workshop"]},
        {"name": "Canggu", "highlights": ["冲浪", "海滩", "夜生活"], "typical_experience_types": ["surf", "beach", "nightlife"]},
        {"name": "Seminyak", "highlights": ["精品店", "海滩俱乐部", "餐厅"], "typical_experience_types": ["shopping", "beach", "food"]},
        {"name": "Nusa Penida", "highlights": ["跳岛", "潜水", "悬崖景观"], "typical_experience_types": ["beach", "nature", "photography"]},
    ],
}
_KNOWN_COMPLEX_DESTINATIONS["巴厘"] = _KNOWN_COMPLEX_DESTINATIONS["巴厘岛"]
_KNOWN_COMPLEX_DESTINATIONS["bali"] = _KNOWN_COMPLEX_DESTINATIONS["巴厘岛"]


class DestinationIntelligenceService:
    def assess_region_split(
        self, destination: str, llm: Optional[Any] = None, system_prompt: str = ""
    ) -> DestinationComplexityAssessment:
        """Decide whether `destination` should be offered a region split."""
        destination = (destination or "").strip()
        if not destination:
            return DestinationComplexityAssessment(destination=destination, is_complex=False)

        regions_data = self._lookup_known_regions(destination)
        if regions_data is None and llm is not None:
            regions_data = self._assess_region_split_with_llm(destination, llm, system_prompt)
        if not regions_data:
            return DestinationComplexityAssessment(destination=destination, is_complex=False)

        regions = [RegionCandidate(**r) for r in regions_data]
        return DestinationComplexityAssessment(
            destination=destination,
            is_complex=True,
            regions=regions,
            confirmation_message=self._build_region_confirmation_message(destination, regions),
        )

    def profile_region(
        self,
        destination: str,
        region_name: str,
        focus_hint: Optional[List[str]] = None,
        llm: Optional[Any] = None,
        system_prompt: str = "",
    ) -> RegionCandidate:
        """Ad-hoc single-region profile -- used when a user names a region
        the original trip-creation split never covered."""
        destination = (destination or "").strip()
        region_name = (region_name or "").strip()

        known = self._lookup_known_region_candidate(destination, region_name)
        if known is not None:
            return known

        if llm is not None:
            profiled = self._profile_region_with_llm(destination, region_name, focus_hint, llm, system_prompt)
            if profiled is not None:
                return profiled

        return self._heuristic_region_candidate(region_name, focus_hint)

    # -- Shared lookup/prompt-building, moved from requirement_agent.py ----

    def _lookup_known_regions(self, destination: str) -> Optional[List[Dict[str, Any]]]:
        lower = destination.lower()
        for key, regions in _KNOWN_COMPLEX_DESTINATIONS.items():
            if key in destination or key in lower or destination in key:
                return regions
        return None

    def _assess_region_split_with_llm(self, destination: str, llm: Any, system_prompt: str) -> Optional[List[Dict[str, Any]]]:
        try:
            # method="function_calling": DeepSeek rejects the (langchain_openai
            # default for pydantic targets) response_format=json_schema mode
            # ("This response_format type is unavailable now", confirmed live)
            # -- tool-calling is the mode DeepSeek actually supports.
            structured_llm = llm.with_structured_output(DestinationComplexityAssessment, method="function_calling")
            prompt = (
                f"目的地「{destination}」是否是一个体验差异很大、通常需要按区域分开安排行程的复杂目的地"
                "（例如巴厘岛需要区分 Ubud/Canggu/Nusa Penida）？如果是，请给出 2-4 个候选区域及其"
                "亮点(highlights)和典型体验类型(typical_experience_types，取值应来自 landmark/nature/beach/"
                "surf/music/shopping/food/nightlife/culture/architecture/photography/local_life/workshop)。"
                "如果不是复杂目的地，返回 is_complex=false，regions 为空。"
            )
            messages = []
            if system_prompt:
                messages.append(("system", system_prompt))
            messages.append(("human", prompt))
            result = structured_llm.invoke(messages)
            if isinstance(result, DestinationComplexityAssessment) and result.is_complex and result.regions:
                return [r.model_dump() for r in result.regions]
        except Exception:
            pass
        return None

    def _build_region_confirmation_message(self, destination: str, regions: List[RegionCandidate]) -> str:
        lines = [f"{destination}不同区域体验差异较大，是否希望安排多个区域？", "", "候选区域："]
        for r in regions:
            lines.append(f"- {r.name}：{'、'.join(r.highlights)}")
        lines.extend(
            [
                "",
                "不同区域会涉及：",
                "- 船票",
                "- 交通时间",
                "- 换酒店",
                "- 时间成本",
                "",
                f"请告诉我希望安排哪些区域（例如“{regions[0].name}和{regions[-1].name}”），"
                "或回复“不用分区”按整体安排。",
            ]
        )
        return "\n".join(lines)

    # -- New: ad-hoc single-region profile ----------------------------------

    def _lookup_known_region_candidate(self, destination: str, region_name: str) -> Optional[RegionCandidate]:
        if not region_name:
            return None
        regions_data = self._lookup_known_regions(destination) or []
        lower = region_name.lower()
        for r in regions_data:
            name = r["name"]
            if name.lower() == lower or region_name in name or name in region_name:
                return RegionCandidate(**r)
        return None

    def _profile_region_with_llm(
        self, destination: str, region_name: str, focus_hint: Optional[List[str]], llm: Any, system_prompt: str
    ) -> Optional[RegionCandidate]:
        try:
            structured_llm = llm.with_structured_output(RegionCandidate, method="function_calling")
            focus_text = (
                f"用户特别想要：{('、'.join(focus_hint))}，请让 signature_experiences 优先体现这些。"
                if focus_hint
                else ""
            )
            prompt = (
                f"请研究「{destination}」里「{region_name}」这个区域/地点的旅行特色，返回："
                "identity（身份标签，例如 ['海岛','浮潜圣地']，自由文本）、"
                "signature_experiences（标志性体验，自由文本，不受固定分类限制，可以是雪橇伞/浮潜这类具体活动）、"
                "local_features（本地特色，自由文本）、highlights（简短亮点列表）、"
                "typical_experience_types（若能对应到 landmark/nature/beach/surf/music/shopping/food/"
                "nightlife/culture/architecture/photography/local_life/workshop 则填写，否则留空）。"
                f"name 字段固定填写「{region_name}」。" + focus_text
            )
            messages = []
            if system_prompt:
                messages.append(("system", system_prompt))
            messages.append(("human", prompt))
            result = structured_llm.invoke(messages)
            if isinstance(result, RegionCandidate):
                # The LLM's own `name` echo can drift (translation/normalization) --
                # downstream code (research_agent.run_expansion(region=...),
                # PlannerAgent's region_overrides) keys off the caller's exact
                # `region_name` string, so it must win over whatever the LLM wrote.
                result.name = region_name
                return result
        except Exception:
            pass
        return None

    def _heuristic_region_candidate(self, region_name: str, focus_hint: Optional[List[str]]) -> RegionCandidate:
        return RegionCandidate(
            name=region_name,
            signature_experiences=list(focus_hint or []),
            notes="未配置 LLM 或该区域暂无已知数据，使用基于用户活动关键词的占位 profile。",
        )
