"""Schemas describing the user's travel requirement.

`TravelRequirement` is the structured output of the Requirement Agent. It is
progressively filled in across multiple conversation turns until every
required field is present, at which point the user is asked to confirm it
before the Research stage begins.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

Pace = str  # "特种兵" | "平衡" | "松弛"
Interest = str  # "购物" | "美食" | "人文" | "自然" | "摄影"

PACE_OPTIONS = ["特种兵", "平衡", "松弛"]
INTEREST_OPTIONS = ["购物", "美食", "人文", "自然", "摄影"]

# Fields that MUST be present before the requirement is considered complete
# enough to move to user confirmation. Other fields are "nice to have" and
# are auto-filled with sensible defaults so the MVP flow doesn't stall on
# every minor detail.
REQUIRED_FIELDS = [
    "destination",
    "trip_length_known",  # derived: start_date+end_date OR duration_days
    "num_travelers",
    "budget",
    "pace",
]

OPTIONAL_FIELDS = [
    "departure_city",
    "passport_country",
    "visa_status",
    "interests",
    "daily_attraction_count",
    "wake_up_time",
    "latest_return_time",
    "special_needs",
]


class TravelRequirement(BaseModel):
    """Structured travel requirement extracted from the conversation."""

    departure_city: Optional[str] = Field(default=None, description="出发城市")
    destination: Optional[str] = Field(default=None, description="目的地")

    start_date: Optional[str] = Field(default=None, description="出行开始日期 (YYYY-MM-DD 或模糊描述如 2026-10)")
    end_date: Optional[str] = Field(default=None, description="出行结束日期")
    duration_days: Optional[int] = Field(default=None, description="行程天数")

    num_travelers: Optional[int] = Field(default=None, description="出行人数")
    budget: Optional[float] = Field(default=None, description="预算总额")
    budget_currency: str = Field(default="CNY", description="预算币种")

    passport_country: Optional[str] = Field(default=None, description="护照国家")
    visa_status: Optional[str] = Field(default=None, description="签证状态，例如已持有/需要申请/免签")

    pace: Optional[str] = Field(default=None, description="旅行节奏：特种兵/平衡/松弛")
    interests: List[str] = Field(default_factory=list, description="兴趣偏好列表")
    requested_places: List[str] = Field(
        default_factory=list,
        description="本次用户明确要求覆盖的地点；研究与选点阶段必须逐项处理",
    )
    excluded_places: List[str] = Field(
        default_factory=list,
        description="本次用户明确不想去的地点；研究、选点与规划阶段均需排除",
    )

    daily_attraction_count: Optional[int] = Field(default=None, description="每日希望景点数量")
    wake_up_time: Optional[str] = Field(default=None, description="起床时间 HH:MM")
    latest_return_time: Optional[str] = Field(default=None, description="最晚返回酒店时间 HH:MM")

    special_needs: Optional[str] = Field(default=None, description="老人/儿童等特殊需求说明")

    confirmed: bool = Field(default=False, description="用户是否已确认该需求")

    # -- Stage-2: richer experience understanding + complex-destination handling --
    experience_preferences: List[str] = Field(
        default_factory=list,
        description="用户真正想体验的细分标签，例如 ['fashion','music','street_culture','local_life']，"
        "对应 TravelExperience.type taxonomy，比 interests 更细粒度",
    )
    destination_complexity: Optional[str] = Field(
        default=None, description="'simple' | 'high' -- 目的地是否需要区域拆分"
    )
    region_candidates: List[dict] = Field(
        default_factory=list, description="目的地复杂时的候选区域列表（RegionCandidate 序列化）"
    )
    region_preferences: List[str] = Field(
        default_factory=list, description="用户确认希望安排的区域名称列表，空表示不拆分"
    )
    region_split_confirmed: bool = Field(default=False, description="用户是否已就区域拆分做出决定")
    constraints: List[str] = Field(default_factory=list, description="显式约束，例如无障碍/不要早起/忌口等")

    def is_field_present(self, field: str) -> bool:
        if field == "trip_length_known":
            return bool(self.duration_days or (self.start_date and self.end_date))
        value = getattr(self, field, None)
        if isinstance(value, list):
            return len(value) > 0
        return value is not None

    def missing_required_fields(self) -> List[str]:
        return [f for f in REQUIRED_FIELDS if not self.is_field_present(f)]

    def missing_optional_fields(self) -> List[str]:
        return [f for f in OPTIONAL_FIELDS if not self.is_field_present(f)]

    def confirmed_field_names(self) -> List[str]:
        all_fields = REQUIRED_FIELDS + OPTIONAL_FIELDS
        return [f for f in all_fields if self.is_field_present(f)]

    def apply_defaults(self) -> None:
        """Fill non-critical optional fields with sane defaults.

        Called once the required fields are present, so the MVP flow does not
        force the user through many clarification rounds for minor details.
        """
        if not self.interests:
            self.interests = ["美食"]
        if self.pace is None:
            self.pace = "平衡"
        if self.daily_attraction_count is None:
            self.daily_attraction_count = {"特种兵": 5, "平衡": 3, "松弛": 2}.get(self.pace, 3)
        if self.wake_up_time is None:
            self.wake_up_time = "07:30" if self.pace == "特种兵" else "08:30"
        if self.latest_return_time is None:
            self.latest_return_time = "23:00" if self.pace == "特种兵" else "21:30"
        if self.departure_city is None:
            self.departure_city = "未指定"
        if self.passport_country is None:
            self.passport_country = "中国"
        if self.visa_status is None:
            self.visa_status = "待查询"
        if self.duration_days is None and self.start_date and self.end_date:
            # Best-effort; real date parsing happens in the requirement agent.
            self.duration_days = 5
        if self.end_date is None and self.start_date and self.duration_days:
            self.end_date = self.start_date  # placeholder, refined by agent


class RequirementExtractionResult(BaseModel):
    """Output of a single Requirement Agent turn."""

    requirement: TravelRequirement
    summary: str = Field(..., description="当前旅行需求总结 (中文)")
    confirmed_fields: List[str] = Field(default_factory=list, description="已确认信息字段名")
    missing_fields: List[str] = Field(default_factory=list, description="仍缺失的必需信息字段名")
    is_complete: bool = Field(default=False, description="必需信息是否已收集完整")
    clarification_question: Optional[str] = Field(
        default=None, description="向用户提出的澄清问题（若信息不完整）"
    )
