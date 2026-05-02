#!/usr/bin/env bash
# Production-ready entrypoint. Designed for Render, Railway, Fly.io, etc.
set -euo pipefail

PORT="${PORT:-8000}"

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --proxy-headers \
    --forwarded-allow-ips='*'
