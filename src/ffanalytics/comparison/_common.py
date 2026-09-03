"""Shared constants and helpers used by _model / _auction / _edge."""

import re
from typing import Any

# Sleeper -> model stat key map for delta display
SLEEPER_TO_MODEL: dict[str, str] = {
    "pass_yd": "passing_yards",
    "pass_td": "passing_tds",
    "pass_int": "passing_interceptions",
    "rush_yd": "rushing_yards",
    "rush_td": "rushing_tds",
    "rec": "receptions",
    "rec_yd": "receiving_yards",
    "rec_td": "receiving_tds",
    "fum_lost": "fumbles_lost_total",
}
MODEL_TO_SLEEPER: dict[str, str] = {v: k for k, v in SLEEPER_TO_MODEL.items()}

# Stats we show in the expanded stat comparison panel
COMPARE_STATS: list[tuple[str, str, str]] = [
    ("passing_yards", "pass_yd", "Pass Yds"),
    ("rushing_yards", "rush_yd", "Rush Yds"),
    ("receiving_yards", "rec_yd", "Rec Yds"),
    ("receptions", "rec", "Rec"),
    ("passing_tds", "pass_td", "Pass TD"),
    ("rushing_tds", "rush_td", "Rush TD"),
    ("receiving_tds", "rec_td", "Rec TD"),
]


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower().strip()
    name = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", name)
    name = re.sub(r"[^a-z0-9 ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def build_gsis_map(sleeper_players: dict) -> dict[str, str]:
    """sleeper_id -> gsis_id."""
    m: dict[str, str] = {}
    for sid, p in sleeper_players.items():
        gsis = p.get("gsis_id")
        if gsis:
            gsis = str(gsis).strip()
            if gsis:
                m[str(sid)] = gsis
    return m


def build_sleeper_map(sleeper_players: dict) -> dict[str, str]:
    """gsis_id -> sleeper_id (reverse of ``build_gsis_map``)."""
    return {gsis: sid for sid, gsis in build_gsis_map(sleeper_players).items()}


def map_market_to_gsis(market_by_sleeper: dict, sleeper_players: dict) -> dict[str, dict]:
    """Convert Sleeper projections keyed by sleeper_id to gsis_id keyed."""
    gsis_map = build_gsis_map(sleeper_players)
    out: dict[str, dict] = {}
    for sid, proj in market_by_sleeper.items():
        gsis = gsis_map.get(str(sid))
        if gsis and isinstance(proj, dict) and proj:
            if "pts_ppr" in proj or "adp_dd_ppr" in proj or "pos_adp_dd_ppr" in proj:
                out[gsis] = proj
    return out


def build_fpros_lookup(fpros_players: list[dict]) -> dict[tuple, dict]:
    """(norm_name, team, pos) -> fpros row."""
    lut: dict[tuple, dict] = {}
    for p in fpros_players:
        name = p.get("player_name") or p.get("short_name") or ""
        team = (p.get("team_id") or "").upper()
        pos = (p.get("position_id") or p.get("position") or "").upper()
        if pos == "DST":
            pos = "DEF"
        key = (_normalize_name(name), team, pos)
        if _normalize_name(name):
            lut[key] = p
    return lut


def _best_fpros_match(
    player_name: str, team: str, position: str, fpros_lut: dict
) -> dict | None:
    team = (team or "").upper()
    pos = (position or "").upper()
    norm = _normalize_name(player_name)
    hit = fpros_lut.get((norm, team, pos))
    if hit:
        return hit
    for (n, _t, p), row in fpros_lut.items():
        if n == norm and p == pos:
            return row
    for (n, _t, p), row in fpros_lut.items():
        if p == pos and (norm in n or n in norm) and len(norm) > 3:
            return row
    return None


__all__ = [
    "COMPARE_STATS",
    "MODEL_TO_SLEEPER",
    "SLEEPER_TO_MODEL",
    "_best_fpros_match",
    "_normalize_name",
    "build_fpros_lookup",
    "build_gsis_map",
    "build_sleeper_map",
    "map_market_to_gsis",
]