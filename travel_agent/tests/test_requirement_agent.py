"""Tests for the offline heuristic path of the Requirement Agent.

These force the LLM off (`no_llm` fixture, see `conftest.py`) so they
exercise the regex/keyword fallback extractor that also powers `demo.py`
without ever calling Kimi -- keeping this test fast, free and deterministic.
"""

from travel_agent.agents.requirement_agent import RequirementAgent
from travel_agent.schemas.travel_requirement import TravelRequirement


def test_demo_sentence_is_extracted_and_complete(no_llm):
    agent = RequirementAgent()
    result = agent.run("我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累")

    req = result.requirement
    assert req.destination == "东京"
    assert req.duration_days == 5
    assert req.num_travelers == 2
    assert req.budget == 20000
    assert "购物" in req.interests
    assert "美食" in req.interests
    assert req.pace == "松弛"
    assert result.is_complete is True
    assert result.missing_fields == []


def test_incomplete_requirement_asks_clarification(no_llm):
    agent = RequirementAgent()
    result = agent.run("我想去东京玩")
    assert result.is_complete is False
    assert result.clarification_question is not None
    assert len(result.missing_fields) > 0


def test_multi_turn_merge_preserves_previous_fields(no_llm):
    agent = RequirementAgent()
    first = agent.run("我想10月去东京玩")
    second = agent.run("两个人，预算2万，节奏松弛一点", previous=first.requirement)
    assert second.requirement.destination == "东京"
    assert second.requirement.num_travelers == 2
    assert second.requirement.budget == 20000


def test_experience_preferences_extracted_from_music_phrasing(no_llm):
    """Test1: "我喜欢东京的潮流文化" / 黑胶 should surface fine-grained tags,
    not just the coarse `interests` category."""
    agent = RequirementAgent()
    result = agent.run("我想10月去东京5天，两个人，预算2万元，我喜欢黑胶和livehouse，不想太累")
    assert "music" in result.requirement.experience_preferences


def test_assess_destination_complexity_bali_returns_known_regions(no_llm):
    """Test2: 巴厘岛 should be recognized as a complex, multi-region destination."""
    agent = RequirementAgent()
    req = TravelRequirement(destination="巴厘岛")
    assessment = agent.assess_destination_complexity(req)
    assert assessment.is_complex is True
    region_names = {r.name for r in assessment.regions}
    assert {"Ubud", "Canggu"}.issubset(region_names)
    assert assessment.confirmation_message and "区域" in assessment.confirmation_message


def test_assess_destination_complexity_simple_destination(no_llm):
    agent = RequirementAgent()
    req = TravelRequirement(destination="东京")
    assessment = agent.assess_destination_complexity(req)
    assert assessment.is_complex is False
    assert assessment.regions == []


def test_parse_region_selection_no_split_keyword(no_llm):
    agent = RequirementAgent()
    assessment = agent.assess_destination_complexity(TravelRequirement(destination="巴厘岛"))
    assert agent.parse_region_selection("不用分区，整体安排就行", assessment) == []


def test_parse_region_selection_named_regions(no_llm):
    agent = RequirementAgent()
    assessment = agent.assess_destination_complexity(TravelRequirement(destination="巴厘岛"))
    selected = agent.parse_region_selection("Canggu和Ubud", assessment)
    assert set(selected) == {"Canggu", "Ubud"}


class _FakeLLM:
    """Minimal stand-in for a `ChatOpenAI` client exposing only `.invoke()`,
    used to exercise the Stage-4 incremental-patch LLM path (`no_llm` forces
    `get_llm()` to `None`, which bypasses this path entirely)."""

    def __init__(self, content: str) -> None:
        self._content = content

    def invoke(self, messages):
        class _Resp:
            pass

        resp = _Resp()
        resp.content = self._content
        return resp


def test_llm_patch_merge_applies_scalars_and_appends_lists(monkeypatch):
    """The LLM only reports *this turn's* delta ({"updates": {...}}); scalars
    overwrite, list fields (interests/...) append+dedupe rather than replace."""
    fake = _FakeLLM('{"updates": {"num_travelers": 2, "budget": 20000, "interests": ["购物"]}}')
    monkeypatch.setattr(
        "travel_agent.agents.requirement_agent.get_llm",
        lambda role=None, tier=None, temperature=None: fake,
    )
    agent = RequirementAgent()
    previous = TravelRequirement(destination="东京", interests=["美食"])
    result = agent.run("两个人，预算2万，我也喜欢购物", previous=previous)

    req = result.requirement
    assert req.num_travelers == 2
    assert req.budget == 20000
    assert set(req.interests) == {"美食", "购物"}
    assert req.destination == "东京"  # untouched field preserved, not overwritten by the patch


def test_llm_patch_merge_drops_unknown_fields(monkeypatch):
    fake = _FakeLLM('{"updates": {"num_travelers": 3, "not_a_real_field": "hallucinated"}}')
    monkeypatch.setattr(
        "travel_agent.agents.requirement_agent.get_llm",
        lambda role=None, tier=None, temperature=None: fake,
    )
    agent = RequirementAgent()
    result = agent.run("三个人")
    assert result.requirement.num_travelers == 3


def test_llm_patch_merge_normalizes_english_pace_synonym(monkeypatch):
    """Regression: DeepSeek has been observed answering `pace` in English
    ("relaxed") despite the prompt instruction; downstream code
    (`TravelRequirement.apply_defaults()`) keys off the exact Chinese strings
    ("特种兵"/"平衡"/"松弛"), so an un-normalized English value would silently
    degrade every pace-dependent default instead of surfacing an error."""
    fake = _FakeLLM('{"updates": {"pace": "relaxed"}}')
    monkeypatch.setattr(
        "travel_agent.agents.requirement_agent.get_llm",
        lambda role=None, tier=None, temperature=None: fake,
    )
    agent = RequirementAgent()
    result = agent.run("节奏松一点")
    assert result.requirement.pace == "松弛"


def test_llm_patch_merge_drops_unrecognized_pace_value(monkeypatch):
    fake = _FakeLLM('{"updates": {"pace": "somewhere in between"}}')
    monkeypatch.setattr(
        "travel_agent.agents.requirement_agent.get_llm",
        lambda role=None, tier=None, temperature=None: fake,
    )
    agent = RequirementAgent()
    result = agent.run("随便")
    assert result.requirement.pace is None


def test_llm_patch_merge_falls_back_to_heuristic_on_malformed_json(monkeypatch):
    fake = _FakeLLM("this is not json")
    monkeypatch.setattr(
        "travel_agent.agents.requirement_agent.get_llm",
        lambda role=None, tier=None, temperature=None: fake,
    )
    agent = RequirementAgent()
    result = agent.run("两个人，预算2万")
    assert result.requirement.num_travelers == 2
    assert result.requirement.budget == 20000
