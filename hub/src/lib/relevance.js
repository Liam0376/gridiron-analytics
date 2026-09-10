// hub/src/lib/relevance.js — demote off-depth-chart players, never remove.
//
// Sort contract: relevant tier first, then healthy-QB-backup demotion,
// then the caller's existing score key (projected_points / totalFair)
// descending. Stable sort, so equal keys keep their previous order. When
// the chart has no entry for a player, depthRank is -1 → irrelevant tier,
// still listed (demote, don't remove — user decision 2026-09-10).
// Non-chart positions (K/DEF/IDP) stay in the relevant tier untouched.
// Next-man-up: a backup whose every chart-ahead teammate is confirmed out
// (Out/IR/…) ranks as relevant — e.g. Lock behind an Out Darnold — while
// a healthy backup (Jones behind a healthy Purdy) sinks to the end.
import { depthRank, isDepthRelevant, DEPTH_TOP_N } from './depthChart.js';

export { DEPTH_TOP_N };

// why mirror (not import): hub must never import ffanalytics (isolation
// gate) — the set below copies src/ffanalytics/api.py:_UNAVAILABLE_STATUSES
// verbatim. Questionable/Doubtful stay available there (flagged, not
// hidden), so they never trigger next-man-up elevation here either.
const UNAVAILABLE = new Set(['out', 'ir', 'injured reserve', 'pup', 'nfi', 'suspended', 'na']);

const defaultAccessors = {
  teamOf: (p) => p.team,
  posOf: (p) => p.position || p.position_group,
  nameOf: (p) => p.player_name ?? p.name,
  scoreOf: (p) => Number(p.projected_points ?? p.totalFair ?? 0) || 0,
  statusOf: (p) => p.injury_status ?? p.injuryStatus ?? null,
  availOf: (p) => p.available,
};

// Tri-state availability: true = out, false = confirmed playing, null =
// unknown. Elevation needs a CONFIRMED out ahead (user decision 2026-09-10):
// an ahead teammate of unknown status counts as playing (conservative).
function outState(p, a) {
  if (a.availOf(p) === false) return true;
  const s = a.statusOf(p);
  if (s == null || s === '') return a.availOf(p) === true ? false : null;
  return UNAVAILABLE.has(String(s).trim().toLowerCase());
}

function chartKey(p, a) {
  return `${String(a.teamOf(p) || '').toUpperCase()}|${String(a.posOf(p) || '').toUpperCase()}`;
}

// why next-man-up (user-caught, 2026-09-10): a healthy backup (Mac Jones
// behind a healthy Purdy) must sink to the end, but a backup starting for
// an injured QB1 (Lock behind an Out Darnold) is a starter this week and
// must rank like one. Elevation needs every chart-ahead teammate in the
// current list confirmed out and the player himself not out.
// Shared across every projection-ordered surface (projections default,
// props cards, auction default, tier members): QB is single-starter, so a
// healthy QB2+ with a starter-level line would otherwise top
// cross-position boards (Mac Jones 3rd on SF@LA). RB/WR/TE committees
// genuinely play their depth, so only QB gets this within-tier demotion.
export function buildAheadMap(items, accessors = {}) {
  return buildAheadMapFor(items, { ...defaultAccessors, ...accessors });
}

function buildAheadMapFor(items, a) {
  const map = new Map(); // key -> [{ rank, out }]
  for (const p of items) {
    const rank = depthRank(a.teamOf(p), a.posOf(p), a.nameOf(p));
    if (rank < 0) continue;
    const k = chartKey(p, a);
    if (!map.has(k)) map.set(k, []);
    map.get(k).push({ rank, out: outState(p, a) });
  }
  return map;
}

function isElevated(p, rank, aheadMap, a) {
  if (rank < 0 || outState(p, a) === true) return false;
  const room = aheadMap.get(chartKey(p, a)) || [];
  const ahead = room.filter((e) => e.rank < rank);
  if (!ahead.length) return false;
  if (ahead.every((e) => e.out === true)) return true;
  // why QB-room carve-out (user decision 2026-09-10): QB is single-starter
  // — when QB1 is confirmed out, the whole healthy backup room is live and
  // preseason order between backups is unreliable (Lock played ahead of
  // chart-QB2 Milroe). Chain rule still governs RB/WR/TE committees.
  if (String(a.posOf(p) || '').toUpperCase() !== 'QB') return false;
  const qb1 = room.find((e) => e.rank === 0);
  return !!qb1 && qb1.out === true;
}

export function relevanceTier(p, accessors = {}, aheadMap = null) {
  const a = { ...defaultAccessors, ...accessors };
  const pos = String(a.posOf(p) || '').toUpperCase();
  if (!pos || pos === 'UNK') return 1;
  if (isDepthRelevant(a.teamOf(p), pos, a.nameOf(p))) return 0;
  if (aheadMap && isElevated(p, depthRank(a.teamOf(p), pos, a.nameOf(p)), aheadMap, a)) return 0;
  return 1;
}

export function backupDemote(p, accessors = {}, aheadMap = null) {
  const a = { ...defaultAccessors, ...accessors };
  if (String(a.posOf(p) || '').toUpperCase() !== 'QB') return 0;
  const rank = depthRank(a.teamOf(p), a.posOf(p), a.nameOf(p));
  if (rank < 1) return 0;
  if (aheadMap && isElevated(p, rank, aheadMap, a)) return 0;
  return 1;
}

export function sortByRelevance(items, accessors = {}) {
  const a = { ...defaultAccessors, ...accessors };
  const aheadMap = buildAheadMap(items, a);
  return sortRelevant([...items], a, aheadMap);
}

function sortRelevant(items, a, aheadMap) {
  return items.sort((x, y) => {
    const tier = relevanceTier(x, a, aheadMap) - relevanceTier(y, a, aheadMap);
    if (tier !== 0) return tier;
    const qb = backupDemote(x, a, aheadMap) - backupDemote(y, a, aheadMap);
    if (qb !== 0) return qb;
    return a.scoreOf(y) - a.scoreOf(x);
  });
}

// why actual-first for finals (user-caught, 2026-09-10): a final game's
// modal sorted by preseason fair buries who actually played — Darnold's
// 233.8-yard projection outranked Lock's card despite 13 vs 187 actual.
// Finals sort by what happened (actual volume desc, nulls last); upcoming
// games keep the relevance order above. Units are mixed across markets —
// this key only ever orders cards within one game, never displayed.
export function sortGameCards(items, accessors = {}, final = false) {
  const a = {
    fairOf: (p) => Number(p.totalFair ?? 0) || 0,
    actualOf: (p) => (p.totalActual == null ? null : Number(p.totalActual) || 0),
    ...accessors,
  };
  if (!final) return sortByRelevance(items, accessors);
  return [...items].sort((x, y) => {
    const ax = a.actualOf(x), ay = a.actualOf(y);
    if (ax == null && ay == null) return a.fairOf(y) - a.fairOf(x);
    if (ax == null) return 1;
    if (ay == null) return -1;
    return ay - ax;
  });
}

export function annotateRelevance(p, accessors = {}) {
  const a = { ...defaultAccessors, ...accessors };
  return {
    tier: relevanceTier(p, a),
    rank: depthRank(a.teamOf(p), a.posOf(p), a.nameOf(p)),
  };
}
