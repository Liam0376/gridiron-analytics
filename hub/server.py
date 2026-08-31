#!/usr/bin/env python3
"""
hub/server.py — read-only DB proxy for the hub.
Isolation contract:
- Binds 127.0.0.1:8002 by default — never 0.0.0.0 (see docs/RUNBOOK.md, CLAUDE.md hard constraints)
- Opens data/fantasy.db with mode=ro (SQLite rejects writes)
- Never imports src/ffanalytics; math below is vendored read-only mirror
- No POST, no writes, no LLM calls

Run: .venv/bin/python hub/server.py
  or: python hub/server.py --db data/fantasy.db --port 8002
"""

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

# --- Vendored scoring logic (mirror of src/ffanalytics/scoring.py @ 2026-08-28 Sleeper Bahamas) ---
DEFAULT_SCORING = {
    "rec": 1.0, "rec_yd": 0.1, "rush_yd": 0.1, "pass_yd": 0.04,
    "pass_td": 5.0, "rush_td": 6.0, "rec_td": 6.0, "pass_int": -1.0,
    "pass_cmp_40p": 1.0, "rush_40p": 1.0, "rec_40p": 1.0,
    "pass_td_40p": 1.0, "rush_td_40p": 1.0, "rec_td_40p": 1.0,
    "fgm_0_19": 3.0, "fgm_20_29": 3.0, "fgm_30_39": 3.0, "fgm_40_49": 4.0, "fgm_50_59": 5.0, "fgm_60p": 6.0,
    "fgmiss": -1.0, "fgmiss_0_19": -1.0, "fgmiss_20_29": -1.0,
    "xpm": 1.0, "xpmiss": -1.0,
    "fum_lost": -2.0, "fum_rec": 2.0, "fum_rec_td": 6.0, "ff": 1.0,
    "pass_2pt": 2.0, "rush_2pt": 2.0, "rec_2pt": 2.0,
}
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
FLEX_SCARCITY_MULTIPLIER = 1.05

def count_flex_slots(roster_positions):
    return sum(1 for p in roster_positions if p == "FLEX")

def apply_flex_adjustment(points: float, position: str, num_flex_slots: int = 2) -> float:
    if position in FLEX_ELIGIBLE and num_flex_slots >= 2:
        extra = num_flex_slots - 1
        adj = 1.0 + (FLEX_SCARCITY_MULTIPLIER - 1.0) * extra
        return points * adj
    return points

def _calc_points_from_raw(p: dict, scoring: dict) -> float:
    # Always score from raw stats using league settings — nflreadpy's fantasy_points
    # uses standard scoring (4pt pass TD), not our league (5pt pass TD + 40+ bonuses).
    # map raw keys (nflverse / stat_projector) to Sleeper scoring keys
    def g(*keys):
        for k in keys:
            v=p.get(k)
            if v is not None:
                try: return float(v)
                except: return 0.0
        return 0.0
    # if any raw stat present, score via Sleeper settings
    raw = {
        "receptions": g("receptions"),
        "receiving_yards": g("receiving_yards","rec_yd"),
        "receiving_tds": g("receiving_tds","rec_td"),
        "rushing_yards": g("rushing_yards","rush_yd"),
        "rushing_tds": g("rushing_tds","rush_td"),
        "passing_yards": g("passing_yards","pass_yd","passing_yards"),
        "passing_tds": g("passing_tds","pass_td"),
        "interceptions": g("passing_interceptions","pass_int","interceptions"),
        "fumbles_lost": g("fumbles_lost_total","fum_lost","fumbles_lost"),
        "passing_2pt": g("passing_2pt_conversions","pass_2pt"),
        "rushing_2pt": g("rushing_2pt_conversions","rush_2pt"),
        "receiving_2pt": g("receiving_2pt_conversions","rec_2pt"),
        "passing_40": g("passing_40","pass_40"),
        "rushing_40": g("rushing_40","rush_40"),
        "receiving_40": g("receiving_40","rec_40"),
        "fg_made_0_19": g("fg_made_0_19"),
        "fg_made_20_29": g("fg_made_20_29"),
        "fg_made_30_39": g("fg_made_30_39"),
        "fg_made_40_49": g("fg_made_40_49"),
        "fg_made_50_59": g("fg_made_50_59"),
        "fg_made_60_": g("fg_made_60_","fg_made_60p"),
        "fg_missed": g("fg_missed"),
        "pat_made": g("pat_made"),
        "pat_missed": g("pat_missed"),
    }
    # quick check: if all zero, try direct fantasy_points fallback again
    if all(v==0 for v in raw.values()):
        return float(p.get("fantasy_points") or p.get("pts_ppr") or 0)
    # Sleeper scoring map (subset, rest defaults to 0 via dict.get)
    stat_to_key = {
        "receptions":"rec","receiving_yards":"rec_yd","rushing_yards":"rush_yd","passing_yards":"pass_yd",
        "passing_tds":"pass_td","rushing_tds":"rush_td","receiving_tds":"rec_td","interceptions":"pass_int","fumbles_lost":"fum_lost",
        "passing_2pt":"pass_2pt","rushing_2pt":"rush_2pt","receiving_2pt":"rec_2pt",
        "passing_40":"pass_cmp_40p","rushing_40":"rush_40p","receiving_40":"rec_40p",
        "fg_made_0_19":"fgm_0_19","fg_made_20_29":"fgm_20_29","fg_made_30_39":"fgm_30_39","fg_made_40_49":"fgm_40_49","fg_made_50_59":"fgm_50_59","fg_made_60_":"fgm_60p",
        "fg_missed":"fgmiss","pat_made":"xpm","pat_missed":"xpmiss",
    }
    pts=0.0
    for sk, s_key in stat_to_key.items():
        pts+= raw.get(sk,0) * scoring.get(s_key,0)
    # 40+ TD bonuses if present as separate keys (rare)
    for k in ("passing_td_40","rushing_td_40","receiving_td_40"):
        if p.get(k):
            try: pts+= float(p.get(k)) * scoring.get(k.replace("_td_40","_td_40p").replace("passing","pass").replace("rushing","rush").replace("receiving","rec"),0)
            except: pass
    return pts

# --- Vendored conformal (minimal) ---
def qhat(residuals, alpha=0.2):
    import math
    if not residuals:
        raise ValueError("residuals empty")
    a = sorted(abs(r) for r in residuals)
    n = len(a)
    rank = math.ceil((n + 1) * (1 - alpha))
    rank = min(rank, n)
    return a[rank - 1]

# --- Vendored week calc (mirrors api.py:24) ---
def compute_nfl_week(now=None):
    if now is None:
        now = datetime.now()
    sept1 = datetime(now.year, 9, 1)
    offset = (0 - sept1.weekday()) % 7
    labor_day = sept1 + timedelta(days=offset)
    season_start = labor_day + timedelta(days=7)
    if now < season_start:
        return 0
    days = (now - season_start).days
    w = days // 7 + 1
    return max(1, min(18, w))

def get_db_path(cli_path: str | None) -> Path:
    if cli_path:
        return Path(cli_path)
    # hub/server.py -> repo root is parent of hub/
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    env = __import__("os").environ.get("FFANALYTICS_DB_PATH")
    if env:
        return Path(env)
    return repo_root / "data" / "fantasy.db"

def get_conn(db_path: Path) -> sqlite3.Connection:
    # read-only, immutable when possible; uri=True required for mode=ro
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def try_fetch_one(conn, sql, params=()):
    try:
        row = conn.execute(sql, params).fetchone()
        return row
    except Exception:
        return None

def load_json_blob(row, key="data"):
    if not row:
        return None
    raw = row[key] if isinstance(row, sqlite3.Row) else row[0]
    try:
        return json.loads(raw)
    except Exception:
        return None

SLEEPER_PLAYERS_CACHE = {}

def get_sleeper_player_name(player_id: str) -> str:
    global SLEEPER_PLAYERS_CACHE
    if not SLEEPER_PLAYERS_CACHE:
        try:
            import urllib.request
            req = urllib.request.urlopen("https://api.sleeper.app/v1/players/nfl", timeout=5)
            SLEEPER_PLAYERS_CACHE = json.loads(req.read().decode())
        except Exception:
            SLEEPER_PLAYERS_CACHE = {}
    p = SLEEPER_PLAYERS_CACHE.get(player_id, {})
    nm = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    pos = (p.get("position") or ("DEF" if player_id.isalpha() else "")).upper()
    if nm:
        return f"{nm} ({pos})" if pos else nm
    return player_id

class Handler(BaseHTTPRequestHandler):
    db_path: Path = get_db_path(None)  # overridden in main

    def log_message(self, format, *args):
        # quiet except errors
        if self.path.startswith("/hub-api"):
            print(f"[{self.log_date_time_string()}] {self.command} {self.path}")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8001")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # never allow writes
        if self.command != "GET" and self.command != "OPTIONS":
            self.send_error(405, "read-only proxy: only GET/OPTIONS")
            return

        # enforce only /hub-api/* or /health
        if path == "/health":
            self.json({"status": "ok", "proxy": "hub read-only", "db": str(self.db_path)})
            return

        if not path.startswith("/hub-api/"):
            self.send_error(404, "only /hub-api/* and /health")
            return

        try:
            conn = get_conn(self.db_path)
        except Exception as e:
            self.json({"error": f"cannot open DB read-only: {e}", "db": str(self.db_path)}, status=503)
            return

        try:
            if path == "/hub-api/meta":
                self.handle_meta(conn, qs)
            elif path == "/hub-api/projections":
                self.handle_projections(conn, qs)
            elif path == "/hub-api/matchups":
                self.handle_matchups(conn, qs)
            elif path == "/hub-api/roster":
                self.handle_roster(conn, qs)
            elif path == "/hub-api/news":
                self.handle_news(conn)
            elif path == "/hub-api/refresh-log":
                self.handle_refresh_log(conn)
            elif path == "/hub-api/team-ratings":
                self.handle_ratings(conn)
            elif path == "/hub-api/waiver":
                self.handle_waiver(conn)
            elif path == "/hub-api/rosters":
                self.handle_rosters_raw(conn)
            elif path == "/hub-api/comparison":
                self.handle_comparison(conn, qs)
            else:
                self.send_error(404, f"unknown hub-api path {path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.json({"error": str(e)}, status=500)
        finally:
            try: conn.close()
            except: pass

    def json(self, obj, status=200):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- handlers ---
    def handle_meta(self, conn, qs):
        week = compute_nfl_week()
        season = datetime.now().year
        # lastUpdated from successful refresh_log or news
        last = None
        row = try_fetch_one(conn, "SELECT ran_at FROM refresh_log WHERE success = 1 ORDER BY ran_at DESC LIMIT 1")
        if row: last = row["ran_at"]
        if not last:
            row = try_fetch_one(conn, "SELECT fetched_at FROM news_data ORDER BY fetched_at DESC LIMIT 1")
            if row: last = row["fetched_at"]

        # league settings
        row = try_fetch_one(conn, "SELECT data FROM league_settings ORDER BY season DESC LIMIT 1")
        data = load_json_blob(row) or {}
        scoring = data.get("scoring_settings", {})
        roster_pos = data.get("roster_positions", [])

        # counts
        counts = {}
        for tbl in ["team_ratings","sleeper_matchups","player_stats","rosters","news_data","weather"]:
            r = try_fetch_one(conn, f"SELECT COUNT(*) as c FROM {tbl}")
            counts[tbl] = r["c"] if r else 0

        # placeholder weather flag
        weather_placeholder = True
        r = try_fetch_one(conn, "SELECT lat, lon FROM weather LIMIT 1")
        if r and not (r["lat"] == 40.0 and r["lon"] == -74.0):
            weather_placeholder = False

        self.json({
            "season": data.get("season") or season,
            "week": week,
            "leagueName": data.get("name") or data.get("league_name") or "Fantasy Bahamas",
            "leagueId": data.get("league_id") or "1397736035240173568",
            "totalRosters": data.get("total_rosters", 12),
            "lastUpdated": last,
            "last_updated": last,
            "scoring_settings": scoring,
            "roster_positions": roster_pos,
            "counts": counts,
            "weather_placeholder": weather_placeholder,
            "db": str(self.db_path),
        })

    def handle_projections(self, conn, qs):
        # Load player_stats blob (latest non-empty — preseason week 0 is often "[]"; also handle invalid JSON with NaN)
        # Prefer SQL json_array_length>0 but fall back to Python scan if SQLite JSON is invalid (NaN)
        row = None
        try:
            row = try_fetch_one(conn, "SELECT data FROM player_stats WHERE json_array_length(data)>0 ORDER BY season DESC, week DESC LIMIT 1")
        except: row = None
        if not row or not load_json_blob(row):
            # Python fallback: scan recent rows for first non-empty list
            try:
                for cand in conn.execute("SELECT data FROM player_stats ORDER BY season DESC, week DESC LIMIT 10").fetchall():
                    data = load_json_blob(cand)
                    if isinstance(data, list) and len(data) > 10:
                        row = cand
                        break
            except: pass
        if not row:
            row = try_fetch_one(conn, "SELECT data FROM player_stats ORDER BY season DESC, week DESC LIMIT 1")
        players = load_json_blob(row) or []
        if not isinstance(players, list):
            players = []

        # league context for flex
        row = try_fetch_one(conn, "SELECT data FROM league_settings ORDER BY season DESC LIMIT 1")
        league = load_json_blob(row) or {}
        scoring = league.get("scoring_settings", DEFAULT_SCORING)
        roster_pos = league.get("roster_positions", ["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF","BN","BN","BN","BN","IR","IR"])
        num_flex = count_flex_slots(roster_pos)

        # injury map
        row = try_fetch_one(conn, "SELECT data FROM injury_status ORDER BY season DESC LIMIT 1")
        injuries = load_json_blob(row) or {}
        # trending set
        trending_ids = set()
        row = try_fetch_one(conn, "SELECT data FROM news_data WHERE kind='trending' ORDER BY fetched_at DESC LIMIT 1")
        trending = load_json_blob(row) or []
        for t in trending if isinstance(trending, list) else []:
            if isinstance(t, dict) and t.get("player_id"):
                trending_ids.add(str(t["player_id"]))

        # Aggregate multi-week data into per-player season averages.
        # nflreadpy stores one row per player per week — raw blob has ~19k rows.
        # Without aggregation we'd show a single arbitrary week, not projections.
        agg = {}
        for p in players:
            pid = str(p.get("player_id") or p.get("id") or "")
            if not pid:
                continue
            pts = _calc_points_from_raw(p, scoring)
            if pid not in agg:
                agg[pid] = {
                    "player_id": pid,
                    "player_name": p.get("player_display_name") or p.get("short_name") or p.get("player_name") or pid,
                    "position": (p.get("position") or p.get("position_group") or "UNK").upper(),
                    "team": p.get("recent_team") or p.get("team") or "",
                    "opponent_team": p.get("opponent_team") or "",
                    "total_pts": 0.0,
                    "games": 0,
                    "week_pts": [],
                }
            agg[pid]["total_pts"] += pts
            agg[pid]["games"] += 1
            agg[pid]["week_pts"].append(pts)
            if p.get("recent_team"):
                agg[pid]["team"] = p["recent_team"]

        def _pos_factor(pos):
            m = {"QB": 1.45, "RB": 1.07, "WR": 1.12, "TE": 0.88, "K": 0.55, "DEF": 0.75}
            return m.get(pos, 1.0)

        def _point_factor(pts):
            return min(1.60, 1.0 + max(0, pts - 12) * 0.022) if pts > 12 else 1.0

        out = []
        for pid, a in agg.items():
            if a["games"] == 0:
                continue
            avg_pts = a["total_pts"] / a["games"]
            pos = a["position"]
            pts = apply_flex_adjustment(avg_pts, pos, num_flex)
            width = 5.0 * _pos_factor(pos) * _point_factor(pts)
            width = max(3.0, min(14.0, width))
            low = pts - width
            high = pts + width
            out.append({
                "player_id": pid,
                "player_name": a["player_name"],
                "position": pos,
                "position_group": pos,
                "team": a["team"],
                "opponent_team": a["opponent_team"],
                "projected_points": round(pts, 2),
                "point_estimate": round(pts, 2),
                "projection_lower": round(low, 2),
                "projection_upper": round(high, 2),
                "lower_bound": round(low, 2),
                "upper_bound": round(high, 2),
                "width": width,
                "projection_width": width,
                "injury_status": injuries.get(pid),
                "trending": pid in trending_ids,
                "wind_mph": None,
                "weather_delta": 0,
                "games": a["games"],
            })
        out.sort(key=lambda x: x["projected_points"], reverse=True)
        out = out[:800]
        self.json({"players": out, "count": len(out), "meta": {"source": "db:player_stats:averaged", "num_flex": num_flex}})

    def handle_matchups(self, conn, qs):
        week_vals = qs.get("week", [None])[0]
        week = int(week_vals) if week_vals and week_vals.isdigit() else None
        if week is None:
            week = compute_nfl_week()
            if week == 0:
                week = None
        league_rows = []
        try:
            if week is not None:
                league_rows = conn.execute("SELECT season, week, roster_id, matchup_id, points, starters FROM sleeper_matchups WHERE week = ? ORDER BY matchup_id, roster_id", (week,)).fetchall()
            else:
                league_rows = conn.execute("SELECT season, week, roster_id, matchup_id, points, starters FROM sleeper_matchups ORDER BY week DESC, matchup_id LIMIT 50").fetchall()
        except Exception:
            league_rows = []
        league = []
        for r in league_rows:
            starters = []
            try: starters = json.loads(r["starters"]) if r["starters"] else []
            except: starters = []
            league.append({"season": r["season"], "week": r["week"], "roster_id": r["roster_id"], "matchup_id": r["matchup_id"], "points": r["points"], "starters": starters})

        # Load real NFL slate for the target week
        nfl_slate = []
        target_wk = week if (week and week > 0) else 10
        repo_root = Path(__file__).resolve().parent.parent
        sched_file = repo_root / "data" / "nfl_cache" / "schedule_2026.json"
        if not sched_file.exists():
            sched_file = repo_root / "data" / "nfl_cache" / "schedule_2025.json"
        if sched_file.exists():
            try:
                with open(sched_file) as f:
                    sched_data = json.load(f)
                games = [g for g in sched_data if g.get("week") == target_wk]
                for g in games:
                    nfl_slate.append({
                        "home_team": g.get("home_team", "—"),
                        "away_team": g.get("away_team", "—"),
                        "stadium": g.get("stadium") or "Stadium",
                        "gameday": g.get("gameday") or "",
                        "gametime": g.get("gametime") or "",
                        "wind_mph": float(g.get("wind") or 0),
                        "precip_prob": 0,
                        "spread_line": g.get("spread_line"),
                        "total_line": g.get("total_line"),
                        "placeholder": False,
                    })
            except Exception as e:
                print(f"Failed to load nfl_slate: {e}")

        self.json({"leagueMatchups": league, "nflSlate": nfl_slate, "week": target_wk})

    def handle_roster(self, conn, qs):
        # Build starters/bench from rosters + player_stats
        row = try_fetch_one(conn, "SELECT data FROM rosters ORDER BY rowid DESC LIMIT 1")
        rosters = load_json_blob(row) or []
        row = None
        try:
            row = try_fetch_one(conn, "SELECT data FROM player_stats WHERE json_array_length(data)>0 ORDER BY rowid DESC LIMIT 1")
        except: row = None
        if not row or not load_json_blob(row):
            try:
                for cand in conn.execute("SELECT data FROM player_stats ORDER BY rowid DESC LIMIT 10").fetchall():
                    data = load_json_blob(cand)
                    if isinstance(data, list) and len(data) > 10:
                        row = cand
                        break
            except: pass
        if not row:
            row = try_fetch_one(conn, "SELECT data FROM player_stats ORDER BY rowid DESC LIMIT 1")
        players = load_json_blob(row) or []
        row = try_fetch_one(conn, "SELECT data FROM injury_status ORDER BY rowid DESC LIMIT 1")
        injuries = load_json_blob(row) or {}

        # Pre-load Sleeper player metadata dictionary if available
        global SLEEPER_PLAYERS_CACHE
        if not SLEEPER_PLAYERS_CACHE:
            try:
                import urllib.request
                req = urllib.request.urlopen("https://api.sleeper.app/v1/players/nfl", timeout=5)
                SLEEPER_PLAYERS_CACHE = json.loads(req.read().decode())
            except Exception:
                SLEEPER_PLAYERS_CACHE = {}

        # map player_id / gsis_id -> stats
        pmap = {}
        for p in (players if isinstance(players, list) else []):
            if isinstance(p, dict):
                pid = str(p.get("player_id") or p.get("id") or "")
                if pid: pmap[pid] = p

        starters, bench = [], []
        if rosters and isinstance(rosters, list):
            # Sleeper rosters: first team with players is active team
            first = None
            for r in rosters:
                if isinstance(r, dict) and r.get("players") and len(r.get("players", [])) > 0:
                    first = r
                    break
            if not first and rosters:
                first = rosters[0]

            if first and isinstance(first, dict):
                ids = first.get("players") or []
                raw_starters = set(first.get("starters") or [])
                for idx, pid in enumerate(ids):
                    sp = SLEEPER_PLAYERS_CACHE.get(str(pid), {})
                    p_name = sp.get("full_name") or f"{sp.get('first_name','')} {sp.get('last_name','')}".strip() or str(pid)
                    pos = (sp.get("position") or ("DEF" if str(pid).isalpha() else "UNK")).upper()
                    team = (sp.get("team") or "").upper()
                    gsis = sp.get("gsis_id")

                    st = pmap.get(str(gsis) if gsis else str(pid)) or {}
                    pts = float(st.get("projected_points") or st.get("fantasy_points") or 0)

                    item = {
                        "player_id": str(pid),
                        "player_name": p_name,
                        "position": pos,
                        "team": team,
                        "projected_points": round(pts, 2),
                        "projection_lower": round(pts - 2.5, 2),
                        "projection_upper": round(pts + 2.5, 2),
                        "width": 5.0,
                        "injury_status": injuries.get(str(pid)) or sp.get("injury_status"),
                        "opponent_team": st.get("opponent_team") or "",
                        "slot": f"SLOT {idx+1}" if str(pid) in raw_starters else "BENCH",
                    }
                    if idx < 10 or str(pid) in raw_starters:
                        starters.append(item)
                    else:
                        bench.append(item)

        self.json({"starters": starters, "bench": bench, "myRoster": starters, "meta": {"rosters": len(rosters), "players": len(players)}})

    def handle_news(self, conn):
        trending = []
        injuries = []
        row = try_fetch_one(conn, "SELECT data FROM news_data WHERE kind='trending' ORDER BY fetched_at DESC LIMIT 1")
        trending = load_json_blob(row) or []
        row = try_fetch_one(conn, "SELECT data FROM news_data WHERE kind='injuries' ORDER BY fetched_at DESC LIMIT 1")
        injuries = load_json_blob(row) or []
        row = try_fetch_one(conn, "SELECT data FROM news_data WHERE kind='fantasypros_news' ORDER BY fetched_at DESC LIMIT 1")
        fp_news = load_json_blob(row) or []

        # Map player_id -> player_name using player_stats in DB
        pmap = {}
        try:
            r = try_fetch_one(conn, "SELECT data FROM player_stats ORDER BY season DESC, week DESC LIMIT 1")
            p_data = load_json_blob(r) or []
            for p in p_data if isinstance(p_data, list) else []:
                pid = str(p.get("player_id") or p.get("id") or "")
                nm = p.get("player_display_name") or p.get("short_name")
                pos = (p.get("position") or "").upper()
                if pid and nm:
                    pmap[pid] = f"{nm} ({pos})" if pos else nm
        except Exception:
            pass

        enriched_trending = []
        for t in trending if isinstance(trending, list) else []:
            if isinstance(t, dict):
                pid = str(t.get("player_id") or "")
                t_name = t.get("player_name") or pmap.get(pid)
                if not t_name or t_name == pid or t_name.isdigit():
                    t_name = get_sleeper_player_name(pid)
                enriched_trending.append({**t, "player_name": t_name})
            else:
                enriched_trending.append(t)

        self.json({
            "trending_adds": enriched_trending,
            "detailed_injuries": injuries if isinstance(injuries, list) else [],
            "fantasypros_news": fp_news if isinstance(fp_news, list) else [],
        })

    def handle_refresh_log(self, conn):
        rows = []
        try:
            rows = conn.execute("SELECT source, ran_at, success, error_message FROM refresh_log ORDER BY ran_at DESC LIMIT 20").fetchall()
        except: pass
        self.json({"entries": [dict(r) for r in rows]})

    def handle_ratings(self, conn):
        rows = []
        try:
            rows = conn.execute("SELECT team, position_group, rating, rating_deviation, last_updated_week, season FROM team_ratings ORDER BY team, position_group LIMIT 100").fetchall()
        except: pass
        self.json({"ratings": [dict(r) for r in rows]})

    def handle_rosters_raw(self, conn):
        row = try_fetch_one(conn, "SELECT data FROM rosters ORDER BY season DESC, week DESC LIMIT 1")
        data = load_json_blob(row) or []
        self.json({"rosters": data})

    def handle_comparison(self, conn, qs):
        # Model vs Market (Sleeper pts+stats vs FantasyPros ECR/ADP) — built by refresh.py
        row = None
        fetched_at = None
        try:
            row = try_fetch_one(conn, "SELECT data, fetched_at FROM market_consensus ORDER BY fetched_at DESC LIMIT 1")
        except Exception:
            row = None
        players = []
        if row:
            players = load_json_blob(row, key="data") or []
            fetched_at = row["fetched_at"] if "fetched_at" in row.keys() else None
        # fallback: if empty, report meta so UI can degrade gracefully
        if not isinstance(players, list):
            players = []
        # optional edge filter ?edge=BUY
        edge_filter = (qs.get("edge", [None])[0] or "").upper()
        if edge_filter in ("BUY", "SELL", "NEUTRAL"):
            players = [p for p in players if (p.get("edge") or "").upper() == edge_filter]
        # cap
        limit = 300
        try:
            if qs.get("limit", [None])[0]:
                limit = max(10, min(800, int(qs.get("limit")[0])))
        except Exception:
            pass
        self.json({"players": players[:limit], "count": len(players), "fetched_at": fetched_at, "meta": {"source": "market_consensus", "preseason_note": "Market pts empty until Week 1 publish; rank comparison (ECR/ADP) works now."}})

    def handle_waiver(self, conn):
        # reuse projections but filter to free agents (not rostered)
        row = try_fetch_one(conn, "SELECT data FROM rosters ORDER BY rowid DESC LIMIT 1")
        rosters = load_json_blob(row) or []
        rostered = set()
        for r in rosters if isinstance(rosters, list) else []:
            for pid in (r.get("players") or []):
                rostered.add(str(pid))
        row = None
        try:
            row = try_fetch_one(conn, "SELECT data FROM player_stats WHERE json_array_length(data)>0 ORDER BY season DESC, week DESC LIMIT 1")
        except: row = None
        if not row or not load_json_blob(row):
            try:
                for cand in conn.execute("SELECT data FROM player_stats ORDER BY season DESC, week DESC LIMIT 10").fetchall():
                    data = load_json_blob(cand)
                    if isinstance(data, list) and len(data) > 10:
                        row = cand
                        break
            except: pass
        if not row:
            row = try_fetch_one(conn, "SELECT data FROM player_stats ORDER BY season DESC, week DESC LIMIT 1")
        players = load_json_blob(row) or []
        recs = []
        for p in players:
            pid = str(p.get("player_id") or p.get("id") or "")
            if pid in rostered:
                continue
            pts = float(p.get("fantasy_points") or 0)
            if pts < 5:  # threshold to avoid noise
                continue
            recs.append({"player_id": pid, "player_name": p.get("short_name") or pid, "position": (p.get("position") or "UNK").upper(), "projected_points": round(pts,2), "improvement_over_roster": round(pts*0.8,2), "waiver_priority": 0, "replaces_player_name": None})
        recs.sort(key=lambda x: x["improvement_over_roster"], reverse=True)
        for i, r in enumerate(recs[:50]): r["waiver_priority"] = i+1
        self.json({"recommendations": recs[:50], "meta": {"source": "db:free_agents"}})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="bind host (127.0.0.1 only)")
    ap.add_argument("--port", type=int, default=8002, help="bind port")
    ap.add_argument("--db", default=None, help="path to fantasy.db")
    args = ap.parse_args()

    db_path = get_db_path(args.db)
    Handler.db_path = db_path
    print(f"hub read-only proxy → {db_path} (mode=ro)")
    print(f"listening on http://{args.host}:{args.port}  (127.0.0.1 only)")
    print("endpoints: /health, /hub-api/meta, /hub-api/projections, /hub-api/matchups, /hub-api/roster, /hub-api/news, /hub-api/refresh-log, /hub-api/team-ratings, /hub-api/comparison")
    print("zero writes, zero tokens, read-only")

    httpd = HTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")

if __name__ == "__main__":
    main()
