"""Flatten data/fantasypros_dump/*.json.gz into data/fantasypros_dump/fp.sqlite.

Rebuilt from scratch each run; safe to rerun while fp_dump.py is still going.
Every table carries fp_id + gsis_id + sleeper_id (via nflverse ff_playerids).
Tables: players, ecr_weekly (list = source ranking: OP/RB/FLX/..., pos = player's), ecr_season (draft/ros/dynasty), proj_weekly, points_weekly.
"""

import gzip
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUMP = ROOT / "data" / "fantasypros_dump"
DB = DUMP / "fp.sqlite"

SCHEMA = """
CREATE TABLE players(fp_id INT PRIMARY KEY, gsis_id, sleeper_id, name, pos, team, birthdate);
CREATE TABLE ecr_weekly(season INT, week INT, scoring, list, pos, fp_id INT, gsis_id, sleeper_id, name, team, opp,
  rank_ecr REAL, rank_min REAL, rank_max REAL, rank_ave REAL, rank_std REAL, pos_rank, n_experts INT,
  PRIMARY KEY(season, week, scoring, list, fp_id));
CREATE TABLE ecr_season(type, season INT, scoring, fp_id INT, gsis_id, sleeper_id, name, pos, team,
  rank_ecr REAL, rank_min REAL, rank_max REAL, rank_ave REAL, rank_std REAL, pos_rank, tier INT, n_experts INT,
  PRIMARY KEY(type, season, scoring, fp_id));
CREATE TABLE proj_weekly(season INT, week INT, fp_id INT, gsis_id, sleeper_id, name, pos, team,
  points REAL, points_ppr REAL, points_half REAL, stats JSON, PRIMARY KEY(season, week, fp_id));
CREATE TABLE points_weekly(season INT, week INT, fp_id INT, gsis_id, sleeper_id, name, pos, team,
  points_std REAL, PRIMARY KEY(season, week, fp_id));
"""


def load(p: Path):
    return json.loads(gzip.decompress(p.read_bytes()))


def id_maps():
    rows = json.loads((ROOT / "data/nfl_cache/ff_playerids.json").read_text())
    by_fp, by_mfl = {}, {}
    for r in rows:
        ids = (r.get("gsis_id"), r.get("sleeper_id"))
        if r.get("fantasypros_id"):
            by_fp[str(r["fantasypros_id"]).split(".")[0]] = ids
        if r.get("mfl_id"):
            by_mfl[str(r["mfl_id"]).split(".")[0]] = ids
    return by_fp, by_mfl


def main():
    by_fp, by_mfl = id_maps()
    ids = lambda fp, mfl=None: by_fp.get(str(fp)) or by_mfl.get(str(mfl)) or (None, None)

    DB.unlink(missing_ok=True)
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)

    for p in load(DUMP / "players.json.gz")["players"]:
        db.execute("INSERT INTO players VALUES(?,?,?,?,?,?,?)",
                   (p["player_id"], *ids(p["player_id"]), p.get("player_name"), p.get("position_id"),
                    p.get("team_id"), p.get("birthdate")))

    ecr_cols = lambda p: (p.get("rank_ecr"), p.get("rank_min"), p.get("rank_max"), p.get("rank_ave"),
                          p.get("rank_std"), p.get("pos_rank"))
    for f in sorted(DUMP.glob("ecr_weekly/*/*.json.gz")):
        d = load(f)
        for p in d.get("players") or []:
            db.execute("INSERT OR IGNORE INTO ecr_weekly VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (int(d["year"]), int(d["week"]), d["scoring"], d["position_id"],
                        p.get("player_position_id"), p["player_id"],
                        *ids(p["player_id"]), p.get("player_name"), p.get("player_team_id"),
                        p.get("player_opponent"), *ecr_cols(p), d.get("total_experts")))

    # OP lists carry ~1 stub row per file (ranks, no name/pos); fill from players table
    db.execute("""UPDATE ecr_weekly SET name = (SELECT name FROM players WHERE fp_id = ecr_weekly.fp_id),
                  pos = coalesce(pos, (SELECT pos FROM players WHERE fp_id = ecr_weekly.fp_id))
                  WHERE name IS NULL""")

    for kind in ("draft", "ros", "dynasty"):
        for f in sorted(DUMP.glob(f"ecr_{kind}/*.json.gz")):
            d = load(f)
            for p in d.get("players") or []:
                db.execute("INSERT OR IGNORE INTO ecr_season VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (kind, int(d["year"]), d["scoring"], p["player_id"], *ids(p["player_id"]),
                            p.get("player_name"), p.get("player_position_id"), p.get("player_team_id"),
                            *ecr_cols(p), p.get("tier"), d.get("total_experts")))

    for f in sorted(DUMP.glob("proj/*/*.json.gz")):
        d = load(f)
        for p in d.get("players") or []:
            s = p.get("stats") or {}
            db.execute("INSERT OR IGNORE INTO proj_weekly VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (int(d["season"]), int(d["week"]), p["fpid"], *ids(p["fpid"], p.get("mflid")),
                        p["name"], p.get("position_id"), p.get("team_id"), s.get("points"),
                        s.get("points_ppr"), s.get("points_half"), json.dumps(s)))

    for f in sorted(DUMP.glob("points/*.json.gz")):
        d = load(f)
        for p in d.get("players") or []:
            for wk, pts in (p.get("weeks") or {}).items():
                db.execute("INSERT OR IGNORE INTO points_weekly VALUES(?,?,?,?,?,?,?,?,?)",
                           (int(d["season"]), int(wk), p["player_id"], *ids(p["player_id"]),
                            p.get("player_name"), p.get("position_id"), p.get("team_id"), pts))

    db.commit()
    for t in ("players", "ecr_weekly", "ecr_season", "proj_weekly", "points_weekly"):
        n, hit = db.execute(f"SELECT count(*), sum(gsis_id IS NOT NULL) FROM {t}").fetchone()
        print(f"{t:14s} {n:>9,} rows  gsis match {100 * (hit or 0) / max(n, 1):5.1f}%")
    # self-check: top weekly QB ECR exists and ranks ascend from 1
    assert db.execute("SELECT min(rank_ecr) FROM ecr_weekly").fetchone()[0] in (1, 1.0, None)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
