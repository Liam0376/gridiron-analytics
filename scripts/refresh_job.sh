#!/bin/bash
# Called by launchd daily during the NFL season. Hits the local API's
# /refresh endpoint — assumes `uvicorn ffanalytics.api:app` is already
# running (see docs/RUNBOOK.md for the manual-fallback command if it isn't).
# Audit C3: flock prevents overlapping runs (launchd + hub/start.sh + manual)
set -euo pipefail
LOCK="/tmp/ffanalytics-refresh.lock"
if command -v flock >/dev/null 2>&1; then
    exec flock -n "$LOCK" -c 'curl -sf -X POST http://localhost:8000/refresh' || {
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refresh skipped — already in progress (flock)" >&2
        exit 0
    }
else
    # macOS without util-linux flock: use shlock via python filelock fallback
    if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refresh skipped — already in progress" >&2
        exit 0
    fi
    echo $$ > "$LOCK"
    trap 'rm -f "$LOCK"' EXIT
    curl -sf -X POST http://localhost:8000/refresh || {
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refresh failed — is the server running?" >&2
        exit 1
    }
fi