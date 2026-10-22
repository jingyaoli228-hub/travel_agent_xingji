"""Validate public self-use deployment settings without printing secrets."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "WECHAT_APP_ID",
    "WECHAT_APP_SECRET",
    "OWNER_OPENID",
    "AUTH_TOKEN_SECRET",
    "CLOUDFLARE_TUNNEL_TOKEN",
    "PUBLIC_API_BASE_URL",
    "HEALTH_ALERT_WEBHOOK_URL",
)
PLACEHOLDERS = ("change_me", "replace_with", "your_", "<", ">")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def validate(values: dict[str, str], private_config: str, legacy_trial_preview: bool = False) -> list[str]:
    required = ("PUBLIC_API_BASE_URL",) if legacy_trial_preview else REQUIRED
    errors = [f"{key} is missing or empty" for key in required if not values.get(key, "").strip()]
    has_trial_key = bool(values.get("TRIAL_ACCESS_KEY", "").strip())
    private_has_trial_key = bool(re.search(r"\btrialAccessKey\s*:", private_config))
    if legacy_trial_preview and not (has_trial_key and private_has_trial_key):
        errors.append("legacy trial preview requires a server and local trial credential")
    if legacy_trial_preview and not re.search(r"\bauthMode\s*:\s*(['\"])trial\1", private_config):
        errors.append('legacy trial preview requires private config authMode "trial"')
    if legacy_trial_preview and has_trial_key and private_has_trial_key:
        match = re.search(r"\btrialAccessKey\s*:\s*(['\"])(.*?)\1", private_config)
        if not match or match.group(2) != values.get("TRIAL_ACCESS_KEY", "").strip():
            errors.append("server and local trial credentials do not match")
    if legacy_trial_preview and values.get("LEGACY_TRIAL_AUTH_ENABLED", "").lower() not in {"1", "true", "yes"}:
        errors.append("LEGACY_TRIAL_AUTH_ENABLED must be explicitly true for preview mode")
    if not legacy_trial_preview and re.search(r"\btrialAccessKey\b", private_config):
        errors.append("miniprogram/config.private.js must not contain the legacy trialAccessKey")
    for key in required:
        value = values.get(key, "").strip()
        if value and any(marker in value.lower() for marker in PLACEHOLDERS):
            errors.append(f"{key} still contains a placeholder")

    token_secret = values.get("AUTH_TOKEN_SECRET", "") if not legacy_trial_preview else ""
    if token_secret and len(token_secret) < 32:
        errors.append("AUTH_TOKEN_SECRET must be at least 32 characters")

    public_url = values.get("PUBLIC_API_BASE_URL", "").strip()
    if public_url:
        parsed = urlsplit(public_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
            errors.append("PUBLIC_API_BASE_URL must be an HTTPS origin without a path")
        elif parsed.hostname.endswith(".trycloudflare.com") and not legacy_trial_preview:
            errors.append("PUBLIC_API_BASE_URL must use a stable hostname, not a temporary trycloudflare URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            errors.append("PUBLIC_API_BASE_URL must not contain credentials, query, or fragment")

        match = re.search(r"\bapiBaseUrl\s*:\s*(['\"])(.*?)\1", private_config)
        if not match:
            errors.append("miniprogram/config.private.js must define apiBaseUrl")
        elif match.group(2).rstrip("/") != public_url.rstrip("/"):
            errors.append("miniprogram/config.private.js apiBaseUrl does not match PUBLIC_API_BASE_URL")

    webhook_url = values.get("HEALTH_ALERT_WEBHOOK_URL", "").strip()
    if webhook_url:
        parsed_webhook = urlsplit(webhook_url)
        if parsed_webhook.scheme != "https" or not parsed_webhook.hostname:
            errors.append("HEALTH_ALERT_WEBHOOK_URL must be an HTTPS URL")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument(
        "--private-config", type=Path, default=REPO_ROOT / "miniprogram" / "config.private.js"
    )
    parser.add_argument(
        "--legacy-trial-preview", action="store_true",
        help="allow prior shared trial auth for a temporary experience preview; this is not owner-only authentication",
    )
    args = parser.parse_args()

    if not args.env_file.is_file():
        print("Preflight failed: env file is missing")
        return 1
    if not args.private_config.is_file():
        print("Preflight failed: miniprogram private config is missing")
        return 1
    errors = validate(
        read_env_file(args.env_file),
        args.private_config.read_text(encoding="utf-8"),
        legacy_trial_preview=args.legacy_trial_preview,
    )
    if errors:
        print("Public deployment preflight failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    if args.legacy_trial_preview:
        print("Preview preflight passed; shared trial credentials are enabled and are not owner-only authentication.")
    else:
        print("Public deployment preflight passed; required values are present and URLs match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
