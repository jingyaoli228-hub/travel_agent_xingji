"""Pattern / rule parser -- the fastest, cheapest signal in the fusion
pipeline. Not a "hand off to a human" fallback: per the design doc it does
high-precision operation detection, entity/quantity/time-range extraction,
scope (preserve/replace) extraction and explicit confirm/reject/side-query
detection, all via regex/keyword rules with zero network calls.

This module is also the canonical home for the confirm/deny/auto/removal
keyword tables that used to live inline in `graph/nodes.py` -- moved here so
there is one place that owns "what counts as a yes/no/auto-pick", reused by
both the Fast Path and the early confirmation nodes.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from travel_agent.intent.schemas import IntentContext, PatternResult
from travel_agent.schemas.experience import EXPERIENCE_TYPES
from travel_agent.skills.registry import get_skill_registry

# -- Reused across graph/nodes.py (requirement/selection confirmation) and
# the Fast Path here -- single source of truth. --------------------------
# Split into "strong" (unambiguous even inside a longer sentence) and "weak"
# (single characters like "对"/"不" that are only trustworthy as a whole
# tiny reply -- otherwise they false-positive on ordinary sentences that
# merely contain the character, e.g. "不太适合我"/"对比一下两个区域").
_STRONG_CONFIRM_WORDS = ["确认", "是的", "对的", "可以", "没问题", "ok", "yes", "好的", "按这个来", "就这样", "就这样吧"]
_WEAK_CONFIRM_TOKENS = ["对"]
_STRONG_DENY_WORDS = ["不对", "不是", "错了", "修改", "改一下", "取消", "no"]
_WEAK_DENY_TOKENS = ["不"]

# Exported as full lists for reuse by graph/nodes.py's narrow "did the user
# just answer yes/no to a direct confirmation prompt" checks, where the weak
# single-character tokens are an intentional, safe simplification.
CONFIRM_WORDS = _STRONG_CONFIRM_WORDS + _WEAK_CONFIRM_TOKENS
DENY_WORDS = _STRONG_DENY_WORDS + _WEAK_DENY_TOKENS
AUTO_WORDS = ["帮我推荐", "帮我选", "自动", "都可以", "你决定", "随便"]
REMOVAL_WORDS = ["去掉", "删除", "不要", "移除"]

_SHORT_REPLY_MAX_LEN = 15
_TINY_REPLY_MAX_LEN = 3

# Signals that the user considers the whole plan done -- used by the
# post-plan feedback loop to decide END vs. keep looping.
STOP_WORDS = ["就这样吧", "没有其他修改了", "不用改了", "结束吧", "不用再改", "可以了不用再改", "满意了"]

_ADD_VERBS = ["增加", "多找", "多加", "多来", "再加", "补充", "再来", "多安排", "多提供", "多准备"]
_REMOVE_VERBS = ["去掉", "删除", "不要", "移除", "别再加", "别加"]
_REPLACE_VERBS = ["换成", "替换", "换个", "换一个", "换掉", "换给", "改成"]
_MOVE_VERBS = ["挪到", "移到", "调整到", "换到", "移动到"]
_REPLAN_VERBS = ["重新排", "重新安排", "重新规划", "重排", "推倒重来"]
_COMPARE_VERBS = ["比较", "对比", "哪个更", "区别"]
_SELECT_VERBS = ["我选", "就选", "要这几个", "选前", "选这"]

_NEGATION_MARKERS = ["不是要", "不是", "没有要"]

# "不要动"/"不要变"/"不要改" ("don't move/change it") is a preserve phrase, not a
# removal -- masked out of the copy used for verb-family detection so bare
# "不要" (a _REMOVE_VERBS entry) doesn't false-positive inside it.
_PRESERVE_PHRASE_RE = re.compile(r"不要(动|变|改)")

_SIDE_QUERY_WORDS = ["天气", "下雨", "签证", "免签", "落地签", "怎么去", "打车", "地铁", "机场", "多久一班"]

# category-keyword -> TravelExperience.type(s). Deliberately allows
# multi-target keywords ("传统"/"寺庙" imply both landmark and culture).
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "瑜伽": ["wellness"], "冥想": ["wellness"], "疗愈": ["wellness"], "spa": ["wellness"], "静修": ["wellness"],
    "冲浪": ["surf"],
    "海滩": ["beach"], "沙滩": ["beach"],
    "夜生活": ["nightlife"], "酒吧": ["nightlife"], "livehouse": ["nightlife"], "夜店": ["nightlife"],
    "唱片店": ["music"], "黑胶": ["music"], "音乐现场": ["music"], "爵士": ["music"], "演出": ["music"],
    "市集": ["local_life"], "集市": ["local_life"], "社区活动": ["local_life"], "本地生活": ["local_life"],
    "当地人": ["local_life"], "本地": ["local_life"],
    "展览": ["culture"], "画廊": ["culture"], "博物馆": ["culture"],
    "咖啡": ["food"], "美食": ["food"], "餐厅": ["food"], "小吃": ["food"],
    "手作": ["workshop"], "工作坊": ["workshop"], "体验课程": ["workshop"],
    "购物": ["shopping"], "买手店": ["shopping"], "潮牌": ["shopping"], "商场": ["shopping"],
    "寺庙": ["landmark", "culture"], "神社": ["landmark", "culture"], "古迹": ["landmark", "culture"],
    "传统景点": ["landmark", "culture"], "传统": ["landmark", "culture"],
    "自然": ["nature"], "公园": ["nature"], "徒步": ["nature"],
    "摄影": ["photography"], "出片": ["photography"],
    "地标": ["landmark"], "景点": ["landmark"],
}

_TIME_PERIOD_MAP = {
    "上午": "MORNING", "早上": "MORNING", "早晨": "MORNING",
    "下午": "AFTERNOON", "午后": "AFTERNOON",
    "晚上": "EVENING", "夜里": "EVENING", "夜晚": "EVENING", "晚间": "EVENING",
}

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_PRESERVE_TRUE_HINTS = ["其他不变", "其他天不要动", "其他安排不要动", "只修改", "只改", "别的不要动", "不用管其他", "其他保持原样", "其他天不动"]
_PRESERVE_FALSE_HINTS = ["全部换掉", "全部重新", "整体重新", "都换掉", "全部推倒重来", "所有安排都换掉"]

_DEMONSTRATIVE_PRONOUNS = ["这个", "那个", "前面那个", "这些", "那些"]


def _extract_day_index(text: str) -> Optional[int]:
    m = re.search(r"第\s*(\d+|[一二三四五六七八九十])\s*天", text)
    if not m:
        return None
    token = m.group(1)
    return int(token) if token.isdigit() else _CN_NUM.get(token)


def _extract_time_period(text: str) -> Optional[str]:
    for kw, period in _TIME_PERIOD_MAP.items():
        if kw in text:
            return period
    return None


def _extract_quantity(text: str) -> Optional[int]:
    m = re.search(r"(\d+|[一二两三四五六七八九十])\s*[个节堂次门]", text)
    if not m:
        return None
    token = m.group(1)
    return int(token) if token.isdigit() else _CN_NUM.get(token)


def _extract_region(text: str, known_regions: List[str]) -> Optional[str]:
    for region in known_regions or []:
        if region and region in text:
            return region
    m = re.search(r"([一-龥A-Za-z]{2,8})(?:附近|区域|一带)", text)
    return m.group(1) if m else None


# -- Region replacement ("把第3天的Ubud换成努沙佩尼达") -----------------------
# Distinct from `_extract_region()` above, which only ever finds a SINGLE
# region and requires it be already known (from `context.current_regions`,
# i.e. the original trip-creation region split). A replacement's *target*
# region is often one the trip has never heard of before -- by definition,
# "swap X for Y" implies Y is new -- so `target` here is accepted even when
# it isn't in `known_regions`; only `source` benefits from that whitelist
# (and even then isn't required to be in it, since a user may reference an
# already-scheduled region by name that was never explicitly "confirmed").
_DAY_PHRASE_RE = re.compile(r"第?\s*(?:\d+|[一二两三四五六七八九十]+)\s*天")
_REGION_TOKEN = r"[A-Za-z一-鿿]{2,10}"
_REGION_REPLACEMENT_PATTERNS = [
    re.compile(rf"(?:把)?({_REGION_TOKEN})(?:换成|改成)({_REGION_TOKEN})"),
    re.compile(rf"替换.*?({_REGION_TOKEN})(?:的行程|的安排)给({_REGION_TOKEN})"),
    # These two are listed separately (rather than one pattern with an
    # optional "(?:的行程|的安排)?" infix) on purpose: an *optional* infix
    # creates two valid parses of the same string, and greedy backtracking
    # prefers the longer one -- e.g. "乌布的行程换给X" would capture source
    # region "乌布的行程" instead of "乌布", since "的行程" itself matches the
    # region-token character class and nothing forces the shorter parse.
    re.compile(rf"({_REGION_TOKEN})(?:的行程|的安排)换给({_REGION_TOKEN})"),
    re.compile(rf"({_REGION_TOKEN})换给({_REGION_TOKEN})"),
]
# Chars that can leak into a captured region token from adjacent grammar
# (day-count phrases, possessive/verb particles, sentence-final particles) --
# stripped from both ends of a match, never expected inside a real region
# name.
_REGION_FILLER_CHARS = "的把给了吧啊呢哦呀啦，。！？ 一二三四五六七八九十天"


def _clean_region_token(token: str) -> str:
    return token.strip(_REGION_FILLER_CHARS)


def _extract_region_replacement(text: str) -> Optional[Tuple[str, str]]:
    stripped = _DAY_PHRASE_RE.sub("", text)
    for pattern in _REGION_REPLACEMENT_PATTERNS:
        m = pattern.search(stripped)
        if not m:
            continue
        source = _clean_region_token(m.group(1))
        target = _clean_region_token(m.group(2))
        if len(source) < 2 or len(target) < 2 or source == target:
            continue
        return source, target
    return None


def _extract_categories_anywhere(text: str) -> List[str]:
    """Unlike `_categories_near_verbs`, scans the *whole* message rather than
    a window near a specific verb -- used for a region-replacement's activity
    ask (e.g. "我要在帕尼达岛浮潜和滑翔伞"), which typically isn't phrased with
    an ADD verb ("增加"/"多找") at all."""
    found: List[str] = []
    skill_synonyms = get_skill_registry().get_synonym_map()
    for keyword, types in CATEGORY_KEYWORDS.items():
        if keyword in text:
            for t in types:
                if t not in found:
                    found.append(t)
    for keyword, activity_type in skill_synonyms.items():
        if keyword in text and activity_type not in found:
            found.append(activity_type)
    return found


def _categories_near_verbs(text: str, verbs: List[str], window: int = 20) -> List[str]:
    found: List[str] = []
    # Skill-declared synonyms (travel_agent/skills/*/SKILL.md, e.g.
    # 浮潜/滑翔伞) extend this table without another code change here --
    # see travel_agent/skills/registry.py::SkillRegistry.get_synonym_map().
    skill_synonyms = get_skill_registry().get_synonym_map()
    for verb in verbs:
        idx = text.find(verb)
        if idx < 0:
            continue
        segment = text[idx: idx + len(verb) + window]
        for keyword, types in CATEGORY_KEYWORDS.items():
            if keyword in segment:
                for t in types:
                    if t not in found:
                        found.append(t)
        for keyword, activity_type in skill_synonyms.items():
            if keyword in segment and activity_type not in found:
                found.append(activity_type)
    return found


def canonicalize_categories(categories: List[str]) -> List[str]:
    """Map possibly-raw category labels onto the canonical `TravelExperience.type`
    vocabulary (`EXPERIENCE_TYPES`).

    Pattern-sourced entities are already canonical (`_categories_near_verbs`
    applies `CATEGORY_KEYWORDS` itself), but the Embedding/LLM signals can
    supply `entities.add_categories`/`remove_categories` too (see
    `fusion_resolver.fuse()`), and nothing guarantees those come back
    canonical -- an LLM might echo the raw keyword, an English synonym, or a
    display label instead. `agent_router._extend_selection()` filters
    `research.experiences` by `e.type in categories`, and experience types
    are always canonical, so a non-canonical entry there silently matches
    zero candidates. Already-canonical values pass through unchanged;
    unrecognized ones are dropped (falling back to an unfiltered search is
    safer than filtering down to nothing)."""
    skill_synonyms = get_skill_registry().get_synonym_map()
    canonical: List[str] = []
    for raw in categories:
        if raw in EXPERIENCE_TYPES:
            if raw not in canonical:
                canonical.append(raw)
            continue
        matched = False
        for keyword, types in CATEGORY_KEYWORDS.items():
            if keyword in raw or raw in keyword:
                for t in types:
                    if t not in canonical:
                        canonical.append(t)
                matched = True
                break
        if matched:
            continue
        # Skill-declared activity types (e.g. "snorkeling"/"paragliding")
        # aren't in EXPERIENCE_TYPES/CATEGORY_KEYWORDS -- without this tier
        # they'd be silently dropped here even though a SKILL.md exists for
        # them (see travel_agent/skills/*/SKILL.md).
        for keyword, activity_type in skill_synonyms.items():
            if keyword in raw or raw in keyword:
                if activity_type not in canonical:
                    canonical.append(activity_type)
                break
    return canonical


class PatternParser:
    """Rule-based first pass: fast, precise, zero-cost."""

    def parse(self, message: str, context: Optional[IntentContext] = None) -> PatternResult:
        text = (message or "").strip()
        lower = text.lower()
        known_regions = context.current_regions if context else []

        result = PatternResult(raw_message=text)
        if not text:
            return result

        # "不要动"/"不要变"/"不要改" ("don't move/change it") is a PRESERVE phrase,
        # not a removal -- bare substring matching on "不要" (a REMOVE_VERBS
        # entry) would otherwise misfire inside it. Verb/category detection
        # runs against this masked copy; day/time/quantity/preserve-hint/
        # confirm-deny extraction still use the original `text` above.
        verb_text = _PRESERVE_PHRASE_RE.sub("维持不变", text)

        # -- explicit confirm / reject -- gated by message length so a bare
        # "对"/"不" (or a "不是"/"不对" embedded in a longer sentence) doesn't
        # false-positive on ordinary text that happens to contain the
        # character (e.g. "这个不太适合我", "对比一下两个区域"). Confirm/reject
        # replies in this app are always short, standalone utterances.
        is_short_reply = len(text) <= _SHORT_REPLY_MAX_LEN
        is_tiny_reply = len(text) <= _TINY_REPLY_MAX_LEN
        strong_confirm = any(w in text or w in lower for w in _STRONG_CONFIRM_WORDS)
        weak_confirm = is_tiny_reply and any(w in text for w in _WEAK_CONFIRM_TOKENS)
        strong_deny = any(w in text for w in _STRONG_DENY_WORDS)
        weak_deny = is_tiny_reply and any(w in text for w in _WEAK_DENY_TOKENS)

        is_confirm = is_short_reply and (strong_confirm or weak_confirm) and not (strong_deny or weak_deny)
        is_reject = is_short_reply and (strong_deny or weak_deny) and not is_confirm

        # -- negation guard: "不是要删除浅草寺，只是..." must NOT become REMOVE --
        negated = any(marker in text for marker in _NEGATION_MARKERS)

        remove_cats = _categories_near_verbs(verb_text, _REMOVE_VERBS)
        add_cats = _categories_near_verbs(verb_text, _ADD_VERBS)
        has_remove_verb = any(v in verb_text for v in _REMOVE_VERBS)
        has_add_verb = any(v in verb_text for v in _ADD_VERBS)

        operation = None
        if negated and any(v in verb_text for v in _MOVE_VERBS):
            operation = "MOVE"
        elif negated and any(v in verb_text for v in _REPLAN_VERBS + ["不想安排在"]):
            operation = "REPLAN"
        elif any(v in verb_text for v in _MOVE_VERBS):
            operation = "MOVE"
        elif any(v in verb_text for v in _REPLAN_VERBS) or ("重新" in verb_text and "排" in verb_text):
            operation = "REPLAN"
        elif any(v in verb_text for v in _REPLACE_VERBS):
            operation = "REPLACE"
        elif any(v in verb_text for v in _COMPARE_VERBS):
            operation = "COMPARE"
        elif any(v in verb_text for v in _SELECT_VERBS):
            operation = "SELECT"
        elif has_remove_verb and not negated:
            operation = "REMOVE"
        elif has_add_verb:
            operation = "ADD"
        elif any(w in text for w in _SIDE_QUERY_WORDS):
            operation = "QUERY"
        elif is_confirm:
            operation = "CONFIRM"
        elif is_reject:
            operation = "REJECT"

        is_side_query = operation == "QUERY" and any(w in text for w in _SIDE_QUERY_WORDS)

        day_index = _extract_day_index(text)
        time_period = _extract_time_period(text)
        quantity = _extract_quantity(text)
        region = _extract_region(text, known_regions)

        region_replacement = _extract_region_replacement(text) if operation == "REPLACE" else None
        source_region: Optional[str] = None
        target_region: Optional[str] = None
        region_focus: List[str] = []
        if region_replacement:
            source_region, target_region = region_replacement
            region_focus = _extract_categories_anywhere(text)

        preserve_other_days: Optional[bool] = None
        if any(h in text for h in _PRESERVE_TRUE_HINTS):
            preserve_other_days = True
        elif any(h in text for h in _PRESERVE_FALSE_HINTS):
            preserve_other_days = False
        elif region_replacement is not None:
            # A region-swap request ("换成"/"替换...给") is inherently a
            # partial operation by definition -- unlike REPLAN_FULL_TRIP,
            # there's no reading of "replace X with Y" that also implies
            # "and also rebuild every other day". Default to preserving the
            # rest unless the user explicitly says otherwise (_PRESERVE_FALSE_HINTS
            # above already took priority).
            preserve_other_days = True

        preserve_other_time_periods = True if (day_index and time_period and preserve_other_days) else None

        referenced_ordinal = None
        m = re.search(r"第\s*([一二三四五六七八九十\d]+)\s*个", text)
        if m:
            token = m.group(1)
            referenced_ordinal = int(token) if token.isdigit() else _CN_NUM.get(token)

        # An ordinal reference ("第二个") is NOT ambiguous when the operation
        # is SELECT -- "选第二个和第四个" is precisely what SELECT_ACTIVITY means
        # (index into a known, currently-visible candidate list). It IS
        # ambiguous for REPLACE/MOVE/etc ("第三个不要了，换成...第二个") because
        # resolving "更小众的" still needs LLM-level judgment.
        has_demonstrative = any(p in text for p in _DEMONSTRATIVE_PRONOUNS) or (
            referenced_ordinal is not None and operation != "SELECT"
        )
        has_ambiguity = has_demonstrative and not (remove_cats or add_cats or day_index)

        # crude multi-intent heuristic: more than one distinct operation
        # family's verbs present at once (e.g. "删除...再找两个...把...换成...")
        op_families_present = sum(
            1
            for verbs in (_ADD_VERBS, _REMOVE_VERBS, _REPLACE_VERBS, _MOVE_VERBS, _REPLAN_VERBS)
            if any(v in text for v in verbs)
        )
        multi_intent = op_families_present >= 2

        # Base credit per signal. Side-query keywords and explicit select-verbs
        # ("我选"/"就选") are high-precision on their own (whole-phrase keyword
        # matches), so they get a bigger base than the generic +0.5 -- entity
        # richness (day/time/category/quantity) only adds on top. A named-
        # target reference with NO category match (e.g. "删除...浅草寺") stays
        # low on purpose: Pattern alone can't verify that name is a real,
        # currently-visible activity, so it should fail the Fast Path's
        # confidence gate and escalate to the Deep Path for verification.
        confidence = 0.0
        if operation:
            confidence += 0.5
        if is_side_query:
            confidence += 0.25
        if operation == "SELECT":
            confidence += 0.3
        if day_index is not None:
            confidence += 0.15
        if time_period is not None:
            confidence += 0.1
        if remove_cats or add_cats:
            confidence += 0.2
        if quantity is not None:
            confidence += 0.05
        if region_replacement:
            confidence += 0.2
        if is_confirm or is_reject:
            confidence = max(confidence, 0.9)
        if has_ambiguity:
            confidence *= 0.5
        confidence = min(confidence, 0.98)

        target = "DAY_PLAN" if (day_index and operation == "REPLAN") else ("ACTIVITY" if (remove_cats or add_cats or operation in ("ADD", "REMOVE", "REPLACE", "MOVE", "SELECT")) else None)
        if region_replacement:
            target = "REGION"

        return PatternResult(
            operation=operation,
            target=target,
            day_index=day_index,
            time_period=time_period,
            activity_categories=list(dict.fromkeys(remove_cats + add_cats)),
            remove_categories=remove_cats,
            add_categories=add_cats,
            region=region,
            source_region=source_region,
            target_region=target_region,
            region_focus=region_focus,
            quantity=quantity,
            is_confirm=is_confirm,
            is_reject=is_reject,
            is_negation=negated,
            is_side_query=is_side_query,
            preserve_other_days=preserve_other_days,
            preserve_other_time_periods=preserve_other_time_periods,
            mentioned_names=[],
            referenced_ordinal=referenced_ordinal,
            has_ambiguity=has_ambiguity,
            multi_intent=multi_intent,
            confidence=confidence,
            raw_message=text,
        )


def extract_mentioned_names(message: str, all_items: List[dict]) -> List[dict]:
    """Moved from `graph/nodes.py::_extract_mentioned_names` -- name-mention
    matching against a list of candidate dicts with a `name` key."""
    return [item for item in all_items if item.get("name") in message]
