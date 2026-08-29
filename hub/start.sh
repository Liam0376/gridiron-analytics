#!/bin/bash
# hub/start.sh — one-click warm-boot launcher. Starts model+proxy+hub, ensures DATA is warm before opening browser.
# Isolation: 127.0.0.1 only, hub reads DB mode=ro, only triggers model POST /refresh (never writes DB directly), no tokens.
# Flags: --auto (auto-refresh if stale, no prompt), --no-refresh (never POST, open even if cold), --force (refresh even if fresh)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# flags
AUTO=0
NO_REFRESH=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --auto) AUTO=1 ;;
    --no-refresh) NO_REFRESH=1 ;;
    --force) FORCE=1 ;;
    -h|--help) echo "Usage: bash hub/start.sh [--auto] [--no-refresh] [--force]"; exit 0 ;;
  esac
done

export SLEEPER_LEAGUE_ID="${SLEEPER_LEAGUE_ID:-test}"

echo "→ Fantasy Hub — warm-boot start (Ctrl+C to stop, 0 resources after)"
echo "  Model: http://127.0.0.1:8000   Hub: http://127.0.0.1:8001   Proxy: http://127.0.0.1:8002  Flags: auto=$AUTO no-refresh=$NO_REFRESH force=$FORCE"
echo ""

cleanup() {
  echo ""
  echo "→ stopping…"
  jobs -p | xargs -I {} kill {} 2>/dev/null || true
  lsof -ti :8000 2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti :8001 2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti :8002 2>/dev/null | xargs kill 2>/dev/null || true
  echo "✓ stopped — 0 processes left"
  exit 0
}
trap cleanup INT TERM EXIT

# 0) If ports already in use from previous run (you double-clicked), reclaim them gracefully
for p in 8000 8001 8002; do
  if lsof -ti :$p >/dev/null 2>&1; then
    echo "  • port $p already in use — reclaiming (previous hub instance)…"
    lsof -ti :$p 2>/dev/null | xargs kill 2>/dev/null || true
    sleep 1
  fi
done

# 1) Model API
echo "→ starting model API :8000…"
if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "  ✓ model already running on :8000 — reusing"
  API_PID=""
else
  .venv/bin/uvicorn ffanalytics.api:app --host 127.0.0.1 --port 8000 --reload > /tmp/fantasy-hub-api.log 2>&1 &
  API_PID=$!
  for i in {1..30}; do
    if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then break; fi
    sleep 0.5
  done
  if ! curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "✗ model failed to start — see /tmp/fantasy-hub-api.log"
    cat /tmp/fantasy-hub-api.log | tail -20
    exit 1
  fi
  echo "  ✓ model up (pid $API_PID)"
fi

# ensure DB + schema exists (warm-boot step 1)
.venv/bin/python -c "from ffanalytics import db; c=db.get_connection(); db.init_schema(c); c.close(); print('  ✓ DB warm (fantasy.db + schema)')" 2>&1 | head -5

# 2) Hub proxy
echo "→ starting hub proxy :8002 (mode=ro)…"
if curl -sf http://127.0.0.1:8002/health >/dev/null 2>&1; then
  echo "  ✓ proxy already running on :8002 — reusing"
  PROXY_PID=""
else
  .venv/bin/python hub/server.py > /tmp/fantasy-hub-proxy.log 2>&1 &
  PROXY_PID=$!
  for i in {1..20}; do
    if curl -sf http://127.0.0.1:8002/health >/dev/null 2>&1; then break; fi
    sleep 0.3
  done
  if ! curl -sf http://127.0.0.1:8002/health >/dev/null 2>&1; then
    echo "⚠ proxy not responding — hub will work API-only (see /tmp/fantasy-hub-proxy.log)"
  else
    echo "  ✓ proxy up (pid $PROXY_PID)"
  fi
fi

# 3) Warm-boot staleness check (model warm, not just process warm)
echo "→ checking data freshness…"
META_JSON=$(curl -sf http://127.0.0.1:8002/hub-api/meta 2>/dev/null || curl -sf http://127.0.0.1:8000/health 2>/dev/null | sed 's/.*//')
# parse via python for robustness
STALENESS=$(SLEEPER_LEAGUE_ID="$SLEEPER_LEAGUE_ID" .venv/bin/python << 'PY'
import json, requests, datetime, pathlib
try:
    r=requests.get("http://127.0.0.1:8002/hub-api/meta", timeout=3).json()
    last=r.get("lastUpdated") or r.get("last_updated")
    week=r.get("week")
    season=r.get("season")
    counts=r.get("counts",{})
    stale=False
    reason=""
    if not last:
        stale=True; reason="cold — no refresh_log"
    else:
        try:
            age=(datetime.datetime.now() - datetime.datetime.fromisoformat(last)).total_seconds()/3600
            if age>24:
                stale=True; reason=f"stale {age:.1f}h ago"
        except: stale=True; reason="bad timestamp"
    # also cold if player_stats empty
    if counts.get("player_stats",0)==0:
        stale=True; reason="cold — player_stats 0"
    print(f"{'stale' if stale else 'fresh'}|{last or ''}|{reason}|{week or ''}|{season or ''}")
except Exception as e:
    print(f"unknown||{e}||")
PY
)
STALENESS_STATE=$(echo "$STALENESS" | cut -d'|' -f1)
LAST_TS=$(echo "$STALENESS" | cut -d'|' -f2)
REASON=$(echo "$STALENESS" | cut -d'|' -f3)
WEEK=$(echo "$STALENESS" | cut -d'|' -f4)
echo "  • freshness: $STALENESS_STATE ${LAST_TS:+($LAST_TS)} ${REASON:+— $REASON} ${WEEK:+week $WEEK}"

SHOULD_REFRESH=0
if [ "$FORCE" = "1" ]; then
  SHOULD_REFRESH=1
  echo "  → --force: will refresh even if fresh"
elif [ "$NO_REFRESH" = "1" ]; then
  SHOULD_REFRESH=0
  echo "  → --no-refresh: skipping refresh, opening even if $STALENESS_STATE"
elif [ "$STALENESS_STATE" = "stale" ] || [ "$STALENESS_STATE" = "unknown" ]; then
  if [ "$AUTO" = "1" ]; then
    SHOULD_REFRESH=1
    echo "  → stale — auto-refreshing ( --auto )…"
  else
    # prompt, default Y
    printf "  → data %s — refresh now? [Y/n] " "$STALENESS_STATE"
    read -r ans || ans="Y"
    case "$ans" in
      [nN]*) SHOULD_REFRESH=0; echo "  → skipping refresh per user" ;;
      *) SHOULD_REFRESH=1; echo "  → refreshing…" ;;
    esac
  fi
else
  echo "  → fresh — skipping refresh"
fi

if [ "$SHOULD_REFRESH" = "1" ]; then
  echo "  → POST http://127.0.0.1:8000/refresh (per-source isolated)…"
  # honor 1h throttle: check refresh_log
  LAST_REFRESH_AGE=$(SLEEPER_LEAGUE_ID="$SLEEPER_LEAGUE_ID" .venv/bin/python << 'PY'
import datetime, json, requests
try:
    r=requests.get("http://127.0.0.1:8002/hub-api/refresh-log", timeout=3).json()
    entries=r.get("entries",[])
    if entries:
        last=entries[0].get("ran_at")
        age=(datetime.datetime.now() - datetime.datetime.fromisoformat(last)).total_seconds()/60 if last else 999
        print(f"{age:.0f}")
    else:
        print("999")
except: print("999")
PY
)
  if [ "$LAST_REFRESH_AGE" != "999" ] && [ "$LAST_REFRESH_AGE" -lt 60 ] && [ "$FORCE" != "1" ]; then
    echo "  ⚠ last refresh ${LAST_REFRESH_AGE}m ago (<60m) — skipping to respect Sleeper players/nfl rate limit (use --force to override)"
    SHOULD_REFRESH=0
  else
    START_TS=$(date +%s)
    if curl -sf -X POST http://127.0.0.1:8000/refresh -H "Content-Type: application/json" 2>/dev/null | head -20 > /tmp/fantasy-hub-refresh.json; then
      cat /tmp/fantasy-hub-refresh.json | head -20
      ELAPSED=$(( $(date +%s) - START_TS ))
      echo "  ✓ refresh done in ${ELAPSED}s (per-source isolation — one failure doesn't abort others)"
      # verify warm: cache or DB has player_stats
      for i in {1..10}; do
        WARM=$(curl -sf http://127.0.0.1:8002/hub-api/meta 2>/dev/null | grep -o '"player_stats":[^,]*' | head -1 || echo "")
        if echo "$WARM" | grep -qv '"player_stats":0'; then break; fi
        sleep 0.5
      done
    else
      echo "  ⚠ POST /refresh failed — hub will open with stale cache (see /tmp/fantasy-hub-api.log, trap won't abort)"
    fi
  fi
fi

# 3b) Preseason auto-seed — so single click always shows a working interface (no manual curl needed)
if curl -sf http://127.0.0.1:8002/hub-api/projections 2>/dev/null | grep -q '"count": 0'; then
  echo "  → still empty (preseason week 0) — seeding demo 2024 week 10 so Projections isn't empty…"
  SLEEPER_LEAGUE_ID="$SLEEPER_LEAGUE_ID" .venv/bin/python scripts/seed_demo.py 2>&1 | sed 's/^/    /' || echo "  ⚠ demo seed failed — hub will show empty state until in-season (not fatal)"
  echo "  ✓ demo check done"
fi

# 4) Hub UI
echo "→ starting hub UI :8001…"
if curl -sf http://127.0.0.1:8001/ >/dev/null 2>&1; then
  echo "  ✓ hub already running on :8001 — reusing (port was in use, now reclaimed above if needed)"
  echo "  → opening browser to existing hub…"
  open http://127.0.0.1:8001 2>/dev/null || xdg-open http://127.0.0.1:8001 2>/dev/null || true
  echo "  → hub ready at http://127.0.0.1:8001 — close this Terminal or Ctrl+C to stop all"
  # keep alive so trap still works, but don't start second vite
  wait
else
  if [ ! -d "hub/node_modules" ]; then
    echo "  installing hub deps (once)…"
    npm install --prefix hub --silent
  fi
  ( sleep 1.2 && open http://127.0.0.1:8001 2>/dev/null || xdg-open http://127.0.0.1:8001 2>/dev/null || true ) &
  echo "  → hub ready — browser should have opened. Press Ctrl+C to stop (0 resources after)."
  npm --prefix hub run dev
fi
