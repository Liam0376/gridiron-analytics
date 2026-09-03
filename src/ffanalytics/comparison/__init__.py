"""Model vs Market comparison builder. Public API: `build_comparison`.
Composes _model (row assembly) + _auction (auction VOR) + _edge (BUY/SELL).
Joins model (gsis_id) + Sleeper market (sleeper_id) + FantasyPros ECR/ADP via
two crosswalks (sleeper->gsis, name+pos->gsis)."""

from ._auction import apply_auction
from ._common import (
    COMPARE_STATS,
    MODEL_TO_SLEEPER,
    SLEEPER_TO_MODEL,
    _best_fpros_match,
    _normalize_name,
    build_fpros_lookup,
    build_gsis_map,
    build_sleeper_map,
    map_market_to_gsis,
)
from ._edge import apply_edge_rules
from ._model import build_fallback_rows, build_lookups, build_model_rows, _rank_model


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
    fpros_lut, statsguy_lut = build_lookups(fpros_players, statsguy_rows)

    sleeper_to_gsis = build_gsis_map(sleeper_players or {})
    gsis_to_sleeper = {gsis: sid for sid, gsis in sleeper_to_gsis.items()}
    name_to_sleeper = {
        _normalize_name(p.get("full_name") or p.get("player_name") or p.get("last_name") or ""): str(sid)
        for sid, p in (sleeper_players or {}).items()
        if _normalize_name(p.get("full_name") or p.get("player_name") or p.get("last_name") or "")
    }

    sorted_model, overall_rank, pos_rank = _rank_model(model_projections)
    rows, seen_keys = build_model_rows(
        sorted_model,
        overall_rank,
        pos_rank,
        market_by_gsis,
        fpros_lut,
        statsguy_lut,
        fp_projections,
        actual_by_gsis,
        draft_prices,
        sleeper_to_gsis=sleeper_to_gsis,
        gsis_to_sleeper=gsis_to_sleeper,
    )

    starting_len = len(rows)
    fallback = build_fallback_rows(
        fpros_players,
        fp_projections,
        statsguy_lut,
        seen_keys,
        starting_len,
        name_to_sleeper=name_to_sleeper,
    )
    rows.extend(fallback)

    apply_auction(rows, draft_prices)
    return rows


__all__ = [
    "COMPARE_STATS",
    "MODEL_TO_SLEEPER",
    "SLEEPER_TO_MODEL",
    "_best_fpros_match",
    "_normalize_name",
    "apply_auction",
    "apply_edge_rules",
    "build_comparison",
    "build_fpros_lookup",
    "build_gsis_map",
    "build_sleeper_map",
    "map_market_to_gsis",
]