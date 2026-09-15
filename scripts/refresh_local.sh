#!/bin/bash
# Unattended refresh runner: in-process, NO server dependency.
# Why not refresh_job.sh: that curls localhost:8000, so a down server means
# a silently stale DB (seen live 2026-09-15). This calls
# run_refresh_with_data directly — same function the API endpoint uses.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export REPO_ROOT
mkdir -p "$REPO_ROOT/logs"
LOG="$REPO_ROOT/logs/refresh-local.out.log"

: "${SLEEPER_LEAGUE_ID:?SLEEPER_LEAGUE_ID must be set (plist provides it)}"

# Pre-refresh backup (WAL-safe): keep last 7, same policy as refresh_job.sh.
if [ -f "$REPO_ROOT/data/fantasy.db" ] && command -v sqlite3 >/dev/null 2>&1; then
    BAK="$REPO_ROOT/data/fantasy.db.bak-$(date +%F)"
    sqlite3 "$REPO_ROOT/data/fantasy.db" ".backup '$BAK'" 2>/dev/null && \
        ls -t "$REPO_ROOT"/data/fantasy.db.bak-* 2>/dev/null | tail -n +8 | xargs rm -f -- 2>/dev/null || true
fi

# mkdir is atomic: doubles as the overlap lock (launchd + manual runs).
# Exit 0 on "already in progress" — a skip is not a failure.
LOCKDIR="/tmp/ffanalytics-refresh-local.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refresh skipped — already in progress" >>"$LOG"
    exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

"$REPO_ROOT/.venv/bin/python" - "$REPO_ROOT" >>"$LOG" 2>&1 <<'PYEOF'
import datetime
import sqlite3
import sys

sys.path.insert(0, sys.argv[1] + "/src")
from ffanalytics import config, db
from ffanalytics.refresh import run_refresh_with_data

lid = config.require_league_id(None)
conn = db.get_connection(config.db_path_for_league(lid))
db.init_schema(conn)
status, data = run_refresh_with_data(
    conn,
    season=config.get_current_nfl_season(),
    stats_season=config.get_stats_season(),
    ran_at_iso=datetime.datetime.now().isoformat(),
    league_id=lid,
)
conn.commit()
n_projs = len(data.get("model_projections") or [])
n_cmp = len(data.get("comparison") or [])
print(f"status={status} projections={n_projs} comparison={n_cmp}", flush=True)
bad = [k for k, v in status.items() if not v]
if bad:
    raise SystemExit(f"REFRESH PARTIAL, failed sources: {bad}")
PYEOF
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refresh ok" >>"$LOG"
