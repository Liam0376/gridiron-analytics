"""Edge labeling: BUY/SELL/NEUTRAL based on rank delta + point delta + season
delta. rank delta >=12 is the primary signal; point delta >=3.0 is the
secondary amplifier; season delta >=51 is the tertiary amplifier."""


def _classify(
    current_edge: str,
    current_score: float,
    new_edge: str,
    new_score: float,
) -> tuple[str, float]:
    # Pick whichever edge dominates; BUY/SELL override NEUTRAL.
    if new_edge == "NEUTRAL":
        return current_edge, current_score
    if current_edge == "NEUTRAL":
        return new_edge, new_score
    # Both edges present — keep whichever has the larger |score|.
    if abs(new_score) > abs(current_score):
        return new_edge, new_score
    return current_edge, current_score


def apply_edge_rules(
    delta_rank: int | None,
    fp_ecr,
    delta_pts: float | None,
    delta_season: float | None,
    current_edge: str = "NEUTRAL",
    current_score: float = 0.0,
) -> tuple[str, float]:
    edge = current_edge
    edge_score = current_score

    if delta_rank is not None and fp_ecr is not None:
        if delta_rank >= 12:
            edge, edge_score = _classify(edge, edge_score, "BUY", float(delta_rank))
        elif delta_rank <= -12:
            edge, edge_score = _classify(edge, edge_score, "SELL", float(delta_rank))

    if delta_pts is not None:
        if delta_pts >= 3.0 and edge != "SELL":
            edge, edge_score = _classify(edge, edge_score, "BUY", delta_pts * 4)
        elif delta_pts <= -3.0 and edge != "BUY":
            edge, edge_score = _classify(edge, edge_score, "SELL", delta_pts * 4)

    if delta_season is not None:
        if delta_season >= 51 and edge != "SELL":
            edge, edge_score = _classify(edge, edge_score, "BUY", delta_season / 4)
        elif delta_season <= -51 and edge != "BUY":
            edge, edge_score = _classify(edge, edge_score, "SELL", delta_season / 4)

    return edge, edge_score