"""Bulk-dump FantasyPros v2 API (premium key) to data/fantasypros_dump/ as gzipped raw JSON.

The key has a request quota (429 "Limit Exceeded"), so jobs are yielded in
priority order (league = full PPR, newest season first) and the run stops
cleanly when the quota is hit. Rerun after the quota resets; existing files
are skipped. Local only, gitignored (see DATA_NOTICE.md).
Usage: python scripts/fp_dump.py [--first 2012] [--dry-run]
"""

import argparse
import gzip
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fantasypros_dump"
BASE = "https://api.fantasypros.com/public/v2/json/nfl"
CUR_SEASON, CUR_WEEK = 2026, 3
PROJ_POS = ("QB", "RB", "WR", "TE", "K", "DST")
DELAY = 1.0  # API throttles ~1 req/s (429 "Too Many Requests" above that)


def weeks(s):
    return range(1, (CUR_WEEK if s == CUR_SEASON else 18) + 1)


def ecr(name, s, typ, sc, pos, week=None):
    params = {"type": typ, "scoring": sc, "position": pos}
    if week is not None:
        params["week"] = week
    return name, f"{s}/consensus-rankings", params


def jobs(first: int):
    seasons = range(CUR_SEASON, first - 1, -1)  # newest first
    # Tier 0: current-state snapshots that vanish when the trial ends
    yield "players", "players", {}
    yield "injuries", "injuries", {}
    yield "news", "news", {}
    for sc in ("PPR", "HALF", "STD"):
        yield ecr(f"ecr_ros/{CUR_SEASON}_w{CUR_WEEK:02d}_{sc}", CUR_SEASON, "ros", sc, "ALL")
    yield ecr(f"ecr_dynasty/{CUR_SEASON}_PPR", CUR_SEASON, "dynasty", "PPR", "ALL")
    # Tier 1: per-season draft ECR + season projections (5 req/season)
    for s in seasons:
        yield ecr(f"ecr_draft/{s}_PPR", s, "draft", "PPR", "ALL")
        for p in ("QB", "RB", "WR", "TE"):
            yield f"proj/{s}/w00_{p}", f"{s}/projections", {"position": p, "week": 0}
    # Tier 2: weekly ECR via OP (QB+RB+WR+TE, full depth, 1 call) + skill projections (5 req/week)
    for s in seasons:
        for w in weeks(s):
            yield ecr(f"ecr_weekly/{s}/w{w:02d}_OP_PPR", s, "weekly", "PPR", "OP", w)
            for p in ("QB", "RB", "WR", "TE"):
                yield f"proj/{s}/w{w:02d}_{p}", f"{s}/projections", {"position": p, "week": w}
    # Tier 3: K/DST, actual points (nflverse has these), other scorings, per-position ECR
    for s in seasons:
        for p in PROJ_POS:
            yield f"points/{s}_{p}", f"{s}/player-points", {"position": p}
        for p in ("K", "DST"):
            yield f"proj/{s}/w00_{p}", f"{s}/projections", {"position": p, "week": 0}
            for w in weeks(s):
                yield ecr(f"ecr_weekly/{s}/w{w:02d}_{p}_STD", s, "weekly", "STD", p, w)
                yield f"proj/{s}/w{w:02d}_{p}", f"{s}/projections", {"position": p, "week": w}
        for sc in ("HALF", "STD"):
            yield ecr(f"ecr_draft/{s}_{sc}", s, "draft", sc, "ALL")
        for w in weeks(s):
            yield f"rankings/{s}/w{w:02d}", f"{s}/rankings", {"type": "weekly", "position": "ALL", "week": w}
            yield ecr(f"ecr_weekly/{s}/w{w:02d}_FLX_PPR", s, "weekly", "PPR", "FLX", w)
            yield ecr(f"ecr_weekly/{s}/w{w:02d}_OP_STD", s, "weekly", "STD", "OP", w)
            for p in ("QB", "RB", "WR", "TE"):
                yield ecr(f"ecr_weekly/{s}/w{w:02d}_{p}_{'STD' if p == 'QB' else 'PPR'}", s, "weekly",
                          "STD" if p == "QB" else "PPR", p, w)
            for p in ("RB", "WR", "TE", "FLX"):
                for sc in ("HALF", "STD"):
                    yield ecr(f"ecr_weekly/{s}/w{w:02d}_{p}_{sc}", s, "weekly", sc, p, w)
    for sc in ("HALF", "STD"):
        yield ecr(f"ecr_dynasty/{CUR_SEASON}_{sc}", CUR_SEASON, "dynasty", sc, "ALL")


def fetch(http, key, name, path, params):
    """-> 'ok' | 'quota' | 'fail <why>'"""
    dest = OUT / f"{name}.json.gz"
    err = ""
    for attempt in range(5):
        time.sleep(DELAY)
        try:
            r = http.get(f"{BASE}/{path}", params=params, headers={"x-api-key": key}, timeout=30)
        except requests.RequestException as e:
            err = str(e)
        else:
            if r.status_code == 200:
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".tmp")
                tmp.write_bytes(gzip.compress(r.content))
                tmp.rename(dest)
                return "ok"
            if r.headers.get("x-amzn-errortype") == "LimitExceededException":
                return "quota"
            err = f"{r.status_code} {r.text[:120]}"
            if r.status_code in (400, 403, 404):
                return f"fail {err}"
        time.sleep(2 ** attempt * 5)  # throttle/5xx/timeout backoff
    return f"fail {err}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", type=int, default=2012)
    ap.add_argument("--max", type=int, default=500, help="request budget for this run (quota: 500/day)")
    ap.add_argument("--dry-run", action="store_true", help="count remaining requests, fetch nothing")
    a = ap.parse_args()
    todo = [j for j in jobs(a.first) if not (OUT / f"{j[0]}.json.gz").exists()][: a.max]
    print(f"{time.strftime('%F %T')} {len(todo)} requests remaining -> {OUT}", flush=True)
    if a.dry_run:
        return 0
    load_dotenv(ROOT / ".env")
    key = os.environ["FANTASYPROS_API_KEY"]
    http = requests.Session()
    ok, fails = 0, []
    for i, (name, path, params) in enumerate(todo, 1):
        st = fetch(http, key, name, path, params)
        if st == "quota":
            print(f"quota exhausted after {ok} ok; next up: {name}. Rerun after reset.", flush=True)
            break
        if st == "ok":
            ok += 1
        else:
            fails.append(f"{name}: {st}")
            print(f"{name} {st}", flush=True)
        if i % 100 == 0:
            print(f"[{i}/{len(todo)}] {name}", flush=True)
    else:
        print("all done", flush=True)
    with open(OUT / "_failures.txt", "a") as f:
        f.writelines(x + "\n" for x in fails)
    print(f"{time.strftime('%F %T')} run: {ok} ok, {len(fails)} failed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
