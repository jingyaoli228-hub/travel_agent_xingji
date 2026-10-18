"""Xiaohongshu (小红书) search via `opencli`, using the user's local logged-in
Chrome session -- replaces the previously broken `xhs` CLI that
`tools/search.py` (Agent Reach) shelled out to, which always failed
("未检测到攻略搜索命令 xhs").

`opencli xiaohongshu search "<query>" --limit N -f json` drives a real Chrome
tab against the user's own authenticated Xiaohongshu session; no API key
involved. Verified live against the installed `opencli` (v1.8.6): returns a
JSON array shaped like `{rank, author, author_url, likes, title, url,
published_at}` in ~12s for a single query.

`content`/`tags` are intentionally left `None`/`[]` here -- only
`opencli xiaohongshu note <id>` returns a note's body text, and calling that
once per search result would blow the ~30s total research time budget. This
is a documented simplification (see README), not a silent gap.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from travel_agent.config.settings import get_settings
from travel_agent.utils.logging import get_logger, log_call

_TIMEOUT_SECONDS = 30

_logger = get_logger("travel_agent.tools.xhs_search")

# `opencli` on Windows resolves to an npm-installed `opencli.cmd` shim, which
# Windows' CreateProcess cannot launch directly from an argv list (WinError 2,
# "the system cannot find the file specified") -- this is the same well-known
# gotcha as `subprocess.run(["npm", ...])` on Windows; the standard fix is
# `shell=True` (verified live: fails without it, works with it). Since
# `shell=True` means `keyword` is interpolated into a real shell command line,
# it's stripped down to word characters + whitespace first -- a destination/
# interest keyword never legitimately needs quotes/`&`/`|`/`%`/backticks etc.,
# so this is a strict allowlist, not a best-effort escape.
_UNSAFE_KEYWORD_CHARS = re.compile(r"[^\w\s]", re.UNICODE)


def _sanitize_keyword(keyword: str) -> str:
    return _UNSAFE_KEYWORD_CHARS.sub(" ", keyword or "").strip()


class XiaohongshuSearcher:
    """Wraps `opencli xiaohongshu search` -- real results, no API key, backed
    by whatever Xiaohongshu account is logged into the user's local Chrome."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _executable(self) -> Optional[str]:
        try:
            parts = shlex.split(self._settings.xhs_search_cmd)
        except ValueError:
            return None
        return parts[0] if parts else None

    @log_call("tool", "xhs_search.search")
    def search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search Xiaohongshu notes for `keyword`.

        Returns a list of `{title, author, likes, url, content, tags}` dicts,
        or a single `{"success": False, "error": "..."}` item if `opencli`
        isn't installed, times out, or returns something unparseable.
        """
        executable = self._executable()
        if not executable or shutil.which(executable) is None:
            return [
                {
                    "success": False,
                    "error": (
                        f"未检测到小红书搜索所需的命令行工具「{executable}」。"
                        "请先安装 opencli 并在本机 Chrome 中登录小红书账号"
                        "（可运行 `opencli xiaohongshu login`），再检查 .env 的 XHS_SEARCH_CMD。"
                    ),
                }
            ]

        safe_keyword = _sanitize_keyword(keyword)
        if not safe_keyword:
            return [{"success": False, "error": "搜索关键词为空或不合法"}]

        command = self._settings.xhs_search_cmd.format(query=safe_keyword, limit=limit)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return [{"success": False, "error": f"小红书搜索超时 (>{_TIMEOUT_SECONDS}s)"}]
        except (subprocess.SubprocessError, OSError) as exc:
            _logger.error("xhs_search.search subprocess failed: %s", exc)
            return [{"success": False, "error": f"小红书搜索命令执行失败: {exc}"}]

        if proc.returncode != 0:
            return [
                {
                    "success": False,
                    "error": f"小红书搜索命令返回非零退出码 ({proc.returncode}): {proc.stderr.strip()[:300]}",
                }
            ]

        return self._parse_output(proc.stdout, limit)

    @staticmethod
    def _parse_output(raw: str, limit: int) -> List[Dict[str, Any]]:
        try:
            data = json.loads(raw)
        except ValueError:
            return [{"success": False, "error": "小红书搜索命令输出不是合法 JSON"}]

        items = data if isinstance(data, list) else data.get("results", data.get("items", []))
        results: List[Dict[str, Any]] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "title": item.get("title") or "",
                    "author": item.get("author") or "",
                    "likes": item.get("likes") or "",
                    "url": item.get("url") or "",
                    "content": None,  # search-level call doesn't return note body -- see module docstring
                    "tags": [],
                }
            )
        return results

    def build_interest_queries(self, destination: str, interests: Optional[List[str]] = None) -> List[str]:
        """Build query variants for a destination + user-stated interest, e.g.
        `build_interest_queries("巴厘岛", ["小众建筑"])` ->
        `["巴厘岛 小众建筑", "巴厘岛 私藏地点", "巴厘岛 本地生活"]`.

        `run_full`'s default social-research worker only uses `queries[0]` to
        stay inside the research time budget; the full list is for
        `ResearchOrchestratorAgent.run_feedback`, where a user explicitly asked
        for more/different content and a few extra seconds is expected UX.
        """
        destination = (destination or "").strip()
        top_interest = next(iter(interests or []), None)
        queries: List[str] = []
        if top_interest:
            queries.append(f"{destination} {top_interest}".strip())
        for suffix in ("私藏地点", "本地生活"):
            query = f"{destination} {suffix}".strip()
            if query not in queries:
                queries.append(query)
        return queries or [destination]
