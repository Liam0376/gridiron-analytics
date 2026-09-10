// hub/src/api.js — read-only data layer. Never POSTs, never writes.
// Tries 127.0.0.1:8000 GET endpoints first, falls back to hub read-only proxy (8002) which reads fantasy.db with mode=ro.
// No import from src/ffanalytics — API boundary is HTTP / JSON only.
import { getLeagueId, setLeagueId as storeLeagueId, getDraftTypeOverride, clearLeagueEconMemo } from './lib/league.js';

const API_BASE = `http://${location.hostname}:8000`;
const HUB_API = '/hub-api'; // proxied to 8002 when hub/server.py is running, otherwise 404 → we degrade gracefully

// Active league plumbing: every hub-api AND model call carries ?league_id=
// when one is stored (setup screen / switcher). Empty string = default
// league (env-configured, legacy behavior) — nothing breaks for single setup.
export function getActiveLeagueId() {
  return getLeagueId();
}

export function setActiveLeague(id) {
  storeLeagueId(id);
  invalidateApiCache(); // cached payloads are per-league; never mix across switch
  // why (graphify-audit finding): league.js's own 60s auction-economics
  // memo (_econMemo — budget/roster shape/replacement counts) is a SEPARATE
  // cache from invalidateApiCache() above. Without this, switching leagues
  // could show the previous league's auction $/VOR values for up to 60s.
  clearLeagueEconMemo();
}

function leagueQuery(explicitId, joiner = '?') {
  const id = explicitId !== undefined ? explicitId : getLeagueId();
  return id ? `${joiner}league_id=${encodeURIComponent(id)}` : '';
}

// why central: ~15 fetch sites must all scope to the active league; missing
// the param silently serves the DEFAULT league's numbers (wrong-league bug).
function hubPath(path, explicitId) {
  const [base, query] = path.split('?');
  const joiner = query ? '&' : '?';
  return `${HUB_API}${base}${query ? `?${query}` : ''}${leagueQuery(explicitId, joiner)}`;
}

function modelUrl(path, explicitId) {
  const [base, query] = path.split('?');
  const joiner = query ? '&' : '?';
  return `${API_BASE}${base}${query ? `?${query}` : ''}${leagueQuery(explicitId, joiner)}`;
}

// 60s TTL cache so repeatedly navigating between tabs (auction ↔ projections)
// doesn't re-fetch the same heavy projections / comparison / roster payloads.
const TTL_MS = 60_000;
const _ttlCache = new Map(); // key -> { at: number, value: Promise }

function cacheKey(fnName, argsObj) {
  const lid = getLeagueId() || '';
  return `${lid}::${fnName}::${JSON.stringify(argsObj ?? {})}`;
}

async function withCache(fnName, argsObj, fetcher) {
  const key = cacheKey(fnName, argsObj);
  const now = Date.now();
  const hit = _ttlCache.get(key);
  if (hit && now - hit.at < TTL_MS) return hit.value;
  const fresh = (async () => {
    try { return await fetcher(); } finally {
      // Single-flight: keep the cached entry alive for the full TTL window.
      _ttlCache.set(key, { at: Date.now(), value: fresh });
    }
  })();
  _ttlCache.set(key, { at: now, value: fresh });
  return fresh;
}

// Manual invalidation (e.g. after a manual refresh). Exposed for tests/debugging.
export function invalidateApiCache(prefix) {
  if (!prefix) { _ttlCache.clear(); return; }
  for (const k of _ttlCache.keys()) {
    if (k.startsWith(`${prefix}::`)) _ttlCache.delete(k);
  }
}

async function getJSON(url, opts = {}) {
  const res = await fetch(url, { ...opts, headers: { Accept: 'application/json', ...(opts.headers || {}) } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  return res.json();
}

async function tryHub(path, opts = {}) {
  try {
    const lid = opts.leagueId !== undefined ? opts.leagueId : undefined;
    return await getJSON(hubPath(path, lid));
  } catch (_) {
    return null;
  }
}

// Draft info for ANY league id (setup screen validates before saving, so it
// takes an explicit id — tryHub would use the stored one). Short TTL keyed
// by id; failures return null (caller shows Sleeper-unreachable copy).
export async function fetchDraftInfo(explicitId) {
  return withCache('fetchDraftInfo', { leagueId: explicitId || '' }, async () => {
    const q = explicitId ? `?league_id=${encodeURIComponent(explicitId)}` : '';
    try {
      return await getJSON(`${HUB_API}/draft${q}`);
    } catch (_) {
      return null;
    }
  });
}

// Effective draft type: manual override wins, else live-fetched, else
// 'unknown' (offline/unfetched) — unknown NEVER gates (fail-open preserves
// current behavior when Sleeper is unreachable).
export async function effectiveDraftType() {
  const override = getDraftTypeOverride();
  if (override === 'snake' || override === 'auction') return override;
  try {
    const info = await fetchDraftInfo();
    const t = (info && info.draft_type) || 'unknown';
    return t === 'snake' || t === 'auction' ? t : 'unknown';
  } catch (_) {
    return 'unknown';
  }
}

export async function fetchHealth() {
  try { return await getJSON(`${API_BASE}/health`); } catch (e) {
    try {
      const res = await fetch('/health');
      if (res.ok) return { status: 'ok', source: 'proxy' };
    } catch (_) {}
    return { status: 'down', error: String(e) };
  }
}

export async function fetchMeta() {
  // meta aggregates what hub/server.py can read from DB directly (league, counts, last refresh)
  const hub = await tryHub('/meta');
  if (hub) return hub;
  // degrade: at least return health + hint
  return { season: null, week: null, lastUpdated: null, counts: {}, stale: true, note: 'hub/server.py not running — start it for DB fallback' };
}

// Trigger sync/refresh for a specific league directly from the UI (no terminal needed).
export async function triggerRefresh(explicitId) {
  const lid = explicitId || getLeagueId();
  const res = await fetch(`${API_BASE}/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(lid ? { league_id: String(lid) } : {}),
  });
  if (!res.ok && res.status !== 202) {
    const text = await res.text().catch(() => '');
    throw new Error(`Refresh failed (${res.status}): ${text || res.statusText}`);
  }
  invalidateApiCache();
  return { ok: true, status: res.status };
}

// League-scoped readiness: 200 when this league has rosters + players.
export async function fetchReady() {
  try {
    return await getJSON(hubPath('/ready'));
  } catch (_) {
    return null;
  }
}

export async function fetchProjections(args = {}) {
  return withCache('fetchProjections', args, async () => {
    const { week, limit = 800 } = args;
    const qs = new URLSearchParams();
    if (week != null && week !== '') qs.set('week', String(week));
    if (limit != null) qs.set('limit', String(limit));
    const suffix = qs.toString() ? `?${qs}` : '';
    // Primary: reuse recommendations if cache is warm (they already contain projected_points)
    // For interval + weather we need richer data — use hub proxy's computed projections
    const hub = await tryHub(`/projections${suffix}`);
    if (hub && Array.isArray(hub.players) && hub.players.length) return hub;

    // Fallback: try start-sit (may 503 if cache cold)
    try {
      const data = await getJSON(modelUrl('/recommendations/start-sit'));
      // Map to expected shape
      return {
        players: (data.recommendations || []).map(r => ({
          player_id: r.player_id,
          player_name: r.player_name,
          position: r.position,
          projected_points: r.projected_points,
          interval: null,
          width: null,
          team: r.team || '',
          opponent_team: r.opponent_team || '',
          injury_status: r.injury_status || null,
          trending: false,
          wind_mph: null,
          weather_delta: 0,
          tier: null,
        })),
        meta: { source: 'api:start-sit', count: data.count, timestamp: data.timestamp },
      };
    } catch (_) {
      return { players: [], meta: { source: 'none', count: 0, timestamp: null, cold: true } };
    }
  });
}

export async function fetchMatchups({ week } = {}) {
  return withCache('fetchMatchups', { week: week ?? '' }, async () => {
    const hub = await tryHub(`/matchups?week=${week ?? ''}`);
    if (hub) return hub;
    return { leagueMatchups: [], nflSlate: [], week: week ?? null };
  });
}

export async function fetchRoster(args = {}) {
  return withCache('fetchRoster', args, async () => {
    const { roster_id } = args;
    // Hub proxy is the only source that can join rosters + player_stats read-only
    const hub = await tryHub(`/roster${roster_id ? `?roster_id=${encodeURIComponent(roster_id)}` : ''}`);
    if (hub) return hub;
    return { starters: [], bench: [], reserve: [], myRoster: [], teamMeta: {}, leagueRosters: [] };
  });
}

export async function fetchRostersFull() {
  return withCache('fetchRostersFull', {}, async () => {
    // Single bulk fetch: all 12 enriched rosters in ONE server pass (fixes N+1).
    const hub = await tryHub('/rosters-full');
    if (hub && (hub.rosters || hub.teams)) return hub;
    return null;
  });
}

export async function fetchWaiver(args = {}) {
  return withCache('fetchWaiver', args, async () => {
    try {
      const data = await getJSON(modelUrl('/recommendations/waiver'));
      return { recommendations: data.recommendations || [], meta: { timestamp: data.timestamp } };
    } catch (_) {
      const hub = await tryHub('/waiver');
      if (hub) return hub;
      return { recommendations: [], meta: { cold: true } };
    }
  });
}

export async function fetchTrade(teamA, teamB) {
  if (!teamA || !teamB) return null;
  try {
    const data = await getJSON(modelUrl(`/recommendations/trade?team_a_id=${encodeURIComponent(teamA)}&team_b_id=${encodeURIComponent(teamB)}`));
    return data.trade_evaluation || data;
  } catch (_) {
    const hub = await tryHub(`/trade?team_a_id=${encodeURIComponent(teamA)}&team_b_id=${encodeURIComponent(teamB)}`);
    return hub;
  }
}

export async function fetchNews(args = {}) {
  return withCache('fetchNews', args, async () => {
    try { return await getJSON(modelUrl('/news')); } catch (_) { return await tryHub('/news') || { trending_adds: [], detailed_injuries: [] }; }
  });
}

export async function fetchRefreshLog() {
  return await tryHub('/refresh-log') || { entries: [] };
}

// Game predictions (spec 2026-09-10): market-consensus win%/predicted score
// per scheduled game. Same model-direct/no-write pattern as props edges.
export async function fetchGamePredictions(args = {}) {
  return withCache('fetchGamePredictions', args, async () => {
    const { week, season } = args;
    const qs = new URLSearchParams();
    if (week != null && week !== '') qs.set('week', String(week));
    if (season != null && season !== '') qs.set('season', String(season));
    const suffix = qs.toString() ? `?${qs}` : '';
    try {
      const data = await getJSON(modelUrl(`/games/predictions${suffix}`));
      return { games: data.games || [], meta: { timestamp: data.timestamp, week: data.week, season: data.season } };
    } catch (_) {
      return { games: [], meta: { cold: true } };
    }
  });
}

// Per-game player props board (spec follow-up, 2026-09-10): every player on
// the given teams' model fair lines, no stored book line required — browses
// a game's props by clicking it, instead of only showing manually-entered
// lines. Same model-direct/no-write pattern as the other props reads.
export async function fetchPropsBoard(args = {}) {
  return withCache('fetchPropsBoard', args, async () => {
    const { teams, week, season } = args;
    if (!teams) return { players: [], meta: {} };
    const qs = new URLSearchParams({ teams });
    if (week != null && week !== '') qs.set('week', String(week));
    if (season != null && season !== '') qs.set('season', String(season));
    try {
      const data = await getJSON(modelUrl(`/props/board?${qs}`));
      return { players: data.players || [], meta: { timestamp: data.timestamp, week: data.week, season: data.season } };
    } catch (_) {
      return { players: [], meta: { cold: true } };
    }
  });
}

export async function fetchTeamRatings() {
  return await tryHub('/team-ratings') || { ratings: [] };
}

export async function fetchComparison(args = {}) {
  return withCache('fetchComparison', args, async () => {
    const { edge, limit } = args;
    const qs = new URLSearchParams();
    if (edge) qs.set('edge', edge);
    if (limit) qs.set('limit', String(limit));
    const hub = await tryHub(`/comparison${qs.toString() ? `?${qs}` : ''}`);
    if (hub && Array.isArray(hub.players)) return hub;
    return { players: [], count: 0, fetched_at: null, meta: { source: 'none' } };
  });
}

// Utility: staleness helper
export function computeStaleness(lastUpdated) {
  if (!lastUpdated) return { level: 'cold', label: 'cold — no data' };
  const ageMs = Date.now() - new Date(lastUpdated).getTime();
  const hours = ageMs / 3600000;
  if (hours < 24) return { level: 'fresh', label: `fresh · ${new Date(lastUpdated).toLocaleString()}` };
  if (hours < 72) return { level: 'stale', label: `stale · ${Math.round(hours)}h ago` };
  return { level: 'cold', label: `cold · ${Math.round(hours/24)}d ago` };
}
