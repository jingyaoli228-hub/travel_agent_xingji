"""Fast/Deep Path latency probe (design doc section XIX, lightweight
version -- no external monitoring stack, just stdout timings).

Default: offline (no real LLM call), so every number here is milliseconds.
Pass `--with-llm` to also time the real LLM branch -- expect 60-100s/call
against the configured Kimi endpoint per this project's operational notes.

Usage:
    python scripts/eval_latency.py
    python scripts/eval_latency.py --with-llm --n 3
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import statistics
import sys
import time
from pathlib import Path
from typing import Callable, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("asyncio").setLevel(logging.WARNING)  # settings.debug=True otherwise leaks noisy proactor logs

from travel_agent.intent.complexity_classifier import RequestComplexityClassifier
from travel_agent.intent.embedding_router import EmbeddingIntentRetriever
from travel_agent.intent.interpreter import MultiSignalIntentInterpreter
from travel_agent.intent.pattern_parser import PatternParser
from travel_agent.intent.schemas import IntentContext

_SIMPLE_MESSAGES = ["确认", "取消", "东京明天天气怎么样", "第三天下午增加一个咖啡店"]
_COMPLEX_MESSAGES = [
    "这些传统景点太多了，多找一些瑜伽和疗愈活动，第三天下午重新排，其他不变。",
    "删除第三天下午的寺庙，多找两个涩谷附近的唱片店，然后把晚上的酒吧换成演出。",
]


class _NullLLMResolver:
    def resolve(self, *args, **kwargs):
        return None


def _time_calls(fn: Callable[[], None], n: int) -> List[float]:
    timings = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - start) * 1000)
    return timings


def _report(label: str, timings: List[float]) -> None:
    timings_sorted = sorted(timings)
    p95_index = max(0, int(len(timings_sorted) * 0.95) - 1)
    print(f"{label:<12} mean={statistics.mean(timings):8.1f}ms  p95={timings_sorted[p95_index]:8.1f}ms  n={len(timings)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args()

    ctx = IntentContext(current_message="", current_phase="post_plan_feedback", current_plan_summary={"day_count": 5})
    pattern_parser = PatternParser()
    embedding_retriever = EmbeddingIntentRetriever()
    classifier = RequestComplexityClassifier()
    interpreter = MultiSignalIntentInterpreter()
    if not args.with_llm:
        interpreter._llm_resolver = _NullLLMResolver()

    print("== Pattern parser ==")
    _report("pattern", _time_calls(lambda: pattern_parser.parse(_COMPLEX_MESSAGES[0], ctx), args.n))

    print("== Embedding router ==")
    _report("embedding", _time_calls(lambda: embedding_retriever.retrieve(_COMPLEX_MESSAGES[0], ctx), args.n))

    print("== Complexity classifier ==")
    _report("classifier", _time_calls(lambda: asyncio.run(classifier.classify(_COMPLEX_MESSAGES[0], ctx)), args.n))

    print("== Fast Path (simple messages) ==")
    fast_timings: List[float] = []
    for msg in _SIMPLE_MESSAGES:
        fast_timings += _time_calls(lambda m=msg: interpreter.interpret(m, ctx), args.n)
    _report("fast_path", fast_timings)

    print(f"== Deep Path (complex messages, LLM {'on' if args.with_llm else 'off'}) ==")
    deep_timings: List[float] = []
    for msg in _COMPLEX_MESSAGES:
        deep_timings += _time_calls(lambda m=msg: interpreter.interpret(m, ctx), args.n)
    _report("deep_path", deep_timings)


if __name__ == "__main__":
    main()
