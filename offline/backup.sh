#!/usr/bin/env bash
# Write the whole database to a dated file in offline/backups/. Run it while the app is up.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p offline/backups
out="offline/backups/peopleopslab-$(date +%Y%m%d-%H%M%S).sql"
docker compose -f docker/docker-compose.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$out"
echo "Saved $out"
