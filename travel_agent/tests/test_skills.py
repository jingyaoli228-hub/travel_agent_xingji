"""Tests for the Phase-2 Dynamic Skill Runtime (`travel_agent/skills/`):
frontmatter parsing, malformed/disabled-file handling, mtime-based hot
reload without a restart, and that `pattern_parser.py`'s category matching
picks up skill-declared synonyms.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from travel_agent.skills.loader import SkillLoader
from travel_agent.skills.registry import SkillRegistry
from travel_agent.skills.watcher import SkillWatcher, fingerprint


def _write_skill(root: Path, name: str, activity_type: str, synonyms, enabled: bool = True) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    synonyms_yaml = "\n".join(f"  - {s}" for s in synonyms)
    content = f"""---
name: {name}
activity_type: {activity_type}
synonyms:
{synonyms_yaml}
query_templates:
  - "{{dest}} {activity_type}"
tool: google_places.search_places
enabled: {str(enabled).lower()}
---

# {name}

Body text.
"""
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


# -- SkillLoader --------------------------------------------------------------


def test_loader_parses_valid_skill(tmp_path):
    _write_skill(tmp_path, "snorkeling_activities", "snorkeling", ["浮潜", "潜水"])
    loader = SkillLoader()
    skills = loader.load_all(str(tmp_path))
    assert "snorkeling_activities" in skills
    manifest = skills["snorkeling_activities"].manifest
    assert manifest.activity_type == "snorkeling"
    assert "浮潜" in manifest.synonyms
    assert manifest.enabled is True


def test_loader_skips_malformed_frontmatter(tmp_path):
    skill_dir = tmp_path / "broken_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("not a valid frontmatter file", encoding="utf-8")
    loader = SkillLoader()
    skills = loader.load_all(str(tmp_path))
    assert skills == {}


def test_loader_skips_invalid_manifest_fields(tmp_path):
    skill_dir = tmp_path / "missing_required"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: missing_required\n---\nbody\n", encoding="utf-8")
    loader = SkillLoader()
    skills = loader.load_all(str(tmp_path))
    # activity_type is required -- validation error, file skipped, no crash.
    assert skills == {}


def test_loader_missing_directory_returns_empty():
    loader = SkillLoader()
    assert loader.load_all("/no/such/skills/dir") == {}


def test_loader_disabled_skill_still_loads_but_flagged(tmp_path):
    _write_skill(tmp_path, "disabled_one", "disabled_activity", ["测试"], enabled=False)
    loader = SkillLoader()
    skills = loader.load_all(str(tmp_path))
    assert skills["disabled_one"].manifest.enabled is False


# -- SkillWatcher ---------------------------------------------------------------


def test_watcher_detects_new_file(tmp_path):
    watcher = SkillWatcher()
    assert watcher.check_and_reload(str(tmp_path)) is False  # empty dir, no change from initial (0,0)

    _write_skill(tmp_path, "new_skill", "new_activity", ["新活动"])
    assert watcher.check_and_reload(str(tmp_path)) is True
    # calling again with no further changes -> no reload signaled
    assert watcher.check_and_reload(str(tmp_path)) is False


def test_watcher_detects_mtime_change_on_edit(tmp_path):
    path = _write_skill(tmp_path, "editable_skill", "editable_activity", ["旧词"])
    watcher = SkillWatcher()
    watcher.check_and_reload(str(tmp_path))  # baseline

    time.sleep(0.05)
    path.write_text(path.read_text(encoding="utf-8").replace("旧词", "新词"), encoding="utf-8")
    assert watcher.check_and_reload(str(tmp_path)) is True


# -- SkillRegistry (hot reload without restart) --------------------------------


def test_registry_hot_reloads_without_restart(tmp_path):
    _write_skill(tmp_path, "paragliding_activities", "paragliding", ["滑翔伞"])
    registry = SkillRegistry(skills_dir_getter=lambda: str(tmp_path))

    vocab = registry.get_activity_vocabulary()
    assert "paragliding" in vocab
    assert registry.get_synonym_map() == {"滑翔伞": "paragliding"}

    # Edit the file in place (simulating a running dev server) -- no
    # registry re-construction, no process restart.
    time.sleep(0.05)
    _write_skill(tmp_path, "paragliding_activities", "paragliding", ["滑翔伞", "跳伞"])
    assert registry.get_synonym_map() == {"滑翔伞": "paragliding", "跳伞": "paragliding"}


def test_registry_excludes_disabled_skills_from_vocabulary(tmp_path):
    _write_skill(tmp_path, "disabled_activity", "disabled_type", ["禁用词"], enabled=False)
    registry = SkillRegistry(skills_dir_getter=lambda: str(tmp_path))
    assert registry.get_activity_vocabulary() == {}
    assert registry.get_synonym_map() == {}


# -- pattern_parser.py integration ---------------------------------------------


def test_pattern_parser_picks_up_skill_synonyms(tmp_path, monkeypatch):
    _write_skill(tmp_path, "snorkeling_activities", "snorkeling", ["浮潜"])
    _write_skill(tmp_path, "paragliding_activities", "paragliding", ["滑翔伞"])

    from travel_agent import skills as skills_pkg
    from travel_agent.skills import registry as registry_module

    monkeypatch.setattr(registry_module, "_registry", registry_module.SkillRegistry(skills_dir_getter=lambda: str(tmp_path)))

    from travel_agent.intent.pattern_parser import canonicalize_categories

    result = canonicalize_categories(["浮潜", "滑翔伞"])
    assert set(result) == {"snorkeling", "paragliding"}
