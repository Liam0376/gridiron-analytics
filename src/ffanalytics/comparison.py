"""Model vs Market comparison builder.

Joins three sources via two crosswalks:
 - Gridiron model weekly projections (nflverse player_id = gsis_id)  -> gsis_id
 - Sleeper market projections (sleeper_id -> pts_ppr + stats)          -> via sleeper_players gsis_id map -> gsis_id
 - FantasyPros ECR/ADP ranks (player_name + team + pos)               -> via name+team+pos join -> gsis_id

Produces per-player comparison rows with:
 - model_points / market_points / delta
 - model_rank / fpros_ecr / adp / delta_rank
 - stat-level deltas for key stats (pass_yd, rush_yd, rec_yd, receptions, TDs)
"""

import re
from collections import defaultdict

# Sleeper -> model stat key map for delta display
SLEEPER_TO_MODEL = {
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
MODEL_TO_SLEEPER = {v: k for k, v in SLEEPER_TO_MODEL.items()}

# Stats we show in the expanded stat comparison panel
COMPARE_STATS = [
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
    # remove suffixes Jr. Sr. II III etc, punctuation
    name = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", name)
    name = re.sub(r"[^a-z0-9 ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def build_gsis_map(sleeper_players: dict) -> dict[str, str]:
    """sleeper_id -> gsis_id"""
    m = {}
    for sid, p in sleeper_players.items():
        gsis = p.get("gsis_id")
        if gsis:
            gsis = str(gsis).strip()
            if gsis:
                m[str(sid)] = gsis
    return m


def map_market_to_gsis(market_by_sleeper: dict, sleeper_players: dict) -> dict[str, dict]:
    """Convert Sleeper projections keyed by sleeper_id to gsis_id keyed."""
    gsis_map = build_gsis_map(sleeper_players)
    out: dict[str, dict] = {}
    for sid, proj in market_by_sleeper.items():
        gsis = gsis_map.get(str(sid))
        if gsis and isinstance(proj, dict) and proj:
            # Keep if it has points or ADP (ADP covers ~3125 gsis vs 264 pts-only)
            # ADP fallback gives every draftable an ADP rank even when weekly starter
            # projection not yet published.
            if "pts_ppr" in proj or "adp_dd_ppr" in proj or "pos_adp_dd_ppr" in proj:
                out[gsis] = proj
    return out


def build_fpros_lookup(fpros_players: list[dict]) -> dict[tuple, dict]:
    """(norm_name, team, pos) -> fpros row. Also store fallback by (norm_name, pos)."""
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


def _best_fpros_match(player_name: str, team: str, position: str, fpros_lut: dict) -> dict | None:
    team = (team or "").upper()
    pos = (position or "").upper()
    norm = _normalize_name(player_name)
    # exact
    hit = fpros_lut.get((norm, team, pos))
    if hit:
        return hit
    # try without team (team changed / FA)
    for (n, _t, p), row in fpros_lut.items():
        if n == norm and p == pos:
            return row
    # fallback: loose name contains
    for (n, _t, p), row in fpros_lut.items():
        if p == pos and (norm in n or n in norm) and len(norm) > 3:
            return row
    return None


def build_comparison(
    model_projections: list[dict],
    market_by_gsis: dict[str, dict],
    fpros_players: list[dict] | None = None,
    sleeper_players: dict | None = None,
    fp_projections: dict[tuple, dict] | None = None,
) -> list[dict]:
    """Build enriched comparison rows.

    model_projections: list from build_weekly_projections (each has player_id=gsis_id,
        player_display_name, position, team, projected_points + stat keys).
    market_by_gsis: gsis_id -> {pts_ppr, pass_yd, rush_yd, rec, rec_yd, ...} (Sleeper weekly)
    fpros_players: full fantasypros players list with rank_ecr etc. (CSV full 790)
    fp_projections: FantasyPros season projections keyed by (norm_name, team, pos) -> {fpts, passing_yards...}
                  (596 players, season totals, e.g., Josh Allen 372.5 / 3816 YDS)

    Returns sorted list (by model_points desc) with delta/rank fields.
    Weekly market (Sleeper) for Projections weekly, season market (FP CSV) for Auction season.
    """
    fpros_lut = build_fpros_lookup(fpros_players or [])

    # Pre-rank model projections by projected_points
    sorted_model = sorted(model_projections, key=lambda p: float(p.get("projected_points") or p.get("point_estimate") or 0), reverse=True)
    # build overall and per-pos rank maps
    overall_rank: dict[str, int] = {}
    pos_rank: dict[str, int] = {}
    pos_counters: dict[str, int] = defaultdict(int)
    for idx, p in enumerate(sorted_model, start=1):
        pid = str(p.get("player_id") or p.get("id") or "")
        if pid:
            overall_rank[pid] = idx
            pos = (p.get("position") or p.get("position_group") or "").upper()
            pos_counters[pos] += 1
            pos_rank[pid] = pos_counters[pos]

    # Build enriched rows
    rows: list[dict] = []
    for p in sorted_model:
        pid = str(p.get("player_id") or p.get("id") or "")
        if not pid:
            continue
        pos = (p.get("position") or p.get("position_group") or "UNK").upper()
        team = p.get("team") or p.get("recent_team") or ""
        model_pts = float(p.get("projected_points") or p.get("point_estimate") or 0)

        market = market_by_gsis.get(pid)
        market_pts = None
        market_stats: dict[str, float] = {}
        if market:
            # pts_ppr absent => no weekly starter projection (ADP-only entry) -> keep None
            if "pts_ppr" in market or "pts_half_ppr" in market:
                try:
                    raw = market.get("pts_ppr")
                    if raw is None:
                        raw = market.get("pts_half_ppr")
                    if raw is not None:
                        market_pts = float(raw)
                except Exception:
                    market_pts = None
            # pull market stats for delta panel
            for mdl_k, slp_k in MODEL_TO_SLEEPER.items():
                v = market.get(slp_k)
                if v is not None:
                    try:
                        market_stats[mdl_k] = float(v)
                    except Exception:
                        pass

        # FPros ranks
        fpros = _best_fpros_match(p.get("player_display_name") or p.get("player_name") or "", team, pos, fpros_lut)
        fp_ecr = None
        fp_ecr_pos = None
        fp_adp = None
        fp_adp_pos = None
        fp_tier = None
        if fpros:
            # prefer PPR ranks, fall back to generic
            fp_ecr = fpros.get("rank_ecr_ppr") if fpros.get("rank_ecr_ppr") else fpros.get("rank_ecr")
            fp_ecr_pos = fpros.get("rank_ecr_pos")
            # ADP
            fp_adp = fpros.get("rank_adp_ppr") if fpros.get("rank_adp_ppr") else fpros.get("rank_adp")
            fp_adp_pos = fpros.get("rank_adp_pos")
            fp_tier = fpros.get("tier")
            # FantasyPros uses 0 to mean unranked; coerce to None
            if fp_ecr == 0:
                fp_ecr = None
            if fp_ecr_pos == 0:
                fp_ecr_pos = None
            if fp_adp == 0:
                fp_adp = None
            if fp_tier == 0:
                fp_tier = None
        # Sleeper ADP fallback — free, covers ~3125 gsis vs FP free tier 10 DST only.
        # Ensures ADP column shows for every draftable player even when FP ECR is sparse.
        # CSV files (if present) already give full 695 ADP coverage, so this fallback
        # only fires when CSV not loaded and API limited.
        if fp_adp is None and market:
            try:
                sleeper_adp = market.get("adp_dd_ppr") if market.get("adp_dd_ppr") is not None else market.get("pos_adp_dd_ppr")
                # Sleeper uses 999/1000 for undrafted/fringe — treat as missing
                if sleeper_adp is not None:
                    v = float(sleeper_adp)
                    if v < 500:
                        fp_adp = int(v)
                        if fp_adp_pos is None:
                            pos_adp = market.get("pos_adp_dd_ppr")
                            if pos_adp is not None:
                                try:
                                    fp_adp_pos = int(float(pos_adp))
                                except Exception:
                                    pass
            except Exception:
                pass

        # FantasyPros season projections (CSV, season totals 596 players, full stat season)
        # Provides Market Season (PFS) points + season stat totals for every draftable,
        # filling the sparse Sleeper weekly starter gap (98/502). Used for Auction season.
        market_season_points = None
        market_season_stats: dict[str, float] = {}
        _fp_season_entry = None
        if fp_projections:
            norm = _normalize_name(p.get("player_display_name") or p.get("player_name") or "")
            _fp_season_entry = fp_projections.get((norm, (team or "").upper(), pos))
            if not _fp_season_entry:
                for (n, t, pp), row in fp_projections.items():
                    if n == norm and pp == pos:
                        _fp_season_entry = row
                        break
            if not _fp_season_entry:
                for (n, t, pp), row in fp_projections.items():
                    if pp == pos and (norm in n or n in norm) and len(norm) > 3:
                        _fp_season_entry = row
                        break
            if _fp_season_entry:
                try:
                    if _fp_season_entry.get("fpts") is not None:
                        market_season_points = float(_fp_season_entry["fpts"])
                except Exception:
                    market_season_points = None
                for mk in ["passing_yards", "passing_tds", "passing_interceptions", "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds", "receptions", "fumbles_lost_total"]:
                    v = _fp_season_entry.get(mk)
                    if v is not None:
                        try:
                            market_season_stats[mk] = float(v)
                        except Exception:
                            pass

        # deltas
        delta_pts = None
        if market_pts is not None:
            delta_pts = round(model_pts - market_pts, 2)
        model_rk = overall_rank.get(pid)
        delta_rank = None
        if fp_ecr is not None and model_rk is not None:
            try:
                delta_rank = int(fp_ecr) - int(model_rk)
            except Exception:
                delta_rank = None
        # pos delta
        delta_pos_rank = None
        if fp_ecr_pos is not None and pos_rank.get(pid) is not None:
            try:
                delta_pos_rank = int(fp_ecr_pos) - int(pos_rank[pid])
            except Exception:
                delta_pos_rank = None

        # Edge label: BUY = model higher than market (delta_pts > 2 or delta_rank > 20)
        # thresholds tuned to bloom filter: rank delta dominated by outliers
        edge = "NEUTRAL"
        edge_score = 0.0
        if delta_rank is not None and fp_ecr is not None:
            # positive delta_rank = market ranks lower (sleeping) => BUY
            if delta_rank >= 12:
                edge = "BUY"
                edge_score = float(delta_rank)
            elif delta_rank <= -12:
                edge = "SELL"
                edge_score = float(delta_rank)
        # market pts delta as secondary: amplify
        if delta_pts is not None:
            if delta_pts >= 3.0 and edge != "SELL":
                edge = "BUY"
                edge_score = max(edge_score, delta_pts * 4)
            elif delta_pts <= -3.0 and edge != "BUY":
                edge = "SELL"
                edge_score = min(edge_score, delta_pts * 4)

        # Stat deltas for panel — weekly (Sleeper weekly starter)
        stat_deltas: list[dict] = []
        for mdl_k, slp_k, label in COMPARE_STATS:
            model_v = p.get(mdl_k)
            market_v = market_stats.get(mdl_k)
            if model_v is not None or market_v is not None:
                try:
                    mv = float(model_v) if model_v is not None else 0.0
                    kv = float(market_v) if market_v is not None else 0.0
                    d = round(mv - kv, 2) if (market_v is not None) else None
                    stat_deltas.append({
                        "key": mdl_k,
                        "label": label,
                        "model": round(mv, 2),
                        "market": round(kv, 2) if market_v is not None else None,
                        "delta": d,
                    })
                except Exception:
                    pass

        # Season deltas — Model season = weekly×17 vs FP season totals (596, full stat season)
        model_season_points = round(model_pts * 17, 1)
        delta_season = round(model_season_points - market_season_points, 1) if market_season_points is not None else None
        # also consider season delta for edge when weekly is missing but season present
        if delta_season is not None:
            if delta_season >= 51 and edge != "SELL":
                edge = "BUY"
                edge_score = max(edge_score, delta_season / 4)
            elif delta_season <= -51 and edge != "BUY":
                edge = "SELL"
                edge_score = min(edge_score, delta_season / 4)
        season_stat_deltas: list[dict] = []
        # Model season stats = weekly stat ×17
        for mdl_k, _slp_k, label in COMPARE_STATS:
            market_s = market_season_stats.get(mdl_k)
            model_w = p.get(mdl_k)
            if model_w is not None or market_s is not None:
                try:
                    mv_s = float(model_w) * 17 if model_w is not None else 0.0
                    kv_s = float(market_s) if market_s is not None else 0.0
                    d_s = round(mv_s - kv_s, 1) if market_s is not None else None
                    # only keep if meaningful (model or market non-zero)
                    if mv_s != 0 or market_s is not None:
                        season_stat_deltas.append({
                            "key": mdl_k,
                            "label": label,
                            "model": round(mv_s, 1),
                            "market": round(kv_s, 1) if market_s is not None else None,
                            "delta": d_s,
                        })
                except Exception:
                    pass

        rows.append({
            "player_id": pid,
            "player_name": p.get("player_display_name") or p.get("player_name") or pid,
            "position": pos,
            "team": team,
            "opponent_team": p.get("opponent_team") or "",
            "model_points": round(model_pts, 2),
            "market_points": round(market_pts, 2) if market_pts is not None else None,
            "delta_points": delta_pts,
            "model_overall_rank": model_rk,
            "model_pos_rank": pos_rank.get(pid),
            "fp_ecr": int(fp_ecr) if fp_ecr is not None else None,
            "fp_ecr_pos": int(fp_ecr_pos) if fp_ecr_pos is not None else None,
            "fp_adp": int(fp_adp) if fp_adp is not None else None,
            "fp_adp_pos": int(fp_adp_pos) if fp_adp_pos is not None else None,
            "fp_tier": int(fp_tier) if fp_tier is not None else None,
            "delta_rank": delta_rank,
            "delta_pos_rank": delta_pos_rank,
            "edge": edge,
            "edge_score": edge_score,
            "stat_deltas": stat_deltas,
            # Season market (FantasyPros CSV season totals) — full stat season for every draftable
            "market_season_points": round(market_season_points, 1) if market_season_points is not None else None,
            "market_season_stats": market_season_stats,
            "model_season_points": model_season_points,
            "delta_season": delta_season,
            "season_stat_deltas": season_stat_deltas,
            # carry model interval for display reuse
            "point_estimate": round(model_pts, 2),
            "projection_lower": p.get("projection_lower"),
            "projection_upper": p.get("projection_upper"),
            "width": p.get("width"),
            "wind_mph": p.get("wind_mph"),
        })

    return rows
