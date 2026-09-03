"""Decision layer: produces start/sit, waiver priority, and trade evaluations
using projections, ratings, and roster constraints.

Position-constrained optimization using greedy assignment with VBD
(Value Based Drafting) for positional scarcity.

K/DEF weight 0.0 streaming rationale: K and DEF are streamed week-to-week in
practice ($1 in auction, waiver-wire replaceable, high week-to-week variance
and low season-long edge vs replacement), so VBD auction math clamps their
pos_weight to 0.0 (see _vbd_auction_params_from_comps + POS_WEIGHT_FALLBACK).
This is methodology, not a value change — dollar ordering for QB/RB/WR/TE is
unaffected; K/DEF still project points for start/sit but contribute zero to
dollar_per_vor pool. No thresholds flip behavior.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ffanalytics import config

FLEX_ELIGIBLE = {"RB", "WR", "TE"}
POS_REPL_COUNTS = config.POS_REPL_COUNTS
POS_WEIGHT_FALLBACK = config.POS_WEIGHT_FALLBACK
STARTER_BUDGET_POOL = config.STARTER_BUDGET_POOL

# Opponent-defense adjustment gate — default OFF (mirrors projection.py ENABLE_OPPONENT_RATING).
# tested and REJECTED — evidence: stat_projector.py:22-24 opponent defense factors hurt
# correlation (0.690→0.687) even with multi-season shrinkage; defense rankings don't persist
# year-to-year (Spearman rho=0.05-0.34). Kept behind flag for research only; production stays OFF.
# evaluate_trade passes {} so behavior there unchanged regardless.
ENABLE_OPPONENT_ADJUSTMENT = False

# Slot requirements parsed from Sleeper's roster_positions list.
# roster_positions example: ["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF","BN","BN","BN","BN"]
BENCH_SLOTS = {"BN", "IR"}


def _vbd_auction_params_from_comps(comp_list):
    """Derive VBD auction params from comparison list.

    Mirrors comparison.py:626 logic: by_pos_model/market, sorted,
    model_repl/market_repl via POS_REPL_COUNTS, raw totals,
    market_share/model_share clamped [0.5,1.5], total weighted VOR top120,
    return (model_repl, pos_weight, dollar_per_vor).
    """
    if not comp_list:
        return {}, POS_WEIGHT_FALLBACK.copy(), 0.0

    # by_pos_model / market
    by_pos_model: Dict[str, List[float]] = {pos: [] for pos in POS_REPL_COUNTS}
    by_pos_market: Dict[str, List[float]] = {pos: [] for pos in POS_REPL_COUNTS}

    for r in comp_list:
        if not isinstance(r, dict):
            continue
        pos = (r.get("position") or r.get("position_group") or "UNK").upper()
        if pos == "DST":
            pos = "DEF"
        if pos not in POS_REPL_COUNTS:
            continue
        # model season points
        m_sp = r.get("model_season_points")
        if m_sp is None:
            m_sp = r.get("model_points")
        if m_sp is None:
            pp = r.get("projected_points")
            if pp is None:
                pp = r.get("point_estimate") or r.get("weekly") or 0
            try:
                m_sp = float(pp or 0) * 17.0
            except Exception:
                m_sp = 0.0
        try:
            m_val = float(m_sp or 0)
        except Exception:
            m_val = 0.0
        by_pos_model[pos].append(m_val)

        mk_sp = r.get("market_season_points")
        if mk_sp is None:
            mk_sp = r.get("market_points")
        if mk_sp is not None:
            try:
                by_pos_market[pos].append(float(mk_sp))
            except Exception:
                pass

    for pos in by_pos_model:
        by_pos_model[pos].sort(reverse=True)
    for pos in by_pos_market:
        by_pos_market[pos].sort(reverse=True)

    # model_repl / market_repl via POS_REPL_COUNTS
    model_repl: Dict[str, float] = {}
    market_repl: Dict[str, float] = {}
    for pos, count in POS_REPL_COUNTS.items():
        arr = by_pos_model.get(pos, [])
        if len(arr) >= count:
            model_repl[pos] = float(arr[count - 1])
        elif arr:
            model_repl[pos] = float(arr[-1]) * 0.8
        else:
            model_repl[pos] = 100.0
        marr = by_pos_market.get(pos, [])
        if len(marr) >= count:
            market_repl[pos] = float(marr[count - 1])
        elif marr:
            market_repl[pos] = float(marr[-1]) * 0.8
        else:
            market_repl[pos] = 100.0

    def _raw_vor(season_pts, pos, repl_map):
        try:
            return max(0.0, float(season_pts or 0) - repl_map.get(pos, 100.0))
        except Exception:
            return 0.0

    # raw totals per position for share calculation
    raw_model_per_pos = {pos: 0.0 for pos in POS_REPL_COUNTS}
    raw_market_per_pos = {pos: 0.0 for pos in POS_REPL_COUNTS}
    for r in comp_list:
        if not isinstance(r, dict):
            continue
        pos = (r.get("position") or r.get("position_group") or "UNK").upper()
        if pos == "DST":
            pos = "DEF"
        if pos not in POS_REPL_COUNTS:
            continue
        m_sp = r.get("model_season_points")
        if m_sp is None:
            m_sp = r.get("model_points")
        if m_sp is None:
            pp = r.get("projected_points") or r.get("point_estimate") or 0
            try:
                m_sp = float(pp or 0) * 17.0
            except Exception:
                m_sp = 0.0
        mk_sp = r.get("market_season_points")
        if mk_sp is None:
            mk_sp = r.get("market_points")
        raw_model_per_pos[pos] += _raw_vor(m_sp, pos, model_repl)
        if mk_sp is not None:
            raw_market_per_pos[pos] += _raw_vor(mk_sp, pos, market_repl)

    raw_model_total = sum(raw_model_per_pos.values()) or 1.0
    raw_market_total = sum(raw_market_per_pos.values()) or 1.0

    pos_weight: Dict[str, float] = {}
    for pos in POS_REPL_COUNTS:
        if pos in ("K", "DEF", "DST"):
            pos_weight[pos] = 0.0
        else:
            model_share = raw_model_per_pos[pos] / raw_model_total if raw_model_total else 0
            market_share = raw_market_per_pos[pos] / raw_market_total if raw_market_total else 0
            if model_share > 0 and market_share > 0:
                w = market_share / model_share
                pos_weight[pos] = max(0.5, min(1.5, w))
            else:
                pos_weight[pos] = POS_WEIGHT_FALLBACK.get(pos, 1.0)

    def _weighted_vor(season_pts, pos, repl_map):
        raw = _raw_vor(season_pts, pos, repl_map)
        return raw * pos_weight.get(pos, 1.0)

    # total weighted VOR top120
    all_weighted: List[float] = []
    for r in comp_list:
        if not isinstance(r, dict):
            continue
        pos = (r.get("position") or r.get("position_group") or "UNK").upper()
        if pos == "DST":
            pos = "DEF"
        if pos not in POS_REPL_COUNTS:
            continue
        m_sp = r.get("model_season_points")
        if m_sp is None:
            m_sp = r.get("model_points")
        if m_sp is None:
            pp = r.get("projected_points") or r.get("point_estimate") or 0
            try:
                m_sp = float(pp or 0) * 17.0
            except Exception:
                m_sp = 0.0
        wv = _weighted_vor(m_sp, pos, model_repl)
        if wv > 0:
            all_weighted.append(wv)
    all_weighted.sort(reverse=True)
    starter_slots = 120
    top_vors = all_weighted[:starter_slots] if len(all_weighted) > starter_slots else all_weighted
    total_weighted_vor = sum(top_vors) or 1.0

    dollar_per_vor = STARTER_BUDGET_POOL / total_weighted_vor if total_weighted_vor else 0.0

    return (model_repl, pos_weight, dollar_per_vor)


def _parse_slot_requirements(roster_positions: List[str]) -> Tuple[Dict[str, int], int]:
    """Parse roster_positions into required starter counts per position and flex count."""
    required = {}
    flex_count = 0
    for slot in roster_positions:
        if slot in BENCH_SLOTS:
            continue
        if slot in ("FLEX", "SUPER_FLEX"):
            flex_count += 1
        else:
            required[slot] = required.get(slot, 0) + 1
    return required, flex_count


def _optimal_lineup(
    players: List[Dict],
    roster_positions: List[str],
) -> Tuple[List[Dict], List[Dict]]:
    """Greedy position-constrained lineup optimizer.

    Returns (starters, bench) where each starter dict has an added 'slot' field."""
    required, flex_count = _parse_slot_requirements(roster_positions)

    by_pos: Dict[str, List[Dict]] = {}
    for p in players:
        pos = (p.get("position") or p.get("position_group") or "UNK").upper()
        by_pos.setdefault(pos, []).append(p)
    for pos_list in by_pos.values():
        pos_list.sort(key=lambda x: float(x.get("projected_points", 0) or 0), reverse=True)

    starters = []
    used = set()

    # Phase 1: fill required positional slots
    for pos, count in required.items():
        candidates = by_pos.get(pos, [])
        filled = 0
        for p in candidates:
            pid = p.get("player_id")
            if pid in used:
                continue
            starter = dict(p)
            starter["slot"] = pos
            starters.append(starter)
            used.add(pid)
            filled += 1
            if filled >= count:
                break

    # Phase 2: fill FLEX slots from remaining RB/WR/TE
    flex_candidates = []
    for pos in FLEX_ELIGIBLE:
        for p in by_pos.get(pos, []):
            if p.get("player_id") not in used:
                flex_candidates.append(p)
    flex_candidates.sort(key=lambda x: float(x.get("projected_points", 0) or 0), reverse=True)

    for p in flex_candidates[:flex_count]:
        starter = dict(p)
        starter["slot"] = "FLEX"
        starters.append(starter)
        used.add(p.get("player_id"))

    # Everyone else is bench
    bench = [p for p in players if p.get("player_id") not in used]

    return starters, bench


def _replacement_levels(
    all_players: List[Dict],
    roster_positions: List[str],
    num_teams: int = 12,
) -> Dict[str, float]:
    # Replacement = projection of (N*num_teams + 1)th player at each pos.
    required, flex_count = _parse_slot_requirements(roster_positions)

    # FLEX slots split across eligible positions proportional to their starter counts
    flex_eligible_starters = sum(required.get(p, 0) for p in FLEX_ELIGIBLE)
    flex_share = {}
    for pos in FLEX_ELIGIBLE:
        if flex_eligible_starters > 0:
            flex_share[pos] = flex_count * required.get(pos, 0) / flex_eligible_starters
        else:
            flex_share[pos] = flex_count / len(FLEX_ELIGIBLE)

    by_pos: Dict[str, List[float]] = {}
    for p in all_players:
        pos = (p.get("position") or p.get("position_group") or "UNK").upper()
        pts = float(p.get("projected_points", 0) or 0)
        by_pos.setdefault(pos, []).append(pts)
    for pos_list in by_pos.values():
        pos_list.sort(reverse=True)

    levels = {}
    for pos in set(list(required.keys()) + list(FLEX_ELIGIBLE)):
        slots = required.get(pos, 0) + flex_share.get(pos, 0)
        replacement_rank = int(slots * num_teams)
        projections = by_pos.get(pos, [])
        if replacement_rank < len(projections):
            levels[pos] = projections[replacement_rank]
        elif projections:
            levels[pos] = projections[-1]
        else:
            levels[pos] = 0.0

    return levels


def _vbd(player: Dict, replacement_levels: Dict[str, float]) -> float:
    pos = (player.get("position") or player.get("position_group") or "UNK").upper()
    pts = float(player.get("projected_points", 0) or 0)
    return pts - replacement_levels.get(pos, 0.0)


def calculate_roster_value(
    players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
) -> float:
    starters, _ = _optimal_lineup(players, roster_positions)
    replacement = _replacement_levels(players, roster_positions)
    return sum(_vbd(s, replacement) for s in starters)


def _ensure_intervals(p: Dict) -> Dict:
    pts = float(p.get("projected_points", 0) or 0)
    pos = (p.get("position") or p.get("position_group") or "UNK").upper()

    if "projection_lower" in p and "projection_upper" in p and "width" in p:
        return p

    m = {"QB": 1.45, "RB": 1.07, "WR": 1.12, "TE": 0.88, "K": 0.55, "DEF": 0.75}
    pos_factor = m.get(pos, 1.0)
    pt_factor = 1.0 if pts <= 12 else min(1.60, 1.0 + (pts - 12) * 0.022)
    width = max(3.0, min(14.0, 5.0 * pos_factor * pt_factor))

    p_copy = dict(p)
    p_copy["projection_lower"] = round(pts - width, 2)
    p_copy["projection_upper"] = round(pts + width, 2)
    p_copy["width"] = round(width, 2)
    return p_copy


def get_start_sit_recommendations(
    roster_players: List[Dict],
    bench_players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
) -> List[Dict]:
    all_players = [_ensure_intervals(p) for p in (roster_players + bench_players)]
    starters, bench = _optimal_lineup(all_players, roster_positions)

    worst_by_pos: Dict[str, Dict] = {}
    for s in starters:
        pos = s.get("slot", "UNK")
        if pos == "FLEX":
            pos = (s.get("position") or s.get("position_group") or "UNK").upper()
        pts = float(s.get("projected_points", 0) or 0)
        if pos not in worst_by_pos or pts < float(worst_by_pos[pos].get("projected_points", 0)):
            worst_by_pos[pos] = s

    recommendations = []

    for s in starters:
        pos = (s.get("position") or s.get("position_group") or "UNK").upper()
        starter_pts = float(s.get("projected_points", 0) or 0)

        # Check if any bench player at same position overlaps starter point estimate
        toss_up = False
        for b in bench:
            b_pos = (b.get("position") or b.get("position_group") or "UNK").upper()
            if b_pos != pos:
                continue
            bench_upper = float(b.get("projection_upper", 0) or 0)
            if bench_upper >= starter_pts:
                toss_up = True
                break

        pts = float(s.get("projected_points", 0) or 0)
        recommendations.append({
            "player_id": s.get("player_id"),
            "player_name": s.get("player_name", f"Player {s.get('player_id')}"),
            "position": pos,
            "slot": s.get("slot", pos),
            "projected_points": pts,
            "projection_lower": float(s.get("projection_lower", pts - 2.5)),
            "projection_upper": float(s.get("projection_upper", pts + 2.5)),
            "width": float(s.get("width", 5.0)),
            "recommendation": "TOSS-UP" if toss_up else "START",
            "confidence": "LOW" if toss_up else ("HIGH" if pts > 12 else "MEDIUM"),
            "team": s.get("team", ""),
            "opponent_team": s.get("opponent_team", ""),
            "injury_status": s.get("injury_status"),
        })

    for b in bench:
        pos = (b.get("position") or b.get("position_group") or "UNK").upper()
        pts = float(b.get("projected_points", 0) or 0)

        # Check if bench player's upper overlaps any starter's point estimate at same pos
        toss_up = False
        bench_upper = float(b.get("projection_upper", 0) or 0)
        worst = worst_by_pos.get(pos)
        if worst:
            worst_pts = float(worst.get("projected_points", 0) or 0)
            if bench_upper >= worst_pts:
                toss_up = True

        recommendations.append({
            "player_id": b.get("player_id"),
            "player_name": b.get("player_name", f"Player {b.get('player_id')}"),
            "position": pos,
            "slot": "BN",
            "projected_points": pts,
            "projection_lower": float(b.get("projection_lower", pts - 2.5)),
            "projection_upper": float(b.get("projection_upper", pts + 2.5)),
            "width": float(b.get("width", 5.0)),
            "recommendation": "TOSS-UP" if toss_up else "SIT",
            "confidence": "LOW" if toss_up else "MEDIUM",
            "team": b.get("team", ""),
            "opponent_team": b.get("opponent_team", ""),
            "injury_status": b.get("injury_status"),
        })

    return recommendations


def get_waiver_priority(
    roster_players: List[Dict],
    free_agents: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
) -> List[Dict]:
    all_rostered = list(roster_players)
    current_starters, _ = _optimal_lineup(all_rostered, roster_positions)
    replacement = _replacement_levels(
        all_rostered + free_agents, roster_positions
    )

    # Worst starter per position for replacement calc
    worst_by_pos: Dict[str, Tuple[float, Dict]] = {}
    for s in current_starters:
        pos = (s.get("position") or s.get("position_group") or "UNK").upper()
        pts = float(s.get("projected_points", 0) or 0)
        if pos not in worst_by_pos or pts < worst_by_pos[pos][0]:
            worst_by_pos[pos] = (pts, s)

    waiver_recs = []

    for agent in free_agents:
        agent_pos = (agent.get("position") or agent.get("position_group") or "UNK").upper()
        agent_pts = float(agent.get("projected_points", 0) or 0)

        if agent_pts < 3.0:
            continue

        # Direct position upgrade: does this player beat worst starter at their position?
        worst = worst_by_pos.get(agent_pos)
        improvement = 0.0
        replaces = None

        if worst:
            improvement = agent_pts - worst[0]
            if improvement > 0:
                replaces = worst[1]

        # FLEX upgrade: for RB/WR/TE, also check if better than worst FLEX starter
        if agent_pos in FLEX_ELIGIBLE and improvement <= 0:
            for flex_pos in FLEX_ELIGIBLE:
                w = worst_by_pos.get(flex_pos)
                if w:
                    flex_improvement = agent_pts - w[0]
                    if flex_improvement > improvement:
                        improvement = flex_improvement
                        replaces = w[1]

        if improvement <= 0:
            vbd_val = _vbd(agent, replacement)
            if vbd_val > 2.0:
                improvement = vbd_val
            else:
                continue

        waiver_recs.append({
            "player_id": agent.get("player_id"),
            "player_name": agent.get("player_name", f"Player {agent.get('player_id')}"),
            "position": agent_pos,
            "projected_points": agent_pts,
            "improvement_over_roster": round(improvement, 2),
            "vbd": round(_vbd(agent, replacement), 2),
            "replaces_player_id": replaces.get("player_id") if replaces else None,
            "replaces_player_name": replaces.get("player_name") if replaces else None,
            "waiver_priority": 0,
        })

    waiver_recs.sort(key=lambda x: x["improvement_over_roster"], reverse=True)
    for i, rec in enumerate(waiver_recs):
        rec["waiver_priority"] = i + 1

    return waiver_recs


def calculate_rest_of_season_value(
    player: Dict,
    current_week: int,
    total_weeks: int,
    team_ratings: Dict[str, Dict[str, float]],
    replacement_levels: Optional[Dict[str, float]] = None,
    pos_weight: float = 1.0,
) -> float:
    """Rest-of-season VBD: (weekly_pts - repl) * weeks_remaining * pos_weight,
    with opponent-defense and injury adjustments applied to weekly_pts."""
    weekly_pts = float(player.get("projected_points", 0) or 0)

    # Opponent defense rating adjustment gated OFF by default (see ENABLE_OPPONENT_ADJUSTMENT).
    # tested and REJECTED — evidence: stat_projector.py:22-24 opponent defense factors hurt
    # correlation even with shrinkage; do not enable in production without honest OOS backtest.
    # evaluate_trade passes {} so behavior there unchanged regardless of flag.
    if ENABLE_OPPONENT_ADJUSTMENT:
        opp = player.get("opponent_team") or ""
        pos = (player.get("position") or player.get("position_group") or "UNK").upper()
        if opp and team_ratings and opp in team_ratings:
            pos_key = f"vs_{pos}"
            rating_entry = team_ratings[opp].get(pos_key) or team_ratings[opp].get("overall")
            if rating_entry is not None:
                r_val = getattr(rating_entry, "value", rating_entry)
                if isinstance(r_val, (int, float)):
                    # Baseline Elo is 1500. Rating >1500 is a tough defense (lower points), <1500 is easy (higher points).
                    mult = max(0.85, min(1.15, 1.0 + (1500.0 - r_val) / 2000.0))
                    weekly_pts *= mult

    weeks_remaining = max(0, total_weeks - current_week + 1)

    # Injury discount: questionable ~15%, doubtful/out ~40%
    injury = (player.get("injury_status") or "").lower()
    if injury == "questionable":
        weekly_pts *= 0.85
    elif injury in ("doubtful", "out"):
        weekly_pts *= 0.60

    if replacement_levels:
        pos = (player.get("position") or player.get("position_group") or "UNK").upper()
        repl = replacement_levels.get(pos, 0.0)
        weekly_vor = weekly_pts - repl
    else:
        weekly_vor = weekly_pts
    ros_pts = weekly_vor * weeks_remaining

    if pos_weight is not None:
        try:
            w = float(pos_weight)
        except Exception:
            w = 1.0
        ros_pts *= w

    return ros_pts


def evaluate_trade(
    team_a_players: List[Dict],
    team_b_players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
    current_week: int = 1,
    total_weeks: int = 18,
    all_league_players: List[Dict] | None = None,
    market_consensus: List[Dict] | None = None,
) -> Dict:
    # Determine comparison list for VBD auction params
    comp_list = None
    use_market = False
    if market_consensus is not None and len(market_consensus) >= 20:
        has_model = False
        for r in market_consensus:
            if isinstance(r, dict) and r.get("model_season_points") is not None:
                has_model = True
                break
        if has_model:
            comp_list = market_consensus
            use_market = True

    if not use_market:
        # fallback to small-set (team_a + team_b) when market not available
        comp_list = (team_a_players or []) + (team_b_players or [])

    # Derive VBD auction params (model_repl, pos_weight, dollar_per_vor)
    try:
        model_repl, pos_weight, dollar_per_vor = _vbd_auction_params_from_comps(comp_list)
    except Exception:
        model_repl, pos_weight, dollar_per_vor = {}, POS_WEIGHT_FALLBACK.copy(), 0.0

    # Fallback pos_weight if empty
    if not pos_weight:
        pos_weight = POS_WEIGHT_FALLBACK.copy()

    # Replacement levels for weekly VBD (traditional)
    all_players = all_league_players if (all_league_players and len(all_league_players) >= 20) else (team_a_players + team_b_players)
    replacement = _replacement_levels(all_players, roster_positions)

    def side_value(players: List[Dict]) -> Tuple[float, float]:
        weekly = 0.0
        ros = 0.0
        for p in players:
            pos = (p.get("position") or p.get("position_group") or "UNK").upper()
            if pos == "DST":
                pos = "DEF"
            w = pos_weight.get(pos, 1.0)
            weekly_vor = _vbd(p, replacement) * w
            weekly += weekly_vor
            ros_vor = calculate_rest_of_season_value(p, current_week, total_weeks, {}, replacement, w)
            ros += ros_vor
        return weekly, ros

    a_weekly, a_ros = side_value(team_a_players)
    b_weekly, b_ros = side_value(team_b_players)

    diff_points = a_ros - b_ros
    # Dollar conversion
    if dollar_per_vor and dollar_per_vor != 0:
        diff_dollars = diff_points * dollar_per_vor
        a_dollars = a_ros * dollar_per_vor
        b_dollars = b_ros * dollar_per_vor
    else:
        # No market to derive dollars: fall back to points with $ threshold scaled
        # Use points diff as proxy for dollars (so $5 threshold still meaningful for small sets)
        # For fallback small-set, we already have weighted points; treat $ = points * 0.5 approx?
        # To keep fair threshold working, use raw points diff for dollar logic when no dollar_per_vor.
        diff_dollars = diff_points
        a_dollars = a_ros
        b_dollars = b_ros

    # Fair threshold +/- $5
    if abs(diff_dollars) < 5:
        winner = "Fair"
        recommendation = f"Trade is roughly fair (weighted VOR diff ${abs(diff_dollars):.1f} < $5)"
    elif diff_dollars > 0:
        winner = "Team A"
        recommendation = f"Team A wins by ${abs(diff_dollars):.1f} ({abs(diff_points):.1f} weighted VOR ROS)"
    else:
        winner = "Team B"
        recommendation = f"Team B wins by ${abs(diff_dollars):.1f} ({abs(diff_points):.1f} weighted VOR ROS)"

    return {
        "winner": winner,
        "value_difference": round(abs(diff_dollars), 2),
        "team_a_weekly_vbd": round(a_weekly, 2),
        "team_b_weekly_vbd": round(b_weekly, 2),
        "team_a_ros_vbd": round(a_ros, 2),
        "team_b_ros_vbd": round(b_ros, 2),
        "team_a_ros_dollars": round(a_dollars, 2),
        "team_b_ros_dollars": round(b_dollars, 2),
        "dollar_per_vor": round(dollar_per_vor, 4) if dollar_per_vor else 0.0,
        "recommendation": recommendation,
    }


def get_decision_layer_recommendations(
    roster_players: List[Dict],
    bench_players: List[Dict],
    free_agents: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
    current_week: int = 4,
    total_weeks: int = 18,
) -> Dict:
    start_sit = get_start_sit_recommendations(
        roster_players, bench_players, scoring_settings, roster_positions
    )

    waiver = get_waiver_priority(
        roster_players, free_agents, scoring_settings, roster_positions
    )

    trade_eval = {
        "note": "Trade evaluation requires specific trade proposals",
        "function_available": True,
    }

    return {
        "start_sit": start_sit,
        "waiver_priority": waiver,
        "trade_evaluation": trade_eval,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Shadow-gated promotion paths (NON-BREAKING, additive only).
# Experimental rules check shadow.is_trusted(kind) and fall back to baseline
# + log when untrusted (default threshold config.MIN_SHADOW_SAMPLES=20,
# resolved-only counting). Existing get_*_recommendations above are unchanged;
# these wrappers only add a "rule" marker (baseline vs experimental) so callers
# can observe which path was taken without behavior change when conn=None.
def get_start_sit_gated(
    conn,
    roster_players: List[Dict],
    bench_players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
    kind: str = "start_sit",
) -> List[Dict]:
    """Start/sit with shadow trust gate (non-breaking).

    - conn=None → baseline (no trust check, rule=baseline).
    - conn + untrusted (<20 resolved) → baseline + log, rule=baseline.
    - conn + trusted (>=20 resolved) → experimental (same optimizer + marker),
      rule=experimental. Experimental currently mirrors baseline optimizer;
      future heuristics plug in here behind the same gate.
    """
    import logging

    logger = logging.getLogger(__name__)
    baseline = get_start_sit_recommendations(
        roster_players, bench_players, scoring_settings, roster_positions
    )
    if conn is None:
        for r in baseline:
            r["rule"] = "baseline"
        return baseline
    try:
        from ffanalytics import shadow as _shadow

        trusted = _shadow.is_trusted(conn, kind)
    except Exception:
        trusted = False
    if not trusted:
        logger.info(
            f"shadow {kind} untrusted (<MIN_SHADOW_SAMPLES resolved) — "
            "falling back to baseline start/sit rule"
        )
        for r in baseline:
            r["rule"] = "baseline"
        return baseline
    for r in baseline:
        r["rule"] = "experimental"
    return baseline


def get_waiver_priority_gated(
    conn,
    roster_players: List[Dict],
    free_agents: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
    kind: str = "waiver",
) -> List[Dict]:
    """Waiver with shadow trust gate (non-breaking, mirrors start_sit_gated)."""
    import logging

    logger = logging.getLogger(__name__)
    baseline = get_waiver_priority(
        roster_players, free_agents, scoring_settings, roster_positions
    )
    if conn is None:
        for r in baseline:
            r["rule"] = "baseline"
        return baseline
    try:
        from ffanalytics import shadow as _shadow

        trusted = _shadow.is_trusted(conn, kind)
    except Exception:
        trusted = False
    if not trusted:
        logger.info(
            f"shadow {kind} untrusted (<MIN_SHADOW_SAMPLES resolved) — "
            "falling back to baseline waiver rule"
        )
        for r in baseline:
            r["rule"] = "baseline"
        return baseline
    for r in baseline:
        r["rule"] = "experimental"
    return baseline
