"""Deterministic P0/P1 validation; never relaxs an explicit constraint."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional

from travel_agent.schemas.constraints import ConstraintValidationReport, ConstraintViolation, TravelConstraintSet
from travel_agent.schemas.itinerary import Itinerary


def _minutes(value: str) -> Optional[int]:
    try:
        hour, minute = value.split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (AttributeError, TypeError, ValueError):
        return None


class ConstraintValidator:
    def validate(self, itinerary: Itinerary, constraints: TravelConstraintSet) -> ConstraintValidationReport:
        p0: list[ConstraintViolation] = []
        p1: list[ConstraintViolation] = []
        hard, common = constraints.hard, constraints.commonsense
        all_items = [item for day in itinerary.days for item in day.items]

        total = itinerary.total_cost()
        if hard.total_budget is not None and total > hard.total_budget:
            p0.append(ConstraintViolation(priority="P0", code="total_budget", message=f"计划费用 {total:.2f} 超过预算 {hard.total_budget:.2f}"))
        modes = " ".join((item.transport or "") for item in all_items).lower()
        if hard.forbid_flights and any(word in modes for word in ("flight", "plane", "飞机", "航班")):
            p0.append(ConstraintViolation(priority="P0", code="forbid_flights", message="行程包含用户禁止的航班"))
        if hard.forbid_self_driving and any(word in modes for word in ("self-drive", "self drive", "rental car", "自驾", "租车")):
            p0.append(ConstraintViolation(priority="P0", code="forbid_self_driving", message="行程包含用户禁止的自驾"))
        categories = {getattr(item, "primary_category", None) for item in all_items}
        activities = {item.activity for item in all_items}
        for required in hard.required_event_types:
            if required not in activities:
                p0.append(ConstraintViolation(priority="P0", code="required_event_types", message=f"缺少必选活动类型：{required}"))
        for required in hard.required_attraction_types:
            if required not in categories:
                p0.append(ConstraintViolation(priority="P0", code="required_attraction_types", message=f"缺少必选景点类型：{required}"))

        seen_attractions: Counter[str] = Counter()
        seen_restaurants: Counter[str] = Counter()
        city_sequence: list[str] = []
        for day in itinerary.days:
            if common.complete_information:
                if not getattr(day, "city", None):
                    p1.append(self._p1("complete_information", "缺少当日城市", day.day_number))
                if not getattr(day, "accommodation", None):
                    p1.append(self._p1("complete_information", "缺少当日住宿", day.day_number))
                if not day.items or any(_minutes(item.time) is None or item.duration_minutes <= 0 for item in day.items):
                    p1.append(self._p1("complete_information", "缺少有效活动时间", day.day_number))
                if not any(item.transport for item in day.items):
                    p1.append(self._p1("complete_information", "缺少交通方式或时间", day.day_number))
                if not any(item.activity in ("breakfast", "lunch", "dinner", "meal") for item in day.items):
                    p1.append(self._p1("complete_information", "缺少餐饮", day.day_number))
                if getattr(day, "daily_cost", None) is None and not day.items:
                    p1.append(self._p1("complete_information", "缺少费用", day.day_number))
            city = getattr(day, "city", None)
            if city:
                city_sequence.append(city)
            if common.sufficient_meal_gaps and common.meals_per_day == 3:
                meals = sorted((_minutes(i.time), i.activity) for i in day.items if i.activity in ("breakfast", "lunch", "dinner") and _minutes(i.time) is not None)
                for (left, _), (right, _) in zip(meals, meals[1:]):
                    if right - left < common.minimum_meal_gap_hours * 60:
                        p1.append(self._p1("sufficient_meal_gaps", "相邻正餐开始时间间隔少于 4 小时", day.day_number))
            for item in day.items:
                name = item.location.strip().casefold()
                if item.activity == "attraction":
                    seen_attractions[name] += 1
                if item.activity in ("breakfast", "lunch", "dinner", "meal"):
                    seen_restaurants[name] += 1
                item_city = getattr(item, "city", None)
                if common.within_current_city and city and item_city and item_city != city and not (getattr(day, "is_day_trip", False) or getattr(day, "is_cross_city", False)):
                    p1.append(self._p1("within_current_city", f"{item.location} 不在当天城市", day.day_number, item.location))
        if common.diverse_attractions:
            p1.extend(self._duplicates(seen_attractions, "diverse_attractions", "景点"))
        if common.diverse_restaurants:
            p1.extend(self._duplicates(seen_restaurants, "diverse_restaurants", "餐厅"))
        if common.reasonable_city_route and len(set(city_sequence)) < len(city_sequence):
            compressed = [city for index, city in enumerate(city_sequence) if index == 0 or city != city_sequence[index - 1]]
            if len(compressed) != len(set(compressed)):
                p1.append(self._p1("reasonable_city_route", "城市顺序存在明显折返"))
        conflicts = [violation.message for violation in p0]
        options = [f"放宽或调整：{violation.code}" for violation in p0]
        return ConstraintValidationReport(hard_violations=p0, commonsense_violations=p1, conflicts=conflicts, relaxation_options=options)

    @staticmethod
    def _p1(code: str, message: str, day: Optional[int] = None, item: Optional[str] = None) -> ConstraintViolation:
        return ConstraintViolation(priority="P1", code=code, message=message, day=day, item=item)

    def _duplicates(self, counts: Counter[str], code: str, label: str) -> Iterable[ConstraintViolation]:
        return [self._p1(code, f"{label}重复：{name}") for name, count in counts.items() if name and count > 1]
