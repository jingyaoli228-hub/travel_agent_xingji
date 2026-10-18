"""Structured logging for agent / tool calls.

`log_call` wraps a tool or agent method and logs: which one was called, a
short summary of its arguments, latency in milliseconds, and whether it
succeeded, failed (returned `{"success": False, ...}`) or raised. This is the
one place that formats those log lines so every tool/agent gets the same
shape without repeating boilerplate.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from travel_agent.config.settings import get_settings

_CONFIGURED = False


def _configure_once() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # urllib3 debug lines include complete query strings. AMap requires the
    # credential as a query parameter, so suppress those lines to keep keys
    # out of logs even when application debug logging is enabled.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure_once()
    return logging.getLogger(name)


def _summarize(args: tuple, kwargs: dict) -> str:
    parts = [repr(a) for a in args if not hasattr(a, "__dict__") or isinstance(a, (str, int, float, bool))]
    parts += [f"{k}={v!r}" for k, v in kwargs.items()]
    summary = ", ".join(parts)
    return summary[:200] + ("…" if len(summary) > 200 else "")


def log_call(kind: str, name: str) -> Callable:
    """Decorator: log a "tool" or "agent" call's args, latency, and outcome.

    Args:
        kind: "tool" or "agent" — just a label for the log line.
        name: human readable name, e.g. "google_places.search_places".
    """

    def decorator(fn: Callable) -> Callable:
        logger = get_logger(f"travel_agent.{kind}")

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            logger.debug("%s CALL %s(%s)", kind, name, _summarize(args, kwargs))
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - we log then re-raise
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.error("%s FAIL %s (%.0fms): %s", kind, name, elapsed_ms, exc)
                raise
            elapsed_ms = (time.perf_counter() - start) * 1000
            ok = not (isinstance(result, dict) and result.get("success") is False)
            if ok:
                logger.info("%s OK   %s (%.0fms)", kind, name, elapsed_ms)
            else:
                logger.warning("%s ERR  %s (%.0fms): %s", kind, name, elapsed_ms, result.get("error"))
            return result

        return wrapper

    return decorator
