"""Local FantasyPros CSV fallback — $0, no API limit.

Reads the two user-provided exports at repo root:
  - FantasyPros_2026_Draft_ALL_Rankings.csv (ECR, tiers, POS rank)
  - FantasyPros_2026_Overall_ADP_Rankings.csv (AVG/Sleeper ADP)
Provides full coverage (519 ECR + 695 ADP) vs free API 10 DST limit.
"""

import csv
import re
from pathlib import Path

# Repo root is two parents up from this file: src/ffanalytics/adapters/ -> src/ffanalytics -> src -> root
REPO_ROOT = Path(__file__).resolve().parents[3]

CANDIDATE_DIRS = [REPO_ROOT, REPO_ROOT / "data", Path.cwd()]

DRAFT_FILES = ["FantasyPros_2026_Draft_ALL_Rankings.csv", "FantasyPros_Draft_ALL_Rankings.csv"]
ADP_FILES = ["FantasyPros_2026_Overall_ADP_Rankings.csv", "FantasyPros_Overall_ADP_Rankings.csv"]


def _find_file(basenames: list[str]) -> Path | None:
    for d in CANDIDATE_DIRS:
        for name in basenames:
            p = d / name
            if p.exists():
                return p
    # also search root glob
    for name in basenames:
        for p in REPO_ROOT.glob(name):
            if p.exists():
                return p
    return None


def _pos_base(pos_raw: str) -> str:
    """WR1 -> WR, DST1 -> DST, K1 -> K"""
    if not pos_raw:
        return ""
    m = re.match(r"^([A-Z]+)", str(pos_raw).strip().upper())
    return m.group(1) if m else str(pos_raw).strip().upper()


def _pos_rank(pos_raw: str) -> int | None:
    m = re.search(r"(\d+)\s*$", str(pos_raw).strip())
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def load_draft_rankings(path: Path | None = None) -> list[dict]:
    """Parse Draft ALL Rankings.csv -> list with ECR/tier."""
    p = path or _find_file(DRAFT_FILES)
    if not p or not p.exists():
        return []
    rows: list[dict] = []
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rk = (raw.get("RK") or "").strip().strip('"')
            if not rk.isdigit():
                continue  # tier separator row
            try:
                rank_ecr = int(rk)
            except Exception:
                continue
            tier_raw = (raw.get("TIERS") or "").strip()
            try:
                tier = int(tier_raw) if tier_raw.isdigit() else None
            except Exception:
                tier = None
            name = (raw.get("PLAYER NAME") or raw.get("PLAYER_NAME") or "").strip()
            team = (raw.get("TEAM") or "").strip().upper()
            pos_raw = (raw.get("POS") or "").strip()
            pos_base = _pos_base(pos_raw)
            if pos_base == "DST":
                pos_base = "DST"
            elif pos_base == "DS":
                pos_base = "DST"
            pos_rank = _pos_rank(pos_raw)
            bye = (raw.get("BYE WEEK") or raw.get("BYE_WEEK") or "").strip()
            try:
                bye_int = int(bye) if bye.isdigit() else None
            except Exception:
                bye_int = None
            rows.append({
                "player_name": name,
                "team_id": team,
                "position_id": pos_base,
                "position": pos_base,
                "rank_ecr": rank_ecr,
                "rank_ecr_pos": pos_rank,
                "rank_ecr_ppr": rank_ecr,  # compat for comparison.py
                "tier": tier,
                "bye_week": bye_int,
                "source": "csv_draft",
            })
    return rows


def load_adp_rankings(path: Path | None = None) -> list[dict]:
    """Parse Overall ADP Rankings.csv -> list with ADP AVG/Sleeper."""
    p = path or _find_file(ADP_FILES)
    if not p or not p.exists():
        return []
    rows: list[dict] = []
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rank_raw = (raw.get("Rank") or "").strip()
            if not rank_raw.isdigit():
                continue
            try:
                rank = int(rank_raw)
            except Exception:
                continue
            player_bye = (raw.get("Player (Bye)") or raw.get("Player") or "").strip()
            # e.g., "Jahmyr Gibbs   DET (6)" -> name "Jahmyr Gibbs", team DET, bye 6
            team = ""
            name = player_bye
            bye_int = None
            m = re.search(r"\s+([A-Z]{2,3})\s*\((\d+)\)\s*$", player_bye)
            if m:
                team = m.group(1).upper()
                try:
                    bye_int = int(m.group(2))
                except Exception:
                    bye_int = None
                name = player_bye[: m.start()].strip()
            # POS like RB1 -> base RB, rank 1
            pos_raw = (raw.get("POS") or "").strip()
            pos_base = _pos_base(pos_raw)
            if pos_base == "DS":
                pos_base = "DST"
            pos_rank = _pos_rank(pos_raw)
            # AVG and Sleeper ADP
            avg_raw = (raw.get("AVG") or "").strip()
            sleeper_raw = (raw.get("Sleeper") or "").strip()
            try:
                avg = float(avg_raw) if avg_raw else None
            except Exception:
                avg = None
            try:
                sleeper_adp = float(sleeper_raw) if sleeper_raw else None
            except Exception:
                sleeper_adp = None
            rows.append({
                "player_name": name,
                "team_id": team,
                "position_id": pos_base,
                "position": pos_base,
                "rank_adp": rank,  # overall rank
                "rank_adp_pos": pos_rank,
                "rank_adp_ppr": rank,
                # keep raw values for merge
                "avg_adp": avg,
                "sleeper_adp": sleeper_adp,
                "bye_week": bye_int,
                "source": "csv_adp",
            })
    return rows


def load_combined_csv() -> list[dict]:
    """Merge Draft ECR + ADP into unified list keyed by name+team+pos.

    For each player, combine:
      rank_ecr / rank_ecr_pos / tier (from draft)
      rank_adp / rank_adp_pos / avg_adp / sleeper_adp (from adp)
    Returns list of merged dicts suitable for comparison.py (has both).
    """
    draft = load_draft_rankings()
    adp = load_adp_rankings()
    # index by normalized key: (norm_name, team, pos)
    def norm(name: str) -> str:
        name = name.lower().strip()
        name = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", name)
        name = re.sub(r"[^a-z0-9 ]", "", name)
        return re.sub(r"\s+", " ", name).strip()

    merged: dict[tuple, dict] = {}
    for row in draft:
        key = (norm(row["player_name"]), row["team_id"], row["position_id"])
        merged[key] = {**row}
    for row in adp:
        key = (norm(row["player_name"]), row["team_id"], row["position_id"])
        if key in merged:
            # merge ADP fields into existing ECR entry
            merged[key].update({
                "rank_adp": row.get("rank_adp"),
                "rank_adp_pos": row.get("rank_adp_pos"),
                "rank_adp_ppr": row.get("rank_adp"),
                "avg_adp": row.get("avg_adp"),
                "sleeper_adp": row.get("sleeper_adp"),
            })
            # keep source marker
            merged[key]["source"] = "csv_merged"
        else:
            # ADP-only player (deeper bench) — keep with only ADP
            entry = {
                "player_name": row["player_name"],
                "team_id": row["team_id"],
                "position_id": row["position_id"],
                "position": row["position_id"],
                "rank_ecr": None,
                "rank_ecr_pos": None,
                "rank_ecr_ppr": None,
                "tier": None,
                "rank_adp": row.get("rank_adp"),
                "rank_adp_pos": row.get("rank_adp_pos"),
                "rank_adp_ppr": row.get("rank_adp"),
                "avg_adp": row.get("avg_adp"),
                "sleeper_adp": row.get("sleeper_adp"),
                "bye_week": row.get("bye_week"),
                "source": "csv_adp_only",
            }
            merged[key] = entry
    # also add draft-only players not in ADP (should be few)
    return list(merged.values())


def get_fantasypros_csv_players() -> list[dict]:
    """Public helper for refresh: returns merged list or [] if no CSVs found."""
    rows = load_combined_csv()
    # filter out empty names
    return [r for r in rows if r.get("player_name")]

