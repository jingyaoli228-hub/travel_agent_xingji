"""Lazy mtime-fingerprint reload check for the skills directory -- no
`watchdog` dependency (see plan decision D2: the requirement is "no restart
needed", not "sub-second reactivity", and `watchdog` would pull in a native
per-platform backend for a project with zero existing background-thread/
file-watcher infrastructure). Checked on every `SkillRegistry` access; cheap
(`Path.glob` + `stat()`) when nothing changed, real reparse only happens when
the fingerprint differs from last time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

Fingerprint = Tuple[float, int]

_NO_SKILLS: Fingerprint = (0.0, 0)


def fingerprint(skills_dir: str) -> Fingerprint:
    root = Path(skills_dir)
    if not root.exists():
        return _NO_SKILLS
    mtimes = []
    for entry in root.glob("*/SKILL.md"):
        try:
            mtimes.append(entry.stat().st_mtime)
        except OSError:
            continue
    return (max(mtimes) if mtimes else 0.0, len(mtimes))


class SkillWatcher:
    def __init__(self) -> None:
        self._last: Fingerprint = _NO_SKILLS

    def check_and_reload(self, skills_dir: str) -> bool:
        """Return True (and remember the new fingerprint) if the skills
        directory's contents changed since the last check."""
        current = fingerprint(skills_dir)
        changed = current != self._last
        self._last = current
        return changed

    def reset(self) -> None:
        self._last = _NO_SKILLS
