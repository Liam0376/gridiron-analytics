#!/bin/bash
# Called by launchd daily during the NFL season. Hits the local API's
# /refresh endpoint — assumes `uvicorn ffanalytics.api:app` is already
# running (see docs/RUNBOOK.md for the manual-fallback command if it isn't).
set -euo pipefail
curl -sf -X POST http://localhost:8000/refresh || {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refresh failed — is the server running?" >&2
    exit 1
}