"""Loads an Agent's System Prompt from the top-level `prompts/` folder.

Kept as a tiny standalone module (no package dependencies) so every agent can
import it without risking circular imports.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    """Read `prompts/{name}.md` and return its contents (cached).

    Returns an empty string if the file is missing so callers can safely do
    `system = load_prompt('foo') or FALLBACK_TEXT`.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
