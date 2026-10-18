"""TravelExperience schema: the unit of Research output.

Stage-2 replaced the old `AttractionCandidate` / `RestaurantCandidate` split
with a single, richer `TravelExperience` shape. Research is no longer "find
attractions" -- it's "find experiences matching what the user actually wants
to do" (music/architecture/surf/local_life/... not just landmarks), and every
experience carries enough scheduling data (duration/cost/best_time) for the
Planner and enough provenance (source) for the Reviewer's fact-checking.

Stage-3 upgrades this same model into a full "Activity Card" (design doc
section XV) instead of introducing a parallel `ActivityCandidate` schema --
`TravelExperience` already flows through Research/Planner/Reviewer and many
tests, so the new fields are added with safe defaults rather than forcing a
migration. A candidate with none of the new fields populated (e.g. an older
cached research result) still validates and behaves exactly as before.
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from travel_agent.schemas.common import Source

ExperienceType = Literal[
    "landmark",
    "nature",
    "beach",
    "surf",
    "music",
    "shopping",
    "food",
    "nightlife",
    "culture",
    "architecture",
    "photography",
    "local_life",
    "workshop",
    "wellness",
]

EXPERIENCE_TYPES: List[str] = [
    "landmark", "nature", "beach", "surf", "music", "shopping", "food",
    "nightlife", "culture", "architecture", "photography", "local_life", "workshop",
    "wellness",
]

PopularityLevel = Literal["mainstream", "niche"]

# Chinese display label per `type` -- used by `to_activity_card_text()` and
# reused by `research_agent.py` for candidate summaries. Kept here (not
# duplicated) since `type` is this schema's own taxonomy; `category` is a
# separate, Google-Places-types-derived label (see research_agent.py's
# `_infer_category_label`) that's often too generic ("地标") to show as the
# headline category on an Activity Card.
TYPE_LABEL_CN = {
    "landmark": "地标景点", "culture": "人文/展览/演出", "nature": "自然风光", "beach": "海滩", "surf": "冲浪",
    "shopping": "购物/买手店", "food": "美食/咖啡", "music": "音乐/唱片店", "nightlife": "夜生活",
    "architecture": "建筑摄影", "photography": "摄影打卡", "local_life": "本地生活/市集", "workshop": "手作工作坊",
    "wellness": "瑜伽/疗愈",
}


class TravelExperience(BaseModel):
    """A single researched experience candidate (replaces Attraction/Restaurant).

    Doubles as the Activity Card presented to the user -- see
    `to_activity_card_text()` and the Stage-3 fields below.
    """

    id: str = Field(default="", description="稳定标识符；未显式提供时基于 name 自动生成，供 IntentContext 跨轮引用")
    name: str
    type: str = Field(..., description="体验类型，见 EXPERIENCE_TYPES")
    category: str = Field(default="", description="更细的子分类，例如 'vinyl shop'/'jazz bar'")
    location: str
    address: Optional[str] = Field(default=None, description="详细地址")
    region: Optional[str] = Field(default=None, description="所属区域（复杂目的地拆分时使用），例如 'Canggu'")
    rating: float = 0.0
    popularity: float = Field(default=0.0, description="0-100 热度分数")
    popularity_level: PopularityLevel = Field(default="mainstream", description="mainstream | niche")
    duration_minutes: int = Field(default=90, description="建议时长（分钟）")
    cost: float = Field(default=0.0, description="人均预计花费")
    currency: str = "CNY"
    best_time: Optional[str] = Field(default=None, description="建议游玩时段，例如 'evening'")
    opening_hours: Optional[str] = None
    advantages: List[str] = Field(default_factory=list)
    disadvantages: List[str] = Field(default_factory=list)
    source: Source

    # -- Stage-3 Activity Card fields (design doc section XV) --------------
    subcategories: List[str] = Field(default_factory=list, description="更细粒度的子类型标签，例如 ['瑜伽','疗愈']")
    short_description: str = Field(default="", description="一句话介绍")
    detailed_description: str = Field(default="", description="详细介绍")
    why_recommended: List[str] = Field(default_factory=list, description="为什么推荐给当前用户")
    highlights: List[str] = Field(default_factory=list, description="主要亮点")
    drawbacks: List[str] = Field(default_factory=list, description="可能缺点")
    target_travelers: List[str] = Field(default_factory=list, description="适合的旅行者画像，例如 ['情侣','家庭']")
    suitable_for_preferences: List[str] = Field(default_factory=list, description="适合的偏好标签")
    unsuitable_for: List[str] = Field(default_factory=list, description="不适合的场景/人群")
    reservation_required: Optional[bool] = Field(default=None, description="是否需要预约")
    travel_time_from_previous: Optional[int] = Field(default=None, description="距行程上一站的交通时长（分钟），由 Planner 填充")
    confidence: float = Field(default=0.6, description="该候选信息完整度/可信度评分 0-1")

    def is_food(self) -> bool:
        return self.type == "food"

    @model_validator(mode="after")
    def _ensure_id(self) -> "TravelExperience":
        if not self.id:
            digest = hashlib.md5(self.name.encode("utf-8")).hexdigest()[:8]
            slug = re.sub(r"[^0-9a-zA-Z一-龥]+", "-", self.name.strip().lower()).strip("-") or "activity"
            self.id = f"{slug}-{digest}"
        return self

    def to_activity_card_text(self) -> str:
        """Render the full Activity Card -- used by Research's candidate
        presentation and the Presentation/Review agent's diff output. Never
        just the bare name (design doc section XV's explicit requirement)."""
        lines = [
            self.name,
            f"类别：{TYPE_LABEL_CN.get(self.type, self.category or self.type)}",
            f"区域：{self.region or self.location}",
            f"建议时长：{self.duration_minutes} 分钟",
            "",
            "介绍：",
            self.detailed_description or self.short_description or "暂无详细介绍。",
        ]
        if self.why_recommended:
            lines += ["", "推荐理由：", "；".join(self.why_recommended)]
        if self.highlights:
            lines += ["", "亮点：", "、".join(self.highlights)]
        if self.drawbacks:
            lines += ["", "可能缺点：", "、".join(self.drawbacks)]
        lines += ["", f"价格：约 {self.cost:.0f} {self.currency}" if self.cost else "价格：暂无数据"]
        if self.reservation_required is not None:
            lines.append(f"是否需要预约：{'需要' if self.reservation_required else '无需预约'}")
        if self.best_time:
            lines.append(f"适合时间：{self.best_time}")
        return "\n".join(lines)
