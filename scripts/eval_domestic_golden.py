"""Run the P0 ten-city domestic golden regression suite offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from travel_agent.evaluation.domestic_golden import evaluate_domestic_golden_suite, load_domestic_golden_cases


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(repo_root / "evaluation_cases" / "domestic_golden_cases.json"))
    parser.add_argument("--json-output", default=None)
    args = parser.parse_args()

    cases = load_domestic_golden_cases(args.cases)
    results = evaluate_domestic_golden_suite(cases)
    payload = {
        "case_count": len(results),
        "passed_count": sum(result.passed for result in results),
        "pass_rate": round(sum(result.passed for result in results) / max(len(results), 1), 3),
        "average_reviewer_score": round(sum(result.reviewer_score for result in results) / max(len(results), 1), 2),
        "minimum_reviewer_score": min((result.reviewer_score for result in results), default=0),
        "average_preferred_ratio": round(sum(result.preferred_ratio for result in results) / max(len(results), 1), 3),
        "results": [result.model_dump() | {"passed": result.passed} for result in results],
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_output:
        Path(args.json_output).write_text(rendered + "\n", encoding="utf-8")
    if payload["passed_count"] != payload["case_count"] or payload["minimum_reviewer_score"] < 85:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
