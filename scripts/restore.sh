#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
source_dir="${1:-}"
if [ -z "$source_dir" ] || [ ! -f "$source_dir/postgres.dump" ] || [ ! -f "$source_dir/state-files.tar.gz" ]; then
  echo "Usage: CONFIRM_RESTORE=YES sh scripts/restore.sh /path/to/backup" >&2
  exit 2
fi
if [ "${CONFIRM_RESTORE:-}" != "YES" ]; then
  echo "Restore is destructive. Re-run with CONFIRM_RESTORE=YES." >&2
  exit 2
fi
if [ -d runtime/chroma ] && [ "$(find runtime/chroma -mindepth 1 -print -quit)" ]; then
  echo "runtime/chroma is not empty; move it aside before restore." >&2
  exit 2
fi
if [ -d runtime/redis ] && [ "$(find runtime/redis -mindepth 1 -print -quit)" ]; then
  echo "runtime/redis is not empty; move it aside before restore." >&2
  exit 2
fi

(cd "$source_dir" && sha256sum -c SHA256SUMS)
docker compose down
tar -xzf "$source_dir/state-files.tar.gz"
docker compose up -d postgres redis chroma
until docker compose exec -T postgres pg_isready -U travel_agent -d travel_agent >/dev/null 2>&1; do sleep 2; done
docker compose exec -T postgres pg_restore -U travel_agent -d travel_agent --clean --if-exists < "$source_dir/postgres.dump"
docker compose up -d
echo "Restore completed; verify /health/ready and a known session before accepting traffic."

