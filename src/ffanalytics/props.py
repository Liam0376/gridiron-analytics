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
