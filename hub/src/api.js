// hub/src/api.js — read-only data layer. Never POSTs, never writes.
// Tries 127.0.0.1:8000 GET endpoints first, falls back to hub read-only proxy (8002) which reads fantasy.db with mode=ro.
// No import from src/ffanalytics — API boundary is HTTP / JSON only.

const API_BASE = `http://${location.hostname}:8000`;
const HUB_API = '/hub-api'; // proxied to 8002 when hub/server.py is running, otherwise 404 → we degrade gracefully

async function getJSON(url, opts = {}) {
  const res = await fetch(url, { ...opts, headers: { Accept: 'application/json', ...(opts.headers || {}) } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  return res.json();
}

async function tryHub(path) {
  try {
    return await getJSON(`${HUB_API}${path}`);
  } catch (_) {
    return null;
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

export async function fetchProjections({ week } = {}) {
  // Primary: leverage existing recommendations if cache is warm (they already contain projected_points)
  // For interval + weather we need richer data — use hub proxy's computed projections
  const hub = await tryHub(`/projections?week=${week ?? ''}`);
  if (hub && Array.isArray(hub.players) && hub.players.length) return hub;

  // Fallback: try start-sit (may 503 if cache cold)
  try {
    const data = await getJSON(`${API_BASE}/recommendations/start-sit`);
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
}

export async function fetchMatchups({ week } = {}) {
  const hub = await tryHub(`/matchups?week=${week ?? ''}`);
  if (hub) return hub;
  return { leagueMatchups: [], nflSlate: [], week: week ?? null };
}

export async function fetchRoster() {
  // Hub proxy is the only source that can join rosters + player_stats read-only
  const hub = await tryHub('/roster');
  if (hub) return hub;
  return { roster: [], bench: [], leagueRosters: [] };
}

export async function fetchWaiver() {
  try {
    const data = await getJSON(`${API_BASE}/recommendations/waiver`);
    return { recommendations: data.recommendations || [], meta: { timestamp: data.timestamp } };
  } catch (_) {
    const hub = await tryHub('/waiver');
    if (hub) return hub;
    return { recommendations: [], meta: { cold: true } };
  }
}

export async function fetchTrade(teamA, teamB) {
  if (!teamA || !teamB) return null;
  try {
    const data = await getJSON(`${API_BASE}/recommendations/trade?team_a_id=${encodeURIComponent(teamA)}&team_b_id=${encodeURIComponent(teamB)}`);
    return data.trade_evaluation || data;
  } catch (_) {
    const hub = await tryHub(`/trade?team_a_id=${encodeURIComponent(teamA)}&team_b_id=${encodeURIComponent(teamB)}`);
    return hub;
  }
}

export async function fetchNews() {
  try { return await getJSON(`${API_BASE}/news`); } catch (_) { return await tryHub('/news') || { trending_adds: [], detailed_injuries: [] }; }
}

export async function fetchRefreshLog() {
  return await tryHub('/refresh-log') || { entries: [] };
}

export async function fetchTeamRatings() {
  return await tryHub('/team-ratings') || { ratings: [] };
}

export async function fetchComparison({ edge, limit } = {}) {
  const qs = new URLSearchParams();
  if (edge) qs.set('edge', edge);
  if (limit) qs.set('limit', String(limit));
  const hub = await tryHub(`/comparison${qs.toString() ? `?${qs}` : ''}`);
  if (hub && Array.isArray(hub.players)) return hub;
  return { players: [], count: 0, fetched_at: null, meta: { source: 'none' } };
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
