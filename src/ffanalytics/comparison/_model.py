"""Model projection loop, FantasyPros / StatsGuy lookup, row assembly.

Pure functions over dicts; takes a list of model projections plus the
already-built lookup tables from the orchestrator and produces a list of
comparison rows enriched with ranks, market joins, stat deltas, and season
totals. Edge labeling lives in ``_edge`` and is applied as a post-step.
"""

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

from ._common import (
    COMPARE_STATS,
    MODEL_TO_SLEEPER,
    _best_fpros_match,
    _normalize_name,
    build_fpros_lookup,
)
from ._edge import apply_edge_rules


_SEASON_STAT_KEYS = (
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "rushing_yards",
    "rushing_tds",
    "receiving_yards",
    "receiving_tds",
    "receptions",
    "fumbles_lost_total",
)


def build_lookups(
    fpros_players: list[dict] | None,
    statsguy_rows: list[dict] | None,
) -> tuple[dict, dict]:
    fpros_lut = build_fpros_lookup(fpros_players or [])
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
    return fpros_lut, statsguy_lut


def _rank_model(
    model_projections: list[dict],
) -> tuple[list[dict], dict[str, int], dict[str, int]]:
    sorted_model = sorted(
        model_projections,
        key=lambda p: float(p.get("projected_points") or p.get("point_estimate") or 0),
        reverse=True,
    )
    overall_rank: dict[str, int] = {}
    pos_rank: dict[str, int] = {}
    pos_counters: dict[str, int] = defaultdict(int)
    for idx, p in enumerate(sorted_model, start=1):
        pid = str(p.get("player_id") or p.get("id") or "")
        if not pid:
            continue
        overall_rank[pid] = idx
        pos = (p.get("position") or p.get("position_group") or "").upper()
        pos_counters[pos] += 1
        pos_rank[pid] = pos_counters[pos]
    return sorted_model, overall_rank, pos_rank


def _market_points_and_stats(market: dict | None) -> tuple[float | None, dict[str, float]]:
    market_pts: float | None = None
    market_stats: dict[str, float] = {}
    if not market:
        return market_pts, market_stats
    if "pts_ppr" in market or "pts_half_ppr" in market:
        try:
            raw = market.get("pts_ppr")
            if raw is None:
                raw = market.get("pts_half_ppr")
            if raw is not None:
                market_pts = float(raw)
        except Exception:
            market_pts = None
    for mdl_k, slp_k in MODEL_TO_SLEEPER.items():
        v = market.get(slp_k)
        if v is not None:
            try:
                market_stats[mdl_k] = float(v)
            except Exception:
                pass
    return market_pts, market_stats


def _actual_points_and_stats(actual: dict | None) -> tuple[float | None, dict[str, float]]:
    actual_pts: float | None = None
    actual_stats: dict[str, float] = {}
    if not actual:
        return actual_pts, actual_stats
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
    return actual_pts, actual_stats


def _fpros_fields(fpros: dict | None) -> tuple:
    fp_ecr = None
    fp_ecr_pos = None
    fp_adp = None
    fp_adp_pos = None
    fp_tier = None
    if not fpros:
        return fp_ecr, fp_ecr_pos, fp_adp, fp_adp_pos, fp_tier
    fp_ecr = fpros.get("rank_ecr_ppr") if fpros.get("rank_ecr_ppr") else fpros.get("rank_ecr")
    fp_ecr_pos = fpros.get("rank_ecr_pos")
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
    return fp_ecr, fp_ecr_pos, fp_adp, fp_adp_pos, fp_tier


def _sleeper_adp_fallback(
    market: dict | None,
    fp_adp,
    fp_adp_pos,
) -> tuple[Any, Any]:
    """Fill fp_adp from Sleeper's ADP when FP didn't provide one."""
    if fp_adp is not None or not market:
        return fp_adp, fp_adp_pos
    try:
        sleeper_adp = (
            market.get("adp_dd_ppr")
            if market.get("adp_dd_ppr") is not None
            else market.get("pos_adp_dd_ppr")
        )
        if sleeper_adp is None:
            return fp_adp, fp_adp_pos
        v = float(sleeper_adp)
        if v < 500:
            new_adp = int(v)
            new_pos = fp_adp_pos
            if fp_adp_pos is None:
                pos_adp = market.get("pos_adp_dd_ppr")
                if pos_adp is not None:
                    try:
                        new_pos = int(float(pos_adp))
                    except Exception:
                        pass
            return new_adp, new_pos
    except Exception:
        pass
    return fp_adp, fp_adp_pos


def _resolve_fp_season_entry(
    p: dict,
    pos: str,
    team: str,
    fp_projections: dict[tuple, dict] | None,
) -> dict | None:
    if not fp_projections:
        return None
    norm = _normalize_name(p.get("player_display_name") or p.get("player_name") or "")
    entry = fp_projections.get((norm, (team or "").upper(), pos))
    if entry:
        return entry
    for (n, _t, pp), row in fp_projections.items():
        if n == norm and pp == pos:
            return row
    for (n, _t, pp), row in fp_projections.items():
        if pp == pos and (norm in n or n in norm) and len(norm) > 3:
            return row
    return None


def _fp_season_points_and_stats(
    entry: dict | None,
    pos: str,
) -> tuple[float | None, dict[str, float]]:
    market_season_points: float | None = None
    market_season_stats: dict[str, float] = {}
    if not entry:
        return market_season_points, market_season_stats
    try:
        if entry.get("fpts") is not None:
            market_season_points = float(entry["fpts"])
            if pos == "QB" and market_season_points is not None:
                try:
                    pass_tds_fp = float(entry.get("passing_tds") or 0)
                    market_season_points += pass_tds_fp * 1.0
                    market_season_points += pass_tds_fp * 0.15
                except Exception:
                    pass
    except Exception:
        market_season_points = None
    for mk in _SEASON_STAT_KEYS:
        v = entry.get(mk)
        if v is not None:
            try:
                market_season_stats[mk] = float(v)
            except Exception:
                pass
    return market_season_points, market_season_stats


def _statsguy_fields(
    p: dict,
    team: str,
    pos: str,
    statsguy_lut: dict,
) -> tuple[float | None, int | None, int | None]:
    if not statsguy_lut:
        return None, None, None
    sg = _best_fpros_match(
        p.get("player_display_name") or p.get("player_name") or "",
        team,
        pos,
        statsguy_lut,
    )
    if not sg:
        return None, None, None
    sg_val = None
    sg_rk = None
    sg_pos_rk = None
    try:
        if sg.get("value") is not None:
            sg_val = float(sg.get("value"))
        if sg.get("rank") is not None:
            sg_rk = int(sg.get("rank"))
        if sg.get("positionRank") is not None:
            sg_pos_rk = int(sg.get("positionRank"))
    except Exception:
        pass
    return sg_val, sg_rk, sg_pos_rk


def _build_stat_deltas(
    p: dict,
    market_stats: dict[str, float],
) -> list[dict]:
    stat_deltas: list[dict] = []
    for mdl_k, _slp_k, label in COMPARE_STATS:
        model_v = p.get(mdl_k)
        market_v = market_stats.get(mdl_k)
        if model_v is None and market_v is None:
            continue
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
    return stat_deltas


def _compute_season_totals(
    p: dict,
    market_season_points: float | None,
    market_season_stats: dict[str, float],
) -> tuple[float, dict[str, float], float | None]:
    # Uses neutral-points/stats to avoid extrapolating a Week-1 shootout to
    # 17 games; shrinks raw delta >= 51 toward market by 20%.
    _neutral_stats_for_season = p.get("_neutral_stats") or {}
    model_season_stats: dict[str, float] = {}
    for mk in _SEASON_STAT_KEYS:
        src_val = (
            _neutral_stats_for_season.get(mk)
            if _neutral_stats_for_season.get(mk) is not None
            else p.get(mk)
        )
        if src_val is not None:
            try:
                model_season_stats[mk] = round(float(src_val) * 17.0, 1)
            except Exception:
                pass
    if not model_season_stats and market_season_stats:
        model_season_stats = dict(market_season_stats)

    neutral_pts = p.get("_neutral_points") if p.get("_neutral_points") is not None else float(
        p.get("projected_points") or p.get("point_estimate") or 0
    )
    _raw_model_season = (
        round(neutral_pts * 17, 1)
        if neutral_pts > 0
        else (round(market_season_points, 1) if market_season_points is not None else 0.0)
    )
    model_season_points = _raw_model_season
    if market_season_points is not None and _raw_model_season is not None:
        raw_delta = _raw_model_season - market_season_points
        if abs(raw_delta) >= 51:
            model_season_points = round(
                0.80 * _raw_model_season + 0.20 * market_season_points, 1
            )
            shrink_factor = (
                model_season_points / _raw_model_season if _raw_model_season else 1.0
            )
            for k in list(model_season_stats.keys()):
                model_season_stats[k] = round(model_season_stats[k] * shrink_factor, 1)
    delta_season = (
        round(model_season_points - market_season_points, 1)
        if market_season_points is not None
        else None
    )
    return model_season_points, model_season_stats, delta_season


def _build_season_stat_deltas(
    p: dict,
    market_season_stats: dict[str, float],
) -> list[dict]:
    season_stat_deltas: list[dict] = []
    _neutral_stats_for_season = p.get("_neutral_stats") or {}
    for mdl_k, _slp_k, label in COMPARE_STATS:
        market_s = market_season_stats.get(mdl_k)
        model_w = (
            _neutral_stats_for_season.get(mdl_k)
            if _neutral_stats_for_season.get(mdl_k) is not None
            else p.get(mdl_k)
        )
        if model_w is None and market_s is None:
            continue
        try:
            mv_s = float(model_w) * 17 if model_w is not None else 0.0
            kv_s = float(market_s) if market_s is not None else 0.0
            d_s = round(mv_s - kv_s, 1) if market_s is not None else None
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
    return season_stat_deltas


def build_model_rows(
    sorted_model: list[dict],
    overall_rank: dict[str, int],
    pos_rank: dict[str, int],
    market_by_gsis: dict[str, dict],
    fpros_lut: dict,
    statsguy_lut: dict,
    fp_projections: dict[tuple, dict] | None,
    actual_by_gsis: dict[str, dict] | None,
    draft_prices: dict[str, float] | None,
    sleeper_to_gsis: dict[str, str] | None = None,
    gsis_to_sleeper: dict[str, str] | None = None,
) -> tuple[list[dict], set[tuple[str, str]]]:
    rows: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    reverse_map: dict[str, str] = dict(gsis_to_sleeper or {})

    for p in sorted_model:
        pid = str(p.get("player_id") or p.get("id") or "")
        if not pid:
            continue
        sleeper_id_for_this_pid = reverse_map.get(pid) or ""
        pos = (p.get("position") or p.get("position_group") or "UNK").upper()
        team = p.get("team") or p.get("recent_team") or ""
        norm_name = _normalize_name(p.get("player_display_name") or p.get("player_name") or "")
        if norm_name and pos:
            seen_keys.add((norm_name, pos))
        model_pts = float(p.get("projected_points") or p.get("point_estimate") or 0)

        market = market_by_gsis.get(pid)
        market_pts, market_stats = _market_points_and_stats(market)

        actual = actual_by_gsis.get(pid) if actual_by_gsis else None
        actual_pts, actual_stats = _actual_points_and_stats(actual)

        fpros = _best_fpros_match(
            p.get("player_display_name") or p.get("player_name") or "",
            team,
            pos,
            fpros_lut,
        )
        fp_ecr, fp_ecr_pos, fp_adp, fp_adp_pos, fp_tier = _fpros_fields(fpros)
        fp_adp, fp_adp_pos = _sleeper_adp_fallback(market, fp_adp, fp_adp_pos)

        fp_entry = _resolve_fp_season_entry(p, pos, team, fp_projections)
        market_season_points, market_season_stats = _fp_season_points_and_stats(fp_entry, pos)

        statsguy_value, statsguy_rank, statsguy_pos_rank = _statsguy_fields(
            p, team, pos, statsguy_lut
        )

        delta_pts = round(model_pts - market_pts, 2) if market_pts is not None else None
        model_rk = overall_rank.get(pid)
        delta_rank = (
            int(fp_ecr) - int(model_rk)
            if fp_ecr is not None and model_rk is not None
            else None
        )
        delta_pos_rank = (
            int(fp_ecr_pos) - int(pos_rank.get(pid))
            if fp_ecr_pos is not None and pos_rank.get(pid) is not None
            else None
        )

        edge, edge_score = apply_edge_rules(delta_rank, fp_ecr, delta_pts, None)

        stat_deltas = _build_stat_deltas(p, market_stats)
        model_season_points, model_season_stats, delta_season = _compute_season_totals(
            p, market_season_points, market_season_stats
        )
        # may also flip edge
        if delta_season is not None:
            edge, edge_score = apply_edge_rules(
                delta_rank, fp_ecr, delta_pts, delta_season,
                current_edge=edge, current_score=edge_score,
            )
        season_stat_deltas = _build_season_stat_deltas(p, market_season_stats)

        rows.append({
            "player_id": pid,
            "sleeper_id": sleeper_id_for_this_pid,
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
            # Auction $ is VOR-derived (computed in VOR loop), not paid amount.
            # Keep paid separately; do not conflate draft price with market value.
            "marketAuction": None,
            "auction": 0,
            "deltaAuction": None,
            "delta_rank": delta_rank,
            "delta_pos_rank": delta_pos_rank,
            "edge": edge,
            "edge_score": edge_score,
            "stat_deltas": stat_deltas,
            "market_season_points": round(market_season_points, 1) if market_season_points is not None else None,
            "market_season_stats": market_season_stats,
            "model_season_points": model_season_points,
            "model_season_stats": model_season_stats,
            "delta_season": delta_season,
            "season_stat_deltas": season_stat_deltas,
            "point_estimate": round(model_pts, 2),
            "projection_lower": p.get("projection_lower"),
            "projection_upper": p.get("projection_upper"),
            "width": p.get("width"),
            "interval_width": float(p.get("width") or p.get("projection_width") or 5.0),
            "wind_mph": p.get("wind_mph"),
        })

    return rows, seen_keys


def build_fallback_rows(
    fpros_players: list[dict] | None,
    fp_projections: dict[tuple, dict] | None,
    statsguy_lut: dict,
    seen_keys: set[tuple[str, str]],
    starting_len: int,
    name_to_sleeper: dict[str, str] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    name_to_sleeper = name_to_sleeper or {}
    for fp in (fpros_players or []):
        name = fp.get("player_name") or fp.get("short_name") or ""
        norm = _normalize_name(name)
        pos = (fp.get("position_id") or fp.get("position") or "").upper()
        if pos == "DST":
            pos = "DEF"
        if not norm or not pos or (norm, pos) in seen_keys:
            continue
        seen_keys.add((norm, pos))
        team = (fp.get("team_id") or fp.get("team") or "").upper()
        pid = f"fp_{fp.get('rank_ecr') or fp.get('rank_adp') or starting_len + len(rows) + 1}_{norm.replace(' ', '_')}"
        fallback_sleeper_id = name_to_sleeper.get(norm) or ""

        m_pts = None
        m_stats: dict[str, float] = {}
        if fp_projections:
            proj_row = fp_projections.get((norm, team, pos))
            if not proj_row:
                for (n, _t, pp), r_row in fp_projections.items():
                    if n == norm and pp == pos:
                        proj_row = r_row
                        break
            if proj_row:
                try:
                    if proj_row.get("fpts") is not None:
                        m_pts = float(proj_row["fpts"])
                except Exception:
                    logger.exception("comparison._model: failed parsing fp_proj fpts for %s", name)
                for mk in _SEASON_STAT_KEYS:
                    if proj_row.get(mk) is not None:
                        try:
                            m_stats[mk] = float(proj_row[mk])
                        except Exception:
                            logger.exception("comparison._model: failed parsing fp_proj %s for %s", mk, name)

        sg_val = None
        sg_rk = None
        sg_pos_rk = None
        if statsguy_lut:
            sg = _best_fpros_match(name, team, pos, statsguy_lut)
            if sg:
                try:
                    if sg.get("value") is not None:
                        sg_val = float(sg["value"])
                    if sg.get("rank") is not None:
                        sg_rk = int(sg["rank"])
                    if sg.get("positionRank") is not None:
                        sg_pos_rk = int(sg["positionRank"])
                except Exception:
                    logger.exception("comparison._model: failed parsing statsguy row for %s", name)

        ecr = fp.get("rank_ecr_ppr") or fp.get("rank_ecr")
        ecr_pos = fp.get("rank_ecr_pos")
        adp = fp.get("rank_adp_ppr") or fp.get("rank_adp")
        adp_pos = fp.get("rank_adp_pos")
        tier = fp.get("tier")

        model_pts_fp = m_pts / 17.0 if m_pts is not None else 0.0

        rows.append({
            "player_id": pid,
            "sleeper_id": fallback_sleeper_id,
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
    return rows