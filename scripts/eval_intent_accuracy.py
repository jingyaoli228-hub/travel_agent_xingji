"""Offline intent-accuracy evaluation against `intent_data/intent_examples.jsonl`.

Default: Pattern + Embedding only -- fast, free, matches this project's
"prefer the offline suite" guidance (the real Kimi endpoint takes
60-100s/call, per `travel_agent/tests/conftest.py`'s docstring). Pass
`--with-llm` to also exercise the LLM-assisted Deep Path (needs a configured
`KIMI_API`/`KIMI_INTENT_API` key); expect this to take much longer.

Usage:
    python scripts/eval_intent_accuracy.py
    python scripts/eval_intent_accuracy.py --with-llm --limit 30
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("asyncio").setLevel(logging.WARNING)  # settings.debug=True otherwise leaks noisy proactor logs

from travel_agent.intent.data_store import load_intent_examples
from travel_agent.intent.interpreter import MultiSignalIntentInterpreter
from travel_agent.intent.schemas import IntentContext


class _NullLLMResolver:
    def resolve(self, *args, **kwargs):
        return None


def _predict(interpreter: MultiSignalIntentInterpreter, message: str) -> str:
    ctx = IntentContext(current_message=message, current_phase="post_plan_feedback", current_plan_summary={"day_count": 5})
    return interpreter.interpret(message, ctx).primary_intent


def _macro_f1(y_true: List[str], y_pred: List[str]) -> float:
    labels = set(y_true) | set(y_pred)
    f1s = []
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if (precision + recall) else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-llm", action="store_true", help="Also exercise the LLM branch (slow, needs a real key)")
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N examples")
    args = parser.parse_args()

    examples = load_intent_examples()
    if args.limit:
        examples = examples[: args.limit]

    interpreter = MultiSignalIntentInterpreter()
    if not args.with_llm:
        interpreter._llm_resolver = _NullLLMResolver()

    y_true, y_pred = [], []
    start = time.perf_counter()
    for ex in examples:
        y_true.append(ex.intent)
        y_pred.append(_predict(interpreter, ex.text))
    elapsed = time.perf_counter() - start

    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    accuracy = correct / len(examples) if examples else 0.0
    macro_f1 = _macro_f1(y_true, y_pred)

    print(f"Examples: {len(examples)}  (LLM branch: {'on' if args.with_llm else 'off'})")
    print(f"Accuracy: {accuracy:.3f}")
    print(f"Macro-F1: {macro_f1:.3f}")
    print(f"Total time: {elapsed:.2f}s  ({elapsed / max(len(examples), 1) * 1000:.1f} ms/example)")

    mismatches = [(t, p, ex.text) for t, p, ex in zip(y_true, y_pred, examples) if t != p]
    if mismatches:
        print(f"\nMismatches ({len(mismatches)}):")
        for true, pred, text in mismatches[:30]:
            print(f"  expected={true:<24} predicted={pred:<24} text={text}")


if __name__ == "__main__":
    main()
