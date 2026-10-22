from pathlib import Path

from travel_agent.evaluation.domestic_golden import evaluate_domestic_golden_suite, load_domestic_golden_cases


def test_ten_domestic_golden_cases_pass_reviewer_gate(no_llm) -> None:
    path = Path(__file__).resolve().parents[2] / "evaluation_cases" / "domestic_golden_cases.json"
    cases = load_domestic_golden_cases(path)
    assert len(cases) == 10
    assert len({case.destination for case in cases}) == 10

    results = evaluate_domestic_golden_suite(cases)
    failures = {result.case_id: result.failures for result in results if not result.passed}
    assert failures == {}
    assert min(result.reviewer_score for result in results) >= 85
    assert sum(result.reviewer_score for result in results) / len(results) >= 85


def test_golden_selection_honors_explicit_exclusions(no_llm) -> None:
    path = Path(__file__).resolve().parents[2] / "evaluation_cases" / "domestic_golden_cases.json"
    cases = load_domestic_golden_cases(path)
    results = evaluate_domestic_golden_suite(cases)
    for case, result in zip(cases, results):
        assert all(excluded not in selected for excluded in case.excluded_names for selected in result.selected_names)
