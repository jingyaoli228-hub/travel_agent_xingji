"""LLM client factory.

Single place that builds chat model clients — no Agent file should ever call
`ChatOpenAI(...)` directly. All four agents (Requirement / Research / Planner /
Reviewer) plus the Stage-3 intent pipeline's LLM resolver (role="intent", see
`travel_agent/intent/llm_resolver.py`) go through `get_llm(role=..., tier=...)`.

Stage-4: DeepSeek is now the primary backend (falls back to Kimi, then the
legacy generic key, then `None` -- same graceful-degradation contract as
before: callers fall back to their rule-based heuristics when `get_llm()`
returns `None`, so the whole pipeline still runs end-to-end offline).

`tier` picks which DeepSeek model is used:
    - "fast" -> `deepseek_fast_model` (deepseek-chat): the default for every
      call site. Used for extraction/classification/anything using
      `.with_structured_output(...)` (tool-calling), *and* for short,
      constrained-output prose rewriting (destination summaries,
      activity-card text, itinerary reason polishing).
    - "deep" -> `deepseek_deep_model` (deepseek-reasoner): available as an
      explicit opt-in for genuinely multi-step reasoning tasks, but nothing
      in this codebase defaults to it. Empirically (live-tested), asking
      deepseek-reasoner to do a bounded rewrite/summarize task still makes it
      "think" at length -- one activity-card enrichment call alone measured
      6366 *output* tokens and ~70s for what should be a few short sentences
      -- which actively fights the app's latency targets for no quality
      benefit on tasks this constrained. Reasoning models pay off on tasks
      that need multi-step deliberation, not "rewrite this into one natural
      sentence, don't invent facts." deepseek-reasoner also rejects
      `tool_choice`/function-calling outright (confirmed against the live
      API: "Thinking mode does not support this tool_choice"), so any call
      site using `with_structured_output` MUST use tier="fast" regardless.

Kimi's `kimi-k2.x`/`k3` models ignore `tier` entirely (one model for everything,
temperature forced to 1, same as before) since they're only the legacy fallback.
"""

from __future__ import annotations

from typing import Literal, Optional

from travel_agent.config.settings import get_settings
from travel_agent.utils.llm_logging import LatencyLoggingHandler

Tier = Literal["fast", "deep"]

_ROLE_KEY_ATTR = {
    "requirement": "kimi_requirement_api_key",
    "research": "kimi_research_api_key",
    "planner": "kimi_planner_api_key",
    "reviewer": "kimi_reviewer_api_key",
    "intent": "kimi_intent_api_key",
}


def _resolve_kimi_key(role: Optional[str]) -> Optional[str]:
    settings = get_settings()
    if role:
        role_key = getattr(settings, _ROLE_KEY_ATTR.get(role, ""), None)
        if role_key:
            return role_key
    return settings.kimi_api_key or None


def get_llm(role: Optional[str] = None, tier: Optional[Tier] = None, temperature: Optional[float] = None):
    """Build a chat model client for the given agent role/tier, or `None`.

    Args:
        role: "requirement" | "research" | "planner" | "reviewer" | "intent" | None.
        tier: "fast" | "deep". Defaults to "fast" for every role -- pass
            tier="deep" explicitly only for a call site that genuinely needs
            multi-step reasoning (nothing currently does, see module docstring).
        temperature: overrides the resolved default when provided (ignored for
            Kimi, which forces temperature=1; ignored for deepseek-reasoner,
            which doesn't accept it either).

    Returns
    -------
    langchain_openai.ChatOpenAI | None
    """
    settings = get_settings()
    resolved_tier = tier or "fast"

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:  # pragma: no cover - dependency should always be installed
        return None

    handler = LatencyLoggingHandler(role, resolved_tier, "")

    if settings.deepseek_api_key:
        model = settings.deepseek_fast_model if resolved_tier == "fast" else settings.deepseek_deep_model
        handler._model = model  # noqa: SLF001 - set after model is known
        kwargs = dict(
            model=model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            callbacks=[handler],
        )
        # deepseek-reasoner doesn't accept a custom temperature; deepseek-chat does.
        if resolved_tier != "deep":
            kwargs["temperature"] = temperature if temperature is not None else settings.llm_temperature
        return ChatOpenAI(**kwargs)

    kimi_key = _resolve_kimi_key(role)
    if kimi_key:
        handler._model = settings.kimi_model  # noqa: SLF001
        # Moonshot's current kimi-k2.x/k3 models are reasoning models that only
        # accept temperature=1 ("invalid temperature: only 1 is allowed for this
        # model"); a lower temperature has to be enforced via prompting instead.
        return ChatOpenAI(
            model=settings.kimi_model,
            api_key=kimi_key,
            base_url=settings.kimi_base_url,
            temperature=1.0,
            callbacks=[handler],
        )

    if settings.llm_api_key:
        handler._model = settings.llm_model  # noqa: SLF001
        kwargs = dict(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            temperature=temperature if temperature is not None else settings.llm_temperature,
            callbacks=[handler],
        )
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        return ChatOpenAI(**kwargs)

    return None


def llm_available(role: Optional[str] = None) -> bool:
    """Whether a real LLM backend is configured for the given role."""
    return get_llm(role) is not None
