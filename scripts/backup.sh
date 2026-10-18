#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="${1:-./backups/server-$stamp}"
mkdir -p "$destination"

cleanup() {
  docker compose start redis chroma worker >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker compose stop worker
docker compose exec -T postgres pg_dump -U travel_agent -d travel_agent -Fc > "$destination/postgres.dump"
docker compose exec -T redis redis-cli SAVE >/dev/null
docker compose stop redis chroma
tar -czf "$destination/state-files.tar.gz" runtime/chroma runtime/redis
cp compose.yaml "$destination/compose.yaml"
sha256sum "$destination/postgres.dump" "$destination/state-files.tar.gz" > "$destination/SHA256SUMS"

cleanup
trap - EXIT INT TERM
echo "Backup created at $destination (copy it to another machine)."

