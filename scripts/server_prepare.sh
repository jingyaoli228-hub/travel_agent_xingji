#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
mkdir -p runtime/postgres runtime/redis runtime/chroma runtime/caddy-data runtime/caddy-config runtime/migrations backups
# Official containers use these UIDs. These paths are dedicated to this app.
sudo chown -R 70:70 runtime/postgres
sudo chown -R 999:999 runtime/redis
sudo chown -R 1000:1000 runtime/chroma runtime/caddy-data runtime/caddy-config
sudo chown -R 10001:10001 runtime/migrations
echo "Runtime directories prepared."
