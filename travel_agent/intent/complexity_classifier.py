"""Fast/Deep path triage (design doc section 3).

`RequestComplexityClassifier` decides SIMPLE vs COMPLEX using only the
Pattern parser + (optionally) the current workflow state -- no LLM call, so
every request pays this cost, and only COMPLEX ones pay for the Deep Path's
embedding/LLM fan-out.
"""

from __future__ import annotations

from typing import List, Optional

from travel_agent.intent.pattern_parser import PatternParser
from travel_agent.intent.schemas import ComplexityResult, IntentContext

# Chinese hedging/complaint markers -- "太游客了"/"感觉不太对"/"不太适合我" etc.
# Their presence means the user is expressing a subjective judgment that
# needs LLM-level reasoning about *why*, not just entity extraction.
_FUZZY_FEEDBACK_MARKERS = ["太", "感觉", "不太", "不算", "有点不", "怪怪的", "说不上"]

_CLEAR_SIMPLE_OPERATIONS = {"ADD", "REMOVE", "REPLACE", "MOVE", "SELECT", "QUERY", "COMPARE"}


class RequestComplexityClassifier:
    def __init__(self) -> None:
        self._pattern_parser = PatternParser()

    async def classify(self, message: str, context: Optional[IntentContext] = None) -> ComplexityResult:
        # Fast/cheap and synchronous under the hood; kept `async def` to match
        # the interpreter's calling convention (it may be invoked alongside
        # awaited I/O elsewhere without forcing callers to special-case it).
        return self._classify_sync(message, context)

    def _classify_sync(self, message: str, context: Optional[IntentContext] = None) -> ComplexityResult:
        pattern = self._pattern_parser.parse(message, context)
        text = (message or "").strip()

        if pattern.is_confirm or pattern.is_reject:
            return ComplexityResult(level="SIMPLE", reasons=["explicit_confirm_or_reject"], confidence=0.95)

        reasons: List[str] = []
        requires_llm = False
        requires_context = False
        requires_multi_intent = False

        if pattern.multi_intent:
            reasons.append("multiple_operations_in_one_message")
            requires_multi_intent = True
        if pattern.is_negation:
            reasons.append("negation_present")
            requires_llm = True
        if pattern.has_ambiguity:
            reasons.append("referential_or_ambiguous_target")
            requires_context = True
        if pattern.preserve_other_days is not None:
            # "其他不变"/"只改第三天" -- resolving what "other" refers to needs
            # the actual current itinerary state, and mis-scoping it is the
            # exact failure mode this whole upgrade exists to prevent.
            reasons.append("explicit_partial_preserve_scope")
            requires_context = True
        if any(m in text for m in _FUZZY_FEEDBACK_MARKERS):
            reasons.append("fuzzy_subjective_feedback")
            requires_llm = True
        if pattern.operation is None and len(text) > 4:
            reasons.append("no_clear_operation_detected")
            requires_llm = True

        if reasons:
            confidence = 0.85 if len(reasons) >= 2 else 0.7
            return ComplexityResult(
                level="COMPLEX",
                reasons=reasons,
                requires_llm=True,
                requires_context=requires_context,
                requires_multi_intent=requires_multi_intent,
                confidence=confidence,
            )

        if pattern.operation in _CLEAR_SIMPLE_OPERATIONS:
            return ComplexityResult(
                level="SIMPLE", reasons=["single_unambiguous_operation"], confidence=max(pattern.confidence, 0.6)
            )

        if context and context.pending_confirmation and len(text) <= 6:
            return ComplexityResult(
                level="SIMPLE",
                reasons=["short_reply_with_pending_confirmation"],
                requires_context=True,
                confidence=0.75,
            )

        # Unknown shape: no operation, no obvious signal either way -- safer
        # to escalate than to silently mishandle it as a no-op.
        return ComplexityResult(
            level="COMPLEX", reasons=["unclassified_defaulting_to_deep_path"], requires_llm=True, confidence=0.4
        )
