"""Tests for `XiaohongshuSearcher` (`tools/xhs_search.py`), the `opencli`-backed
replacement for the previously-broken Agent Reach `xhs` CLI path.

Mocks at the `subprocess`/`shutil` boundary (same pattern as
`test_tools.py::test_search_travel_guides_*`), so these stay fast, free and
fully offline while still exercising the real command-construction and
response-parsing logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from travel_agent.tools import xhs_search
from travel_agent.tools.xhs_search import XiaohongshuSearcher


def test_search_missing_opencli_binary(monkeypatch):
    monkeypatch.setattr(xhs_search.shutil, "which", lambda exe: None)
    result = XiaohongshuSearcher().search("巴厘岛 冲浪")
    assert result[0]["success"] is False
    assert "opencli" in result[0]["error"]


def test_search_parses_json_output(monkeypatch):
    monkeypatch.setattr(xhs_search.shutil, "which", lambda exe: "/usr/bin/opencli")
    fake_proc = MagicMock(
        returncode=0,
        stdout=(
            '[{"rank":1,"author":"Ad森｜印尼","author_url":"https://x.com/u/1","likes":"611",'
            '"title":"巴厘岛保姆级玩法","url":"https://xiaohongshu.com/1","published_at":"2026-05-23"}]'
        ),
        stderr="",
    )
    with patch.object(xhs_search.subprocess, "run", return_value=fake_proc) as mock_run:
        result = XiaohongshuSearcher().search("巴厘岛 冲浪", limit=5)

    assert mock_run.called
    command = mock_run.call_args[0][0]
    assert "巴厘岛 冲浪" in command
    assert mock_run.call_args.kwargs.get("shell") is True
    assert result[0]["title"] == "巴厘岛保姆级玩法"
    assert result[0]["author"] == "Ad森｜印尼"
    assert result[0]["likes"] == "611"
    assert result[0]["url"] == "https://xiaohongshu.com/1"
    # search-level call doesn't return note body/tags -- documented, not silently faked.
    assert result[0]["content"] is None
    assert result[0]["tags"] == []


def test_search_nonzero_exit_code(monkeypatch):
    monkeypatch.setattr(xhs_search.shutil, "which", lambda exe: "/usr/bin/opencli")
    fake_proc = MagicMock(returncode=1, stdout="", stderr="not logged in")
    with patch.object(xhs_search.subprocess, "run", return_value=fake_proc):
        result = XiaohongshuSearcher().search("巴厘岛")
    assert result[0]["success"] is False
    assert "not logged in" in result[0]["error"]


def test_search_timeout(monkeypatch):
    import subprocess as sp

    monkeypatch.setattr(xhs_search.shutil, "which", lambda exe: "/usr/bin/opencli")
    with patch.object(xhs_search.subprocess, "run", side_effect=sp.TimeoutExpired(cmd="opencli", timeout=30)):
        result = XiaohongshuSearcher().search("巴厘岛")
    assert result[0]["success"] is False
    assert "超时" in result[0]["error"]


def test_search_malformed_json_output(monkeypatch):
    monkeypatch.setattr(xhs_search.shutil, "which", lambda exe: "/usr/bin/opencli")
    fake_proc = MagicMock(returncode=0, stdout="not json at all", stderr="")
    with patch.object(xhs_search.subprocess, "run", return_value=fake_proc):
        result = XiaohongshuSearcher().search("巴厘岛")
    assert result[0]["success"] is False


def test_search_sanitizes_shell_metacharacters_from_keyword(monkeypatch):
    """`shell=True` is required on Windows (opencli.cmd can't be exec'd from an
    argv list without it); the keyword must therefore be stripped of shell
    metacharacters before being interpolated into the command line, or a
    malicious destination/interest string could break out into arbitrary
    shell commands."""
    monkeypatch.setattr(xhs_search.shutil, "which", lambda exe: "/usr/bin/opencli")
    fake_proc = MagicMock(returncode=0, stdout="[]", stderr="")
    with patch.object(xhs_search.subprocess, "run", return_value=fake_proc) as mock_run:
        XiaohongshuSearcher().search('巴厘岛"; rm -rf ~ #& calc.exe &')
    command = mock_run.call_args[0][0]
    # The template itself wraps {query} in literal double-quotes -- check the
    # *sanitized keyword* didn't smuggle any shell metacharacters through,
    # not that the whole command line is quote-free.
    for bad_char in (";", "&", "|", "`", "$", ">", "<", "#"):
        assert bad_char not in command
    assert "巴厘岛" in command


def test_build_interest_queries_with_top_interest():
    queries = XiaohongshuSearcher().build_interest_queries("巴厘岛", ["小众建筑"])
    assert queries[0] == "巴厘岛 小众建筑"
    assert "巴厘岛 私藏地点" in queries
    assert "巴厘岛 本地生活" in queries


def test_build_interest_queries_without_interests():
    queries = XiaohongshuSearcher().build_interest_queries("东京", [])
    assert queries[0] in ("东京 私藏地点", "东京")
    assert all(q.startswith("东京") for q in queries)
