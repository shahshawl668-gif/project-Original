#!/usr/bin/env bash
# Stop Peopleopslab. The data is kept; start.sh brings it back.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker/docker-compose.yml down
