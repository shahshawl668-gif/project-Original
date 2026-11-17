#!/usr/bin/env bash
# Start Peopleopslab on this computer. Nothing leaves the machine.
# The first run downloads the base images and builds; later runs need no internet.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker/docker-compose.yml up -d --build
echo
echo "Peopleopslab is starting. Open http://localhost:3000 in a minute."
echo "Stop it with offline/stop.sh. Your data stays on this computer."
