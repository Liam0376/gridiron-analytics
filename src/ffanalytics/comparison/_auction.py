"""Auction VOR, market auction consensus, and K/DEF streamer handling.
12 teams × $200 = $2400 pool; 48 bench at $1 → $2352 starter budget.
K/DEF devalued to $1 in practice — clamped here. Positional scarcity weight =
market_share / model_share, clamped [0.5, 1.5] to avoid thin-data overcorrection."""


_STARTER_BUDGET_POOL = 2352.0
_POS_REPL_COUNTS = {"QB": 12, "RB": 28, "WR": 32, "TE": 12, "K": 12, "DEF": 12}
_FALLBACK_WEIGHTS = {"QB": 0.65, "RB": 1.10, "WR": 0.92, "TE": 0.78}


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


def _build_pos_weights(rows: list[dict]) -> dict[str, float]:
    pos_weights = {pos: 1.0 for pos in _POS_REPL_COUNTS}
    model_repl_pts = {
        p: _replacement_points(rows, p, c, "model_season_points")
        for p, c in _POS_REPL_COUNTS.items()
    }
    market_repl_pts = {
        p: _replacement_points(rows, p, c, "market_season_points")
        for p, c in _POS_REPL_COUNTS.items()
    }

    raw_model_per_pos: dict[str, float] = {p: 0.0 for p in _POS_REPL_COUNTS}
    raw_market_per_pos: dict[str, float] = {p: 0.0 for p in _POS_REPL_COUNTS}
    for r in rows:
        pos = r.get("position")
        if pos in _POS_REPL_COUNTS:
            raw_model_per_pos[pos] += _raw_vor(r.get("model_season_points"), pos, model_repl_pts)
            raw_market_per_pos[pos] += _raw_vor(r.get("market_season_points"), pos, market_repl_pts)
    raw_model_total = sum(raw_model_per_pos.values()) or 1.0
    raw_market_total = sum(raw_market_per_pos.values()) or 1.0

    for pos in _POS_REPL_COUNTS:
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
    return raw * pos_weights.get(pos, 1.0)


def _uncapped_auction_value(
    season_pts,
    weighted_vor: float,
    total_weighted_vor: float,
    pos: str,
) -> int:
    if weighted_vor > 0:
        return int(round((weighted_vor / total_weighted_vor) * _STARTER_BUDGET_POOL)) if total_weighted_vor else 0
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
) -> int:
    if weighted_vor > 0:
        return max(1, int(round((weighted_vor / total_weighted_vor) * _STARTER_BUDGET_POOL)))
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
) -> int | None:
    if weighted_vor > 0:
        return max(1, int(round((weighted_vor / total_weighted_vor) * _STARTER_BUDGET_POOL)))
    if statsguy_value is not None and statsguy_value > 0:
        return max(1, int(round((statsguy_value / 9500.0) ** 1.2 * 65.0)))
    return 1 if season_pts and season_pts > 50 else None


def apply_auction(rows: list[dict], draft_prices: dict[str, float] | None) -> None:
    pos_weights = _build_pos_weights(rows)
    model_repl_pts = {
        p: _replacement_points(rows, p, c, "model_season_points")
        for p, c in _POS_REPL_COUNTS.items()
    }
    market_repl_pts = {
        p: _replacement_points(rows, p, c, "market_season_points")
        for p, c in _POS_REPL_COUNTS.items()
    }
    total_model_vor = sum(
        _weighted_vor(r.get("model_season_points"), r.get("position"), model_repl_pts, pos_weights)
        for r in rows
    ) or 1.0
    total_market_vor = sum(
        _weighted_vor(r.get("market_season_points"), r.get("position"), market_repl_pts, pos_weights)
        for r in rows
    ) or 1.0

    for r in rows:
        pos_k = r.get("position")
        msp = r.get("model_season_points")
        mk_sp = r.get("market_season_points")
        sg_val = r.get("statsguy_value")

        is_streamer_pos = pos_k in ("K", "DEF", "DST")
        m_vor = _weighted_vor(msp, pos_k, model_repl_pts, pos_weights)
        m_uncapped = _uncapped_auction_value(msp, m_vor, total_model_vor, pos_k)
        r["auctionUncapped"] = m_uncapped
        r["vor"] = round(m_vor, 1)

        if is_streamer_pos:
            auction_val = _streamer_auction_value(msp, m_vor)
        else:
            auction_val = _starter_auction_value(msp, m_vor, total_model_vor)
        r["auction"] = auction_val

        mk_vor = _weighted_vor(mk_sp, pos_k, market_repl_pts, pos_weights)
        mk_uncapped = _uncapped_auction_value(mk_sp, mk_vor, total_market_vor, pos_k)
        r["marketAuctionUncapped"] = mk_uncapped
        r["marketVor"] = round(mk_vor, 1)

        if is_streamer_pos:
            mk_auction_val = _market_streamer_value(mk_sp, mk_vor, sg_val)
        else:
            mk_auction_val = _market_starter_value(mk_sp, mk_vor, total_market_vor, sg_val)
        r["marketAuction"] = mk_auction_val

        _paid = draft_prices.get(r.get("player_id")) if draft_prices else None
        if _paid is not None:
            r["deltaAuction"] = int(auction_val - _paid)
        elif auction_val is not None and mk_auction_val is not None:
            r["deltaAuction"] = int(auction_val - mk_auction_val)
        else:
            r["deltaAuction"] = None