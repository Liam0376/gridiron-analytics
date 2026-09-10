// hub/src/lib/relevance.js — demote off-depth-chart players, never remove.
//
// Sort contract: relevant tier first, then the caller's existing score key
// (projected_points / totalFair) descending within each tier. Stable sort,
// so equal keys keep their previous order. When the chart has no entry for
// a player, depthRank is -1 → irrelevant tier, still listed (demote, don't
// remove — user decision 2026-09-10). Non-chart positions (K/DEF/IDP) stay
// in the relevant tier untouched.
import { depthRank, isDepthRelevant, DEPTH_TOP_N } from './depthChart.js';

export { DEPTH_TOP_N };

const defaultAccessors = {
  teamOf: (p) => p.team,
  posOf: (p) => p.position || p.position_group,
  nameOf: (p) => p.player_name ?? p.name,
  scoreOf: (p) => Number(p.projected_points ?? p.totalFair ?? 0) || 0,
};

export function relevanceTier(p, accessors = {}) {
  const a = { ...defaultAccessors, ...accessors };
  const pos = String(a.posOf(p) || '').toUpperCase();
  if (!pos || pos === 'UNK') return 1;
  return isDepthRelevant(a.teamOf(p), pos, a.nameOf(p)) ? 0 : 1;
}

export function sortByRelevance(items, accessors = {}) {
  const a = { ...defaultAccessors, ...accessors };
  return [...items].sort((x, y) => {
    const tier = relevanceTier(x, a) - relevanceTier(y, a);
    if (tier !== 0) return tier;
    return a.scoreOf(y) - a.scoreOf(x);
  });
}

export function annotateRelevance(p, accessors = {}) {
  const a = { ...defaultAccessors, ...accessors };
  return {
    tier: relevanceTier(p, a),
    rank: depthRank(a.teamOf(p), a.posOf(p), a.nameOf(p)),
  };
}
