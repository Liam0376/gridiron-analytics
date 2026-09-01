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
    statsguy_rows: list[dict] | None = None,
    actual_by_gsis: dict[str, dict] | None = None,
    draft_prices: dict[str, float] | None = None,
) -> list[dict]:
    """Build enriched comparison rows.

    model_projections: list from build_weekly_projections (each has player_id=gsis_id,
        player_display_name, position, team, projected_points + stat keys).
    market_by_gsis: gsis_id -> {pts_ppr, pass_yd, rush_yd, rec, rec_yd, ...} (Sleeper weekly)
    fpros_players: full fantasypros players list with rank_ecr etc. (CSV full 790)
    fp_projections: FantasyPros season projections keyed by (norm_name, team, pos) -> {fpts, passing_yards...}
                  (596 players, season totals, e.g., Josh Allen 372.5 / 3816 YDS)
    statsguy_by_gsis: Sleeper ID -> gsis mapped StatsGuy values (non_sf_redraft, 500, value 0-10000)

    Returns sorted list (by model_points desc) with delta/rank fields.
    Weekly market (Sleeper) for Projections weekly, season market (FP CSV + StatsGuy) for Auction season.
    """
    fpros_lut = build_fpros_lookup(fpros_players or [])
    # StatsGuy lookup via name+team+pos (Sleeper ID mapping often missing gsis)
    statsguy_lut: dict[tuple, dict] = {}
    if statsguy_rows:
        for r in statsguy_rows:
            name = r.get("name") or r.get("player_name") or ""
            team = (r.get("team") or "").upper()
            pos = (r.get("position") or r.get("position_id") or "").upper()
            if pos == "DST":
                pos = "DEF"
            key = (_normalize_name(name), team, pos)
            if _normalize_name(name):
                statsguy_lut[key] = r

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
    seen_keys: set[tuple[str, str]] = set()
    for p in sorted_model:
        pid = str(p.get("player_id") or p.get("id") or "")
        if not pid:
            continue
        pos = (p.get("position") or p.get("position_group") or "UNK").upper()
        team = p.get("team") or p.get("recent_team") or ""
        norm_name = _normalize_name(p.get("player_display_name") or p.get("player_name") or "")
        if norm_name and pos:
            seen_keys.add((norm_name, pos))
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

        # Actual points / stats (if available)
        actual = actual_by_gsis.get(pid) if actual_by_gsis else None
        actual_pts = None
        actual_stats: dict[str, float] = {}
        if actual:
            if "pts_ppr" in actual or "pts_half_ppr" in actual:
                try:
                    raw_act = actual.get("pts_ppr")
                    if raw_act is None:
                        raw_act = actual.get("pts_half_ppr")
                    if raw_act is not None:
                        actual_pts = float(raw_act)
                except Exception:
                    actual_pts = None
            for mdl_k, slp_k in MODEL_TO_SLEEPER.items():
                v = actual.get(slp_k)
                if v is not None:
                    try:
                        actual_stats[mdl_k] = float(v)
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
                        # FantasyPros QB FPTS uses 4pt pass TD; Sleeper Bahamas uses 5pt.
                        # Align to Sleeper scoring for Apples-to-Apples delta: +1 per pass TD.
                        if pos == "QB" and market_season_points is not None:
                            try:
                                pass_tds_fp = float(_fp_season_entry.get("passing_tds") or 0)
                                market_season_points += pass_tds_fp * 1.0
                                # Also add rough 40+ bonus estimate if not in FP: ~0.15 per pass TD at 1pt
                                # (empirical: ~15% of pass TDs are 40+; Sleeper gives +1)
                                market_season_points += pass_tds_fp * 0.15
                            except Exception:
                                pass
                except Exception:
                    market_season_points = None
                for mk in ["passing_yards", "passing_tds", "passing_interceptions", "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds", "receptions", "fumbles_lost_total"]:
                    v = _fp_season_entry.get(mk)
                    if v is not None:
                        try:
                            market_season_stats[mk] = float(v)
                        except Exception:
                            pass

        # StatsGuy real-trade market (free 500, non_sf_redraft value 0-10000) — name+team+pos join (gsis often missing)
        statsguy_value = None
        statsguy_rank = None
        statsguy_pos_rank = None
        if statsguy_lut:
            sg = _best_fpros_match(p.get("player_display_name") or p.get("player_name") or "", team, pos, statsguy_lut)
            if sg:
                try:
                    if sg.get("value") is not None:
                        statsguy_value = float(sg.get("value"))
                    if sg.get("rank") is not None:
                        statsguy_rank = int(sg.get("rank"))
                    if sg.get("positionRank") is not None:
                        statsguy_pos_rank = int(sg.get("positionRank"))
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

        # Stat deltas for panel — weekly (Sleeper weekly starter) — only meaningful per position
        stat_deltas: list[dict] = []
        for mdl_k, slp_k, label in COMPARE_STATS:
            model_v = p.get(mdl_k)
            market_v = market_stats.get(mdl_k)
            if model_v is not None or market_v is not None:
                try:
                    mv = float(model_v) if model_v is not None else 0.0
                    kv = float(market_v) if market_v is not None else 0.0
                    if abs(mv) > 0.5 or (market_v is not None and abs(kv) > 0.5):
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

        # Model season stats = neutral weekly stat ×17 (not Vegas-boosted)
        _neutral_stats_for_season = p.get("_neutral_stats") or {}
        model_season_stats: dict[str, float] = {}
        for mk in ["passing_yards", "passing_tds", "passing_interceptions", "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds", "receptions", "fumbles_lost_total"]:
            # Prefer neutral stat for season; fallback to Vegas weekly stat
            src_val = _neutral_stats_for_season.get(mk) if _neutral_stats_for_season.get(mk) is not None else p.get(mk)
            if src_val is not None:
                try:
                    model_season_stats[mk] = round(float(src_val) * 17.0, 1)
                except Exception:
                    pass
        if not model_season_stats and market_season_stats:
            model_season_stats = dict(market_season_stats)

        # Season total uses Vegas-neutral weekly (avoid extrapolating Week-1 shootout to 17 games)
        neutral_pts = p.get("_neutral_points") if p.get("_neutral_points") is not None else model_pts
        _raw_model_season = round(neutral_pts * 17, 1) if neutral_pts > 0 else (round(market_season_points, 1) if market_season_points is not None else 0.0)
        # Shrink extreme deltas toward market to avoid overconfidence (model MAE ~4.5 ≈ 76/season)
        # Empirical: delta >51 is >3 pts/wk ~0.7σ; shrink 20% toward market for stability
        model_season_points = _raw_model_season
        if market_season_points is not None and _raw_model_season is not None:
            raw_delta = _raw_model_season - market_season_points
            if abs(raw_delta) >= 51:
                # Pull 20% toward market (conservative) — preserves direction but moderates $ impact
                model_season_points = round(0.80 * _raw_model_season + 0.20 * market_season_points, 1)
                # Recompute neutral stats proportionally
                _shrink_factor = model_season_points / _raw_model_season if _raw_model_season else 1.0
                for _k in list(model_season_stats.keys()):
                    model_season_stats[_k] = round(model_season_stats[_k] * _shrink_factor, 1)
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
        # Model season stats = neutral weekly stat ×17 (not Vegas-boosted weekly)
        for mdl_k, _slp_k, label in COMPARE_STATS:
            market_s = market_season_stats.get(mdl_k)
            # Prefer neutral stat for season; fallback to Vegas weekly stat
            model_w = _neutral_stats_for_season.get(mdl_k) if _neutral_stats_for_season.get(mdl_k) is not None else p.get(mdl_k)
            if model_w is not None or market_s is not None:
                try:
                    mv_s = float(model_w) * 17 if model_w is not None else 0.0
                    kv_s = float(market_s) if market_s is not None else 0.0
                    d_s = round(mv_s - kv_s, 1) if market_s is not None else None
                    # keep only if either side is meaningful (>0.5 yards or >0.05 TD/rec)
                    if abs(mv_s) > 0.5 or (market_s is not None and abs(kv_s) > 0.5):
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
            "actual_points": round(actual_pts, 2) if actual_pts is not None else None,
            "delta_points": delta_pts,
            "actual_delta_model": round(actual_pts - model_pts, 2) if actual_pts is not None else None,
            "actual_delta_market": round(actual_pts - market_pts, 2) if (actual_pts is not None and market_pts is not None) else None,
            "model_error": round(abs(model_pts - actual_pts), 2) if actual_pts is not None else None,
            "market_error": round(abs(market_pts - actual_pts), 2) if (actual_pts is not None and market_pts is not None) else None,
            "model_overall_rank": model_rk,
            "model_pos_rank": pos_rank.get(pid),
            "fp_ecr": int(fp_ecr) if fp_ecr is not None else None,
            "fp_ecr_pos": int(fp_ecr_pos) if fp_ecr_pos is not None else None,
            "fp_adp": int(fp_adp) if fp_adp is not None else None,
            "fp_adp_pos": int(fp_adp_pos) if fp_adp_pos is not None else None,
            "fp_tier": int(fp_tier) if fp_tier is not None else None,
            "statsguy_value": round(statsguy_value, 1) if statsguy_value is not None else None,
            "statsguy_rank": statsguy_rank,
            "statsguy_pos_rank": statsguy_pos_rank,
            "auction_price_paid": draft_prices.get(pid) if draft_prices else None,
            # Auction $ is VOR-derived (computed in VOR loop below), not paid amount.
            # Keep paid separately; do not conflate draft price with market value.
            "marketAuction": None,
            "auction": 0,
            "deltaAuction": None,
            "delta_rank": delta_rank,
            "delta_pos_rank": delta_pos_rank,
            "edge": edge,
            "edge_score": edge_score,
            "stat_deltas": stat_deltas,
            # Season market (FantasyPros CSV season totals) — full stat season for every draftable
            "market_season_points": round(market_season_points, 1) if market_season_points is not None else None,
            "market_season_stats": market_season_stats,
            "model_season_points": model_season_points,
            "model_season_stats": model_season_stats,
            "delta_season": delta_season,
            "season_stat_deltas": season_stat_deltas,
            # carry model interval for display reuse
            "point_estimate": round(model_pts, 2),
            "projection_lower": p.get("projection_lower"),
            "projection_upper": p.get("projection_upper"),
            "width": p.get("width"),
            "interval_width": float(p.get("width") or p.get("projection_width") or 5.0),
            "wind_mph": p.get("wind_mph"),
        })

    # Fallback pass: Add all draftable market players (CSVs, FP season projs, StatsGuy) not captured in model_projections
    market_fallback_candidates: list[dict] = []
    for fp in (fpros_players or []):
        name = fp.get("player_name") or fp.get("short_name") or ""
        norm = _normalize_name(name)
        pos = (fp.get("position_id") or fp.get("position") or "").upper()
        if pos == "DST": pos = "DEF"
        if not norm or not pos or (norm, pos) in seen_keys:
            continue
        seen_keys.add((norm, pos))
        team = (fp.get("team_id") or fp.get("team") or "").upper()
        pid = f"fp_{fp.get('rank_ecr') or fp.get('rank_adp') or len(rows)+1}_{norm.replace(' ', '_')}"

        # check FP season projections
        m_pts = None
        m_stats: dict[str, float] = {}
        if fp_projections:
            proj_row = fp_projections.get((norm, team, pos))
            if not proj_row:
                for (n, t, pp), r_row in fp_projections.items():
                    if n == norm and pp == pos: proj_row = r_row; break
            if proj_row:
                try:
                    if proj_row.get("fpts") is not None: m_pts = float(proj_row["fpts"])
                except Exception: pass
                for mk in ["passing_yards", "passing_tds", "passing_interceptions", "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds", "receptions", "fumbles_lost_total"]:
                    if proj_row.get(mk) is not None:
                        try: m_stats[mk] = float(proj_row[mk])
                        except Exception: pass

        # check StatsGuy
        sg_val = None; sg_rk = None; sg_pos_rk = None
        if statsguy_lut:
            sg = _best_fpros_match(name, team, pos, statsguy_lut)
            if sg:
                try:
                    if sg.get("value") is not None: sg_val = float(sg["value"])
                    if sg.get("rank") is not None: sg_rk = int(sg["rank"])
                    if sg.get("positionRank") is not None: sg_pos_rk = int(sg["positionRank"])
                except Exception: pass

        ecr = fp.get("rank_ecr_ppr") or fp.get("rank_ecr")
        ecr_pos = fp.get("rank_ecr_pos")
        adp = fp.get("rank_adp_ppr") or fp.get("rank_adp")
        adp_pos = fp.get("rank_adp_pos")
        tier = fp.get("tier")

        # Use FP season total as model source when Gridiron has no data (preseason)
        model_pts_fp = m_pts / 17.0 if m_pts is not None else 0.0

        rows.append({
            "player_id": pid,
            "player_name": name,
            "position": pos,
            "team": team,
            "opponent_team": "",
            "model_points": round(model_pts_fp, 2),
            "market_points": round(m_pts / 17.0, 2) if m_pts is not None else None,
            "delta_points": round(model_pts_fp - (m_pts / 17.0), 2) if m_pts is not None else None,
            "model_overall_rank": None,
            "model_pos_rank": None,
            "fp_ecr": int(ecr) if ecr else None,
            "fp_ecr_pos": int(ecr_pos) if ecr_pos else None,
            "fp_adp": int(adp) if adp else None,
            "fp_adp_pos": int(adp_pos) if adp_pos else None,
            "fp_tier": int(tier) if tier else None,
            "statsguy_value": round(sg_val, 1) if sg_val is not None else None,
            "statsguy_rank": sg_rk,
            "statsguy_pos_rank": sg_pos_rk,
            "delta_rank": None,
            "delta_pos_rank": None,
            "edge": "NEUTRAL",
            "edge_score": 0.0,
            "stat_deltas": [],
            "market_season_points": round(m_pts, 1) if m_pts is not None else None,
            "market_season_stats": m_stats,
            "model_season_points": round(m_pts, 1) if m_pts is not None else 0.0,
            "model_season_stats": m_stats,
            "delta_season": 0.0 if m_pts is not None else None,
            "season_stat_deltas": [],
            "point_estimate": round(model_pts_fp, 2),
            "projection_lower": None,
            "projection_upper": None,
            "width": 20.0,
            "interval_width": 5.0,
            "wind_mph": None,
        })

    # Calculate Auction ($ Gridiron VOR) & Market Auction ($ FP/SG consensus)
    # 12 teams × $200 = $2400 pool; 48 bench at $1 → $2352 starter budget (10 starters ×12)
    # (legacy 2040 was incorrect — assumed 5 bench? Now aligned with auction.js and vbdAuction.js)
    # Note: K/DEF are devalued to $1 in practice but VBD still allocates proportional; we clamp
    # K/DEF later to $1 to match real draft behavior where they are streamed.
    starter_budget_pool = 2352.0
    # Replacement counts: positional starters for 12-team 2-FLEX: QB12, RB24+? Actually 2 RB +2 WR +2 FLEX
    # RB28/WR32 reflect realistic starters after flex (24 RB/WR base + 4/8 flex share). Keep RB28/WR32
    # TE12 stable (only 12 TE starters). K12/DEF12 included but will be clamped to $1 post-VBD.
    pos_repl_counts = {"QB": 12, "RB": 28, "WR": 32, "TE": 12, "K": 12, "DEF": 12}

    model_repl_pts = {}
    for pos_k, count in pos_repl_counts.items():
        pos_rows = [r for r in rows if r.get("position") == pos_k and r.get("model_season_points") is not None]
        pos_rows.sort(key=lambda r: float(r["model_season_points"]), reverse=True)
        if len(pos_rows) >= count:
            model_repl_pts[pos_k] = float(pos_rows[count - 1]["model_season_points"])
        elif pos_rows:
            model_repl_pts[pos_k] = float(pos_rows[-1]["model_season_points"]) * 0.8
        else:
            model_repl_pts[pos_k] = 100.0

    market_repl_pts = {}
    for pos_k, count in pos_repl_counts.items():
        pos_rows = [r for r in rows if r.get("position") == pos_k and r.get("market_season_points") is not None]
        pos_rows.sort(key=lambda r: float(r["market_season_points"]), reverse=True)
        if len(pos_rows) >= count:
            market_repl_pts[pos_k] = float(pos_rows[count - 1]["market_season_points"])
        elif pos_rows:
            market_repl_pts[pos_k] = float(pos_rows[-1]["market_season_points"]) * 0.8
        else:
            market_repl_pts[pos_k] = 100.0

    # Positional scarcity adjustment: dynamic from market vs model share (audit 2026-09-01 follow-on)
    # Pure VOR overvalues QB/TE in 1QB (QB 11% vs market 6%). Derive weight = market_share / model_share per pos,
    # clamped to [0.5, 1.5] to avoid overcorrection when a position has thin market data.
    # K/DEF streamed $1 → weight 0 (excluded from pool, already accounted via 2352=2400-48).
    def _raw_vor(season_pts, pos, repl_map):
        return max(0.0, float(season_pts or 0) - repl_map.get(pos, 100.0))

    # Raw totals per position for share calculation
    _raw_model_per_pos = {pos: 0.0 for pos in pos_repl_counts}
    _raw_market_per_pos = {pos: 0.0 for pos in pos_repl_counts}
    for r in rows:
        pos = r.get("position")
        if pos in _raw_model_per_pos:
            _raw_model_per_pos[pos] += _raw_vor(r.get("model_season_points"), pos, model_repl_pts)
            _raw_market_per_pos[pos] += _raw_vor(r.get("market_season_points"), pos, market_repl_pts)
    _raw_model_total = sum(_raw_model_per_pos.values()) or 1.0
    _raw_market_total = sum(_raw_market_per_pos.values()) or 1.0
    POS_WEIGHT = {}
    for pos in pos_repl_counts:
        if pos in ("K", "DEF", "DST"):
            POS_WEIGHT[pos] = 0.0
        else:
            model_share = _raw_model_per_pos[pos] / _raw_model_total if _raw_model_total else 0
            market_share = _raw_market_per_pos[pos] / _raw_market_total if _raw_market_total else 0
            if model_share > 0 and market_share > 0:
                w = market_share / model_share
                POS_WEIGHT[pos] = max(0.5, min(1.5, w))
            else:
                # Fallback to previous empirical if insufficient data
                POS_WEIGHT[pos] = {"QB": 0.65, "RB": 1.10, "WR": 0.92, "TE": 0.78}.get(pos, 1.0)
    def _weighted_vor(season_pts, pos, repl_map):
        raw = _raw_vor(season_pts, pos, repl_map)
        return raw * POS_WEIGHT.get(pos, 1.0)

    total_model_vor = sum(_weighted_vor(r.get("model_season_points"), r.get("position"), model_repl_pts) for r in rows) or 1.0
    total_market_vor = sum(_weighted_vor(r.get("market_season_points"), r.get("position"), market_repl_pts) for r in rows) or 1.0

    for r in rows:
        pos_k = r.get("position")
        msp = r.get("model_season_points")
        mk_sp = r.get("market_season_points")
        sg_val = r.get("statsguy_value")

        # K/DEF are streamed at $1 in real 12-team drafts — cap VOR-derived auction to $1
        # even if VOR technically positive due to model overprojection (K daily noise MAE 4.09)
        # Also compute uncapped true value for display ($1 bench still shows true bench value)
        is_streamer_pos = pos_k in ("K", "DEF", "DST")
        m_vor = _weighted_vor(msp, pos_k, model_repl_pts)
        # Uncapped true VOR $ (no floor) — for bench VOR 0, show points-based bench value so $1 ($0) not empty
        if m_vor > 0:
            m_uncapped = int(round((m_vor / total_model_vor) * starter_budget_pool)) if total_model_vor else 0
        elif msp and msp > 50:
            # Bench true value: linear bench scale so Godwin 10.5→$3, Dowdle 11.6→$4 (regardless of VOR 0)
            # Uses weekly proxy: model season /17 *0.35 ≈ $2-5 for WR3/RB3
            _weekly_proxy = (msp or 0) / 17.0
            m_uncapped = max(1, int(round(_weekly_proxy * 0.35)))
            # Clamp to $1-5 bench range to avoid inflating
            m_uncapped = max(1, min(5, m_uncapped))
        else:
            m_uncapped = 0
        r["auctionUncapped"] = m_uncapped
        r["vor"] = round(m_vor, 1)
        if is_streamer_pos:
            # K/DEF: $1 always except top-3 kickers at $2-3 if truly elite
            if m_vor > 40:
                auction_val = 2
            elif m_vor > 0 and (msp or 0) > 130:
                auction_val = 1
            else:
                auction_val = 1 if (msp and msp > 50) else 0
        else:
            if m_vor > 0:
                auction_val = max(1, int(round((m_vor / total_model_vor) * starter_budget_pool)))
            elif msp and msp > 50:
                auction_val = 1
            else:
                auction_val = 0
        r["auction"] = auction_val

        mk_vor = _weighted_vor(mk_sp, pos_k, market_repl_pts)
        if mk_vor > 0:
            mk_uncapped = int(round((mk_vor / total_market_vor) * starter_budget_pool)) if total_market_vor else 0
        elif mk_sp and mk_sp > 50:
            _weekly_proxy = (mk_sp or 0) / 17.0
            mk_uncapped = max(1, int(round(_weekly_proxy * 0.35)))
            mk_uncapped = max(1, min(5, mk_uncapped))
        else:
            mk_uncapped = 0
        r["marketAuctionUncapped"] = mk_uncapped
        r["marketVor"] = round(mk_vor, 1)
        if is_streamer_pos:
            if mk_vor > 40:
                mk_auction_val = 2
            elif mk_vor > 0 and (mk_sp or 0) > 110:
                mk_auction_val = 1
            elif sg_val is not None and sg_val > 0:
                mk_auction_val = 1
            elif mk_sp and mk_sp > 50:
                mk_auction_val = 1
            else:
                mk_auction_val = None
        else:
            if mk_vor > 0:
                mk_auction_val = max(1, int(round((mk_vor / total_market_vor) * starter_budget_pool)))
            elif sg_val is not None and sg_val > 0:
                mk_auction_val = max(1, int(round((sg_val / 9500.0) ** 1.2 * 65.0)))
            elif mk_sp and mk_sp > 50:
                mk_auction_val = 1
            else:
                mk_auction_val = None
        r["marketAuction"] = mk_auction_val

        # Delta vs paid takes precedence if this player was drafted (real $ edge),
        # otherwise vs market consensus VOR.
        _paid = draft_prices.get(r.get("player_id")) if draft_prices else None
        if _paid is not None:
            r["deltaAuction"] = int(auction_val - _paid)
        elif auction_val is not None and mk_auction_val is not None:
            r["deltaAuction"] = int(auction_val - mk_auction_val)
        else:
            r["deltaAuction"] = None

    return rows
