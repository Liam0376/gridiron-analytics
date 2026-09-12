"""Auction VOR, market auction consensus, and K/DEF streamer handling.
12 teams × $200 = $2400 pool; 48 bench at $1 → $2352 starter budget.
K/DEF devalued to $1 in practice — clamped here. Positional scarcity weight =
market_share / model_share, clamped [0.5, 1.5] to avoid thin-data overcorrection."""


_STARTER_BUDGET_POOL = 2352.0
_POS_REPL_COUNTS = {"QB": 12, "RB": 28, "WR": 32, "TE": 12, "K": 12, "DEF": 12}
_FALLBACK_WEIGHTS = {"QB": 0.65, "RB": 1.10, "WR": 0.92, "TE": 0.78, "K": 0.0, "DEF": 0.0, "DST": 0.0}
_STREAMER_POS = ("K", "DEF", "DST")


def _replacement_points(
    rows: list[dict],
    pos: str,
    count: int,
    points_key: str,
) -> float:
    pos_rows = [
        r for r in rows
        if r.get("position") == pos and r.get(points_key) is not None
    ]
    pos_rows.sort(key=lambda r: float(r[points_key]), reverse=True)
    if len(pos_rows) >= count:
        return float(pos_rows[count - 1][points_key])
    if pos_rows:
        return float(pos_rows[-1][points_key]) * 0.8
    return 100.0


def _raw_vor(season_pts, pos: str, repl_map: dict) -> float:
    return max(0.0, float(season_pts or 0) - repl_map.get(pos, 100.0))


def _build_pos_weights(rows: list[dict], repl_counts: dict | None = None) -> dict[str, float]:
    repl_counts = repl_counts or _POS_REPL_COUNTS
    pos_weights = {pos: 1.0 for pos in repl_counts}
    model_repl_pts = {
        p: _replacement_points(rows, p, c, "model_season_points")
        for p, c in repl_counts.items()
    }
    market_repl_pts = {
        p: _replacement_points(rows, p, c, "market_season_points")
        for p, c in repl_counts.items()
    }

    raw_model_per_pos: dict[str, float] = {p: 0.0 for p in repl_counts}
    raw_market_per_pos: dict[str, float] = {p: 0.0 for p in repl_counts}
    for r in rows:
        pos = r.get("position")
        if pos in repl_counts:
            raw_model_per_pos[pos] += _raw_vor(r.get("model_season_points"), pos, model_repl_pts)
            raw_market_per_pos[pos] += _raw_vor(r.get("market_season_points"), pos, market_repl_pts)
    raw_model_total = sum(raw_model_per_pos.values()) or 1.0
    raw_market_total = sum(raw_market_per_pos.values()) or 1.0

    for pos in repl_counts:
        if pos in ("K", "DEF", "DST"):
            pos_weights[pos] = 0.0
            continue
        model_share = raw_model_per_pos[pos] / raw_model_total if raw_model_total else 0
        market_share = raw_market_per_pos[pos] / raw_market_total if raw_market_total else 0
        if model_share > 0 and market_share > 0:
            w = market_share / model_share
            pos_weights[pos] = max(0.5, min(1.5, w))
        else:
            pos_weights[pos] = _FALLBACK_WEIGHTS.get(pos, 1.0)
    return pos_weights


def _weighted_vor(season_pts, pos: str, repl_map: dict, pos_weights: dict) -> float:
    raw = _raw_vor(season_pts, pos, repl_map)
    # why streamer default 0.0 (correctness batch 2026-09-12): DST rows never
    # get a weight entry (repl_counts has DEF, not DST), so .get default 1.0
    # minted unweighted VOR. Streamers weight 0 outside this map.
    default_w = 0.0 if pos in _STREAMER_POS else 1.0
    return raw * pos_weights.get(pos, default_w)


def _uncapped_auction_value(
    season_pts,
    weighted_vor: float,
    total_weighted_vor: float,
    pos: str,
    pool: float | None = None,
) -> int:
    pool = _STARTER_BUDGET_POOL if pool is None else pool
    if weighted_vor > 0:
        return int(round((weighted_vor / total_weighted_vor) * pool)) if total_weighted_vor else 0
    if season_pts and season_pts > 50:
        weekly_proxy = (season_pts or 0) / 17.0
        val = max(1, int(round(weekly_proxy * 0.35)))
        return max(1, min(5, val))
    return 0


def _streamer_auction_value(season_pts, weighted_vor: float) -> int | None:
    if weighted_vor > 40:
        return 2
    if weighted_vor > 0 and (season_pts or 0) > 130:
        return 1
    return 1 if (season_pts and season_pts > 50) else 0


def _starter_auction_value(
    season_pts,
    weighted_vor: float,
    total_weighted_vor: float,
    pool: float | None = None,
) -> int:
    # why slice lives in apply_auction (not here): the pool must divide over
    # the league's starter slots only — paying every positive-VOR row
    # overshoots the pool (fantasy audit: $2,782 vs $2,352).
    pool = _STARTER_BUDGET_POOL if pool is None else pool
    if weighted_vor > 0:
        return max(1, int(round((weighted_vor / total_weighted_vor) * pool)))
    return 1 if season_pts and season_pts > 50 else 0


def _market_streamer_value(
    season_pts,
    weighted_vor: float,
    statsguy_value,
) -> int | None:
    if weighted_vor > 40:
        return 2
    if weighted_vor > 0 and (season_pts or 0) > 110:
        return 1
    if statsguy_value is not None and statsguy_value > 0:
        return 1
    return 1 if season_pts and season_pts > 50 else None


def _market_starter_value(
    season_pts,
    weighted_vor: float,
    total_weighted_vor: float,
    statsguy_value,
    pool: float | None = None,
) -> int | None:
    pool = _STARTER_BUDGET_POOL if pool is None else pool
    if weighted_vor > 0:
        return max(1, int(round((weighted_vor / total_weighted_vor) * pool)))
    if statsguy_value is not None and statsguy_value > 0:
        return max(1, int(round((statsguy_value / 9500.0) ** 1.2 * 65.0)))
    return 1 if season_pts and season_pts > 50 else None


def apply_auction(rows: list[dict], draft_prices: dict[str, float] | None, econ: dict | None = None) -> None:
    # why econ: replacement counts, starter slice, and $ pool scale with
    # league size/budget — pass config.league_economics(...); None keeps the
    # legacy 12x$200 constants (backward compat).
    econ = econ or {}
    repl_counts = econ.get("repl_counts", _POS_REPL_COUNTS)
    pool = econ.get("starter_pool", _STARTER_BUDGET_POOL)
    starter_slots = econ.get("starter_slots_total", 120)
    pos_weights = _build_pos_weights(rows, repl_counts)
    model_repl_pts = {
        p: _replacement_points(rows, p, c, "model_season_points")
        for p, c in repl_counts.items()
    }
    market_repl_pts = {
        p: _replacement_points(rows, p, c, "market_season_points")
        for p, c in repl_counts.items()
    }
    def _vor_pair(r):
        pos_k = r.get("position")
        return (
            _weighted_vor(r.get("model_season_points"), pos_k, model_repl_pts, pos_weights),
            _weighted_vor(r.get("market_season_points"), pos_k, market_repl_pts, pos_weights),
        )

    # why slice to the league's starter slots: pool $ must divide over
    # starters only. Paying every positive-VOR row overshoots the pool
    # (fantasy audit measured $2,782 vs $2,352 on the default league).
    # Mirrors hub/src/lib/auctionMath.js slicing. K/DEF stream at $1 outside.
    skill_rows = [r for r in rows if (r.get("position") not in ("K", "DEF", "DST"))]
    model_slice = {
        id(r) for r in sorted(skill_rows, key=lambda r: _vor_pair(r)[0], reverse=True)[:starter_slots]
    }
    market_slice = {
        id(r) for r in sorted(skill_rows, key=lambda r: _vor_pair(r)[1], reverse=True)[:starter_slots]
    }
    total_model_vor = sum(_vor_pair(r)[0] for r in skill_rows if id(r) in model_slice) or 1.0
    total_market_vor = sum(_vor_pair(r)[1] for r in skill_rows if id(r) in market_slice) or 1.0

    for r in rows:
        pos_k = r.get("position")
        msp = r.get("model_season_points")
        mk_sp = r.get("market_season_points")
        sg_val = r.get("statsguy_value")

        is_streamer_pos = pos_k in ("K", "DEF", "DST")
        m_vor, mk_vor = _vor_pair(r)
        m_uncapped = _uncapped_auction_value(msp, m_vor, total_model_vor, pos_k, pool)
        r["auctionUncapped"] = m_uncapped
        r["vor"] = round(m_vor, 1)

        if is_streamer_pos:
            auction_val = _streamer_auction_value(msp, m_vor)
        elif id(r) in model_slice:
            auction_val = _starter_auction_value(msp, m_vor, total_model_vor, pool)
        else:
            auction_val = 1 if msp and msp > 50 else 0
        r["auction"] = auction_val

        mk_uncapped = _uncapped_auction_value(mk_sp, mk_vor, total_market_vor, pos_k, pool)
        r["marketAuctionUncapped"] = mk_uncapped
        r["marketVor"] = round(mk_vor, 1)

        if is_streamer_pos:
            mk_auction_val = _market_streamer_value(mk_sp, mk_vor, sg_val)
        elif id(r) in market_slice:
            mk_auction_val = _market_starter_value(mk_sp, mk_vor, total_market_vor, sg_val, pool)
        else:
            mk_auction_val = 1 if mk_sp and mk_sp > 50 else None
        r["marketAuction"] = mk_auction_val

        _paid = draft_prices.get(r.get("player_id")) if draft_prices else None
        if _paid is not None:
            r["deltaAuction"] = int(auction_val - _paid)
        elif auction_val is not None and mk_auction_val is not None:
            r["deltaAuction"] = int(auction_val - mk_auction_val)
        else:
            r["deltaAuction"] = None