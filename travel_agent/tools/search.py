"""Travel guide / social content search tool: `search_travel_guides`.

Replaces the old mock `web_search.py`. Backed by Agent Reach
(https://github.com/Panniantong/agent-reach), a CLI router the user installs
and configures locally (it in turn installs upstream CLIs such as a
Xiaohongshu/Twitter search command). We cannot install or configure Agent
Reach on the user's behalf, so this tool only *calls* whatever command is
already on PATH, via the template configured in `AGENT_REACH_SEARCH_CMD`
(`{query}` is substituted with the search string). If the command isn't
installed or fails, we return `{"success": False, "error": "..."}` instead of
fabricating "popular guide" content.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from travel_agent.config.settings import get_settings
from travel_agent.schemas.tool_results import GuideResult
from travel_agent.utils.logging import get_logger, log_call

_TIMEOUT_SECONDS = 30

_logger = get_logger("travel_agent.tools.search")


def _executable_from_template(cmd_template: str) -> Optional[str]:
    try:
        parts = shlex.split(cmd_template)
    except ValueError:
        return None
    return parts[0] if parts else None


def _parse_output(raw: str, platform: str, limit: int) -> List[Dict[str, Any]]:
    """Best-effort parse of the upstream CLI's stdout.

    Tries JSON first (list of {title,url,snippet} or similar); falls back to
    treating each non-empty line as one result's title/snippet so a wide
    range of upstream CLI output formats still produce something usable.
    """
    results: List[Dict[str, Any]] = []
    try:
        data = json.loads(raw)
        items = data if isinstance(data, list) else data.get("results", data.get("items", []))
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            results.append(
                GuideResult(
                    title=item.get("title") or item.get("name") or "",
                    url=item.get("url") or item.get("link") or "",
                    snippet=item.get("snippet") or item.get("summary") or item.get("content"),
                    platform=platform,
                ).model_dump()
            )
        if results:
            return results
    except (ValueError, AttributeError):
        pass

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    for line in lines[:limit]:
        results.append(GuideResult(title=line, url="", snippet=None, platform=platform).model_dump())
    return results


@tool
@log_call("tool", "search.search_travel_guides")
def search_travel_guides(
    destination: str,
    keywords: Optional[List[str]] = None,
    platform: str = "web",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """搜索大众攻略/小红书热门玩法/避坑信息/当地特色 (通过本地已安装的 Agent Reach)。

    Args:
        destination: 目的地城市。
        keywords: 可选补充关键词，例如 ["购物","避坑"]。
        platform: "web"（大众攻略）或 "xiaohongshu"（小红书/社媒热门玩法）。
        limit: 返回结果数量上限。

    Returns:
        攻略结果列表，每项包含 title/url/snippet/platform/source；
        Agent Reach 未安装或调用失败时返回单个 `{"success": false, "error": "..."}`，
        说明需要用户先按 https://github.com/Panniantong/agent-reach 安装配置。
    """
    settings = get_settings()
    cmd_template = settings.agent_reach_search_cmd
    executable = _executable_from_template(cmd_template)
    if not executable or shutil.which(executable) is None:
        return [
            {
                "success": False,
                "error": (
                    f"未检测到攻略搜索所需的命令行工具「{executable}」。"
                    "请先按 https://github.com/Panniantong/agent-reach 安装并配置 Agent Reach，"
                    "并在 .env 的 AGENT_REACH_SEARCH_CMD 中填入你本机实际可用的命令模板。"
                ),
            }
        ]

    query_parts = [destination] + (keywords or []) + (["小红书"] if platform == "xiaohongshu" else ["攻略"])
    query = " ".join(query_parts)
    command = cmd_template.format(query=query)

    try:
        proc = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.SubprocessError, OSError) as exc:
        _logger.error("search.search_travel_guides subprocess failed: %s", exc)
        return [{"success": False, "error": f"攻略搜索命令执行失败: {exc}"}]

    if proc.returncode != 0:
        return [
            {
                "success": False,
                "error": f"攻略搜索命令返回非零退出码 ({proc.returncode}): {proc.stderr.strip()[:300]}",
            }
        ]

    return _parse_output(proc.stdout, platform, limit)
