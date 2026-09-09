"""Player props odds math: fair odds, EV, edge rule. Pure functions only.

Separate from fantasy projections: fantasy asks "who scores more PPR?", props asks
"is the book's line mispriced vs my distribution?". This module does the second
half (odds math). Fair-line means/sigmas arrive in Task 3 from `stat_projector`
outputs — this file never imports the projector, the DB, or any adapter, so the
math stays unit-testable with zero deps.

Conventions (pinned Task 1, 2026-09-09):
- `width` = HALF-width (src semantics: `lower = point - width`,
  `projection.py:216-217`), never the hub full-span rendering.
- `prob_to_american` returns unrounded float (exact inverse of
  `american_to_prob`); round only for display.
- Edge defaults (`edge_pp_min=0.05`, `ev_min=0.04`): at edge >= 5pp, EV is always
  >= 5% (EV = edge_pp * (q+1), q+1 > 1), so `ev_min` is a backstop for custom
  thresholds, not the binding constraint at defaults. Honest, not redundant.
"""

import math
import statistics

from ffanalytics.stat_projector import project_player_stats

# 80% central normal quantile: P(|Z| <= Z_80) = 0.8. Converts a pinned
# half-width into sigma under the v1 normal approximation
# (sigma = width / Z_80). Approximation is flagged uncalibrated until
# per-market shadow >= MIN_SHADOW_SAMPLES — see spec.
Z_80 = 1.2815515655446004

EDGE_PP_MIN = 0.05
EV_MIN = 0.04


def _require_prob(p: float, name: str = "p", allow_degenerate: bool = False) -> float:
    """Validate a probability. Degenerate 0/1 allowed only when asked."""
    try:
        p = float(p)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {p!r}")
    if math.isnan(p):
        raise ValueError(f"{name} probability must not be NaN")
    lo, hi = (0.0, 1.0) if allow_degenerate else (0.0, 1.0)
    if allow_degenerate:
        if not (lo <= p <= hi):
            raise ValueError(f"{name} probability must be in [0, 1], got {p}")
    else:
        if not (lo < p < hi):
            raise ValueError(f"{name} probability must be in (0, 1), got {p}")
    return p


def _require_price(price: float) -> float:
    """Validate an American-odds price (zero has no meaning)."""
    try:
        price = float(price)
    except (TypeError, ValueError):
        raise ValueError(f"price must be a number, got {price!r}")
    if math.isnan(price) or price == 0:
        raise ValueError(f"price must be non-zero and finite, got {price!r}")
    if math.isinf(price):
        raise ValueError(f"price must be finite, got {price!r}")
    return price


def american_to_prob(price: float) -> float:
    """Implied (no-vig) probability of one side at an American price.

    -110 -> 110/210 ~= 0.5238; +150 -> 100/250 = 0.4; +-100 -> 0.5.
    """
    price = _require_price(price)
    if price > 0:
        return 100.0 / (price + 100.0)
    return abs(price) / (abs(price) + 100.0)


def prob_to_american(p: float) -> float:
    """No-vig fair American odds for a probability. Exact inverse of
    `american_to_prob` (unrounded float — round for display).

    0.5 -> 100 (even); 0.6 -> -150; 1/3 -> +200.
    """
    p = _require_prob(p)
    if p == 0.5:
        return 100.0
    if p > 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def ev_per_unit(p_model: float, book_price: float) -> float:
    """Expected profit per $1 staked: p * payout - (1 - p) * 1.

    Caller passes the side-adjusted model prob (P(over) with the over price,
    or P(under) = 1 - P(over) with the under price). -110 both sides at true
    p=0.5 gives -0.0227 (the vig) — the bet must clear the juice, not just 50%.
    """
    p = _require_prob(p_model, "p_model", allow_degenerate=True)
    price = _require_price(book_price)
    payout = price / 100.0 if price > 0 else 100.0 / abs(price)
    return p * payout - (1.0 - p)


def poisson_anytime_td(mean_tds: float) -> float:
    """P(anytime TD) = 1 - e^-lambda for projected TD mean lambda.

    Negative means (impossible) clamp to 0.0; NaN raises — a silent 0.0 would
    masquerade as "no chance" instead of "bad input".
    """
    try:
        lam = float(mean_tds)
    except (TypeError, ValueError):
        raise ValueError(f"mean_tds must be a number, got {mean_tds!r}")
    if math.isnan(lam):
        raise ValueError("mean_tds (lambda) must not be NaN")
    if lam <= 0:
        return 0.0
    return 1.0 - math.exp(-lam)


def normal_over_prob(mean: float, sigma: float, line: float) -> float:
    """P(stat > line) under Normal(mean, sigma). Degenerate sigma<=0 is a step
    (certainty above / below, coin-flip exactly at). Non-finite inputs raise.
    """
    for name, v in (("mean", mean), ("sigma", sigma), ("line", line)):
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number, got {v!r}")
        if not math.isfinite(fv):
            raise ValueError(f"{name} must be finite, got {v!r}")
    mean, sigma, line = float(mean), float(sigma), float(line)
    if sigma <= 0:
        if mean > line:
            return 1.0
        if mean < line:
            return 0.0
        return 0.5
    return 0.5 * math.erfc((line - mean) / (sigma * math.sqrt(2.0)))


def apply_prop_edge_rule(
    p_model: float,
    book_price: float,
    edge_pp_min: float = EDGE_PP_MIN,
    ev_min: float = EV_MIN,
    is_empty: bool = False,
) -> dict:
    """Edge decision for one side of one prop market.

    Args:
        p_model: side-adjusted model probability (P(over) vs over price, or
            P(under) vs under price).
        book_price: American price on that side.
        is_empty: True when the projection is unknown (rookie/no history) —
            vetoes VALUE unconditionally; unknown is not an edge.

    Returns dict with book_prob, edge_pp, ev_per_unit, decision
    ("VALUE" / "NO EDGE" / "NO EDGE (unknown)"). Never "LOCK" — RG copy rule.
    """
    p = _require_prob(p_model, "p_model", allow_degenerate=True)
    price = _require_price(book_price)
    book_prob = american_to_prob(price)
    edge_pp = p - book_prob
    ev = ev_per_unit(p, price)
    if is_empty:
        decision = "NO EDGE (unknown)"
    elif edge_pp >= edge_pp_min and ev >= ev_min:
        decision = "VALUE"
    else:
        decision = "NO EDGE"
    return {
        "book_prob": book_prob,
        "edge_pp": edge_pp,
        "ev_per_unit": ev,
        "decision": decision,
    }


# ---------------------------------------------------------------------------
# Fair lines from stat projections (Task 3). Reads `project_player_stats`
# outputs; never modifies the projector, scoring, decision, or comparison
# layers (g rep-guard: `git status` after this task shows only props.py +
# tests/test_props.py).
# ---------------------------------------------------------------------------

# Position -> [(prop market, source stat key, probability model)].
# K excluded v1: fg distance buckets don't map to standard K props and K has
# the thinnest coverage (displayed 58.6%). DEF excluded: no player-stat base.
PROP_MARKETS = {
    "QB": [
        ("passing_yards", "passing_yards", "normal"),
        ("passing_tds", "passing_tds", "normal"),
        ("rushing_yards", "rushing_yards", "normal"),
        ("anytime_td", "rushing_tds", "poisson"),
    ],
    "RB": [
        ("rushing_yards", "rushing_yards", "normal"),
        ("receiving_yards", "receiving_yards", "normal"),
        ("receptions", "receptions", "normal"),
        ("anytime_td", "rushing_tds+receiving_tds", "poisson"),
    ],
    "WR": [
        ("receiving_yards", "receiving_yards", "normal"),
        ("receptions", "receptions", "normal"),
        ("rushing_yards", "rushing_yards", "normal"),
        ("anytime_td", "rushing_tds+receiving_tds", "poisson"),
    ],
    "TE": [
        ("receiving_yards", "receiving_yards", "normal"),
        ("receptions", "receptions", "normal"),
        ("rushing_yards", "rushing_yards", "normal"),
        ("anytime_td", "rushing_tds+receiving_tds", "poisson"),
    ],
}

# Sigma floors per stat: sample std of a flat history (e.g. zeros every game)
# is 0.0, which would make every line a false certainty. Floors are STARTING
# values (~half a typical single-game std), not calibrated claims — Task 4
# backtest (Brier + reliability) judges them and they move to config.py if kept.
SIGMA_FLOORS = {
    "passing_yards": 30.0,   # why: typical QB game std ~60-80; half is conservative
    "passing_tds": 0.5,      # why: TDs are ~0/1/2 coin flips; 0.5 keeps P(over) sane
    "rushing_yards": 10.0,   # why: typical skill game std ~20-30
    "receiving_yards": 10.0,  # why: same scale as rushing
    "receptions": 1.0,       # why: catch counts move in ones
}

# Pinned src width semantics (Task 1): width IS the half-width, so a normal
# 80% half-width converts with the 80% quantile (see Z_80 above).


def _stat_values(player_history, prior_season_stats, stat_key):
    """All usable values for one stat: current history + prior REG rows."""
    vals = []
    for g in player_history or []:
        try:
            v = float(g.get(stat_key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            vals.append(v)
    for g in prior_season_stats or []:
        if g.get("season_type", "REG") != "REG":
            continue
        try:
            v = float(g.get(stat_key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            vals.append(v)
    return vals


def _dispersion_sigma(values, stat_key):
    """Sample std of the player's own history for that stat, floored.

    Uncalibrated by construction — same-data dispersion, not a conformal
    guarantee. Task 4 measures whether it predicts (Brier/reliability).
    """
    floor = SIGMA_FLOORS.get(stat_key, 1.0)
    if len(values) >= 2:
        try:
            return max(float(statistics.stdev(values)), floor)
        except statistics.StatisticsError:
            return floor
    return floor


def _coerce_finite(v):
    """scoring.py discipline: non-finite projection output coerces to 0.0."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def build_prop_fair_lines(
    player_history,
    position,
    game_ctx=None,
    prior_season_stats=None,
    week=None,
):
    """Fair lines + sigmas per prop market from stat projections.

    Args:
        player_history: game logs this season, ordered by week (same shape as
            `project_player_stats` expects).
        position: QB/RB/WR/TE. Anything else (K/DEF/unknown) is excluded v1.
        game_ctx: {implied_total, wind_mph|wind, temp_f|temp}. None = neutral.
        prior_season_stats: previous season logs (REG filtered for sigma).
        week: target week. week == 1 is EXCLUDED (week-1 leakage guard hole at
            `stat_projector.py:512-513`); None skips the check (caller must pass
            week in production paths — Task 5 API does).

    Returns envelope {"excluded", "reason", "position", "is_empty_projection",
    "markets"} where markets maps name -> {"model", "fair_line", "sigma", ...}
    (poisson entries carry "p_yes" instead of a sigma).
    """
    pos = (position or "").upper()
    if pos not in PROP_MARKETS:
        return {
            "excluded": True,
            "reason": f"position {pos or '?'} has no v1 prop markets (K/DEF out of scope)",
            "position": pos,
            "is_empty_projection": False,
            "markets": {},
        }
    if week is not None and week < 2:
        return {
            "excluded": True,
            "reason": "week 1 excluded: history filter leaks future weeks (stat_projector.py:512-513)",
            "position": pos,
            "is_empty_projection": False,
            "markets": {},
        }

    ctx = game_ctx or {}
    implied = ctx.get("implied_total", 0) or 0
    wind = ctx.get("wind_mph", ctx.get("wind", 0)) or 0
    temp = ctx.get("temp_f", ctx.get("temp", None))

    proj = project_player_stats(
        player_history=player_history or [],
        position=pos,
        prior_season_stats=prior_season_stats,
        implied_total=implied,
        wind_mph=wind,
        temp_f=temp,
    )
    is_empty = bool(proj.get("is_empty_projection", False))

    markets = {}
    for market, source, model in PROP_MARKETS[pos]:
        if model == "poisson":
            lam = sum(_coerce_finite(proj.get(k, 0)) for k in source.split("+"))
            markets[market] = {
                "model": "poisson",
                "fair_line": lam,
                "sigma": None,
                "p_yes": poisson_anytime_td(lam),
            }
        else:
            fair = _coerce_finite(proj.get(source, 0))
            sigma = _dispersion_sigma(
                _stat_values(player_history, prior_season_stats, source), source
            )
            markets[market] = {"model": "normal", "fair_line": fair, "sigma": sigma}

    return {
        "excluded": False,
        "reason": "",
        "position": pos,
        "is_empty_projection": is_empty,
        "markets": markets,
    }


def prop_over_prob(market_entry, line):
    """P(stat > line) for a normal-market entry from `build_prop_fair_lines`.

    Poisson (yes/no) markets carry p_yes directly — over/under lines don't
    apply, so this raises instead of guessing.
    """
    if market_entry.get("model") == "poisson":
        raise ValueError("poisson markets are yes/no — use entry['p_yes']")
    return normal_over_prob(market_entry["fair_line"], market_entry["sigma"], line)


# ---------------------------------------------------------------------------
# Calibration metrics (Task 4). Pure functions over observation lists, so the
# backtest script stays a thin data-plumbing layer and every number here is
# unit-tested on synthetic fixtures. No book lines needed:
# - normal markets: PIT uniformity + 80%-band coverage + fair-line MAE.
#   (P(over = fair) is 0.5 by construction, so Brier needs book lines we
#   don't have — PIT/coverage test the sigma honesty instead.)
# - anytime_td: Brier vs base-rate-naive + binned reliability (real 0/1).
# ---------------------------------------------------------------------------

# Gate thresholds: starting values, same honesty regime as the rest of the
# repo — fail-closed (unknown/small/miscalibrated => "tracking", never edges).
CAL_N_MIN = 500
CAL_COVERAGE_TARGET = 0.80
CAL_COVERAGE_TOL = 0.05
CAL_PIT_MAX_DEV = 0.04


def pit_value(actual, fair, sigma):
    """Probability integral transform: Phi((actual - fair) / sigma).

    Well-calibrated sigmas => PIT values ~ Uniform(0, 1) across observations.
    """
    for name, v in (("actual", actual), ("fair", fair), ("sigma", sigma)):
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number, got {v!r}")
        if not math.isfinite(fv):
            raise ValueError(f"{name} must be finite, got {v!r}")
    if float(sigma) <= 0:
        raise ValueError(f"sigma must be positive, got {sigma!r}")
    z = (float(actual) - float(fair)) / float(sigma)
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def band_coverage(observations):
    """Fraction of (fair, sigma, actual) with |actual - fair| <= sigma * Z_80.

    Target 0.80 when sigmas are honest 80% half-widths. Empty => None
    (no silent 0.0 — same discipline as empirical_coverage).
    """
    obs = list(observations)
    if not obs:
        return None
    hits = sum(1 for fair, sigma, actual in obs if abs(actual - fair) <= sigma * Z_80)
    return hits / len(obs)


def pit_deciles(observations):
    """PIT histogram over 10 deciles for (fair, sigma, actual) observations.

    Returns {"deciles": [10 proportions], "max_dev": max|bin - 0.1|}.
    Uniform (calibrated) => every decile ~0.1, max_dev ~0.
    """
    obs = list(observations)
    bins = [0.0] * 10
    for fair, sigma, actual in obs:
        u = pit_value(actual, fair, sigma)
        idx = min(int(u * 10), 9)
        bins[idx] += 1.0
    n = len(obs)
    props = [b / n for b in bins] if n else [0.0] * 10
    return {"deciles": props, "max_dev": max(abs(p - 0.1) for p in props) if n else None}


def brier_score(pairs):
    """Mean((p - y)^2) for (prob, outcome in {0,1}) pairs. Perfect => 0.0."""
    pairs = list(pairs)
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def base_rate_brier(outcomes):
    """Naive baseline: always predict the base rate. Model must beat this."""
    outcomes = list(outcomes)
    if not outcomes:
        return None
    base = sum(outcomes) / len(outcomes)
    return sum((base - y) ** 2 for y in outcomes) / len(outcomes)


def reliability_bins(pairs, k=5):
    """Equal-count bins sorted by predicted prob: [{n, mean_pred, hit_rate}].

    Monotonic non-decreasing hit_rate => higher model probs really mean more
    frequent hits (the minimum honesty for an edge label).
    """
    pairs = sorted((float(p), int(y)) for p, y in pairs)
    n = len(pairs)
    if n == 0 or k <= 0:
        return []
    bins = []
    for i in range(k):
        chunk = pairs[i * n // k:(i + 1) * n // k]
        if not chunk:
            continue
        bins.append(
            {
                "n": len(chunk),
                "mean_pred": sum(p for p, _ in chunk) / len(chunk),
                "hit_rate": sum(y for _, y in chunk) / len(chunk),
            }
        )
    return bins


def bins_monotonic(bins):
    """True when hit_rate never decreases across bins (equal counts)."""
    rates = [b["hit_rate"] for b in bins]
    return all(b >= a for a, b in zip(rates, rates[1:])) if rates else False


def fair_mae(observations):
    """Mean|fair - actual| for (fair, sigma, actual) — line accuracy sans sigma."""
    obs = list(observations)
    if not obs:
        return None
    return sum(abs(fair - actual) for fair, _, actual in obs) / len(obs)


def verdict_normal_market(n, coverage, pit_max_dev):
    """'edges_on' only with size + band coverage + PIT uniformity. Else tracking."""
    if n < CAL_N_MIN:
        return "tracking"
    if coverage is None or abs(coverage - CAL_COVERAGE_TARGET) > CAL_COVERAGE_TOL:
        return "tracking"
    if pit_max_dev is None or pit_max_dev > CAL_PIT_MAX_DEV:
        return "tracking"
    return "edges_on"


def verdict_td_market(n, brier, naive_brier, monotonic):
    """'edges_on' only with size + beating base-rate + monotonic reliability."""
    if n < CAL_N_MIN:
        return "tracking"
    if brier is None or naive_brier is None or not brier < naive_brier:
        return "tracking"
    if not monotonic:
        return "tracking"
    return "edges_on"
