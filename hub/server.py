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
import logging
import os
import sqlite3
import threading
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

# Audit: thread safety for global caches (if moved to ThreadingHTTPServer)
_CACHE_LOCK = threading.Lock()
# Single-flight locks for Sleeper refresh — never hold _CACHE_LOCK across network I/O.
_SLEEPER_FETCH_LOCK = threading.Lock()
_SLEEPER_USERS_FETCH_LOCK = threading.Lock()
_SLEEPER_PLAYERS_TTL = 24 * 3600
_SLEEPER_PLAYERS_AT = 0.0
_SLEEPER_USERS_TTL = 3600
_SLEEPER_USERS_AT = 0.0
# rosters-full: one build_league_analytics pass cached 60s + Last-Modified
_ROSTERS_FULL_TTL = 60
_ROSTERS_FULL_CACHE = {"at": 0.0, "payload": None, "last_modified": ""}
# projections + comparison mirror rosters-full: 60s server TTL + Last-Modified/304
_PROJECTIONS_TTL = 60
_PROJECTIONS_CACHE = {"at": 0.0, "payload": None, "last_modified": ""}
_COMPARISON_TTL = 60
_COMPARISON_CACHE = {"at": 0.0, "payload": None, "last_modified": ""}

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
    # Audit: guard NaN/inf from CSV (float('nan') truthy but should be 0)
    def g(*keys):
        for k in keys:
            v=p.get(k)
            if v is not None:
                try:
                    fv=float(v)
                    if fv!=fv or fv==float("inf") or fv==float("-inf"):
                        continue
                    return fv
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
        raw_v=raw.get(sk,0)
        # Guard NaN raw (audit edge-case 13)
        try:
            if isinstance(raw_v,float) and (raw_v!=raw_v or raw_v==float("inf") or raw_v==float("-inf")):
                raw_v=0
        except Exception:
            raw_v=0
        mult=scoring.get(s_key,0)
        try:
            if isinstance(mult,float) and (mult!=mult or mult==float("inf") or mult==float("-inf")):
                mult=0
        except Exception:
            mult=0
        pts+= raw_v * float(mult)
    # 40+ TD bonuses if present as separate keys (rare)
    for k in ("passing_td_40","rushing_td_40","receiving_td_40"):
        if p.get(k):
            try:
                fv=float(p.get(k))
                if fv!=fv or fv==float("inf") or fv==float("-inf"):
                    continue
                pts+= fv * scoring.get(k.replace("_td_40","_td_40p").replace("passing","pass").replace("rushing","rush").replace("receiving","rec"),0)
            except: pass
    if pts!=pts or pts==float("inf") or pts==float("-inf"):
        return 0.0
    return pts

# --- Vendored conformal (minimal) ---
def qhat(residuals, alpha=0.2):
    import math
    # Audit: fallback to WR residuals if empty (mirrors stat_projector POS_RESIDUALS default)
    if not residuals:
        residuals=[0.7,1.8,3.0,4.4,5.8,7.2,8.8,10.2,11.9]
    # Filter NaN/inf
    clean=[]
    for r in residuals:
        try:
            fv=float(r)
            if fv!=fv or fv==float("inf") or fv==float("-inf"):
                continue
            clean.append(abs(fv))
        except Exception:
            continue
    if not clean:
        return 5.0
    a = sorted(clean)
    n = len(a)
    rank = math.ceil((n + 1) * (1 - alpha))
    rank = min(rank, n)
    return a[rank - 1]

# --- Vendored week calc (mirrors api.py:24) ---
# NOTE(divergence): src/ffanalytics/config.py::compute_nfl_week returns 0 in
# preseason, but hub keeps 1 so the UI always has a valid 1-18 week slate.
# TODO: unify preseason sentinel (0 vs 1) once hub handles week-0 empty slate gracefully.
def compute_nfl_week(now=None):
    if now is None:
        now = datetime.now()
    sept1 = datetime(now.year, 9, 1)
    offset = (0 - sept1.weekday()) % 7
    labor_day = sept1 + timedelta(days=offset)
    season_start = labor_day + timedelta(days=7)
    if now < season_start:
        return 1
    days = (now - season_start).days
    w = days // 7 + 1
    return max(1, min(18, w))

def get_db_path(cli_path: str | None) -> Path:
    # Allowlist: DB must live inside repo data/ dir.
    # Rejects "..", absolute escapes outside repo, and file: URI metachars ?#.
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    data_dir = repo_root / "data"
    try:
        data_resolved = data_dir.resolve()
    except Exception:
        data_resolved = data_dir
    raw = None
    if cli_path:
        raw = str(cli_path)
    else:
        # hub/server.py -> repo root is parent of hub/
        env = os.environ.get("FFANALYTICS_DB_PATH")
        if env:
            raw = str(env)
        else:
            return repo_root / "data" / "fantasy.db"
    if not raw:
        return repo_root / "data" / "fantasy.db"
    # file: URI query/fragment metachars would break mode=ro URI — reject.
    if "?" in raw or "#" in raw:
        raise ValueError("invalid DB path: must be inside data/")
    # Explicit parent-traversal rejection (even if it would resolve inside).
    if ".." in Path(raw).parts:
        raise ValueError("invalid DB path: must be inside data/")
    p = Path(raw)
    try:
        base = Path.cwd()
        candidate = (p if p.is_absolute() else (base / p)).resolve()
    except Exception:
        raise ValueError("invalid DB path: must be inside data/")
    try:
        candidate.relative_to(data_resolved)
    except ValueError:
        raise ValueError("invalid DB path: must be inside data/")
    return candidate

def get_conn(db_path: Path) -> sqlite3.Connection:
    # read-only, immutable when possible; uri=True required for mode=ro
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_nfl_opponent_map(target_wk: int = 1) -> dict[str, str]:
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    sched_file = repo_root / "data" / "nfl_cache" / "schedule_2026.json"
    if not sched_file.exists():
        sched_file = repo_root / "data" / "nfl_cache" / "schedule_2025.json"
    if not sched_file.exists():
        return {}
    try:
        with open(sched_file) as f:
            games = json.load(f)
        opp_map = {}
        for g in games:
            if g.get("week") == target_wk:
                home = g.get("home_team")
                away = g.get("away_team")
                if home and away:
                    opp_map[home] = away
                    opp_map[away] = home
        return opp_map
    except Exception:
        return {}

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
SLEEPER_USERS_CACHE = {}


def _fetch_sleeper_players_from_network():
    # Network I/O helper — never call with _CACHE_LOCK held.
    import urllib.request
    req = urllib.request.urlopen("https://api.sleeper.app/v1/players/nfl", timeout=5)
    return json.loads(req.read().decode())


def _fetch_sleeper_users_from_network():
    # Network I/O helper — never call with _CACHE_LOCK held.
    import urllib.request
    req = urllib.request.urlopen("https://api.sleeper.app/v1/league/1397736035240173568/users", timeout=5)
    return json.loads(req.read().decode())


def _ensure_sleeper_players_refresh_background():
    # Trigger single-flight background refresh; serve stale meanwhile.
    if _SLEEPER_FETCH_LOCK.locked():
        return

    def _bg():
        acquired = _SLEEPER_FETCH_LOCK.acquire(blocking=False)
        if not acquired:
            return
        try:
            try:
                data = _fetch_sleeper_players_from_network()
            except Exception:
                return  # serve stale on failure
            if isinstance(data, dict) and data:
                global SLEEPER_PLAYERS_CACHE, _SLEEPER_PLAYERS_AT
                with _CACHE_LOCK:
                    SLEEPER_PLAYERS_CACHE = data
                    _SLEEPER_PLAYERS_AT = time.time()
        finally:
            try:
                _SLEEPER_FETCH_LOCK.release()
            except Exception:
                pass

    t = threading.Thread(target=_bg, daemon=True)
    t.start()


def _ensure_sleeper_users_refresh_background():
    if _SLEEPER_USERS_FETCH_LOCK.locked():
        return

    def _bg():
        acquired = _SLEEPER_USERS_FETCH_LOCK.acquire(blocking=False)
        if not acquired:
            return
        try:
            try:
                users_list = _fetch_sleeper_users_from_network()
            except Exception:
                return  # serve stale on failure
            if isinstance(users_list, list) and users_list:
                fresh = {}
                for u in users_list:
                    if not isinstance(u, dict):
                        continue
                    uid = str(u.get("user_id") or "")
                    if not uid:
                        continue
                    meta = u.get("metadata") or {}
                    avatar = u.get("avatar")
                    avatar_url = f"https://sleepercdn.com/avatars/thumbs/{avatar}" if avatar else None
                    fresh[uid] = {
                        "user_id": uid,
                        "display_name": u.get("display_name") or uid,
                        "team_name": meta.get("team_name") or u.get("display_name") or f"Team {uid[:4]}",
                        "avatar": avatar,
                        "avatar_url": avatar_url,
                    }
                global SLEEPER_USERS_CACHE, _SLEEPER_USERS_AT
                with _CACHE_LOCK:
                    SLEEPER_USERS_CACHE = fresh
                    _SLEEPER_USERS_AT = time.time()
        finally:
            try:
                _SLEEPER_USERS_FETCH_LOCK.release()
            except Exception:
                pass

    t = threading.Thread(target=_bg, daemon=True)
    t.start()


def warm_sleeper_caches_async():
    # Startup-warmed cache: prefetch players/users in background so request
    # path serves cache without blocking urlopen. Safe to call multiple times.
    global _SLEEPER_PLAYERS_AT, _SLEEPER_USERS_AT
    with _CACHE_LOCK:
        players_empty = not SLEEPER_PLAYERS_CACHE
        users_empty = not SLEEPER_USERS_CACHE
    if players_empty:
        _ensure_sleeper_players_refresh_background()
    if users_empty:
        _ensure_sleeper_users_refresh_background()


def get_sleeper_players_cached() -> dict:
    # TTL + single-flight + serve-stale. Never holds _CACHE_LOCK across I/O.
    # Double-checked locking: fast check under lock, fetch without lock,
    # re-check after acquiring single-flight lock.
    global SLEEPER_PLAYERS_CACHE, _SLEEPER_PLAYERS_AT
    now = time.time()
    with _CACHE_LOCK:
        cached = SLEEPER_PLAYERS_CACHE
        at = _SLEEPER_PLAYERS_AT
        if cached and (now - at < _SLEEPER_PLAYERS_TTL):
            return cached
        stale = cached
    if stale:
        # Stale present: refresh in background, serve stale now (off request path).
        _ensure_sleeper_players_refresh_background()
        return stale
    # Cold miss: single-flight synchronous fetch (startup path only).
    acquired = _SLEEPER_FETCH_LOCK.acquire(blocking=False)
    if not acquired:
        with _CACHE_LOCK:
            return SLEEPER_PLAYERS_CACHE
    try:
        with _CACHE_LOCK:
            if SLEEPER_PLAYERS_CACHE and (time.time() - _SLEEPER_PLAYERS_AT < _SLEEPER_PLAYERS_TTL):
                return SLEEPER_PLAYERS_CACHE
        try:
            data = _fetch_sleeper_players_from_network()
        except Exception:
            with _CACHE_LOCK:
                return SLEEPER_PLAYERS_CACHE  # serve stale (possibly {}) on failure
        with _CACHE_LOCK:
            if isinstance(data, dict) and data:
                SLEEPER_PLAYERS_CACHE = data
                _SLEEPER_PLAYERS_AT = time.time()
            return SLEEPER_PLAYERS_CACHE
    finally:
        try:
            _SLEEPER_FETCH_LOCK.release()
        except Exception:
            pass


def get_sleeper_users(conn=None):
    global SLEEPER_USERS_CACHE, _SLEEPER_USERS_AT
    now = time.time()
    with _CACHE_LOCK:
        if SLEEPER_USERS_CACHE and (now - _SLEEPER_USERS_AT < _SLEEPER_USERS_TTL):
            return SLEEPER_USERS_CACHE
        stale = dict(SLEEPER_USERS_CACHE) if SLEEPER_USERS_CACHE else {}
    # Prefer DB snapshot (fast, no network, no lock held across I/O).
    if conn is not None:
        try:
            row = try_fetch_one(conn, "SELECT data FROM league_settings ORDER BY season DESC LIMIT 1")
            l_data = load_json_blob(row) or {}
            db_users = l_data.get("users") or []
            fresh = {}
            for u in db_users:
                if isinstance(u, dict):
                    uid = str(u.get("user_id", ""))
                    if uid:
                        avatar = u.get("avatar")
                        avatar_url = f"https://sleepercdn.com/avatars/thumbs/{avatar}" if avatar else None
                        fresh[uid] = {
                            "user_id": uid,
                            "display_name": u.get("display_name") or uid,
                            "team_name": u.get("team_name") or u.get("display_name") or f"Team {uid[:4]}",
                            "avatar": avatar,
                            "avatar_url": avatar_url,
                        }
            if fresh:
                with _CACHE_LOCK:
                    SLEEPER_USERS_CACHE = fresh
                    _SLEEPER_USERS_AT = time.time()
                    return SLEEPER_USERS_CACHE
        except Exception:
            pass
    if stale:
        _ensure_sleeper_users_refresh_background()
        return stale
    acquired = _SLEEPER_USERS_FETCH_LOCK.acquire(blocking=False)
    if not acquired:
        with _CACHE_LOCK:
            return SLEEPER_USERS_CACHE
    try:
        with _CACHE_LOCK:
            if SLEEPER_USERS_CACHE and (time.time() - _SLEEPER_USERS_AT < _SLEEPER_USERS_TTL):
                return SLEEPER_USERS_CACHE
        try:
            users_list = _fetch_sleeper_users_from_network()
        except Exception:
            with _CACHE_LOCK:
                return SLEEPER_USERS_CACHE  # serve stale on failure
        fresh = {}
        for u in users_list if isinstance(users_list, list) else []:
            if not isinstance(u, dict):
                continue
            uid = str(u.get("user_id") or "")
            if not uid:
                continue
            meta = u.get("metadata") or {}
            avatar = u.get("avatar")
            avatar_url = f"https://sleepercdn.com/avatars/thumbs/{avatar}" if avatar else None
            fresh[uid] = {
                "user_id": uid,
                "display_name": u.get("display_name") or uid,
                "team_name": meta.get("team_name") or u.get("display_name") or f"Team {uid[:4]}",
                "avatar": avatar,
                "avatar_url": avatar_url,
            }
        with _CACHE_LOCK:
            if fresh:
                SLEEPER_USERS_CACHE = fresh
                _SLEEPER_USERS_AT = time.time()
            return SLEEPER_USERS_CACHE
    finally:
        try:
            _SLEEPER_USERS_FETCH_LOCK.release()
        except Exception:
            pass

def get_sleeper_player_name(player_id: str) -> str:
    players = get_sleeper_players_cached()
    p = players.get(player_id, {}) if isinstance(players, dict) else {}
    if p:
        nm = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        pos = (p.get("position") or ("DEF" if player_id.isalpha() else "")).upper()
        if nm:
            return f"{nm} ({pos})" if pos else nm
        return player_id
    # Cache miss / unknown ID: return ID without blocking on network (stale served above).
    return player_id

def _build_sleeper_gsis_map(conn) -> dict:
    """gsis_id -> sleeper_id. Used by endpoints that need to enrich cached
    comparison/projection rows whose player_id is a GSIS string."""
    players = get_sleeper_players_cached()
    out = {}
    for sid, sp in (players.items() if isinstance(players, dict) else []):
        if not isinstance(sp, dict):
            continue
        g = sp.get("gsis_id")
        if g:
            out[str(g)] = str(sid)
    return out

def _normalize_team_abbrev(team: str) -> str:
    """Normalize team abbreviations to match Sleeper's format."""
    team = (team or "").upper().strip()
    # Common mappings: comparison uses short names, Sleeper uses full
    mapping = {
        "LA": "LAR",  # Rams
        "JAC": "JAX",
        "WSH": "WAS",
        "GB": "GB",
        "KC": "KC",
        "LV": "LV",
        "NE": "NE",
        "NO": "NO",
        "SF": "SF",
        "TB": "TB",
        "TEN": "TEN",
    }
    return mapping.get(team, team)

NFL_TEAM_BYES_CACHE = {}

def get_nfl_team_byes() -> dict[str, int]:
    global NFL_TEAM_BYES_CACHE
    with _CACHE_LOCK:
        if NFL_TEAM_BYES_CACHE:
            return NFL_TEAM_BYES_CACHE
    repo_root = Path(__file__).resolve().parent.parent
    for fname in ["schedule_2026.json", "schedule_2025.json"]:
        sched_file = repo_root / "data" / "nfl_cache" / fname
        if sched_file.exists():
            try:
                with open(sched_file) as f:
                    sched = json.load(f)
                from collections import defaultdict
                team_weeks = defaultdict(set)
                for g in sched:
                    w = g.get("week")
                    if w and 1 <= w <= 18:
                        if g.get("home_team"): team_weeks[g["home_team"]].add(w)
                        if g.get("away_team"): team_weeks[g["away_team"]].add(w)
                byes = {}
                for t, weeks in team_weeks.items():
                    missing = sorted(list(set(range(1, 19)) - weeks))
                    if missing:
                        byes[t] = missing[0]
                if len(byes) >= 30:
                    NFL_TEAM_BYES_CACHE = byes
                    return NFL_TEAM_BYES_CACHE
            except Exception:
                pass
    NFL_TEAM_BYES_CACHE = {
        'ATL': 11, 'NYJ': 13, 'MIA': 6, 'DAL': 14, 'SF': 8, 'LA': 11, 'BUF': 7, 'TB': 10,
        'MIN': 6, 'TEN': 9, 'LAC': 7, 'LV': 13, 'CLE': 11, 'NE': 11, 'KC': 5, 'HOU': 8,
        'CIN': 6, 'CAR': 5, 'JAX': 7, 'CHI': 10, 'WAS': 7, 'IND': 13, 'ARI': 14, 'PIT': 9,
        'NYG': 8, 'SEA': 11, 'PHI': 10, 'DET': 6, 'DEN': 10, 'NO': 8, 'BAL': 13, 'GB': 11
    }
    return NFL_TEAM_BYES_CACHE

def _norm_n(name: str) -> str:
    if not name: return ""
    import re
    n = name.lower().strip()
    n = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", n)
    n = re.sub(r"[^a-z0-9 ]", "", n)
    return re.sub(r"\s+", " ", n).strip()

def build_league_analytics(conn):
    row = try_fetch_one(conn, "SELECT data FROM rosters ORDER BY rowid DESC LIMIT 1")
    rosters = load_json_blob(row) or []
    
    row = None
    try:
        row = try_fetch_one(conn, "SELECT data FROM player_stats WHERE json_array_length(data)>0 ORDER BY rowid DESC LIMIT 1")
    except Exception:
        row = None
    if not row or not load_json_blob(row):
        try:
            for cand in conn.execute("SELECT data FROM player_stats ORDER BY rowid DESC LIMIT 10").fetchall():
                data = load_json_blob(cand)
                if isinstance(data, list) and len(data) > 10:
                    row = cand
                    break
        except Exception:
            pass
    if not row:
        row = try_fetch_one(conn, "SELECT data FROM player_stats ORDER BY rowid DESC LIMIT 1")
    players = load_json_blob(row) or []

    row = try_fetch_one(conn, "SELECT data FROM injury_status ORDER BY rowid DESC LIMIT 1")
    injuries = load_json_blob(row) or {}

    comp_row = try_fetch_one(conn, "SELECT data FROM market_consensus ORDER BY fetched_at DESC LIMIT 1")
    comp_list = load_json_blob(comp_row, key="data") or []

    comp_by_id = {}
    comp_by_name_pos = {}
    comp_by_name = {}
    for c in (comp_list if isinstance(comp_list, list) else []):
        if isinstance(c, dict):
            pid = str(c.get("player_id", ""))
            if pid:
                comp_by_id[pid] = c
            p_name = c.get("player_name") or ""
            pos = (c.get("position") or "").upper()
            norm = _norm_n(p_name)
            if norm:
                if pos:
                    comp_by_name_pos[(norm, pos)] = c
                comp_by_name[norm] = c

    # Sleeper players via startup-warmed TTL cache (never blocks on network
    # when stale data exists; never holds _CACHE_LOCK across I/O).
    _sleeper_players = get_sleeper_players_cached()

    users_map = get_sleeper_users(conn)
    byes_map = get_nfl_team_byes()
    # PERF: compute once per request — never per-player (was N file reads).
    _opponent_map = get_nfl_opponent_map(compute_nfl_week())

    draft_prices = {}
    try:
        r_rows = conn.execute("SELECT player_id, amount FROM draft_picks").fetchall()
        for r in r_rows:
            if r["player_id"] and r["amount"] is not None:
                draft_prices[str(r["player_id"])] = float(r["amount"])
    except Exception:
        pass

    pmap = {}
    for p in (players if isinstance(players, list) else []):
        if isinstance(p, dict):
            pid = str(p.get("player_id") or p.get("id") or "")
            if pid: pmap[pid] = p

    teams_data_map = {}
    team_summaries = []

    for r in (rosters if isinstance(rosters, list) else []):
        if not isinstance(r, dict): continue
        r_id = r.get("roster_id")
        o_id = str(r.get("owner_id") or "")
        u_info = users_map.get(o_id, {})
        disp_name = u_info.get("display_name") or u_info.get("team_name") or f"Team {r_id}"
        t_name = u_info.get("team_name") or u_info.get("display_name") or f"Team {r_id}"
        avatar = u_info.get("avatar")
        avatar_url = u_info.get("avatar_url")

        team_info = {
            "roster_id": r_id,
            "user_id": o_id,
            "owner_id": o_id,
            "owner_name": disp_name,
            "display_name": disp_name,
            "team_name": t_name,
            "avatar": avatar,
            "avatar_url": avatar_url,
        }

        ids = r.get("players") or []
        raw_starters = set(r.get("starters") or [])
        raw_reserve = set(r.get("reserve") or [])

        starters, bench, reserve = [], [], []
        pos_counters = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "K": 0, "DEF": 0}

        for idx, pid in enumerate(ids):
            sp = (_sleeper_players.get(str(pid), {}) if isinstance(_sleeper_players, dict) else {})
            p_name = sp.get("full_name") or f"{sp.get('first_name','')} {sp.get('last_name','')}".strip() or str(pid)
            pos = (sp.get("position") or ("DEF" if str(pid).isalpha() else "UNK")).upper()
            team = (sp.get("team") or "").upper()
            gsis = sp.get("gsis_id")

            st = pmap.get(str(gsis) if gsis else str(pid)) or {}
            comp = (
                comp_by_id.get(str(pid)) or
                (comp_by_id.get(str(gsis)) if gsis else None) or
                comp_by_name_pos.get((_norm_n(p_name), pos)) or
                comp_by_name.get(_norm_n(p_name)) or
                {}
            )

            # Universal League-Wide Projection Engine for ALL 12 Teams:
            raw_pts = float(st.get("projected_points") or st.get("fantasy_points") or 0)
            m_pts = comp.get("model_points")
            mk_s = comp.get("market_season_points")
            mk_per_game = round(float(mk_s) / 17.0, 2) if (mk_s is not None and float(mk_s) > 0) else None

            # Always prefer Gridiron model projection first:
            if m_pts is not None and float(m_pts) > 0:
                gridiron_pts = float(m_pts)
            elif raw_pts > 0:
                gridiron_pts = raw_pts
            elif mk_per_game and mk_per_game > 0:
                gridiron_pts = mk_per_game
            else:
                gridiron_pts = 0.0

            pts = gridiron_pts

            # Conformal interval logic
            width = float(comp.get("interval_width") or comp.get("width") or 5.0)
            proj_lower = round(pts - (width / 2.0), 2)
            proj_upper = round(pts + (width / 2.0), 2)

            # Full season projected stats
            m_season = comp.get("model_season_stats") or {}
            mk_season = comp.get("market_season_stats") or {}
            def _get_season_val(k, alts=()):
                val = m_season.get(k)
                if val is None: val = mk_season.get(k)
                if val is None:
                    for ak in alts:
                        if ak in m_season: val = m_season[ak]; break
                        if ak in mk_season: val = mk_season[ak]; break
                if val is None and st and k in st:
                    try: val = float(st[k]) * 17.0
                    except: pass
                if val is not None:
                    try: return round(float(val), 1)
                    except: pass
                return 0.0

            pass_yds = _get_season_val("passing_yards", ("pass_yds", "pass_yd"))
            pass_tds = _get_season_val("passing_tds", ("pass_tds", "pass_td"))
            rush_yds = _get_season_val("rushing_yards", ("rush_yds", "rush_yd"))
            rush_tds = _get_season_val("rushing_tds", ("rush_tds", "rush_td"))
            receptions = _get_season_val("receptions", ("rec",))
            rec_yds = _get_season_val("receiving_yards", ("rec_yds", "rec_yd"))
            rec_tds = _get_season_val("receiving_tds", ("rec_tds", "rec_td"))
            targets = _get_season_val("targets")
            if targets == 0.0 and receptions > 0:
                targets = round(receptions / 0.70, 1)
            r_att = _get_season_val("rushing_att")
            if r_att == 0.0 and rush_yds > 0:
                r_att = round(rush_yds / 4.2, 1)
            touches = round(r_att + receptions, 1)

            is_starter = str(pid) in raw_starters or (not raw_starters and idx < 10)
            is_ir = str(pid) in raw_reserve

            slot_label = "BENCH"
            if is_ir:
                slot_label = "IR"
            elif is_starter:
                pos_counters[pos] = pos_counters.get(pos, 0) + 1
                count = pos_counters[pos]
                if pos == "QB": slot_label = "QB"
                elif pos == "RB": slot_label = f"RB{count}" if count <= 2 else f"FLEX{count-2}"
                elif pos == "WR": slot_label = f"WR{count}" if count <= 2 else f"FLEX{count-2}"
                elif pos == "TE": slot_label = "TE" if count == 1 else f"FLEX{count-1}"
                elif pos == "K": slot_label = "K"
                elif pos == "DEF": slot_label = "DEF"
                else: slot_label = f"SLOT {idx+1}"

            item = {
                "player_id": str(pid),
                "player_name": p_name,
                "position": pos,
                "team": team,
                "projected_points": round(pts, 2),
                "projection_lower": proj_lower,
                "projection_upper": proj_upper,
                "width": round(width, 2),
                "injury_status": injuries.get(str(pid)) or sp.get("injury_status"),
                "opponent_team": _opponent_map.get(team) or st.get("opponent_team") or "",
                "slot": slot_label,
                "pass_yds": pass_yds,
                "pass_tds": pass_tds,
                "rush_yds": rush_yds,
                "rush_tds": rush_tds,
                "receptions": receptions,
                "rec_yds": rec_yds,
                "rec_tds": rec_tds,
                "touches": touches,
                "targets": targets,
                # Comparison enrichment
                "market_season_points": comp.get("market_season_points"),
                "gridiron_points": round(pts, 2),
                "model_points": comp.get("model_points") if comp.get("model_points") is not None else round(pts, 2),
                "model_season_points": comp.get("model_season_points") if comp.get("model_season_points") is not None else round(pts * 17.0, 1),
                "auction": draft_prices.get(str(pid)) if draft_prices.get(str(pid)) is not None else (comp.get("auction") or 0),
                "auction_price_paid": draft_prices.get(str(pid)),
                "marketAuction": draft_prices.get(str(pid)) if draft_prices.get(str(pid)) is not None else (comp.get("marketAuction") or 0),
                "deltaAuction": round((comp.get("model_season_points", pts * 17.0) / 20.0) - draft_prices[str(pid)], 1) if str(pid) in draft_prices else comp.get("deltaAuction"),
                "edge": comp.get("edge") or "NEUTRAL",
                "fp_ecr": comp.get("fp_ecr"),
                "fp_ecr_pos": comp.get("fp_ecr_pos"),
                "fp_adp": comp.get("fp_adp"),
                "fp_tier": comp.get("fp_tier"),
                "statsguy_rank": comp.get("statsguy_rank"),
                "statsguy_value": comp.get("statsguy_value"),
                "season_stat_deltas": comp.get("season_stat_deltas") or [],
                "market_season_stats": comp.get("market_season_stats") or {},
            }

            if is_ir:
                reserve.append(item)
            elif is_starter:
                starters.append(item)
            else:
                bench.append(item)

        all_rostered = starters + bench + reserve

        # 2. Team Analytics Calculations
        gridiron_val = round(sum(float(p.get("auction") or 0) for p in all_rostered), 2)
        market_val = round(sum(float(p.get("marketAuction") or 0) for p in all_rostered), 2)
        starter_pts = round(sum(float(p.get("projected_points") or 0) for p in starters), 2)

        def _get_p_season(p):
            if p.get("model_season_points") is not None:
                return float(p["model_season_points"])
            if p.get("market_season_points") is not None:
                return float(p["market_season_points"])
            return float(p.get("projected_points") or 0) * 17.0

        total_season_pts = round(sum(_get_p_season(p) for p in all_rostered), 2)

        # Position group scores (0-100)
        pos_benchmarks = {"QB": 35.0, "RB": 75.0, "WR": 75.0, "TE": 30.0}
        pos_scores = {}
        for pos_k in ["QB", "RB", "WR", "TE"]:
            p_list = [p for p in all_rostered if p.get("position") == pos_k]
            pos_vor = sum(float(p.get("auction") or 0) for p in p_list)
            bmark = pos_benchmarks.get(pos_k, 50.0)
            raw_score = (pos_vor / bmark) * 80.0
            depth_bonus = min(20.0, len(p_list) * 4.0)
            score = min(100.0, max(15.0, round(raw_score + depth_bonus, 1)))
            pos_scores[pos_k] = score

        weakest_pos = min(pos_scores, key=pos_scores.get)

        # Bye week matrix (1 to 18)
        bye_matrix = {w: [] for w in range(1, 19)}
        for p in all_rostered:
            tm = p.get("team")
            bw = byes_map.get(tm)
            if bw and 1 <= bw <= 18:
                bye_matrix[bw].append({
                    "player_id": p["player_id"],
                    "player_name": p["player_name"],
                    "position": p["position"],
                    "team": tm
                })

        # Start sit tossups
        tossups = []
        for b_p in bench:
            b_pos = b_p.get("position")
            b_upper = b_p.get("projection_upper", 0)
            for s_p in starters:
                s_pos = s_p.get("position")
                s_slot = s_p.get("slot", "")
                is_eligible = (b_pos == s_pos) or (b_pos in FLEX_ELIGIBLE and "FLEX" in s_slot)
                if is_eligible:
                    s_lower = s_p.get("projection_lower", 0)
                    if b_upper > s_lower:
                        tossups.append({
                            "bench_player": b_p["player_name"],
                            "bench_player_id": b_p["player_id"],
                            "bench_position": b_p["position"],
                            "bench_projection": b_p["projected_points"],
                            "bench_upper": b_upper,
                            "starter_player": s_p["player_name"],
                            "starter_player_id": s_p["player_id"],
                            "starter_position": s_p["position"],
                            "starter_slot": s_slot,
                            "starter_projection": s_p["projected_points"],
                            "starter_lower": s_lower,
                            "diff": round(b_upper - s_lower, 2),
                        })

        team_analytics = {
            "gridiron_value": gridiron_val,
            "market_value": market_val,
            "projected_weekly_starter_pts": starter_pts,
            "total_season_projected_pts": total_season_pts,
            "position_group_scores": pos_scores,
            "bye_week_matrix": bye_matrix,
            "weakest_position": weakest_pos,
            "start_sit_tossups": tossups,
        }

        team_entry = {
            "roster_id": r_id,
            "user_id": o_id,
            "owner_id": o_id,
            "owner_name": disp_name,
            "display_name": disp_name,
            "team_name": t_name,
            "avatar": avatar,
            "avatar_url": avatar_url,
            "gridiron_value": gridiron_val,
            "market_value": market_val,
            "projected_weekly_starter_pts": starter_pts,
            "total_season_projected_pts": total_season_pts,
            "position_group_scores": pos_scores,
            "weakest_position": weakest_pos,
        }
        team_summaries.append(team_entry)

        teams_data_map[str(r_id)] = {
            "starters": starters,
            "bench": bench,
            "reserve": reserve,
            "team_info": team_info,
            "team_analytics": team_analytics,
        }

    # 3. League-Wide Team Power Leaderboard
    sorted_gridiron = sorted(team_summaries, key=lambda t: t["gridiron_value"], reverse=True)
    for rk, t in enumerate(sorted_gridiron, 1): t["rank_gridiron"] = rk

    sorted_market = sorted(team_summaries, key=lambda t: t["market_value"], reverse=True)
    for rk, t in enumerate(sorted_market, 1): t["rank_market"] = rk

    sorted_starter = sorted(team_summaries, key=lambda t: t["projected_weekly_starter_pts"], reverse=True)
    for rk, t in enumerate(sorted_starter, 1): t["rank_starter_pts"] = rk

    sorted_total = sorted(team_summaries, key=lambda t: t["total_season_projected_pts"], reverse=True)
    for rk, t in enumerate(sorted_total, 1): t["rank_total_pts"] = rk

    for t in team_summaries:
        avg_rank = (t["rank_gridiron"] + t["rank_market"] + t["rank_starter_pts"] + t["rank_total_pts"]) / 4.0
        t["composite_score"] = round(avg_rank, 2)

    sorted_composite = sorted(team_summaries, key=lambda t: t["composite_score"])
    for rk, t in enumerate(sorted_composite, 1):
        t["composite_rank"] = rk
        t["rank"] = rk
        t["starter_fpts"] = t["projected_weekly_starter_pts"]

    league_leaderboard = sorted_composite

    for str_id, data in teams_data_map.items():
        r_id = int(str_id)
        for t in sorted_composite:
            if t["roster_id"] == r_id:
                data["team_info"]["rank"] = t["rank"]
                data["team_info"]["composite_rank"] = t["composite_rank"]
                data["team_info"]["rank_gridiron"] = t["rank_gridiron"]
                data["team_info"]["rank_market"] = t["rank_market"]
                data["team_info"]["rank_starter_pts"] = t["rank_starter_pts"]
                data["team_analytics"]["rank"] = t["rank"]
                break

    return teams_data_map, league_leaderboard, rosters, players

class Handler(BaseHTTPRequestHandler):
    db_path: Path = get_db_path(None)  # overridden in main

    def log_message(self, format, *args):
        # quiet except errors
        if self.path.startswith("/hub-api"):
            print(f"[{self.log_date_time_string()}] {self.command} {self.path}")

    def end_headers(self):
        origin = self.headers.get("Origin", "")
        # Allowlist the local Vite dev server on both loopback names.
        # Omit header for non-allowlisted origins (never emit `null`).
        if origin in ("http://127.0.0.1:8001", "http://localhost:8001"):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
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
            self.json({"status": "ok", "proxy": "hub read-only", "db": "ok"})
            return

        if not path.startswith("/hub-api/"):
            self.send_error(404, "only /hub-api/* and /health")
            return

        try:
            conn = get_conn(self.db_path)
        except Exception:
            # Generic message — never disclose absolute db path; log server-side.
            logging.warning("hub proxy: cannot open DB read-only", exc_info=True)
            self.json({"error": "database unavailable"}, status=503)
            return

        try:
            if path == "/hub-api/meta":
                self.handle_meta(conn, qs)
            elif path == "/hub-api/ready":
                self.handle_ready(conn)
            elif path == "/hub-api/projections":
                self.handle_projections(conn, qs)
            elif path == "/hub-api/matchups":
                self.handle_matchups(conn, qs)
            elif path == "/hub-api/roster":
                self.handle_roster(conn, qs)
            elif path == "/hub-api/rosters-full":
                self.handle_rosters_full(conn)
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
        except Exception:
            logging.exception("proxy error handling %s", path)
            self.json({"error": "Internal server error"}, status=500)
        finally:
            try: conn.close()
            except: pass

    def json(self, obj, status=200, headers=None):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Consistent caching: no-store by default; callers may override.
        _extra = dict(headers or {})
        if "Cache-Control" not in _extra:
            self.send_header("Cache-Control", "no-store")
        for k, v in _extra.items():
            self.send_header(k, v)
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

        # placeholder weather flag (40.0,-74.0 coords are the refresh.py placeholder)
        weather_placeholder = True
        r = try_fetch_one(conn, "SELECT lat, lon FROM weather LIMIT 1")
        if r and not (r["lat"] == 40.0 and r["lon"] == -74.0):
            weather_placeholder = False
        weather_status = "placeholder" if weather_placeholder else "live"

        # PERF: fetch blobs directly — never run full build_league_analytics
        # here just to extract rosters/players (was 12-team enrichment per call).
        row = try_fetch_one(conn, "SELECT data FROM rosters ORDER BY rowid DESC LIMIT 1")
        rosters = load_json_blob(row) or []
        if not isinstance(rosters, list):
            rosters = []
        # data_source for frontend banners: demo when player_stats empty/seeded.
        data_source = "live"
        try:
            has_players = False
            try:
                prow = try_fetch_one(conn, "SELECT data FROM player_stats WHERE json_array_length(data)>0 ORDER BY rowid DESC LIMIT 1")
                pdata = load_json_blob(prow) if prow else None
                if isinstance(pdata, list) and len(pdata) > 0:
                    has_players = True
                else:
                    for cand in conn.execute("SELECT data FROM player_stats ORDER BY rowid DESC LIMIT 10").fetchall():
                        d = load_json_blob(cand)
                        if isinstance(d, list) and len(d) > 0:
                            has_players = True
                            break
            except Exception:
                pass
            if not has_players:
                data_source = "demo"
            else:
                srow = try_fetch_one(conn, "SELECT source FROM refresh_log ORDER BY ran_at DESC LIMIT 1")
                if srow:
                    try:
                        src = (srow["source"] or "").lower()
                    except Exception:
                        src = ""
                    if "demo" in src or "seed" in src:
                        data_source = "demo"
        except Exception:
            pass
        teams = []
        users_map = get_sleeper_users(conn)
        for r in (rosters if isinstance(rosters, list) else []):
            if not isinstance(r, dict): continue
            r_id = r.get("roster_id")
            o_id = str(r.get("owner_id") or "")
            u_info = users_map.get(o_id, {})
            owner_name = u_info.get("display_name") or u_info.get("team_name") or f"Team {r_id}"
            teams.append({
                "roster_id": r_id,
                "user_id": o_id,
                "owner_name": owner_name,
                "avatar": u_info.get("avatar"),
            })
        # Serve last cached leaderboard when fresh; never trigger a full build here.
        league_leaderboard = []
        try:
            with _CACHE_LOCK:
                _cached_full = _ROSTERS_FULL_CACHE.get("payload")
                _cached_at = _ROSTERS_FULL_CACHE.get("at", 0.0)
                if _cached_full is not None and (time.time() - _cached_at < _ROSTERS_FULL_TTL):
                    league_leaderboard = _cached_full.get("league_leaderboard") or []
        except Exception:
            league_leaderboard = []

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
            "teams": teams,
            "weather_placeholder": weather_placeholder,
            "weather_status": weather_status,
            "data_source": data_source,
            "league_leaderboard": league_leaderboard,
        })

    def handle_ready(self, conn):
        # Readiness (model has /ready; proxy mirrors it): 200 when DB present
        # + fresh-ish (rosters + player_stats non-empty), 503 otherwise.
        try:
            rrow = try_fetch_one(conn, "SELECT data FROM rosters ORDER BY rowid DESC LIMIT 1")
            rosters = load_json_blob(rrow) or []
            has_rosters = isinstance(rosters, list) and len(rosters) > 0
        except Exception:
            has_rosters = False
        try:
            has_players = False
            try:
                prow = try_fetch_one(conn, "SELECT data FROM player_stats WHERE json_array_length(data)>0 ORDER BY rowid DESC LIMIT 1")
                pdata = load_json_blob(prow) if prow else None
                if isinstance(pdata, list) and len(pdata) > 0:
                    has_players = True
                else:
                    for cand in conn.execute("SELECT data FROM player_stats ORDER BY rowid DESC LIMIT 10").fetchall():
                        d = load_json_blob(cand)
                        if isinstance(d, list) and len(d) > 0:
                            has_players = True
                            break
            except Exception:
                pass
        except Exception:
            has_players = False
        if has_rosters and has_players:
            self.json({"status": "ready"})
        else:
            self.json({"error": "not ready: database empty or missing"}, status=503)

    def handle_projections(self, conn, qs):
        # 60s server-side cache + Last-Modified/304 mirroring rosters-full.
        global _PROJECTIONS_CACHE
        _now = time.time()
        with _CACHE_LOCK:
            _pcached = _PROJECTIONS_CACHE.get("payload")
            _pat = _PROJECTIONS_CACHE.get("at", 0.0)
            _plm = _PROJECTIONS_CACHE.get("last_modified", "")
            if _pcached is not None and (_now - _pat < _PROJECTIONS_TTL):
                _ims = self.headers.get("If-Modified-Since")
                if _ims and _plm and _ims == _plm:
                    self.send_response(304)
                    self.send_header("Cache-Control", "private, max-age=60")
                    self.send_header("Last-Modified", _plm)
                    self.end_headers()
                    return
                _limit0 = 800
                try:
                    if qs.get("limit", [None])[0]:
                        _limit0 = max(10, min(2000, int(qs.get("limit")[0])))
                except Exception:
                    pass
                _full0 = _pcached.get("players_full") or []
                _nf0 = _pcached.get("num_flex", 2)
                _sliced0 = _full0[:_limit0]
                self.json({"players": _sliced0, "count": len(_sliced0), "meta": {"source": "db:player_stats:averaged", "num_flex": _nf0}}, headers={"Cache-Control": "private, max-age=60", "Last-Modified": _plm})
                return
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
                    # nflverse quirk: prefer `team` over `recent_team` for abbrev.
                    "team": p.get("team") or p.get("recent_team") or "",
                    "opponent_team": p.get("opponent_team") or "",
                    "total_pts": 0.0,
                    "games": 0,
                    "week_pts": [],
                }
            agg[pid]["total_pts"] += pts
            agg[pid]["games"] += 1
            agg[pid]["week_pts"].append(pts)
            # nflverse quirk: prefer `team` over `recent_team`.
            if p.get("team"):
                agg[pid]["team"] = p["team"]
            elif p.get("recent_team"):
                agg[pid]["team"] = p["recent_team"]

        def _pos_factor(pos):
            m = {"QB": 1.45, "RB": 1.07, "WR": 1.12, "TE": 0.88, "K": 0.55, "DEF": 0.75}
            return m.get(pos, 1.0)

        def _point_factor(pts):
            return min(1.60, 1.0 + max(0, pts - 12) * 0.022) if pts > 12 else 1.0

        comp_row = try_fetch_one(conn, "SELECT data FROM market_consensus ORDER BY fetched_at DESC LIMIT 1")
        comp_list = load_json_blob(comp_row, key="data") or []
        comp_by_id = {}
        for c in (comp_list if isinstance(comp_list, list) else []):
            if isinstance(c, dict) and c.get("player_id"):
                comp_by_id[str(c["player_id"])] = c

        # Sleeper cache via startup-warmed TTL (never holds _CACHE_LOCK across I/O).
        _sleeper_players = get_sleeper_players_cached()

        gsis_to_sleeper = {}
        name_team_pos_to_sleeper = {}
        for sid, sp in (_sleeper_players.items() if isinstance(_sleeper_players, dict) else []):
            if not isinstance(sp, dict):
                continue
            g = sp.get("gsis_id")
            if g: gsis_to_sleeper[str(g)] = str(sid)
            # Also build name+team+pos -> sleeper_id for fallback lookup
            nm = (sp.get("full_name") or f"{sp.get('first_name','')} {sp.get('last_name','')}".strip()).lower()
            tm = (sp.get("team") or "").upper()
            ps = (sp.get("position") or "").upper()
            if nm and tm and ps:
                name_team_pos_to_sleeper[(nm, tm, ps)] = str(sid)

        # PERF: compute once per request — never per-player.
        _opp_map = get_nfl_opponent_map(compute_nfl_week())

        out = []
        for pid, a in agg.items():
            if a["games"] == 0:
                continue
            pos = a["position"]
            raw_pts = apply_flex_adjustment(a["total_pts"] / a["games"], pos, num_flex)
            comp = comp_by_id.get(pid) or comp_by_id.get(gsis_to_sleeper.get(pid, "")) or {}
            m_pts = comp.get("model_points")
            mk_s = comp.get("market_season_points")
            mk_per_game = round(float(mk_s) / 17.0, 2) if (mk_s is not None and float(mk_s) > 0) else None

            if m_pts is not None and float(m_pts) > 0:
                pts = float(m_pts)
            elif raw_pts > 0:
                pts = raw_pts
            elif mk_per_game and mk_per_game > 0:
                pts = mk_per_game
            else:
                pts = 0.0

            width = float(comp.get("interval_width") or comp.get("width") or (5.0 * _pos_factor(pos) * _point_factor(pts)))
            width = max(3.0, min(14.0, width))
            low = pts - (width / 2.0)
            high = pts + (width / 2.0)
            # Try GSIS map first, then name+team+pos lookup against Sleeper cache
            sleeper_id = gsis_to_sleeper.get(pid)
            if not sleeper_id:
                nm = (a["player_name"] or "").lower()
                tm = (a["team"] or "").upper()
                ps = (pos or "").upper()
                if nm and tm and ps:
                    sleeper_id = name_team_pos_to_sleeper.get((nm, tm, ps))

            out.append({
                "player_id": pid,
                "sleeper_id": sleeper_id if sleeper_id else (pid if pid.isdigit() else None),
                "player_name": a["player_name"],
                "position": pos,
                "position_group": pos,
                "team": a["team"],
                "opponent_team": _opp_map.get(a["team"]) or a["opponent_team"] or "",
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
        _last_modified = formatdate(timeval=_now, localtime=False, usegmt=True)
        with _CACHE_LOCK:
            _PROJECTIONS_CACHE = {"at": _now, "payload": {"players_full": out, "num_flex": num_flex}, "last_modified": _last_modified}
        # ?limit support (default 800 for UI, max 2000 to bound payload).
        limit = 800
        try:
            if qs.get("limit", [None])[0]:
                limit = max(10, min(2000, int(qs.get("limit")[0])))
        except Exception:
            pass
        sliced = out[:limit]
        self.json({"players": sliced, "count": len(sliced), "meta": {"source": "db:player_stats:averaged", "num_flex": num_flex}}, headers={"Cache-Control": "private, max-age=60", "Last-Modified": _last_modified})

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
        target_wk = week if (week and week > 0) else 1
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
        teams_data_map, league_leaderboard, rosters, players = build_league_analytics(conn)
        users_map = get_sleeper_users(conn)

        # Build list of 12 league rosters summary (allTeams)
        all_teams = []
        for r in (rosters if isinstance(rosters, list) else []):
            if not isinstance(r, dict): continue
            r_id = r.get("roster_id")
            o_id = str(r.get("owner_id") or "")
            u_info = users_map.get(o_id, {})
            disp_name = u_info.get("display_name") or u_info.get("team_name") or f"Team {r_id}"
            t_name = u_info.get("team_name") or u_info.get("display_name") or f"Team {r_id}"
            all_teams.append({
                "roster_id": r_id,
                "user_id": o_id,
                "owner_id": o_id,
                "owner_name": disp_name,
                "display_name": disp_name,
                "team_name": t_name,
                "avatar": u_info.get("avatar"),
                "avatar_url": u_info.get("avatar_url"),
                "players_count": len(r.get("players") or []),
            })

        # Target roster selection: ?roster_id=N or ?owner_id=X. Default to roster_id=1.
        # NOTE: server default stays 1; client derives the actual selection from
        # leagueRosters/allTeams (see hub/src roster picker).
        req_roster_id = (qs.get("roster_id", [None])[0] or "").strip()
        req_owner_id = (qs.get("owner_id", [None])[0] or "").strip()

        target_roster_id = "1"
        if req_roster_id:
            target_roster_id = req_roster_id
        elif req_owner_id:
            for r in (rosters if isinstance(rosters, list) else []):
                if isinstance(r, dict) and str(r.get("owner_id") or "").lower() == req_owner_id.lower():
                    target_roster_id = str(r.get("roster_id"))
                    break

        if target_roster_id not in teams_data_map and teams_data_map:
            target_roster_id = list(teams_data_map.keys())[0]

        target_data = teams_data_map.get(target_roster_id, {
            "starters": [], "bench": [], "reserve": [],
            "team_info": {}, "team_analytics": {}
        })

        self.json({
            "starters": target_data["starters"],
            "bench": target_data["bench"],
            "reserve": target_data["reserve"],
            "myRoster": target_data["starters"],
            "team_info": target_data["team_info"],
            "teamMeta": target_data["team_info"],
            "allTeams": all_teams,
            "leagueRosters": all_teams,
            "team_analytics": target_data["team_analytics"],
            "teamSummary": target_data["team_analytics"],
            "league_leaderboard": league_leaderboard,
            "team_leaderboard": league_leaderboard,
            "meta": {"rosters": len(rosters), "players": len(players)}
        })

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

    def handle_rosters_full(self, conn):
        # ONE build_league_analytics pass for all 12 enriched rosters (fixes N+1).
        # 60s server-side cache + Last-Modified; clients may use If-Modified-Since.
        global _ROSTERS_FULL_CACHE
        now = time.time()
        with _CACHE_LOCK:
            cached = _ROSTERS_FULL_CACHE.get("payload")
            at = _ROSTERS_FULL_CACHE.get("at", 0.0)
            lm = _ROSTERS_FULL_CACHE.get("last_modified", "")
            if cached is not None and (now - at < _ROSTERS_FULL_TTL):
                ims = self.headers.get("If-Modified-Since")
                if ims and lm and ims == lm:
                    self.send_response(304)
                    self.send_header("Cache-Control", "private, max-age=60")
                    self.send_header("Last-Modified", lm)
                    self.end_headers()
                    return
                self.json(cached, headers={"Cache-Control": "private, max-age=60", "Last-Modified": lm})
                return
        teams_data_map, league_leaderboard, rosters, players = build_league_analytics(conn)
        users_map = get_sleeper_users(conn)
        all_teams = []
        for r in (rosters if isinstance(rosters, list) else []):
            if not isinstance(r, dict):
                continue
            r_id = r.get("roster_id")
            o_id = str(r.get("owner_id") or "")
            u_info = users_map.get(o_id, {})
            disp_name = u_info.get("display_name") or u_info.get("team_name") or f"Team {r_id}"
            t_name = u_info.get("team_name") or u_info.get("display_name") or f"Team {r_id}"
            all_teams.append({
                "roster_id": r_id,
                "user_id": o_id,
                "owner_id": o_id,
                "owner_name": disp_name,
                "display_name": disp_name,
                "team_name": t_name,
                "avatar": u_info.get("avatar"),
                "avatar_url": u_info.get("avatar_url"),
                "players_count": len(r.get("players") or []),
            })
        payload = {
            "rosters": teams_data_map,
            "league_leaderboard": league_leaderboard,
            "team_leaderboard": league_leaderboard,
            "leagueRosters": all_teams,
            "allTeams": all_teams,
            "meta": {"rosters": len(rosters) if isinstance(rosters, list) else 0, "players": len(players) if isinstance(players, list) else 0},
        }
        last_modified = formatdate(timeval=now, localtime=False, usegmt=True)
        with _CACHE_LOCK:
            _ROSTERS_FULL_CACHE = {"at": now, "payload": payload, "last_modified": last_modified}
        self.json(payload, headers={"Cache-Control": "private, max-age=60", "Last-Modified": last_modified})

    def handle_comparison(self, conn, qs):
        # Model vs Market (Sleeper pts+stats vs FantasyPros ECR/ADP) — built by refresh.py
        # 60s server-side cache + Last-Modified/304 mirroring rosters-full.
        global _COMPARISON_CACHE
        _cnow = time.time()
        with _CACHE_LOCK:
            _ccached = _COMPARISON_CACHE.get("payload")
            _cat = _COMPARISON_CACHE.get("at", 0.0)
            _clm = _COMPARISON_CACHE.get("last_modified", "")
            if _ccached is not None and (_cnow - _cat < _COMPARISON_TTL):
                _cims = self.headers.get("If-Modified-Since")
                if _cims and _clm and _cims == _clm:
                    self.send_response(304)
                    self.send_header("Cache-Control", "private, max-age=60")
                    self.send_header("Last-Modified", _clm)
                    self.end_headers()
                    return
                _cfull = _ccached.get("players_full") or []
                _cfetched = _ccached.get("fetched_at")
                _cedge = (qs.get("edge", [None])[0] or "").upper()
                _cfiltered = _cfull
                if _cedge in ("BUY", "SELL", "NEUTRAL"):
                    _cfiltered = [p for p in _cfull if isinstance(p, dict) and (p.get("edge") or "").upper() == _cedge]
                _climit = 2000
                try:
                    if qs.get("limit", [None])[0]:
                        _climit = max(10, min(2000, int(qs.get("limit")[0])))
                except Exception:
                    pass
                self.json({"players": _cfiltered[:_climit], "count": len(_cfiltered), "fetched_at": _cfetched, "meta": {"source": "market_consensus", "preseason_note": "Market pts empty until Week 1 publish; rank comparison (ECR/ADP) works now."}}, headers={"Cache-Control": "private, max-age=60", "Last-Modified": _clm})
                return
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

        # Enrich every row with sleeper_id (same map /projections uses).
        # Cached comparison rows may predate the backend fix that emits sleeper_id;
        # without this, playerAvatar() falls back to the letter initial.
        # Sleeper via startup-warmed TTL cache (never holds _CACHE_LOCK across I/O).
        _sleeper_players = get_sleeper_players_cached()

        gsis_to_sleeper = {}
        name_team_pos_to_sleeper = {}
        for sid, sp in (_sleeper_players.items() if isinstance(_sleeper_players, dict) else []):
            if not isinstance(sp, dict):
                continue
            g = sp.get("gsis_id")
            if g: gsis_to_sleeper[str(g)] = str(sid)
            # Also build name+team+pos -> sleeper_id for fallback lookup
            nm = (sp.get("full_name") or f"{sp.get('first_name','')} {sp.get('last_name','')}".strip()).lower()
            tm = (sp.get("team") or "").upper()
            ps = (sp.get("position") or "").upper()
            if nm and tm and ps:
                name_team_pos_to_sleeper[(nm, tm, ps)] = str(sid)

        for p in players:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("player_id") or "")
            if not p.get("sleeper_id"):
                # Try GSIS map first
                sleeper_id = gsis_to_sleeper.get(pid)
                if not sleeper_id:
                    # Fallback: name+team+pos lookup (normalize team abbrevs)
                    nm = (p.get("player_name") or "").lower()
                    tm = _normalize_team_abbrev(p.get("team") or "")
                    ps = (p.get("position") or "").upper()
                    if nm and tm and ps:
                        sleeper_id = name_team_pos_to_sleeper.get((nm, tm, ps))
                if sleeper_id:
                    p["sleeper_id"] = sleeper_id
        _clast = formatdate(timeval=_cnow, localtime=False, usegmt=True)
        with _CACHE_LOCK:
            _COMPARISON_CACHE = {"at": _cnow, "payload": {"players_full": players, "fetched_at": fetched_at}, "last_modified": _clast}
        # optional edge filter ?edge=BUY
        edge_filter = (qs.get("edge", [None])[0] or "").upper()
        if edge_filter in ("BUY", "SELL", "NEUTRAL"):
            players = [p for p in players if (p.get("edge") or "").upper() == edge_filter]
        # cap
        limit = 2000
        try:
            if qs.get("limit", [None])[0]:
                limit = max(10, min(2000, int(qs.get("limit")[0])))
        except Exception:
            pass
        self.json({"players": players[:limit], "count": len(players), "fetched_at": fetched_at, "meta": {"source": "market_consensus", "preseason_note": "Market pts empty until Week 1 publish; rank comparison (ECR/ADP) works now."}}, headers={"Cache-Control": "private, max-age=60", "Last-Modified": _clast})

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
            # TODO(consistency): waiver scores from raw fantasy_points while
            # projections/roster prefer model_points with raw fallback; use model
            # points when present once waiver loads market_consensus (multi-line).
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

    if args.host != "127.0.0.1":
        # No behavior change — warn on clumsy non-loopback --host.
        logging.warning("hub: --host %s is not loopback; expected 127.0.0.1", args.host)
        print(f"WARNING: --host {args.host} is not loopback; expected 127.0.0.1")
    try:
        db_path = get_db_path(args.db)
    except ValueError as e:
        # Generic message — never disclose absolute path; log server-side.
        logging.error("hub: invalid DB path: %s", e)
        print(f"invalid DB path: {e}")
        raise SystemExit(2)
    Handler.db_path = db_path
    print(f"hub read-only proxy → {db_path} (mode=ro)")
    print(f"listening on http://{args.host}:{args.port}  (127.0.0.1 only)")
    print("endpoints: /health, /hub-api/meta, /hub-api/ready, /hub-api/projections, /hub-api/matchups, /hub-api/roster, /hub-api/rosters-full, /hub-api/news, /hub-api/refresh-log, /hub-api/team-ratings, /hub-api/comparison")
    print("zero writes, zero tokens, read-only")
    # Startup-warm Sleeper caches in background so request path serves cache.
    try:
        warm_sleeper_caches_async()
    except Exception:
        pass

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")

if __name__ == "__main__":
    main()
