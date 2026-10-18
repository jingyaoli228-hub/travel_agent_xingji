from travel_agent.agents.requirement_agent import RequirementAgent
from travel_agent.schemas.destination import DestinationComplexityAssessment, RegionCandidate


def _assessment():
    return DestinationComplexityAssessment(
        is_complex=True,
        regions=[
            RegionCandidate(name="涩谷·新宿·原宿（西东京潮流区）"),
            RegionCandidate(name="浅草·上野·东京站（下町与传统文化区）"),
            RegionCandidate(name="银座·丸之内·日本桥（高端商业与美食区）"),
            RegionCandidate(name="台场·丰洲·迪士尼周边（湾区亲子娱乐区）"),
        ],
    )


def test_region_selection_matches_short_visible_place_names(no_llm):
    agent = RequirementAgent()
    selected = agent.parse_region_selection(
        "安排涩谷、新宿、原宿，再加浅草和银座；不换酒店。", _assessment()
    )
    assert selected == [region.name for region in _assessment().regions[:3]]


def test_region_correction_removes_named_region(no_llm):
    agent = RequirementAgent()
    all_regions = [region.name for region in _assessment().regions]
    corrected = agent.parse_region_correction(
        "修正：不要台场、丰洲和迪士尼，只保留前三个区域；不换酒店。",
        all_regions,
        _assessment(),
    )
    assert corrected == all_regions[:3]


def test_region_correction_replaces_with_explicit_keep_list(no_llm):
    agent = RequirementAgent()
    all_regions = [region.name for region in _assessment().regions]
    corrected = agent.parse_region_correction(
        "只保留浅草和银座", all_regions, _assessment()
    )
    assert corrected == all_regions[1:3]
