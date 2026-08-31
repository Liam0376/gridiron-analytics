"""FantasyPros season projections CSVs — $0 local, full season market.

Reads 7 exports at repo root (CRLF, BOM):
  - FantasyPros_Fantasy_Football_Projections_QB.csv   (79 QBs, passing + rushing + FL)
  - RB.csv  (126 RBs)
  - WR.csv  (184 WRs)
  - TE.csv  (118 TEs)
  - FLX.csv (421 flex RB/WR/TE, POS like RB1)
  - DST.csv (34 DSTs)
  - K.csv   (37 kickers)

Headers have duplicate names (ATT/YDS/TDS) and empty spacer rows.
We parse by column index per file type, not by DictReader name, to avoid
collision. Returns dict keyed by (norm_name, team, pos_base) -> season stats
with at least FPTS (season total, ~372 for QB1) and mapped model keys for
deltas: passing_yards, passing_tds, passing_interceptions, rushing_yards,
rushing_tds, receiving_yards, receiving_tds, receptions, fumbles_lost_total
(for FLX/RB/WR) plus Tier/ECR already via fantasypros_csv.

Team for DST: CSV has empty Team; we map Player full name "Houston Texans"
to abbreviation via lookup.
"""

import csv
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

PROJ_FILES = {
    "QB": "FantasyPros_Fantasy_Football_Projections_QB.csv",
    "RB": "FantasyPros_Fantasy_Football_Projections_RB.csv",
    "WR": "FantasyPros_Fantasy_Football_Projections_WR.csv",
    "TE": "FantasyPros_Fantasy_Football_Projections_TE.csv",
    "FLX": "FantasyPros_Fantasy_Football_Projections_FLX.csv",
    "DST": "FantasyPros_Fantasy_Football_Projections_DST.csv",
    "K": "FantasyPros_Fantasy_Football_Projections_K.csv",
}

# Full team name -> abbr for DST
TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def _norm_name(name: str) -> str:
    name = (name or "").lower().strip()
    name = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", name)
    name = re.sub(r"[^a-z0-9 ]", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _pos_base(pos_raw: str) -> str:
    if not pos_raw:
        return ""
    m = re.match(r"^([A-Z]+)", str(pos_raw).strip().upper())
    return m.group(1) if m else str(pos_raw).strip().upper()


def _find_proj_file(name: str) -> Path | None:
    fname = PROJ_FILES.get(name)
    if not fname:
        return None
    # Search REPO_ROOT and data and cwd
    for d in [REPO_ROOT, REPO_ROOT / "data", Path.cwd()]:
        p = d / fname
        if p.exists():
            return p
    # glob fallback
    for p in REPO_ROOT.glob(fname):
        if p.exists():
            return p
    return None


def _safe_float(v) -> float | None:
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(str(v).strip().replace(",", ""))
    except Exception:
        return None


def load_qb_projections() -> dict[tuple, dict]:
    p = _find_proj_file("QB")
    if not p or not p.exists():
        return {}
    out: dict[tuple, dict] = {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        if not headers:
            return {}
        for row in reader:
            # skip spacer rows: Player blank or NBSP
            if not row or len(row) < 2 or not row[0] or row[0].strip() in ("", "\xa0", " "):
                continue
            if len(row) < 12:
                continue
            # Columns: Player, Team, ATT1, CMP, YDS1, TDS1, INTS, ATT2, YDS2, TDS2, FL, FPTS
            player = row[0].strip()
            team = row[1].strip().upper()
            att_pass = _safe_float(row[2])
            cmp_pass = _safe_float(row[3])
            yds_pass = _safe_float(row[4])
            tds_pass = _safe_float(row[5])
            ints = _safe_float(row[6])
            att_rush = _safe_float(row[7])
            yds_rush = _safe_float(row[8])
            tds_rush = _safe_float(row[9])
            fl = _safe_float(row[10])
            fpts = _safe_float(row[11])
            if not player:
                continue
            # Normalize pos
            pos = "QB"
            key = (_norm_name(player), team, pos)
            out[key] = {
                "player_name": player,
                "team_id": team,
                "position_id": pos,
                "position": pos,
                "fpts": fpts,
                "passing_yards": yds_pass,
                "passing_tds": tds_pass,
                "passing_interceptions": ints,
                "rushing_yards": yds_rush,
                "rushing_tds": tds_rush,
                "receptions": 0.0,
                "receiving_yards": 0.0,
                "receiving_tds": 0.0,
                "fumbles_lost_total": fl,
                # raw passing cmp/att for completeness
                "passing_att": att_pass,
                "passing_cmp": cmp_pass,
                "rushing_att": att_rush,
            }
    return out


def load_rb_projections() -> dict[tuple, dict]:
    p = _find_proj_file("RB")
    if not p or not p.exists():
        return {}
    out: dict[tuple, dict] = {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row or len(row) < 2 or not row[0] or row[0].strip() in ("", "\xa0"):
                continue
            if len(row) < 10:
                continue
            # RB: Player, Team, ATT, YDS, TDS, REC, YDS, TDS, FL, FPTS
            player = row[0].strip()
            team = row[1].strip().upper()
            att = _safe_float(row[2])
            yds_rush = _safe_float(row[3])
            tds_rush = _safe_float(row[4])
            rec = _safe_float(row[5])
            yds_rec = _safe_float(row[6])
            tds_rec = _safe_float(row[7])
            fl = _safe_float(row[8])
            fpts = _safe_float(row[9])
            if not player:
                continue
            pos = "RB"
            key = (_norm_name(player), team, pos)
            out[key] = {
                "player_name": player,
                "team_id": team,
                "position_id": pos,
                "position": pos,
                "fpts": fpts,
                "rushing_yards": yds_rush,
                "rushing_tds": tds_rush,
                "rushing_att": att,
                "receptions": rec,
                "receiving_yards": yds_rec,
                "receiving_tds": tds_rec,
                "passing_yards": 0.0,
                "passing_tds": 0.0,
                "passing_interceptions": 0.0,
                "fumbles_lost_total": fl,
            }
    return out


def load_wr_projections() -> dict[tuple, dict]:
    p = _find_proj_file("WR")
    if not p or not p.exists():
        return {}
    out: dict[tuple, dict] = {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row or len(row) < 2 or not row[0] or row[0].strip() in ("", "\xa0"):
                continue
            if len(row) < 10:
                continue
            # WR: Player, Team, REC, YDS, TDS, ATT, YDS, TDS, FL, FPTS
            player = row[0].strip()
            team = row[1].strip().upper()
            rec = _safe_float(row[2])
            yds_rec = _safe_float(row[3])
            tds_rec = _safe_float(row[4])
            att = _safe_float(row[5])
            yds_rush = _safe_float(row[6])
            tds_rush = _safe_float(row[7])
            fl = _safe_float(row[8])
            fpts = _safe_float(row[9])
            if not player:
                continue
            pos = "WR"
            key = (_norm_name(player), team, pos)
            out[key] = {
                "player_name": player,
                "team_id": team,
                "position_id": pos,
                "position": pos,
                "fpts": fpts,
                "receptions": rec,
                "receiving_yards": yds_rec,
                "receiving_tds": tds_rec,
                "rushing_yards": yds_rush,
                "rushing_tds": tds_rush,
                "rushing_att": att,
                "passing_yards": 0.0,
                "passing_tds": 0.0,
                "passing_interceptions": 0.0,
                "fumbles_lost_total": fl,
            }
    return out


def load_te_projections() -> dict[tuple, dict]:
    p = _find_proj_file("TE")
    if not p or not p.exists():
        return {}
    out: dict[tuple, dict] = {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row or len(row) < 2 or not row[0] or row[0].strip() in ("", "\xa0"):
                continue
            if len(row) < 6:
                continue
            # TE: Player, Team, REC, YDS, TDS, FL, FPTS
            player = row[0].strip()
            team = row[1].strip().upper()
            rec = _safe_float(row[2])
            yds = _safe_float(row[3])
            tds = _safe_float(row[4])
            fl = _safe_float(row[5])
            fpts = _safe_float(row[6]) if len(row) > 6 else None
            if not player:
                continue
            pos = "TE"
            key = (_norm_name(player), team, pos)
            out[key] = {
                "player_name": player,
                "team_id": team,
                "position_id": pos,
                "position": pos,
                "fpts": fpts,
                "receptions": rec,
                "receiving_yards": yds,
                "receiving_tds": tds,
                "rushing_yards": 0.0,
                "rushing_tds": 0.0,
                "passing_yards": 0.0,
                "passing_tds": 0.0,
                "passing_interceptions": 0.0,
                "fumbles_lost_total": fl,
            }
    return out


def load_flx_projections() -> dict[tuple, dict]:
    p = _find_proj_file("FLX")
    if not p or not p.exists():
        return {}
    out: dict[tuple, dict] = {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row or len(row) < 3 or not row[0] or row[0].strip() in ("", "\xa0"):
                continue
            if len(row) < 11:
                continue
            # FLX: Player, Team, POS (RB1 etc), ATT, YDS, TDS, REC, YDS, TDS, FL, FPTS
            player = row[0].strip()
            team = row[1].strip().upper()
            pos_raw = row[2].strip()
            # POS like RB1 -> base RB
            import re as _re
            m = _re.match(r"^([A-Z]+)", pos_raw.upper())
            pos = m.group(1) if m else pos_raw.upper()
            if pos not in ("RB", "WR", "TE"):
                continue
            att = _safe_float(row[3])
            yds_rush = _safe_float(row[4])
            tds_rush = _safe_float(row[5])
            rec = _safe_float(row[6])
            yds_rec = _safe_float(row[7])
            tds_rec = _safe_float(row[8])
            fl = _safe_float(row[9])
            fpts = _safe_float(row[10])
            if not player:
                continue
            key = (_norm_name(player), team, pos)
            # Skip if already has more specific RB/WR/TE entry? Prefer FLX as superset, but don't overwrite if RB/WR already loaded — caller will merge.
            if key in out:
                continue
            out[key] = {
                "player_name": player,
                "team_id": team,
                "position_id": pos,
                "position": pos,
                "fpts": fpts,
                "rushing_yards": yds_rush,
                "rushing_tds": tds_rush,
                "rushing_att": att,
                "receptions": rec,
                "receiving_yards": yds_rec,
                "receiving_tds": tds_rec,
                "passing_yards": 0.0,
                "passing_tds": 0.0,
                "passing_interceptions": 0.0,
                "fumbles_lost_total": fl,
            }
    return out


def load_all_projections() -> dict[tuple, dict]:
    """Merge all position files into one dict keyed by (norm_name, team, pos)."""
    merged: dict[tuple, dict] = {}
    # FLX first as base for RB/WR/TE, then individual files will overwrite with more precise if needed
    for loader in [load_flx_projections, load_rb_projections, load_wr_projections, load_te_projections, load_qb_projections]:
        chunk = loader()
        for k, v in chunk.items():
            # RB/WR/TE files overwrite FLX entries for same player (more precise per-pos)
            # QB distinct keys so no collision
            merged[k] = v
    # Add K and DST separately (they use different pos bases)
    # K
    p_k = _find_proj_file("K")
    if p_k and p_k.exists():
        with open(p_k, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if not row or len(row) < 2 or not row[0] or row[0].strip() in ("", "\xa0"):
                    continue
                player = row[0].strip()
                team = row[1].strip().upper()
                fpts = _safe_float(row[4]) if len(row) > 4 else None
                key = (_norm_name(player), team, "K")
                merged[key] = {
                    "player_name": player,
                    "team_id": team,
                    "position_id": "K",
                    "position": "K",
                    "fpts": fpts,
                    "passing_yards": 0.0,
                    "passing_tds": 0.0,
                    "passing_interceptions": 0.0,
                    "rushing_yards": 0.0,
                    "rushing_tds": 0.0,
                    "receiving_yards": 0.0,
                    "receiving_tds": 0.0,
                    "receptions": 0.0,
                    "fumbles_lost_total": 0.0,
                }
    # DST
    p_dst = _find_proj_file("DST")
    if p_dst and p_dst.exists():
        with open(p_dst, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if not row or len(row) < 1 or not row[0] or row[0].strip() in ("", "\xa0"):
                    continue
                player = row[0].strip()  # e.g., "Houston Texans"
                team = ""
                # map full name to abbr
                team = TEAM_NAME_TO_ABBR.get(player, "")
                fpts = _safe_float(row[10]) if len(row) > 10 else None
                key = (_norm_name(player), team, "DST")
                # also add DEF variant for comparison lookup
                merged[key] = {
                    "player_name": player,
                    "team_id": team,
                    "position_id": "DST",
                    "position": "DST",
                    "fpts": fpts,
                }
                key2 = (_norm_name(player), team, "DEF")
                merged[key2] = {
                    "player_name": player,
                    "team_id": team,
                    "position_id": "DEF",
                    "position": "DEF",
                    "fpts": fpts,
                }
    return merged


def get_fantasypros_projections_map() -> dict[tuple, dict]:
    """Public: season market projections keyed for comparison builder."""
    return load_all_projections()
