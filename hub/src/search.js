// hub/src/search.js — zero-token client-side search. No embeddings, no LLM.
// Supports text substring + structured chips: pos:WR team:BUF opp:MIA proj>12 wind>15 healthy:true trending:true interval<3

const TEAM_NAMES = {
  BUF: 'Buffalo Bills',
  MIA: 'Miami Dolphins',
  NE: 'New England Patriots',
  NYJ: 'New York Jets',
  BAL: 'Baltimore Ravens',
  CIN: 'Cincinnati Bengals',
  CLE: 'Cleveland Browns',
  PIT: 'Pittsburgh Steelers',
  HOU: 'Houston Texans',
  IND: 'Indianapolis Colts',
  JAX: 'Jacksonville Jaguars',
  TEN: 'Tennessee Titans',
  DEN: 'Denver Broncos',
  KC: 'Kansas City Chiefs',
  LV: 'Las Vegas Raiders',
  LAC: 'Los Angeles Chargers',
  DAL: 'Dallas Cowboys',
  NYG: 'New York Giants',
  PHI: 'Philadelphia Eagles',
  WAS: 'Washington Commanders',
  CHI: 'Chicago Bears',
  DET: 'Detroit Lions',
  GB: 'Green Bay Packers',
  MIN: 'Minnesota Vikings',
  ATL: 'Atlanta Falcons',
  CAR: 'Carolina Panthers',
  NO: 'New Orleans Saints',
  TB: 'Tampa Bay Buccaneers',
  ARI: 'Arizona Cardinals',
  LAR: 'Los Angeles Rams',
  SEA: 'Seattle Seahawks',
  SF: 'San Francisco 49ers',
};

export function parseQuery(raw) {
  const q = (raw || '').trim();
  if (!q) return { text: '', chips: {} };
  const tokens = q.split(/\s+/);
  const chips = {};
  const textParts = [];
  for (const t of tokens) {
    const m = t.match(/^(\w+)([:><=]+)(.+)$/);
    if (m) {
      const [, k, op, v] = m;
      const key = k.toLowerCase();
      if (['pos','position','team','opp','opponent','proj','points','wind','interval','width','tier'].includes(key)) {
        chips[key] = { op, value: v };
        continue;
      }
      if (['healthy','trending'].includes(key)) {
        chips[key] = { op: ':', value: v.toLowerCase() };
        continue;
      }
    }
    textParts.push(t);
  }
  return { text: textParts.join(' ').toLowerCase(), chips };
}

export function matchesPlayer(p, parsed) {
  const { text, chips } = parsed;
  if (text) {
    const pTeamAbbr = (p.team || '').toLowerCase();
    const pTeamFullName = (TEAM_NAMES[p.team] || '').toLowerCase();
    const pName = `${p.player_name || ''} ${p.full_name || ''} ${p.short_name || ''} ${p.name || ''}`.toLowerCase();
    const pOwner = `${p.owner_name || ''} ${p.team_name || ''} ${p.display_name || ''}`.toLowerCase();
    const pPos = (p.position || p.position_group || '').toLowerCase();

    // Plain text search matches Player Name, Player Team, Team Full Name, Owner/Fantasy Team, Position ID
    const hay = `${pName} ${pTeamAbbr} ${pTeamFullName} ${pOwner} ${pPos} ${p.player_id || ''}`;
    if (!hay.includes(text)) return false;
  }
  for (const [k, { op, value }] of Object.entries(chips)) {
    if (k === 'pos' || k === 'position') {
      if ((p.position || p.position_group || '').toLowerCase() !== value.toLowerCase()) return false;
    } else if (k === 'team') {
      const pTeamAbbr = (p.team || '').toLowerCase();
      const pTeamFullName = (TEAM_NAMES[p.team] || '').toLowerCase();
      const want = value.toLowerCase();
      if (pTeamAbbr !== want && !pTeamFullName.includes(want)) return false;
    } else if (k === 'opp' || k === 'opponent') {
      if ((p.opponent_team || '').toLowerCase() !== value.toLowerCase()) return false;
    } else if (k === 'proj' || k === 'points') {
      if (!compareNum(p.projected_points ?? p.point_estimate ?? 0, op, Number(value))) return false;
    } else if (k === 'wind') {
      if (!compareNum(p.wind_mph ?? 0, op, Number(value))) return false;
    } else if (k === 'interval' || k === 'width') {
      const w = p.width ?? p.projection_width ?? p.interval_width ?? 5;
      if (!compareNum(w, op, Number(value))) return false;
    } else if (k === 'tier') {
      if (String(p.tier ?? '') !== String(value)) return false;
    } else if (k === 'healthy') {
      const wantHealthy = value === 'true' || value === '1';
      const isHealthy = !p.injury_status || p.injury_status === 'Healthy' || p.injury_status === null;
      if (wantHealthy !== isHealthy) return false;
    } else if (k === 'trending') {
      const want = value === 'true' || value === '1';
      if (Boolean(p.trending) !== want) return false;
    }
  }
  return true;
}

function compareNum(a, op, b) {
  if (Number.isNaN(a) || Number.isNaN(b)) return false;
  if (op === '>' ) return a > b;
  if (op === '>=' ) return a >= b;
  if (op === '<' ) return a < b;
  if (op === '<=' ) return a <= b;
  if (op === ':' || op === '=' || op === '==') return a === b;
  return false;
}

export function filterPlayers(players, rawQuery) {
  const parsed = parseQuery(rawQuery);
  if (!parsed.text && Object.keys(parsed.chips).length === 0) return players;
  return players.filter(p => matchesPlayer(p, parsed));
}
