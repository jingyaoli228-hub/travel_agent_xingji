"""Idempotently import local JSON/JSONL memory into PostgreSQL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from travel_agent.persistence import database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", default="./data/user_profiles.json")
    parser.add_argument("--episodes", default="./data/episodic_memory.jsonl")
    args = parser.parse_args()
    if not database.enabled():
        raise SystemExit("DATABASE_URL must point to PostgreSQL")
    database.init_schema()

    profiles = json.loads(Path(args.profiles).read_text(encoding="utf-8-sig"))
    for user_id, profile in profiles.items():
        database.save_profile(user_id, profile)

    imported = 0
    with Path(args.episodes).open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                episode = json.loads(line)
            except ValueError as exc:
                raise SystemExit(f"invalid JSONL at line {line_number}: {exc}") from exc
            database.append_episode(episode)
            imported += 1
    print(f"profiles processed={len(profiles)}, episodes processed={imported}")


if __name__ == "__main__":
    main()
