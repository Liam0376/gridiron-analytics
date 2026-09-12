// hub/src/lib/auctionMath.js — pure VBD/auction pricing math for auction view.
// Deduped from views/auction.js (was inline) so bidAdvice, table, and orchestrator
// can share the same numbers. No DOM, no fetch — pure functions.
import { leagueEconomics } from './league.js';

export const BUDGET = 200;
export const TEAMS = 12;
export const ROSTER_SIZE = 14; // 10 starters + 4 bench
export const SEASON_GAMES = 17;

// Replacement-level indices (0-based) for the reference 12-team 2-FLEX league.
// Mirrors src/ffanalytics/comparison.py: QB12 RB28 WR32 TE12 (72 flex-eligible starters).
// Audit 2026-09-01: RB24/WR24 understated RB/WR scarcity; now 28/32.
// NOTE: legacy defaults — live code derives per-league indices from
// opts.league (see leagueEconomics); these stay for backward compat.
export const REPL_IDX = { QB: 12 - 1, RB: 28 - 1, WR: 32 - 1, TE: 12 - 1, K: 12 - 1, DEF: 12 - 1 };

// Positional weights to dampen 1QB overvaluation in pure VOR.
// Mirrors src/ffanalytics/comparison.py and components/vbdAuction.js fallback.
export const POS_WEIGHT = { QB: 0.65, RB: 1.10, WR: 0.92, TE: 0.78, K: 0, DEF: 0 };

function namePosKey(p) {
  return `${(p.player_name || '').toLowerCase().replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim()}|${(p.position || '').toUpperCase()}`;
}

// Merge any market-only or rookie players from compRaw into players list if missing
// by id or by name+position. Mutates `players` in place and returns it.
export function mergeComparisonPlayers(players, compRaw) {
  const compPlayers = compRaw?.players || [];
  if (!compPlayers.length) return players;
  const existingIds = new Set(players.map(p => String(p.player_id)));
  const existingByNamePos = new Set(players.map(namePosKey));
  for (const c of compPlayers) {
    const cid = String(c.player_id);
    const nkey = namePosKey(c);
    if (!existingIds.has(cid) && !existingByNamePos.has(nkey)) {
      players.push({
        player_id: cid,
        player_name: c.player_name,
        position: c.position,
        team: c.team,
        projected_points: c.model_points || 0,
        point_estimate: c.model_points || 0,
        ...c,
      });
      existingIds.add(cid);
      existingByNamePos.add(nkey);
    }
  }
  return players;
}

// Build the per-player season objects with VOR, auction $, market $, tiers, drafted flags.
// Returns { rosPlayers, starters, benchPlayers, allRanked, posBudget, nominationTargets, myNeeds, myRosterCount, mySpent, myRemaining, maxBid, slotsLeft }.
//
// players      — array from fetchProjections
// compRaw      — array from fetchComparison (or null)
// compById     — Map<player_id, compPlayer> built by orchestrator
// compByNamePos— Map<"name|pos", compPlayer>
// state        — draft tracker { drafted, myRoster, myBudget, nominations }
// opts         — { budget, remaining?, league? } (budget defaults to league
//                 budget or BUDGET; league defaults to the 12x$200 reference,
//                 reproducing legacy numbers exactly — see leagueEconomics)
export function computeAuctionMath(players, compRaw, compById, compByNamePos, state, opts = {}) {
  const league = opts.league || leagueEconomics({});
  const budget = opts.budget ?? league.budget;
  const remaining = opts.remaining ?? SEASON_GAMES;
  const replIdx = {};
  for (const pos of ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']) {
    replIdx[pos] = Math.max(0, (league.replCounts[pos] ?? 12) - 1);
  }
  const rosterSize = league.startersPerTeam + league.benchPerTeam;

  const compPlayers = compRaw?.players || [];
  const existingByNamePos = new Set(players.map(namePosKey));

  // rosPlayers — full-season enriched per player
  const rosPlayers = players.map(p => {
    const nkey = namePosKey(p);
    const c = compByNamePos.get(nkey) || compById.get(String(p.player_id));
    // Prefer backend's neutral, shrunk, weighted season totals (model_season_points)
    // over weekly*17 to avoid Vegas-extrapolation and scoring-alias bias (audit 2026-09-01)
    const seasonFromBackend = c && c.model_season_points != null ? Number(c.model_season_points) : null;
    const weeklyModel = c && c.model_points != null ? Number(c.model_points) : Number(p.projected_points ?? p.point_estimate ?? 0);
    const weeklyMarket = c && c.market_points != null ? Number(c.market_points) : null;
    const ros = seasonFromBackend != null ? seasonFromBackend : weeklyModel * remaining;
    const seasonMarketFromFP = c && c.market_season_points != null ? Number(c.market_season_points) : null;
    const marketRos = seasonMarketFromFP != null ? seasonMarketFromFP : (weeklyMarket != null ? weeklyMarket * remaining : null);
    const deltaRos = marketRos != null ? +(ros - marketRos).toFixed(1) : null;

    let seasonStatDeltas = null;
    if (c && Array.isArray(c.season_stat_deltas) && c.season_stat_deltas.length) {
      seasonStatDeltas = c.season_stat_deltas;
    } else if (c && Array.isArray(c.stat_deltas) && c.stat_deltas.length) {
      seasonStatDeltas = c.stat_deltas.map(s => ({
        ...s,
        modelSeason: s.model != null ? +(s.model * remaining).toFixed(1) : null,
        marketSeason: s.market != null ? +(s.market * remaining).toFixed(1) : null,
        deltaSeason: s.delta != null ? +(s.delta * remaining).toFixed(1) : null,
      }));
    }
    return {
      ...p,
      weekly: weeklyModel,
      ros,
      marketWeekly: weeklyMarket,
      marketRos,
      deltaRos,
      seasonStatDeltas,
      // why (user-caught live bug, 2026-09-10): without this, opening a
      // player card from the Auction board showed correct $ (this file's
      // VOR math is real) but honest-empty yards/TDs — same fix as
      // projections.js (93b7b91/d910ac1).
      market_season_stats: c?.market_season_stats || null,
      widthRos: Number(p.width ?? c?.width ?? 5) * Math.sqrt(remaining),
      fp_ecr: c?.fp_ecr ?? null,
      fp_ecr_pos: c?.fp_ecr_pos ?? null,
      fp_adp: c?.fp_adp ?? null,
      fp_tier: c?.fp_tier ?? null,
      delta_rank: c?.delta_rank ?? null,
      edge: c?.edge || 'NEUTRAL',
      edge_score: c?.edge_score ?? 0,
      isDrafted: !!state.drafted[p.player_id],
      draftedBy: state.drafted[p.player_id]?.by || null,
      draftedPrice: state.drafted[p.player_id]?.price || null,
    };
  });

  // Position buckets (sorted desc by ros)
  const byPos = { QB: [], RB: [], WR: [], TE: [], K: [], DEF: [] };
  rosPlayers.forEach(p => {
    const pos = (p.position || 'UNK').toUpperCase();
    if (byPos[pos]) byPos[pos].push(p);
    else byPos[pos] = [p];
  });
  Object.values(byPos).forEach(arr => arr.sort((a, b) => b.ros - a.ros));

  // Replacement levels (positional, pure).
  // why pure positional (correctness batch 2026-09-12): mirrors Python
  // src/ffanalytics/comparison/_auction.py _replacement_points. The prior
  // max(posRepl, flexRepl) floor minted a second $ rule and drifted VOR/$.
  const replPts = {};
  for (const pos of Object.keys(byPos)) {
    const arr = byPos[pos];
    const idx = replIdx[pos] ?? 0;
    replPts[pos] = arr[idx]?.ros ?? (arr[arr.length - 1]?.ros ?? 0);
  }

  // Weighted VOR (model, pure positional replacement)
  rosPlayers.forEach(p => {
    const pos = (p.position || '').toUpperCase();
    const baseRepl = replPts[pos] ?? 0;
    p.repl = baseRepl;
    const rawVor = Math.max(0, p.ros - baseRepl);
    const w = POS_WEIGHT[pos] ?? 1;
    p.vor = rawVor * w;
    if (pos === 'K' || pos === 'DEF') p.vor = 0;
  });

  // Auction pricing — starter pool = teams*budget - bench $1 spots
  const totalStarterBudget = league.starterPool;
  const starters = rosPlayers.filter(p => p.vor > 0).sort((a, b) => b.vor - a.vor).slice(0, league.starterSlotsTotal);
  const totalVor = starters.reduce((s, p) => s + p.vor, 0) || 1;
  starters.forEach(p => {
    if (p.position === 'K' || p.position === 'DEF') p.auction = 1;
    else p.auction = Math.max(1, Math.round((p.vor / totalVor) * totalStarterBudget));
  });
  const benchPlayers = rosPlayers.filter(p => !starters.includes(p));
  benchPlayers.forEach(p => p.auction = 1);

  // Market $ — same weighted VOR on marketRos
  const marketByPos = { QB: [], RB: [], WR: [], TE: [], K: [], DEF: [] };
  rosPlayers.forEach(pp => {
    const pos = (pp.position || '').toUpperCase();
    if (marketByPos[pos]) marketByPos[pos].push(pp);
  });
  Object.values(marketByPos).forEach(arr => arr.sort((a, b) => (b.marketRos || 0) - (a.marketRos || 0)));
  const marketReplPts = {};
  for (const pos of Object.keys(marketByPos)) {
    const arr = marketByPos[pos];
    const idx = replIdx[pos] ?? 0;
    marketReplPts[pos] = arr[idx]?.marketRos ?? (arr[arr.length - 1]?.marketRos ?? 0);
  }
  rosPlayers.forEach(pp => {
    const pos = (pp.position || '').toUpperCase();
    const base = marketReplPts[pos] ?? 0;
    pp.marketRepl = base;
    const raw = Math.max(0, (pp.marketRos || 0) - base);
    const w = POS_WEIGHT[pos] ?? 1;
    pp.marketVor = (pos === 'K' || pos === 'DEF') ? 0 : raw * w;
  });
  const marketStarters = rosPlayers.filter(pp => pp.marketVor > 0).sort((a, b) => b.marketVor - a.marketVor).slice(0, league.starterSlotsTotal);
  const totalMarketVor = marketStarters.reduce((s, pp) => s + pp.marketVor, 0) || 1;
  marketStarters.forEach(pp => {
    if (pp.position === 'K' || pp.position === 'DEF') pp.marketAuction = 1;
    else pp.marketAuction = Math.max(1, Math.round((pp.marketVor / totalMarketVor) * totalStarterBudget));
  });
  rosPlayers.filter(pp => !marketStarters.includes(pp)).forEach(pp => { pp.marketAuction = 1; });

  // Blend with StatsGuy 60/40 where available
  const topFpAuction = Math.max(...rosPlayers.map(x => x.marketAuction || 0)) || 45;
  rosPlayers.forEach(pp => {
    if (pp.statsguy_value != null) {
      const sgAuction = Math.max(1, Math.round((pp.statsguy_value / 10000) * topFpAuction));
      const blended = Math.round(pp.marketAuction * 0.6 + sgAuction * 0.4);
      pp.marketAuctionFP = pp.marketAuction;
      pp.marketAuctionSG = sgAuction;
      pp.marketAuction = blended;
    }
    pp.deltaAuction = pp.auction - (pp.marketAuction || 1);
    if (pp.deltaAuction >= 5 && pp.edge !== 'BUY') pp.edge = 'BUY';
    else if (pp.deltaAuction <= -5 && pp.edge !== 'SELL') pp.edge = 'SELL';
  });

  const allRanked = [...starters, ...benchPlayers].sort((a, b) => b.auction - a.auction || b.ros - a.ros);

  // Assign tiers (positions in ranked list)
  allRanked.forEach((p, i) => {
    if (i < 8) p.tier = 1;
    else if (i < 20) p.tier = 2;
    else if (i < 40) p.tier = 3;
    else if (i < 70) p.tier = 4;
    else p.tier = 5;
  });

  // Positional budget allocation from the league's real starter slots
  const posGroups = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];
  const posBudget = {};
  for (const pos of posGroups) {
    const posStarters = starters.filter(p => (p.position || '').toUpperCase() === pos);
    const posVor = posStarters.reduce((s, p) => s + p.vor, 0);
    const share = posVor / totalVor;
    const posSlots = league.posStarterSlots[pos] ?? 1;
    posBudget[pos] = {
      recommended: Math.round(share * budget),
      slots: posSlots,
      perSlot: posSlots ? Math.round(share * budget / posSlots) : 0,
    };
  }
  const flexBudget = Math.round(budget - Object.values(posBudget).reduce((s, v) => s + v.recommended, 0));

  // My roster needs — league starter slots + standard depth
  // (QB+0, RB/WR+2, TE+1 — reproduces the tuned 1/4/4/2/1/1 at 14-man).
  const myRosterPositions = state.myRoster.map(id => {
    const p = rosPlayers.find(x => x.player_id === id);
    return p ? (p.position || '').toUpperCase() : '';
  });
  const myNeeds = {};
  const depthExtra = { QB: 0, RB: 2, WR: 2, TE: 1, K: 0, DEF: 0 };
  for (const pos of posGroups) {
    const have = myRosterPositions.filter(p => p === pos).length;
    const target = (league.posStarterSlots[pos] ?? 1) + (depthExtra[pos] ?? 1);
    myNeeds[pos] = Math.max(0, target - have);
  }

  // Nomination strategy: players to nominate that drain opponents
  const nominationTargets = allRanked
    .filter(p => !p.isDrafted && p.auction >= 5)
    .filter(p => {
      const pos = (p.position || '').toUpperCase();
      return myNeeds[pos] === 0 || p.tier >= 3;
    })
    .slice(0, 10);

  // Draft tracker stats
  const draftedCount = Object.keys(state.drafted).length;
  const availablePlayers = allRanked.filter(p => !p.isDrafted);
  const myRosterPlayers = state.myRoster.map(id => allRanked.find(p => p.player_id === id)).filter(Boolean);
  const mySpent = myRosterPlayers.reduce((s, p) => s + (state.drafted[p.player_id]?.price || 0), 0);
  const myRemaining = budget - mySpent;
  const myRosterCount = state.myRoster.length;
  const slotsLeft = rosterSize - myRosterCount;
  const maxBid = slotsLeft > 1 ? myRemaining - (slotsLeft - 1) : myRemaining;

  return {
    rosPlayers,
    starters,
    benchPlayers,
    allRanked,
    posGroups,
    posBudget,
    flexBudget,
    nominationTargets,
    myNeeds,
    myRosterPlayers,
    myRosterCount,
    mySpent,
    myRemaining,
    maxBid,
    slotsLeft,
    draftedCount,
    availablePlayers,
    budget,
  };
}

// Header/badges helpers shared by table + bidAdvice + view (kept here so no cycle).
export function edgeBadgeAuction(edge) {
  if (edge === 'BUY') return `<span class="badge" style="background:var(--emerald-dim); color:var(--emerald); border:1px solid rgba(16,185,129,0.22); font-size:10px">▲ BUY</span>`;
  if (edge === 'SELL') return `<span class="badge" style="background:var(--crimson-dim); color:var(--crimson); border:1px solid rgba(239,68,68,0.22); font-size:10px">▼ SELL</span>`;
  return `<span class="badge" style="background:rgba(var(--text-rgb,0,0,0),0.05); color:var(--text-faint); border:1px solid var(--border); font-size:10px">—</span>`;
}

export function deltaSeasonBadge(d) {
  if (d == null) return `<span class="mono" style="color:var(--text-faint)">—</span>`;
  const v = Number(d);
  const color = v > 8 ? 'var(--emerald)' : v < -8 ? 'var(--crimson)' : 'var(--text-muted)';
  const arrow = v > 8 ? '↑' : v < -8 ? '↓' : '·';
  const sign = v > 0 ? '+' : '';
  return `<span class="mono" style="color:${color}; font-weight:700; font-size:11px">${arrow} ${sign}${v.toFixed(0)}</span>`;
}