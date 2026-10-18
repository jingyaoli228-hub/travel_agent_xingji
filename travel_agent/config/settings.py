"""Application configuration loaded from environment variables / .env.

Uses pydantic-settings so every config value is typed and documented in one
place. All LLM-related settings are provider-agnostic: any OpenAI-compatible
endpoint (OpenAI, DeepSeek, Claude-compatible gateways, local vLLM, etc.) can
be used by pointing `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` at it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import AliasChoices, Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "travel-agent"
    debug: bool = False
    environment: str = "development"
    require_persistent_services: bool = False
    cors_origins: str = "http://localhost:5173,http://localhost"

    # --- Kimi (Moonshot, OpenAI-compatible) — the LLM used by all four agents ---
    # get_llm(role=...) in config/llm.py is the single place that builds model clients;
    # agents never instantiate their own client. A role-specific key (if set) wins over
    # the shared KIMI_API key, which in turn wins over the legacy llm_api_key fallback.
    kimi_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("KIMI_API", "kimi_api_key"))
    kimi_base_url: str = Field(default="https://api.moonshot.cn/v1", validation_alias=AliasChoices("KIMI_BASE_URL", "kimi_base_url"))
    kimi_model: str = Field(default="kimi-k2.6", validation_alias=AliasChoices("KIMI_MODEL", "kimi_model"))

    kimi_requirement_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("KIMI_REQUIREMENT_API", "kimi_requirement_agent_api")
    )
    kimi_research_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("KIMI_RESEARCH_API", "kimi_research_api")
    )
    kimi_planner_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("KIMI_PLANNER_API", "kimi_plan_agent_api")
    )
    kimi_reviewer_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("KIMI_REVIEWER_API", "kimi_reviewer_api")
    )
    kimi_intent_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("KIMI_INTENT_API", "kimi_intent_agent_api")
    )

    # --- DeepSeek (OpenAI-compatible) — Stage-4: now the primary LLM backend ---
    # get_llm(role=..., tier=...) prefers DeepSeek whenever `deepseek_api_key` is set, falling
    # back to Kimi (above) and then the legacy generic key, same graceful-degradation contract.
    # tier="fast" (deepseek_fast_model) is used for extraction/classification/tool-calling work;
    # tier="deep" (deepseek_deep_model) for free-form synthesis/reasoning prose -- deepseek-reasoner
    # cannot do function-calling/structured-output, so every with_structured_output() call site
    # must request tier="fast" regardless of its agent role.
    deepseek_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("DEEPSEEK_API_KEY", "deekseek_api")
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com", validation_alias=AliasChoices("DEEPSEEK_BASE_URL", "deepseek_base_url")
    )
    deepseek_fast_model: str = Field(
        default="deepseek-chat", validation_alias=AliasChoices("DEEPSEEK_FAST_MODEL", "deepseek_fast_model")
    )
    deepseek_deep_model: str = Field(
        default="deepseek-reasoner", validation_alias=AliasChoices("DEEPSEEK_DEEP_MODEL", "deepseek_deep_model")
    )

    # --- AMap (Gaode) Web Service / JavaScript API ---
    # Keep server and browser keys separate: a Web Service key must never be
    # embedded in frontend bundles.
    amap_web_service_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("AMAP_WEB_SERVICE_KEY", "AMAP_API_KEY", "GAODE_MAPS_API_KEY"),
    )
    amap_js_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("AMAP_JS_API_KEY", "amap_js_api_key")
    )
    amap_js_security_code: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("AMAP_JS_SECURITY_CODE", "amap_js_security_code")
    )

    # --- Agent Reach (generic web travel guide search, installed locally by the user) ---
    agent_reach_search_cmd: str = Field(
        default='xhs search "{query}"', validation_alias=AliasChoices("AGENT_REACH_SEARCH_CMD", "agent_reach_search_cmd")
    )

    # --- Xiaohongshu (小红书) search via `opencli`, using the user's local logged-in Chrome ---
    xhs_search_cmd: str = Field(
        default='opencli xiaohongshu search "{query}" --limit {limit} -f json',
        validation_alias=AliasChoices("XHS_SEARCH_CMD", "xhs_search_cmd"),
    )

    # --- LLM (generic OpenAI-compatible fallback, kept for offline/dev use) ---
    # provider is informational only; base_url/model fully determine behavior.
    llm_provider: str = "openai"  # openai | deepseek | claude_compatible | none
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None  # e.g. https://api.deepseek.com/v1
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3

    # --- Redis (state persistence) ---
    redis_url: Optional[str] = None  # e.g. redis://localhost:6379/0
    redis_key_prefix: str = "travel_agent:session:"
    redis_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days

    # --- Durable production state ---
    database_url: Optional[str] = None
    research_queue_name: str = "research"
    research_job_timeout_seconds: int = 900
    research_job_max_retries: int = 2
    research_stale_after_seconds: int = 1200

    # --- Chroma: embedded locally, HTTP service in Docker ---
    chroma_host: Optional[str] = None
    chroma_port: int = 8000
    chroma_ssl: bool = False

    # --- Reviewer loop ---
    max_review_loops: int = 3
    review_pass_score: int = 85

    # --- Planner <-> Research feasibility/expansion loop ---
    max_research_expansion_loops: int = 2

    # --- Memory (L2 episodic / L3 profile) ---
    # No vector DB dependency is required: episodic memory falls back to a local
    # JSON-lines file with tag-overlap similarity when `vector_db_path` is unset
    # or `chromadb` isn't installed (same graceful-degradation pattern as Redis).
    episodic_memory_path: str = "./data/episodic_memory.jsonl"
    user_profile_store_path: str = "./data/user_profiles.json"
    vector_db_path: Optional[str] = None

    # --- Stage-3: Multi-signal intent pipeline (see travel_agent/intent/) ---
    # Weights/thresholds/Top-K/timeouts live in intent_fusion_config_path (YAML),
    # not here -- see travel_agent/intent/config.py::load_fusion_config(). These
    # are just the filesystem locations, kept in Settings so they're env-overridable.
    intent_data_dir: str = "./intent_data"
    intent_fusion_config_path: str = "./config/intent_fusion.yaml"

    # --- Round-5: Production Tool Runtime (see travel_agent/tool_runtime/) ---
    # Per-tool timeout/cache-ttl/circuit-breaker thresholds live in
    # tool_runtime_config_path (YAML), not here -- see
    # travel_agent/tool_runtime/config.py::load_tool_runtime_config().
    tool_runtime_config_path: str = "./config/tool_runtime.yaml"

    # --- Round-5: Dynamic Skill Runtime (see travel_agent/skills/) ---
    skills_dir: str = "./skills"

    # --- Round-5: LLM-as-Judge evaluation harness (see travel_agent/evaluation/) ---
    evaluation_criteria_path: str = "./config/evaluation_criteria.yaml"
    evaluation_cases_dir: str = "./evaluation_cases"

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @field_validator("debug", mode="before")
    @classmethod
    def parse_legacy_debug(cls, value):
        if isinstance(value, str) and value.lower() in {"release", "production", "prod"}:
            return False
        if isinstance(value, str) and value.lower() in {"development", "dev"}:
            return True
        return value

    @property
    def cors_origin_list(self) -> List[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()
