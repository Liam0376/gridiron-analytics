#!/usr/bin/env python3
"""Seed demo 2024 week 10 projections into fantasy.db so hub shows 300+ players even in preseason week 0. Run automatically by hub/start.sh when player_stats is empty."""
import json, pathlib, sys
# robust to cwd: use repo root absolute
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
import os
os.environ.setdefault("SLEEPER_LEAGUE_ID","1397736035240173568")
os.environ.setdefault("FFANALYTICS_DB_PATH", str(REPO_ROOT / "data" / "fantasy.db"))
from ffanalytics import db
from ffanalytics.stat_projector import build_weekly_projections
import requests
REPO_CACHE = REPO_ROOT / "data" / "nfl_cache"
SCRATCH_CACHE = pathlib.Path("/private/tmp/claude-501/-Users-liam/88d4447f-857f-4e47-88fe-c423d3893260/scratchpad/nfl_cache")
CACHE = REPO_CACHE
for p in [REPO_CACHE, SCRATCH_CACHE]:
    if (p / "stats_2025.json").exists() or (p / "stats_2024.json").exists():
        CACHE = p
        break
stats_path = CACHE/"stats_2025.json" if (CACHE/"stats_2025.json").exists() else CACHE/"stats_2024.json"
schedule_path = CACHE/"schedule_2025.json" if (CACHE/"schedule_2025.json").exists() else CACHE/"schedule_2024.json"
stats_2025=json.loads(stats_path.read_text())
# prefer live 2026 schedule via nflreadpy (PIT@CIN etc.), fallback to 2025 cache
try:
    import nflreadpy
    sched_frame=nflreadpy.load_schedules(seasons=[2026])
    schedule_2026=sched_frame.to_dicts()
    # cache it for next time
    try:
        (REPO_CACHE/"schedule_2026.json").parent.mkdir(parents=True, exist_ok=True)
        import json as _js
        with open(REPO_CACHE/"schedule_2026.json","w") as f: _js.dump(schedule_2026,f)
    except: pass
    schedule=schedule_2026
    print(f"using live 2026 schedule ({len(schedule)} games) + {stats_path.name}")
except Exception as e:
    print(f"live 2026 schedule fetch failed ({e}) — fallback to {schedule_path.name}")
    schedule=json.loads(schedule_path.read_text())
    stats_2025=stats_2025  # keep as stats_2025 for naming
scoring=requests.get("https://api.sleeper.app/v1/league/1397736035240173568",timeout=10).json().get("scoring_settings",{})
# build weekly projections for week 10 — use 2025 stats as history (most recent complete season)
from collections import Counter
game_counts = Counter(r.get("player_id") for r in stats_2025 if r.get("season_type") == "REG")
filtered_stats_2025 = [r for r in stats_2025 if game_counts.get(r.get("player_id"), 0) >= 4]
projs=build_weekly_projections(filtered_stats_2025, schedule, target_week=10, scoring_settings=scoring)
# Sleeper team override for 2026 offseason moves (Rodgers NYJ→PIT etc. — 24% stale if not patched)
try:
    sleeper=requests.get("https://api.sleeper.app/v1/players/nfl", timeout=30).json()
    name_to_team={p["full_name"]: p["team"] for p in sleeper.values() if p.get("full_name") and p.get("team")}
    from ffanalytics.adapters.schedule import get_nfl_team_matchups
    opp_map=get_nfl_team_matchups(schedule, 10)
    patched=0
    for p in projs:
        nm=p.get("player_display_name")
        if nm in name_to_team and name_to_team[nm]:
            new_team=name_to_team[nm]
            if p.get("team")!=new_team:
                patched+=1
            p["team"]=p["recent_team"]=new_team
            p["opponent_team"]=opp_map.get(new_team,"")
    print(f"Sleeper patch: {patched} teams corrected for 2026 (e.g., Rodgers → {name_to_team.get('Aaron Rodgers')})")
except Exception as e:
    print(f"Sleeper patch skipped ({e})")
    projs=projs  # keep original
# sanitize NaN/Inf for SQLite JSON (json.dumps would emit NaN which is invalid JSON for json_array_length)
import math
for p in projs:
    for k,v in list(p.items()):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            p[k]=0
        # also handle nested? projs are flat per player
conn=db.get_connection()
db.init_schema(conn)
# clean empty/invalid rows that block latest non-empty logic
try:
    # delete obvious empties
    conn.execute("DELETE FROM player_stats WHERE data='[]' OR data='null' OR length(data)<10")
    # also delete any with invalid JSON (where json_array_length is null but length>2)
    # fallback: Python scan deletes invalid
    for r in list(conn.execute("SELECT rowid, data FROM player_stats")):
        try:
            d=json.loads(r["data"])
            if not isinstance(d, list) or len(d)<10:
                if len(d)==0:
                    conn.execute("DELETE FROM player_stats WHERE rowid=?", (r["rowid"],))
        except:
            conn.execute("DELETE FROM player_stats WHERE rowid=?", (r["rowid"],))
except: pass
# remove prior demo for same week so latest is the patched 2025→2026 one (not stale 2024)
try:
    conn.execute("DELETE FROM player_stats WHERE season=2026 AND week=10")
except: pass
# insert as 2026 week 10 (current season)
conn.execute("INSERT INTO player_stats (season, week, data) VALUES (?, ?, ?)", (2026, 10, json.dumps(projs, allow_nan=False)))
conn.execute("INSERT OR REPLACE INTO league_settings (season, data) VALUES (?, ?)", (2026, json.dumps({"scoring_settings": scoring, "roster_positions": ["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF","BN","BN","BN","BN"]})))
import datetime
conn.execute("INSERT INTO refresh_log (source, ran_at, success, error_message) VALUES (?, ?, ?, ?)", ("demo-seed-auto", datetime.datetime.now().isoformat(), 1, None))
conn.commit()
conn.close()
print(f"seeded {len(projs)} demo projections for 2026 week 10")
