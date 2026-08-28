"""Decision layer: produces start/sit, waiver priority, and trade evaluations
using projections, ratings, and roster constraints."""

from typing import Dict, List, Optional, Tuple
from ffanalytics import config
from ffanalytics.projection import calculate_weekly_projections
import heapq


def calculate_roster_value(
    players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str]
) -> float:
    """
    Calculate total fantasy value of a roster based on scoring settings.

    Args:
        players: List of player dicts with projected_points
        scoring_settings: League scoring settings (e.g., {"pass_td": 4, "pass_yd": 0.04})
        roster_positions: List of required position slots (e.g., ["QB", "RB", "RB", ...])

    Returns:
        Total projected points for the roster
    """
    # Sort players by projected points descending
    sorted_players = sorted(players, key=lambda x: x.get("projected_points", 0), reverse=True)

    # Simple assignment: assign highest scorers to positions in order
    # In reality, this would need position matching logic
    total_points = 0.0
    for i, player in enumerate(sorted_players[:len(roster_positions)]):
        total_points += player.get("projected_points", 0)

    return total_points


def get_start_sit_recommendations(
    roster_players: List[Dict],
    bench_players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str]
) -> List[Dict]:
    """
    Generate start/sit recommendations for each roster slot.

    Args:
        roster_players: Players currently on roster
        bench_players: Players on bench available to start
        scoring_settings: League scoring settings
        roster_positions: Required position slots for the league

    Returns:
        List of recommendations with player info and start/sit advice
    """
    all_players = roster_players + bench_players
    # Sort by projected points descending
    sorted_players = sorted(all_players, key=lambda x: x.get("projected_points", 0), reverse=True)

    recommendations = []
    starting_slots = max(1, len(roster_positions) - 1)

    for i, player in enumerate(sorted_players):
        is_starter = i < starting_slots
        recommendation = {
            "player_id": player.get("player_id"),
            "player_name": player.get("player_name", f"Player {player.get('player_id')}"),
            "position": player.get("position_group", "UNK"),
            "projected_points": player.get("projected_points", 0),
            "recommendation": "START" if is_starter else "SIT",
            "confidence": "HIGH" if is_starter and i < starting_slots - 2 else "MEDIUM"  # Simplified
        }
        recommendations.append(recommendation)

    return recommendations


def get_waiver_priority(
    roster_players: List[Dict],
    free_agents: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str]
) -> List[Dict]:
    """
    Generate waiver priority rankings for free agents.

    Args:
        roster_players: Players currently on roster
        free_agents: Available free agent players
        scoring_settings: League scoring settings
        roster_positions: Required position slots for the league

    Returns:
        List of free agents ranked by upgrade value
    """
    # Calculate current roster value
    current_value = calculate_roster_value(roster_players, scoring_settings, roster_positions)

    # Count required starters per position
    required_counts = {}
    for pos in roster_positions:
        required_counts[pos] = required_counts.get(pos, 0) + 1

    # Count current starters per position
    current_counts = {}
    for player in roster_players:
        pos = player.get("position_group", "UNK")
        current_counts[pos] = current_counts.get(pos, 0) + 1

    waiver_recommendations = []

    for agent in free_agents:
        agent_pos = agent.get("position_group", "UNK")
        agent_points = float(agent.get("projected_points", 0) or 0)

        best_improvement = 0.0
        best_replaced_player = None
        best_replaced_index = -1
        found_compatible_position = False

        # Try replacing each roster player with this free agent
        for i, roster_player in enumerate(roster_players):
            roster_pos = roster_player.get("position_group", "UNK")

            # Simple position compatibility check (would be more sophisticated in reality)
            compatible = (
                roster_pos == agent_pos or
                "FLEX" in roster_positions and agent_pos in ["RB", "WR", "TE"] or
                agent_pos == "FLEX" or
                # Allow TE to replace WR/RB and vice versa (common in fantasy leagues)
                (roster_pos == "TE" and agent_pos in ["WR", "RB"]) or
                (agent_pos == "TE" and roster_pos in ["WR", "RB"])
            )

            if compatible:
                found_compatible_position = True
                # Create test roster with this substitution
                test_roster = roster_players.copy()
                test_roster[i] = agent

                # Calculate new roster value
                new_value = calculate_roster_value(test_roster, scoring_settings, roster_positions)
                improvement = new_value - current_value

                if improvement > best_improvement:
                    best_improvement = improvement
                    best_replaced_player = roster_player
                    best_replaced_index = i

        # Consider adding agent to an open starter slot (if we need more of this position)
        needed = required_counts.get(agent_pos, 0)
        have = current_counts.get(agent_pos, 0)
        if needed > have:
            found_compatible_position = True
            # New value would be current value plus agent's points (adding to vacant slot)
            new_value = current_value + agent_points
            improvement = new_value - current_value  # which is agent_points
            if improvement > best_improvement:
                best_improvement = improvement
                best_replaced_player = None  # No player replaced
                best_replaced_index = -1

        # Only recommend if we found at least one compatible position AND it gives positive improvement
        if found_compatible_position and best_improvement > 0:
            recommendation = {
                "player_id": agent.get("player_id"),
                "player_name": agent.get("player_name", f"Player {agent.get('player_id')}"),
                "position": agent.get("position_group", "UNK"),
                "projected_points": agent_points,
                "improvement_over_roster": best_improvement,
                "replaces_player_id": best_replaced_player.get("player_id") if best_replaced_player else None,
                "replaces_player_name": best_replaced_player.get("player_name") if best_replaced_player else None,
                "waiver_priority": 0  # Placeholder, will be set after sorting
            }
            waiver_recommendations.append(recommendation)

    # Sort by improvement descending and assign priority ranks
    waiver_recommendations.sort(key=lambda x: x["improvement_over_roster"], reverse=True)
    for i, rec in enumerate(waiver_recommendations):
        rec["waiver_priority"] = i + 1

    return waiver_recommendations


def calculate_rest_of_season_value(
    player: Dict,
    current_week: int,
    total_weeks: int,
    team_ratings: Dict[str, Dict[str, float]]
) -> float:
    """
    Calculate projected rest-of-season value for a player.

    Args:
        player: Player dict with projected_points and trend info
        current_week: Current NFL week (1-18)
        total_weeks: Total weeks in season
        team_ratings: Team ratings for strength of schedule adjustments

    Returns:
        Projected rest-of-season value
    """
    weekly_points = player.get("projected_points", 0)
    weeks_remaining = total_weeks - current_week

    # Simple projection: assume same weekly points for remainder of season
    # In reality, would adjust for injuries, schedule strength, etc.
    ros_value = weekly_points * weeks_remaining

    return ros_value


def evaluate_trade(
    team_a_players: List[Dict],
    team_b_players: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
    current_week: int = 4,
    total_weeks: int = 18
) -> Dict:
    """
    evaluate a proposed trade between two teams.

    Args:
        team_a_players: Players Team A would give up
        team_b_players: Players Team B would give up
        scoring_settings: League scoring settings
        roster_positions: Required position slots
        current_week: Current week in season
        total_weeks: Total weeks in season

    Returns:
        Trade evaluation with winner and value change for each team
    """
    # This is a simplified version - in reality would need full rosters for both teams
    # For now, just compare the total value of players being traded

    team_a_value = sum(p.get("projected_points", 0) for p in team_a_players)
    team_b_value = sum(p.get("projected_points", 0) for p in team_b_players)

    # Rest-of-season value would be more sophisticated
    team_a_ros = sum(calculate_rest_of_season_value(p, current_week, total_weeks, {}) for p in team_a_players)
    team_b_ros = sum(calculate_rest_of_season_value(p, current_week, total_weeks, {}) for p in team_b_players)

    if team_a_value > team_b_value:
        winner = "Team A"
        difference = team_a_value - team_b_value
    elif team_b_value > team_a_value:
        winner = "Team B"
        difference = team_b_value - team_a_value
    else:
        winner = "Tie"
        difference = 0.0

    return {
        "winner": winner,
        "value_difference": difference,
        "team_a_weeks_value": team_a_value,
        "team_b_weeks_value": team_b_value,
        "recommendation": f"{winner} wins the trade" if winner != "Tie" else "Trade is fair"
    }


def get_decision_layer_recommendations(
    roster_players: List[Dict],
    bench_players: List[Dict],
    free_agents: List[Dict],
    scoring_settings: Dict[str, float],
    roster_positions: List[str],
    current_week: int = 4,
    total_weeks: int = 18
) -> Dict:
    """
    Get all decision layer recommendations at once.

    Args:
        roster_players: Players currently on roster
        bench_players: Players on bench
        free_agents: Available free agents
        scoring_settings: League scoring settings
        roster_positions: Required position slots
        current_week: Current NFL week
        total_weeks: Total weeks in season

    Returns:
        Dict containing start/sit, waiver, and trade evaluation recommendations
    """
    start_sit = get_start_sit_recommendations(
        roster_players, bench_players, scoring_settings, roster_positions
    )

    waiver = get_waiver_priority(
        roster_players, free_agents, scoring_settings, roster_positions
    )

    # For trade evaluation, we'd need specific trade proposals
    # This is a placeholder showing the structure
    trade_eval = {
        "note": "Trade evaluation requires specific trade proposals",
        "function_available": True
    }

    return {
        "start_sit": start_sit,
        "waiver_priority": waiver,
        "trade_evaluation": trade_eval,
        "timestamp": "2026-08-27T00:00:00Z"  # Would be real timestamp in practice
    }