"""`SkillRegistry` -- process-wide view of every currently-loaded Skill.

`get_activity_vocabulary()` is consumed by Phase 5's query generator
(`agents/query_generation.py`); `get_synonym_map()` extends
`intent/pattern_parser.py`'s `CATEGORY_KEYWORDS`-style keyword matching so a
new `SKILL.md` file (e.g. adding "浮潜"/"滑翔伞") becomes recognizable without
another code change to the pattern parser.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from travel_agent.config.settings import get_settings
from travel_agent.skills.loader import SkillLoader
from travel_agent.skills.schema import SkillDocument, SkillManifest
from travel_agent.skills.watcher import SkillWatcher


class SkillRegistry:
    def __init__(self, skills_dir_getter: Optional[Callable[[], str]] = None) -> None:
        self._skills_dir_getter = skills_dir_getter or (lambda: get_settings().skills_dir)
        self._loader = SkillLoader()
        self._watcher = SkillWatcher()
        self._skills: Dict[str, SkillDocument] = {}

    def _sync(self) -> None:
        skills_dir = self._skills_dir_getter()
        if self._watcher.check_and_reload(skills_dir):
            self._skills = self._loader.load_all(skills_dir)

    def all_skills(self) -> Dict[str, SkillDocument]:
        self._sync()
        return dict(self._skills)

    def get_activity_vocabulary(self) -> Dict[str, SkillManifest]:
        """activity_type -> SkillManifest, for enabled skills only."""
        self._sync()
        return {doc.manifest.activity_type: doc.manifest for doc in self._skills.values() if doc.manifest.enabled}

    def get_synonym_map(self) -> Dict[str, str]:
        """keyword -> activity_type, for enabled skills only."""
        self._sync()
        mapping: Dict[str, str] = {}
        for doc in self._skills.values():
            if not doc.manifest.enabled:
                continue
            for synonym in doc.manifest.synonyms:
                mapping[synonym] = doc.manifest.activity_type
        return mapping

    def force_reload(self) -> None:
        self._watcher.reset()
        self._sync()


_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def reset_skill_registry() -> None:
    """Test-only: drop the process-wide singleton so the next
    `get_skill_registry()` rebuilds from current settings/files."""
    global _registry
    _registry = None
