// hub/src/lib/league.js — active-league state (pure storage, no network).
// The UI is multi-league: every hub-api/model call carries ?league_id=
// (see api.js withLeague). Everything else (settings, rosters, scoring,
// draft type) is fetched from Sleeper per league — never typed twice.
const LEAGUE_KEY = 'ffba-league-id';
const DRAFTTYPE_KEY = 'ffba-draft-type'; // 'auto' | 'snake' | 'auction'
const TEAM_KEY_PREFIX = 'ffba-selected-team-id:';

function storage() {
  try {
    return localStorage;
  } catch (_) {
    return null; // private mode
  }
}

export function isValidLeagueId(id) {
  return typeof id === 'string' && /^\d+$/.test(id.trim());
}

// Accept a raw id or a pasted Sleeper URL/app link; returns digits or ''.
export function parseLeagueInput(raw) {
  const s = String(raw || '').trim();
  if (/^\d+$/.test(s)) return s;
  const m = s.match(/leagues?\/(\d{6,})/i) || s.match(/(\d{15,})/);
  return m ? m[1] : '';
}

export function getLeagueId() {
  const store = storage();
  try {
    return (store && store.getItem(LEAGUE_KEY)) || '';
  } catch (_) {
    return '';
  }
}

export function setLeagueId(id) {
  const store = storage();
  if (!store) return;
  try {
    if (id) store.setItem(LEAGUE_KEY, String(id));
    else store.removeItem(LEAGUE_KEY);
  } catch (_) {}
}

export function getDraftTypeOverride() {
  const store = storage();
  try {
    const v = store && store.getItem(DRAFTTYPE_KEY);
    return v === 'snake' || v === 'auction' ? v : 'auto';
  } catch (_) {
    return 'auto';
  }
}

export function setDraftTypeOverride(v) {
  const store = storage();
  if (!store) return;
  try {
    if (v === 'snake' || v === 'auction') store.setItem(DRAFTTYPE_KEY, v);
    else store.removeItem(DRAFTTYPE_KEY);
  } catch (_) {}
}

// Team selection is namespaced per league so switching leagues never
// restores another league's roster pick.
export function teamStorageKey(leagueId) {
  return `${TEAM_KEY_PREFIX}${leagueId || 'default'}`;
}

// Known leagues: client-side list of leagues viewed on this machine, backing
// the topbar switcher. The stateless backend has no configured-leagues
// registry (the stateful father's SQLite scan has no equivalent here), so
// the list is maintained locally: most-recent-first, capped, deduplicated.
const KNOWN_LEAGUES_KEY = 'ffba-known-leagues';
const MAX_KNOWN_LEAGUES = 20;

export function getKnownLeagues() {
  const store = storage();
  try {
    const raw = store && store.getItem(KNOWN_LEAGUES_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter(l => l && l.league_id) : [];
  } catch (_) {
    return [];
  }
}

export function addKnownLeague(leagueId, leagueName, season) {
  if (!leagueId) return;
  const store = storage();
  if (!store) return;
  try {
    const id = String(leagueId);
    const rest = getKnownLeagues().filter(l => String(l.league_id) !== id);
    rest.unshift({ league_id: id, league_name: leagueName || '', season: season || '' });
    store.setItem(KNOWN_LEAGUES_KEY, JSON.stringify(rest.slice(0, MAX_KNOWN_LEAGUES)));
  } catch (_) {}
}

// League economics: auction $/VOR math scaled to any league's size, roster
// shape, and draft budget. Mirrors ffanalytics.config.league_economics —
// same methodology, same 12x$200 reproduction (verified in test_config.py).
// meta: /hub-api/meta (totalRosters, roster_positions). draft: /hub-api/draft
// (auction_budget). Missing pieces fall back to reference-league defaults so
// offline/cold states render exactly as before.
export const DEFAULT_ECON = {
  teams: 12,
  budget: 200,
  startersPerTeam: 10,
  benchPerTeam: 4,
  flexSlots: 2,
  rosterPositions: ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'FLEX', 'K', 'DEF', 'BN', 'BN', 'BN', 'BN'],
};

export function leagueEconomics({ totalRosters, rosterPositions, auctionBudget } = {}) {
  const teams = Math.max(1, Number(totalRosters) || 12);
  const budget = Number(auctionBudget) > 0 ? Number(auctionBudget) : 200;
  const positions = Array.isArray(rosterPositions) && rosterPositions.length
    ? rosterPositions.map(p => String(p).toUpperCase())
    : [...DEFAULT_ECON.rosterPositions];
  const bench = positions.filter(p => p === 'BN').length || 4;
  const flex = positions.filter(p => p === 'FLEX').length;
  const starters = Math.max(1, positions.length - bench);
  const countBase = (pos, fallback) => {
    const n = positions.filter(p => p === pos).length;
    return n || fallback;
  };
  const rbBase = countBase('RB', 2);
  const wrBase = countBase('WR', 2);
  // why flex split RB F/6, WR F/3, TE 0: TEs are ~never flexed over RB/WR —
  // reproduces the tuned 28/32 at 12-team 2-FLEX. Starting values.
  const replCounts = {
    QB: teams * countBase('QB', 1),
    RB: Math.round(teams * (rbBase + flex / 6)),
    WR: Math.round(teams * (wrBase + flex / 3)),
    TE: teams * countBase('TE', 1),
    K: teams * countBase('K', 1),
    DEF: teams * countBase('DEF', 1),
  };
  const posStarterSlots = {
    QB: countBase('QB', 1), RB: rbBase, WR: wrBase,
    TE: countBase('TE', 1), K: countBase('K', 1), DEF: countBase('DEF', 1),
  };
  return {
    teams, budget, startersPerTeam: starters, benchPerTeam: bench, flexSlots: flex,
    rosterPositions: positions,
    starterPool: teams * budget - teams * bench * 1,
    starterSlotsTotal: teams * starters,
    benchSlotsTotal: teams * bench,
    replCounts, posStarterSlots,
  };
}

// Cached combo fetch: meta + draft → econ. Views call this (1 line) instead
// of prop-drilling league shape. Memoized 60s like the api TTLs.
let _econMemo = null;
export async function getLeagueEcon(fetchMetaFn, fetchDraftFn) {
  const now = Date.now();
  if (_econMemo && now - _econMemo.at < 60_000) return _econMemo.econ;
  let meta = null;
  let draft = null;
  try { meta = await fetchMetaFn(); } catch (_) {}
  try { draft = await fetchDraftFn(); } catch (_) {}
  const econ = leagueEconomics({
    totalRosters: meta && meta.totalRosters,
    rosterPositions: meta && meta.roster_positions,
    auctionBudget: draft && draft.auction_budget,
  });
  econ.season = (meta && meta.season) || '';
  econ.leagueName = (meta && (meta.leagueName || meta.name)) || '';
  _econMemo = { at: now, econ };
  return econ;
}

export function clearLeagueEconMemo() {
  _econMemo = null;
}

// "10-Team · 1 FLEX · 2026" style tagline from live meta/econ (replaces
// hardcoded "12-Team ..." strings). Accepts meta or econ shapes.
export function leagueTagline(src) {
  const teams = (src && (src.totalRosters || src.teams)) || 12;
  const positions = (src && (src.roster_positions || src.rosterPositions)) || [];
  const flex = positions.filter(p => p === 'FLEX').length;
  const flexPart = flex > 0 ? ` · ${flex} FLEX` : '';
  const season = (src && src.season) || '';
  return `${teams}-Team${flexPart}${season ? ` · ${season}` : ''}`;
}
