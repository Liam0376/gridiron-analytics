// VBD (Value Based Drafting) auction pricing from comparison data
// Mirrors auction.js logic: dynamic replacement levels + budget-proportional pricing
import { leagueEconomics } from '../lib/league.js';
import { SEASON_GAMES } from '../lib/auctionMath.js';

const TEAMS = 12;
const BUDGET = 200;
// Aligned with src/ffanalytics/comparison.py: QB12 RB28 WR32 TE12 (12-team 2-FLEX: 72 flex-eligible starters)
// K/DEF capped to $1 in real drafts (streamed) — VBD computes but vbdAuction clamps
// NOTE: legacy defaults — live code derives per-league indices from the
// league param (see leagueEconomics); these stay for backward compat.
const REPL_IDX = { QB: 12, RB: 28, WR: 32, TE: 12, K: 12, DEF: 12 };

export function computeVbdParams(compPlayers, league) {
  const econ = league || leagueEconomics({});
  const replIdx = {};
  for (const pos of ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']) {
    replIdx[pos] = econ.replCounts[pos] ?? REPL_IDX[pos];
  }
  const flexSlotsTotal = econ.flexSlots * econ.teams;
  const byPos = { QB: [], RB: [], WR: [], TE: [], K: [], DEF: [] };

  compPlayers.forEach(p => {
    const pos = (p.position || '').toUpperCase();
    if (!byPos[pos]) return;
    const weekly = Number(p.projected_points || p.weekly || 0);
    // Audit 22.0: use league season length instead of hardcoded *17 —
    // keeps consistent with auctionMath.js SEASON_GAMES constant.
    const szn = Number(p.model_season_points || 0) || (weekly * SEASON_GAMES);
    byPos[pos].push(szn);
  });

  // why 1-based counts here (not 0-based like auctionMath REPL_IDX):
  // these feed slice(n) cutoffs + [n-1] indexing below, both count-based.
  for (const pos in byPos) byPos[pos].sort((a, b) => b - a);

  const replPts = {};
  for (const pos in replIdx) {
    const arr = byPos[pos] || [];
    const idx = replIdx[pos] - 1;
    replPts[pos] = idx < arr.length ? arr[idx] : 0;
  }

  // FLEX pool: remaining RB/WR/TE after positional starters
  const flexPool = [
    ...byPos.RB.slice(replIdx.RB),
    ...byPos.WR.slice(replIdx.WR),
    ...byPos.TE.slice(replIdx.TE),
  ].sort((a, b) => b - a);
  const flexRepl = flexSlotsTotal - 1 < flexPool.length ? flexPool[flexSlotsTotal - 1] : 0;

  // Effective replacement: max(positional, flex) for FLEX-eligible positions
  for (const pos of ['RB', 'WR', 'TE']) {
    replPts[pos] = Math.max(replPts[pos], flexRepl);
  }

  // Dynamic positional weighting: market_share / model_share (mirrors comparison.py)
  // Pure VOR overvalues QB in 1QB; recompute per-refresh and clamp [0.5,1.5]
  // First, raw VOR per pos for share calc
  const rawPerPos = {};
  const rawTotal = { model: 0, market: 0 };
  // Need market season for weighting — use model season for now, but frontend has both
  // For frontend, approximate weight from model distribution vs empirical market 6/47/37/8
  // Fallback to last empirical: QB0.65 etc, but recompute if market data available
  // Here we compute weight from model-only vs expected market share (6/47/37/8) as proxy
  const POS_WEIGHT = { QB: 0.65, RB: 1.10, WR: 0.92, TE: 0.78, K: 0, DEF: 0 };
  // If comparison data includes market_season_points, derive dynamic weight
  const hasMarket = compPlayers.some(p => p.market_season_points != null);
  if (hasMarket) {
    const byPosMarket = { QB: [], RB: [], WR: [], TE: [] };
    compPlayers.forEach(p => {
      const pos = (p.position || '').toUpperCase();
      if (!byPosMarket[pos]) return;
      const ms = Number(p.market_season_points || 0);
      if (ms > 0) byPosMarket[pos].push(ms);
    });
    Object.keys(byPosMarket).forEach(pos => byPosMarket[pos].sort((a,b)=>b-a));
    const rawModelPerPos = {};
    const rawMarketPerPos = {};
    let rawModelTotal = 0, rawMarketTotal = 0;
    for (const pos of ['QB','RB','WR','TE']) {
      const repl = replPts[pos] ?? 0;
      const modelVals = byPos[pos] || [];
      const marketVals = byPosMarket[pos] || [];
      // market repl
      const mIdx = replIdx[pos]-1;
      const marketRepl = mIdx < marketVals.length ? marketVals[mIdx] : (marketVals[marketVals.length-1]||0);
      const modelSum = modelVals.reduce((s,szn)=> s + Math.max(0, szn - repl), 0);
      const marketSum = marketVals.reduce((s,szn)=> s + Math.max(0, szn - marketRepl), 0);
      rawModelPerPos[pos]=modelSum;
      rawMarketPerPos[pos]=marketSum;
      rawModelTotal+=modelSum;
      rawMarketTotal+=marketSum;
    }
    for (const pos of ['QB','RB','WR','TE']) {
      const modelShare = rawModelTotal ? rawModelPerPos[pos]/rawModelTotal : 0;
      const marketShare = rawMarketTotal ? rawMarketPerPos[pos]/rawMarketTotal : 0;
      if (modelShare>0 && marketShare>0) {
        const w = marketShare / modelShare;
        POS_WEIGHT[pos] = Math.max(0.5, Math.min(1.5, w));
      }
    }
  }
  // Compute total VOR across all starters to determine $/VOR ratio
  let totalVor = 0;
  const allVors = [];
  for (const pos in byPos) {
    const repl = replPts[pos] || 0;
    const w = POS_WEIGHT[pos] ?? 1;
    byPos[pos].forEach(szn => {
      const vor = Math.max(0, szn - repl) * w;
      if (vor > 0) allVors.push(vor);
    });
  }
  allVors.sort((a, b) => b - a);
  const starterSlots = econ.starterSlotsTotal;
  const starters = allVors.slice(0, starterSlots);
  totalVor = starters.reduce((s, v) => s + v, 0) || 1;

  const starterBudget = econ.starterPool;

  return { replPts, dollarPerVor: starterBudget / totalVor, posWeight: POS_WEIGHT };
}

export function vbdAuction(modelSeasonPts, pos, params) {
  // K/DEF are streamed at $1 — cap even if VOR positive due to model noise
  if (pos === 'K' || pos === 'DEF' || pos === 'DST') {
    if (modelSeasonPts == null || modelSeasonPts < 50) return 1;
    const repl = params.replPts[pos] ?? 0;
    const vor = Math.max(0, modelSeasonPts - repl);
    if (vor > 40) return 2;
    return 1;
  }
  const w = params.posWeight?.[pos] ?? 1;
  const repl = params.replPts[pos] ?? 0;
  const vor = Math.max(0, modelSeasonPts - repl) * w;
  if (vor <= 0) return 1;
  return Math.max(1, Math.round(vor * params.dollarPerVor));
}

export function vbdAuctionUncapped(modelSeasonPts, pos, params) {
  const w = params.posWeight?.[pos] ?? 1;
  const repl = params.replPts[pos] ?? 0;
  const vor = Math.max(0, (Number(modelSeasonPts)||0) - repl) * w;
  const uncapped = Math.round(vor * params.dollarPerVor);
  if (uncapped > 0) return uncapped;
  // Bench true value: show points-based $2-5 even when VOR 0 (so $1 bench not $0)
  const season = Number(modelSeasonPts)||0;
  if (season > 50) {
    const weekly = season / 17;
    return Math.max(1, Math.min(5, Math.round(weekly * 0.35)));
  }
  return 0;
}
