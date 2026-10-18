"""Parses `<skills_dir>/<name>/SKILL.md` files: YAML frontmatter (between
`---` markers) + a free-text markdown body. Never hard-fails the whole
load -- a malformed or unreadable file is skipped with a warning, same
graceful-degradation philosophy as `intent/config.py::load_fusion_config()`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

import yaml
from pydantic import ValidationError

from travel_agent.skills.schema import SkillDocument, SkillManifest
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.skills")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class SkillLoader:
    def load_all(self, skills_dir: str) -> Dict[str, SkillDocument]:
        root = Path(skills_dir)
        result: Dict[str, SkillDocument] = {}
        if not root.exists():
            return result
        for skill_md in sorted(root.glob("*/SKILL.md")):
            doc = self._load_one(skill_md)
            if doc is not None:
                result[doc.manifest.name] = doc
        return result

    def _load_one(self, path: Path) -> Optional[SkillDocument]:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            _logger.warning("skill_runtime: failed to read %s: %s", path, exc)
            return None

        match = _FRONTMATTER_RE.match(raw)
        if not match:
            _logger.warning("skill_runtime: %s missing YAML frontmatter (---...---), skipping", path)
            return None

        frontmatter_raw, body = match.groups()
        try:
            frontmatter = yaml.safe_load(frontmatter_raw) or {}
            if not isinstance(frontmatter, dict):
                raise ValueError("frontmatter is not a mapping")
            manifest = SkillManifest(**frontmatter)
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            _logger.warning("skill_runtime: %s has invalid frontmatter, skipping: %s", path, exc)
            return None

        return SkillDocument(manifest=manifest, body=body.strip())
