// hub/src/lib/depthChart.js — FantasyPros 2026 depth-chart relevance.
//
// Snapshot: ./depthChart.json, generated once from repo-root
// FantasyPros_Fantasy_Football_2026_Depth_Charts.csv — one JSON object per
// team abbr, each position an array of normed names in ECR row order
// (index = depth rank). Regen: re-parse team blocks the same way and
// replace the JSON; the .js contract (ordered arrays) is unchanged.
// Team full-name→abbr mirrored from
// src/ffanalytics/adapters/fantasypros_projections.py:TEAM_NAME_TO_ABBR,
// then through config.TEAM_CANONICAL (Rams LAR→LA, the schedule/hub
// convention) — without that the whole Rams roster misses every lookup.
// Name norm mirrors projections.js normName AND _norm_name in
// adapters/fantasypros_projections.py (suffix-strip) so lookups match.
// Missing/unparseable chart or unknown (team,pos) → rank -1, and callers
// must fall back to existing order (never fail-closed).
import depthChart from './depthChart.json' with { type: 'json' };

// why these cutoffs (user-confirmed 2026-09-10): top-N per position counts
// as fantasy-relevant; deeper names are demoted, never removed.
export const DEPTH_TOP_N = { QB: 2, RB: 4, WR: 6, TE: 3 };

export const DEPTH_POSITIONS = new Set(Object.keys(DEPTH_TOP_N));

export function normDepthName(n) {
  return String(n || '').toLowerCase()
    .replace(/\b(jr\.?|sr\.?|ii|iii|iv|v)\b/g, '')
    .replace(/[^a-z0-9 ]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// 0-based rank within (team, pos) ECR order, or -1 when unknown.
export function depthRank(team, pos, name) {
  const t = String(team || '').toUpperCase();
  const p = String(pos || '').toUpperCase();
  if (!DEPTH_POSITIONS.has(p)) return -1;
  const list = (depthChart[t] || {})[p];
  if (!Array.isArray(list)) return -1;
  return list.indexOf(normDepthName(name));
}

// Relevant = on the chart within the top-N cut. Positions without depth
// data (K/DEF/IDP) are untouched → treated as relevant.
export function isDepthRelevant(team, pos, name) {
  const p = String(pos || '').toUpperCase();
  if (!DEPTH_POSITIONS.has(p)) return true;
  const rank = depthRank(team, pos, name);
  return rank !== -1 && rank < (DEPTH_TOP_N[p] ?? 0);
}
