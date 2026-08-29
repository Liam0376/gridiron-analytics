"""Decision layer: produces start/sit, waiver priority, and trade evaluations
using projections, ratings, and roster constraints.

Position-constrained optimization using greedy assignment with VBD
(Value Based Drafting) for positional scarcity."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ffanalytics import config

FLEX_ELIGIBLE = {"RB", "WR", "TE"}

# Slot requirements parsed from Sleeper's roster_positions list.
# roster_positions example: ["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF","BN","BN","BN","BN"]
BENCH_SLOTS = {"BN", "IR"}


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
    """Compute replacement-level projection per position.

    Replacement level = projection of the (N*num_teams + 1)th player at that position,
    where N = number of starting slots for that position (including FLEX share)."""
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
    """Value Based Drafting: player projection minus replacement level at their position."""
    pos = (player.get("position") or player.get("position_group") or "UNK").upper()
    pts = float(player.get("projected_points", 0) or 0)
    return pts - replacement_levels.get(pos, 0.0)


def calculate_roster_value(
    players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
) -> float:
    """Total VBD-based roster value using optimal lineup assignment."""
    starters, _ = _optimal_lineup(players, roster_positions)
    replacement = _replacement_levels(players, roster_positions)
    return sum(_vbd(s, replacement) for s in starters)


def get_start_sit_recommendations(
    roster_players: List[Dict],
    bench_players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
) -> List[Dict]:
    """Position-constrained start/sit with interval overlap detection."""
    all_players = roster_players + bench_players
    starters, bench = _optimal_lineup(all_players, roster_positions)

    # Build worst-starter-per-position for toss-up detection
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
        starter_lower = float(s.get("projection_lower", 0) or 0)

        # Check if any bench player at same position has upper bound overlapping
        toss_up = False
        for b in bench:
            b_pos = (b.get("position") or b.get("position_group") or "UNK").upper()
            if b_pos != pos:
                continue
            bench_upper = float(b.get("projection_upper", 0) or 0)
            if bench_upper > 0 and starter_lower > 0 and bench_upper >= starter_lower:
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

        # Check if bench player's upper overlaps any starter's lower at same pos
        toss_up = False
        bench_upper = float(b.get("projection_upper", 0) or 0)
        worst = worst_by_pos.get(pos)
        if worst and bench_upper > 0:
            worst_lower = float(worst.get("projection_lower", 0) or 0)
            if worst_lower > 0 and bench_upper >= worst_lower:
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
    """Waiver priority using VBD improvement over current optimal lineup."""
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
) -> float:
    """Rest-of-season VBD value with injury discount and defensive rating adjustment."""
    weekly_pts = float(player.get("projected_points", 0) or 0)

    # Opponent defense rating adjustment if available
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

    weeks_remaining = max(0, total_weeks - current_week)

    # Injury discount: questionable ~15%, doubtful/out ~40%
    injury = (player.get("injury_status") or "").lower()
    if injury == "questionable":
        weekly_pts *= 0.85
    elif injury in ("doubtful", "out"):
        weekly_pts *= 0.60

    ros_pts = weekly_pts * weeks_remaining

    if replacement_levels:
        pos = (player.get("position") or player.get("position_group") or "UNK").upper()
        repl = replacement_levels.get(pos, 0.0)
        ros_pts -= repl * weeks_remaining

    return ros_pts


def evaluate_trade(
    team_a_players: List[Dict],
    team_b_players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
    current_week: int = 4,
    total_weeks: int = 18,
) -> Dict:
    """Trade evaluation using positional VBD, not raw point sums."""
    all_players = team_a_players + team_b_players
    replacement = _replacement_levels(all_players, roster_positions)

    def side_value(players: List[Dict]) -> Tuple[float, float]:
        weekly = sum(_vbd(p, replacement) for p in players)
        ros = sum(
            calculate_rest_of_season_value(p, current_week, total_weeks, {}, replacement)
            for p in players
        )
        return weekly, ros

    a_weekly, a_ros = side_value(team_a_players)
    b_weekly, b_ros = side_value(team_b_players)

    diff = a_ros - b_ros
    if abs(diff) < 2.0:
        winner = "Fair"
        recommendation = "Trade is roughly fair (VBD difference < 2 pts/week ROS)"
    elif diff > 0:
        winner = "Team A"
        recommendation = f"Team A wins by {abs(diff):.1f} VBD points ROS"
    else:
        winner = "Team B"
        recommendation = f"Team B wins by {abs(diff):.1f} VBD points ROS"

    return {
        "winner": winner,
        "value_difference": round(abs(diff), 2),
        "team_a_weekly_vbd": round(a_weekly, 2),
        "team_b_weekly_vbd": round(b_weekly, 2),
        "team_a_ros_vbd": round(a_ros, 2),
        "team_b_ros_vbd": round(b_ros, 2),
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
    """All decision layer recommendations at once."""
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
