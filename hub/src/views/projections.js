import { fetchProjections, fetchComparison, fetchRoster, fetchRosProjections } from '../api.js';
import { filterPlayers } from '../search.js';
import { posBadge, injuryBadge, windBadge, confBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { playerCard } from '../components/playerCard.js';
import { getTeamColor } from '../components/teamColors.js';
import { openPlayerModal } from '../components/playerModal.js';
import { escapeHtml } from '../lib/escape.js';
import { relevanceTier, backupDemote, buildAheadMap } from '../lib/relevance.js';

let allPlayers = [];
let compById = new Map();
let comparisonMeta = null;
let currentQuery = '';
let currentPage = 1;
let compareEnabled = true;
let edgeFilter = 'ALL'; // ALL | BUY | SELL
let rosterPlayerIds = new Set(); // Audit 22.0: "My Roster" filter
let rosMode = false; // RoS toggle: weekly ↔ rest-of-season
let selectedWeek = null; // null = current week (server default); weekly mode only
const PAGE_SIZE = 50;

// Interval fallback mirrors src/ffanalytics/projection.py v2
// (QB/K recalibration 2026-09-15). Change together. Widths frozen.
// Unknown players get the same scaled band as calibrated peers, never a
// narrower fixed default that understates their uncertainty.
const POS_W = { QB: 1.55, RB: 1.07, WR: 1.12, TE: 0.88, K: 0.85, DEF: 0.75 };
function scaledFallbackWidth(pos, pts) {
  const pf = POS_W[(pos || 'UNK').toUpperCase()] ?? 1.0;
  const qf = pts > 12 ? Math.min(1.60, 1.0 + (pts - 12) * 0.022) : 1.0;
  return Math.max(3.0, Math.min(14.0, 5.0 * pf * qf));
}

function edgeBadge(edge) {
  if (edge === 'BUY') return `<span class="badge" style="background:var(--emerald-dim); color:var(--emerald); border:1px solid rgba(16,185,129,0.22)">▲ BUY</span>`;
  if (edge === 'SELL') return `<span class="badge" style="background:var(--crimson-dim); color:var(--crimson); border:1px solid rgba(239,68,68,0.22)">▼ SELL</span>`;
  return `<span class="badge" style="background:rgba(var(--text-rgb,0,0,0),0.05); color:var(--text-faint); border:1px solid var(--border)">—</span>`;
}
function deltaPtsBadge(d) {
  if (d == null) return `<span class="mono" style="color:var(--text-faint)">—</span>`;
  const v = Number(d);
  const color = v > 0.5 ? 'var(--emerald)' : v < -0.5 ? 'var(--crimson)' : 'var(--text-muted)';
  const arrow = v > 0.5 ? '↑' : v < -0.5 ? '↓' : '·';
  const sign = v > 0 ? '+' : '';
  return `<span class="mono" style="color:${color}; font-weight:700">${arrow} ${sign}${v.toFixed(1)}</span>`;
}
function deltaRankBadge(d) {
  if (d == null) return `<span class="mono" style="color:var(--text-faint)">—</span>`;
  const v = Number(d);
  const color = v >= 12 ? 'var(--emerald)' : v <= -12 ? 'var(--crimson)' : 'var(--text-muted)';
  const arrow = v > 0 ? '↑' : v < 0 ? '↓' : '·';
  const sign = v > 0 ? '+' : '';
  return `<span class="mono" style="color:${color}; font-weight:700">${arrow} ${sign}${v}</span>`;
}
function statDeltaBar(model, market, delta) {
  if (market == null) return `<span class="mono" style="color:var(--text-faint); font-size:11px">${model?.toFixed ? model.toFixed(1) : model} <span style="color:var(--text-faint)">· market —</span></span>`;
  const maxAbs = Math.max(Math.abs(model), Math.abs(market), 10);
  const pctM = Math.round((Math.abs(model) / maxAbs) * 100);
  const pctK = Math.round((Math.abs(market) / maxAbs) * 100);
  const dColor = delta > 0 ? 'var(--emerald)' : delta < 0 ? 'var(--crimson)' : 'var(--text-faint)';
  return `<div style="display:flex; align-items:center; gap:6px; min-width:160px"><span class="mono" style="font-size:11px; min-width:44px; text-align:right">${model.toFixed(1)}</span><div style="flex:1; height:4px; background:rgba(var(--text-rgb,0,0,0),0.06); border-radius:999px; position:relative; overflow:hidden"><div style="position:absolute; left:0; top:0; bottom:0; width:${pctM}%; background:var(--amber); opacity:0.9; border-radius:999px"></div><div style="position:absolute; left:0; top:0; bottom:0; width:${pctK}%; background:var(--sky); opacity:0.35; border-radius:999px"></div></div><span class="mono" style="font-size:11px; color:var(--text-muted); min-width:36px">${market.toFixed(1)}</span><span class="mono" style="font-size:11px; color:${dColor}; font-weight:700; min-width:36px; text-align:right">${delta > 0 ? '+' : ''}${delta.toFixed(1)}</span></div>`;
}

export async function renderProjections(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  // Deep links (#projections?week=3) must work, not just picker clicks:
  // the URL is the source of truth on navigation.
  const urlWeek = params.get('week');
  if (urlWeek != null && urlWeek !== '' && Number.isFinite(Number(urlWeek))) {
    selectedWeek = Number(urlWeek);
  }
  currentQuery = params.get('q') || document.getElementById('globalSearch')?.value || '';
  currentPage = 1;
  // Honor ?limit on projections (default 800, max 2000 like server).
  const limitParam = Number(params.get('limit') || 800);
  const projLimit = Number.isFinite(limitParam) ? Math.max(10, Math.min(2000, Math.floor(limitParam))) : 800;

  // Fetch rosters FIRST (they have Sleeper IDs which work with CDN).
  // This mirrors team hub's approach — roster player IDs are Sleeper IDs.
  // why normName: Sleeper strips suffixes ("Michael Penix") while display
  // names keep them ("Michael Penix Jr.") — raw lower() never matches.
  const normName = (n) => String(n || '').toLowerCase().replace(/\b(jr\.?|sr\.?|ii|iii|iv|v)\b/g, '').replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim();
  let sleeperIdByNamePos = new Map();
  rosterPlayerIds = new Set(); // Audit 22.0: reset for "My Roster" filter
  try {
    const rosterData = await fetchRoster({});
    const allRosterPlayers = [].concat(
      rosterData.starters || [],
      rosterData.bench || [],
      rosterData.reserve || []
    ).map(p => ({ player_id: p.player_id, team_name: p.team_name || '' }));
    for (const p of allRosterPlayers) {
      if (p.player_id) {
        rosterPlayerIds.add(String(p.player_id));
        if (p.player_name) {
          const key = `${normName(p.player_name)}|${(p.position || '').toUpperCase()}`;
          sleeperIdByNamePos.set(key, String(p.player_id));
        }
      }
    }
  } catch {}

  const data = rosMode
    ? await fetchRosProjections({ limit: projLimit })
    : await fetchProjections({ week: selectedWeek, limit: projLimit });
  // Map RoS shape to weekly shape so the table renders uniformly. RoS points
  // are a season-scaled sum (see stat_projector.compute_ros_projections) —
  // no per-game interval data comes back, so approximate a wider band by
  // compounding the single-week fallback width over remaining_games
  // (independent-week variance sums, so SD scales with sqrt(n)).
  allPlayers = rosMode
    ? (data.players || []).map(p => {
        const remaining = Math.max(1, Number(p.remaining_games) || 1);
        const wkWidth = scaledFallbackWidth(p.position, Number(p.per_game_neutral) || 0);
        const width = Number((wkWidth * Math.sqrt(remaining)).toFixed(2));
        return {
          ...p,
          projected_points: p.ros_points,
          point_estimate: p.ros_points,
          player_name: p.player_name || p.player_display_name,
          position_group: p.position,
          width,
          projection_lower: Math.max(0, Number((p.ros_points - width).toFixed(2))),
          projection_upper: Number((p.ros_points + width).toFixed(2)),
        };
      })
    : (data.players || []);
  const meta = data.meta || {};
  // Server default (no ?week=) reports the current NFL week — anchors the
  // week-picker's "current" highlight and label even before a user pick.
  if (!rosMode && selectedWeek == null && meta.week != null) selectedWeek = meta.week;

  // Fetch market comparison in parallel (free, $0; graceful degrade if no DB table yet)
  let compRaw = { players: [], count: 0, meta: {}, fetched_at: null };
  try { compRaw = await fetchComparison({ limit: 2000 }); } catch { compRaw = { players: [], count: 0, meta: {}, fetched_at: null }; }
  compById = new Map((compRaw.players || []).map(c => [String(c.player_id), c]));
  comparisonMeta = compRaw;

  // Enrich ALL players with Sleeper IDs from roster lookup (bypasses GSIS→Sleeper gap)
  for (const p of allPlayers) {
    const key = `${normName(p.player_name || '')}|${(p.position || '').toUpperCase()}`;
    if (!p.sleeper_id && sleeperIdByNamePos.has(key)) {
      p.sleeper_id = sleeperIdByNamePos.get(key);
    }
  }

  // Ensure all market players are included so no player is missing
  const seenIds = new Set(allPlayers.map(p => String(p.player_id)));
  for (const c of (compRaw.players || [])) {
    const pid = String(c.player_id || '');
    if (pid && !seenIds.has(pid)) {
      seenIds.add(pid);
      allPlayers.push({
        player_id: pid,
        sleeper_id: c.sleeper_id || (/^\d+$/.test(pid) ? pid : null),
        espn_id: c.espn_id || null,
        player_name: c.player_name || c.full_name || pid,
        position: (c.position || 'UNK').toUpperCase(),
        team: (c.team || '').toUpperCase(),
        projected_points: c.model_points ?? c.projected_points ?? 0,
        point_estimate: c.model_points ?? c.projected_points ?? 0,
        projection_lower: c.projection_lower ?? ((c.model_points ?? 0) - scaledFallbackWidth(c.position, c.model_points ?? 0)),
        projection_upper: c.projection_upper ?? ((c.model_points ?? 0) + scaledFallbackWidth(c.position, c.model_points ?? 0)),
        width: c.width ?? scaledFallbackWidth(c.position, c.model_points ?? 0),
        injury_status: c.injury_status || null,
        market_points: c.market_points,
        delta_points: c.delta_points,
        model_overall_rank: c.model_overall_rank,
        model_pos_rank: c.model_pos_rank,
        fp_ecr: c.fp_ecr,
        fp_ecr_pos: c.fp_ecr_pos,
        fp_adp: c.fp_adp,
        fp_tier: c.fp_tier,
        delta_rank: c.delta_rank,
        delta_pos_rank: c.delta_pos_rank,
        edge: c.edge || 'NEUTRAL',
        edge_score: c.edge_score || 0,
        stat_deltas: c.stat_deltas || [],
      });
    }
  }

  // Enrich allPlayers with comparison fields (model vs market + ECR/ADP)
  const hasComparison = compById.size > 0;
  for (const p of allPlayers) {
    if (p.player_id && /^\d+$/.test(String(p.player_id))) p.sleeper_id = p.player_id;
    const c = compById.get(String(p.player_id));
    if (c) {
      if (c.sleeper_id) p.sleeper_id = c.sleeper_id;
      if (c.espn_id) p.espn_id = c.espn_id;
      p.market_points = c.market_points;
      p.delta_points = c.delta_points;
      p.model_overall_rank = c.model_overall_rank;
      p.model_pos_rank = c.model_pos_rank;
      p.fp_ecr = c.fp_ecr;
      p.fp_ecr_pos = c.fp_ecr_pos;
      p.fp_adp = c.fp_adp;
      p.fp_tier = c.fp_tier;
      p.delta_rank = c.delta_rank;
      p.delta_pos_rank = c.delta_pos_rank;
      p.edge = c.edge;
      p.edge_score = c.edge_score;
      p.stat_deltas = c.stat_deltas;
      p.market_season_stats = c.market_season_stats || null;
      // why forward these (user-caught live bug, 2026-09-10): the backend
      // already computes real VOR-based auction $ (comparison/_model.py)
      // for every player — without this, playerModal's own fallback
      // guessed dollar value from weekly points alone, giving a
      // below-replacement QB15 $55 instead of the real $19.
      p.auction = c.auction;
      p.gridironAuction = c.auction;
      p.marketAuction = c.marketAuction;
      p.vor = c.vor;
    } else {
      p.market_points = null; p.delta_points = null; p.edge = 'NEUTRAL'; p.stat_deltas = [];
    }
    if (!rosMode) {
      // why (live bug 2026-09-15): this weekly model/market blend used to
      // run unconditionally and clobbered RoS mode's season total (443 pts)
      // with a single week's number (28 pts) whenever comparison data
      // existed — defeating "independent per-week projections summed",
      // the whole point of the RoS toggle. Weekly mode only past this gate.
      const m_pts = c && c.model_points != null && Number(c.model_points) > 0 ? Number(c.model_points) : null;
      const raw_pts = p.projected_points != null && Number(p.projected_points) > 0 ? Number(p.projected_points) : null;
      const mk_s = (c && c.market_season_points != null && Number(c.market_season_points) > 0) ? Number(c.market_season_points) / 17.0 : null;
      const weekly = m_pts ?? raw_pts ?? mk_s ?? 0;

      p.projected_points = Number(weekly.toFixed(2));
      p.point_estimate = Number(weekly.toFixed(2));
      p.weekly = Number(weekly.toFixed(2));

      const rawWidth = c?.interval_width ?? c?.width ?? p.width;
      const width = Number(rawWidth ?? scaledFallbackWidth(p.position, weekly));
      p.width = Number(width.toFixed(2));
      // why no /2: width is HALF-width (unified 2026-09-09). Floor restores
      // src's max(0,…) that the old symmetric rebuild discarded.
      p.projection_lower = Number(Math.max(0, weekly - width).toFixed(2));
      p.projection_upper = Number((weekly + width).toFixed(2));
      p.lower = p.projection_lower;
      p.upper = p.projection_upper;
    } else {
      // p.projected_points/width/projection_lower/upper are already the
      // season-scaled RoS values set when mapping data.players above.
      p.weekly = Number(p.per_game_neutral) || 0;
      p.lower = p.projection_lower;
      p.upper = p.projection_upper;
      // Market comparison is weekly-only (c.market_points) — pairing it
      // with a season total is apples-to-oranges, so compare season sums
      // (c.market_season_points) instead of falling through to the
      // per-week market figure the block above uses.
      const mkSeason = c && c.market_season_points != null && Number(c.market_season_points) > 0 ? Number(c.market_season_points) : null;
      p.market_points = mkSeason;
      p.delta_points = mkSeason != null ? Number((p.projected_points - mkSeason).toFixed(2)) : null;
    }
    p.ecr = p.fp_ecr;
    p.adp = p.fp_adp;
    p.tier = p.fp_tier;
  }

  // sync global search
  const g = document.getElementById('globalSearch');
  if (g && !g.dataset.bound) {
    g.dataset.bound = '1';
    g.addEventListener('input', debounce(()=>{ currentQuery = g.value; currentPage = 1; renderTable(); syncHash(); }, 150));
    g.addEventListener('keydown', e=>{ if(e.key==='/' && document.activeElement!==g){ e.preventDefault(); g.focus(); }});
  }
  if (g) g.value = currentQuery;

  // Compute BUY/SELL counts for header
  const buyCount = [...compById.values()].filter(c => c.edge === 'BUY').length;
  const sellCount = [...compById.values()].filter(c => c.edge === 'SELL').length;
  const marketCovered = [...compById.values()].filter(c => c.market_points != null).length;
  // Deployments without any market source (no market_points, no FP ECR/ADP)
  // force compare mode off: every Market/ECR column would render empty.
  // Father (data present) is unaffected — gates below reduce to the old logic.
  const hasMarketPts = marketCovered > 0 || [...compById.values()].some(c => c.fp_ecr != null || c.fp_adp != null);
  if (!hasMarketPts) compareEnabled = false;

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Projections</h1>
      <p>Weekly projections. Bars show the model range (floor–ceiling); overlap = toss-up (heuristic, not a statistical test).</p>
      <p class="micro faint" style="margin-top:4px">Each week's projections are calculated after the previous week's games complete, from season-to-date stats blended with last season — early weeks lean on last season, later weeks on current form. Data refreshes daily.</p>
    </div>
    ${!rosMode && meta.stale ? `<div class="alert alert-warn reveal in" role="status" style="margin-top:12px">${escapeHtml(meta.note || `No precomputed projections for week ${selectedWeek ?? meta.week} — showing nearest available data.`)}</div>` : ''}

    ${hasComparison ? `
    <div class="kpi-row reveal in" style="margin-top:4px">
      <div class="kpi-card" style="border-top:1px solid var(--emerald)">
        <div class="kpi-label" style="color:var(--emerald)">BUY edges${hasMarketPts ? ': market sleeping' : ''}</div>
        <div class="kpi-value" style="color:var(--emerald)">${buyCount}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill good" style="width:${Math.min(100, Math.round((buyCount/ Math.max(1, Math.min(40, compById.size/6)))*100))}%"></div></div>
        <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:6px">${hasMarketPts ? 'Model rank ≥12 better than FP ECR or +3.0 pts vs Sleeper market' : 'Model $/VOR ≥15% below pool average'}</div>
      </div>
      <div class="kpi-card" style="border-top:1px solid var(--crimson)">
        <div class="kpi-label" style="color:var(--crimson)">SELL flags${hasMarketPts ? ': market overvalued' : ''}</div>
        <div class="kpi-value" style="color:var(--crimson)">${sellCount}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill bad" style="width:${Math.min(100, Math.round((sellCount/ Math.max(1, Math.min(40, compById.size/6)))*100))}%"></div></div>
        <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:6px">${hasMarketPts ? 'Market rank ≥12 higher or −3.0 pts vs model' : 'Model $/VOR ≥15% above pool average'}</div>
      </div>
      ${hasMarketPts ? `
      <div class="kpi-card" style="border-top:1px solid var(--sky)">
        <div class="kpi-label" style="color:var(--sky)">Market coverage: Sleeper + FantasyPros</div>
        <div class="kpi-value" style="color:var(--sky)">${marketCovered} / ${compById.size}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill" style="background:var(--sky); width:${Math.round((marketCovered/Math.max(1, compById.size))*100)}%"></div></div>
        <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:6px">Sleeper pts+stats keyed by gsis_id · FP ECR/ADP via name+team+pos</div>
      </div>
      ` : ''}
      <div class="kpi-card" style="border-top:1px solid var(--amber)">
        <div class="kpi-label" style="color:var(--amber)">Comparison source</div>
        <div class="kpi-value" style="font-size:14px; line-height:1.3">${hasMarketPts ? 'Model vs Market' : 'Model values'}<br><span style="font:600 11px "Helvetica Neue", Helvetica,sans-serif; color:var(--text-muted); letter-spacing:0.04em; text-transform:uppercase">${compRaw.fetched_at ? new Date(compRaw.fetched_at).toLocaleString() : 'DB snapshot'} · ${compById.size} ranked</span></div>
        <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:6px">${hasMarketPts ? 'Free, local: Sleeper projections + FP free ECR/ADP' : 'VBD auction values from league scoring'}</div>
      </div>
    </div>
    <div class="card reveal in" style="margin-top:8px; border-top:1px solid var(--amber)">
      <div class="card-body" style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; justify-content:space-between">
        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center">
          ${hasMarketPts ? `<span class="kicker">Compare vs Market</span>
          <button class="chip ${compareEnabled ? 'active' : ''}" id="toggleCompare" title="Toggle market comparison">${compareEnabled ? 'Market + ECR on' : 'Show Market & ECR'}</button>` : `<span class="kicker">Value edges</span>`}
          <div style="display:flex; gap:6px; margin-left:8px; flex-wrap:wrap">
            <button class="chip ${edgeFilter==='ALL' ? 'active' : ''}" data-edge="ALL">All (${compById.size})</button>
            <button class="chip ${edgeFilter==='BUY' ? 'active' : ''}" data-edge="BUY" style="${edgeFilter==='BUY' ? 'background:var(--emerald-dim); border-color:rgba(16,185,129,0.35); color:var(--emerald)' : ''}">▲ BUY (${buyCount})</button>
            <button class="chip ${edgeFilter==='SELL' ? 'active' : ''}" data-edge="SELL" style="${edgeFilter==='SELL' ? 'background:var(--crimson-dim); border-color:rgba(239,68,68,0.35); color:var(--crimson)' : ''}">▼ SELL (${sellCount})</button>
          </div>
        </div>
        <span class="mono" style="font-size:11px; color:var(--text-faint)">Click row ▶ to see stat deltas (pass/rush/rec yds, TDs). Preseason: Sleeper pts empty until Week 1 publish: rank delta (ECR) works now.</span>
      </div>
    </div>
    ` : `<div class="alert alert-info reveal in" style="margin-top:8px">Market comparison not loaded. Showing model only.</div>`}

    <div class="card reveal in" style="margin-top:12px">
      <div class="card-body" style="display:flex; flex-direction:column; gap:12px">
        ${!rosMode ? `
        <div class="row" style="gap:8px">
          <span class="kicker">Week</span>
          <div class="filters week-picker-scroll" style="overflow-x:auto; flex-wrap:nowrap; max-width:100%; padding-bottom:4px">
            ${Array.from({length:18},(_,i)=>i+1).map(w=>`<button class="chip ${w===Number(selectedWeek)?'active':''}" data-proj-week="${w}" title="Show week ${w} projections" style="flex-shrink:0">${w}</button>`).join('')}
          </div>
        </div>
        ` : ''}
        <div class="row">
          <label class="search-mini" style="flex:1; min-width:260px">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            <input id="localSearch" placeholder="pos:WR wind>15 healthy:true" autocomplete="off" />
          </label>
          <span class="kicker" id="countLabel" style="white-space:nowrap"></span>
          <button class="chip" id="toggleProjSortDir" title="Flip sorting: highest ↔ lowest">↕ Highest → Lowest</button>
          <button class="chip ${rosMode ? 'active' : ''}" id="toggleRos" title="Switch between weekly and rest-of-season projections" style="${rosMode ? 'background:var(--amber-dim); border-color:rgba(245,158,11,0.35); color:var(--amber)' : ''}">${rosMode ? '📅 RoS (×17)' : '📊 Weekly'}</button>
        </div>
        <div class="filters" id="quickChips">
          <button class="chip" data-chip="pos:QB">QB</button>
          <button class="chip" data-chip="pos:RB">RB</button>
          <button class="chip" data-chip="pos:WR">WR</button>
          <button class="chip" data-chip="pos:TE">TE</button>
          <button class="chip" data-chip="healthy:true">Healthy</button>
          <button class="chip" data-chip="trending:true">Trending</button>
          <button class="chip" data-chip="roster:true">My Roster</button>
          <button class="chip" data-chip="wind>15">Wind &gt;15</button>
          <button class="chip" data-chip="interval<4">Tight (±&lt;4)</button>
        </div>
        ${meta.cold ? `<div class="alert alert-warn">No fresh data. Refresh to populate.</div>` : ``}
        ${!allPlayers.length ? `<div class="alert alert-info">No projections yet. Search works once data loads.</div>` : ``}
      </div>
    </div>

    <div class="responsive-view">
    ${compareEnabled && hasComparison ? `
    <details style="padding:8px 12px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; margin-bottom:10px; font:500 11px "Helvetica Neue", Helvetica,sans-serif; line-height:1.4" aria-label="Projections legend: Model vs Market, BUY and SELL">
      <summary style="cursor:pointer; font-weight:700" title="Toggle legend">Legend: Model vs Market, BUY/SELL</summary>
      <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-top:8px">
      <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--amber); border-radius:2px; display:inline-block"></span> <strong style="color:var(--amber)">Model</strong> <span>weekly PPR (×17 for Auction)</span></span>
      <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--sky); border-radius:2px; display:inline-block"></span> <strong style="color:var(--sky)">Sleeper</strong> <span>Market: free Sleeper projections</span></span>
      </div>
      <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-top:6px">
      <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--emerald); border-radius:2px; display:inline-block"></span> BUY = Model ≥ +3 pts / ≥12 ranks better</span>
      <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--crimson); border-radius:2px; display:inline-block"></span> SELL = Market ≥ +3 / 12 better</span>
      <span class="mono" style="color:var(--text-faint); margin-left:auto">FP ECR/ADP sparse on free tier: Market pts primary</span>
      </div>
    </details>
    ` : ''}
    <div class="table-wrap sticky-player reveal in" style="margin-top:16px; overflow-x:auto; max-width:100%">
      <table id="projTable" style="min-width:${compareEnabled && hasComparison ? '1180px' : '760px'}">
        <thead>
          <tr>
            <th data-sort="player_name" tabindex="0" role="button" aria-label="Sort by Player">Player</th>
            <th data-sort="position" tabindex="0" role="button" aria-label="Sort by Position">Pos</th>
            <th data-sort="team" tabindex="0" role="button" aria-label="Sort by Team">Team</th>
            <th data-sort="projected_points" tabindex="0" role="button" aria-label="Sort by Model Points" style="${compareEnabled && hasComparison ? 'color:var(--amber); border-bottom:2px solid var(--amber)' : ''}">${rosMode ? 'RoS' : 'Model'}<br><span style="font:600 10px "Helvetica Neue", Helvetica,sans-serif; color:${compareEnabled && hasComparison ? 'var(--amber)' : 'var(--text-faint)'}; opacity:0.7">${rosMode ? 'total' : 'proj'}</span></th>
            ${compareEnabled && hasComparison ? `
            <th data-sort="market_points" tabindex="0" role="button" aria-label="Sort by Sleeper Market Points" style="color:var(--sky); border-bottom:2px solid var(--sky)">Market<br><span style="font:600 10px "Helvetica Neue", Helvetica,sans-serif; color:var(--sky); opacity:0.7">${rosMode ? 'Sleeper season' : 'Sleeper'}</span></th>
            <th data-sort="delta_points" tabindex="0" role="button" aria-label="Sort by Points Delta" style="border-bottom:2px solid var(--border)">Δ<br><span style="font:600 10px "Helvetica Neue", Helvetica,sans-serif; color:var(--text-faint)">Grid−Mkt</span></th>
            <th data-sort="fp_ecr" tabindex="0" role="button" aria-label="Sort by FantasyPros ECR">ECR</th>
            <th data-sort="delta_rank" tabindex="0" role="button" aria-label="Sort by Rank Delta">Δ Rk</th>
            <th data-sort="fp_adp" tabindex="0" role="button" aria-label="Sort by ADP">ADP</th>
            <th data-sort="edge_score" tabindex="0" role="button" aria-label="Sort by Edge">Edge</th>
            ` : ''}
            <th>Interval</th>
            <th data-sort="wind_mph" tabindex="0" role="button" aria-label="Sort by Wind Speed">Wind</th>
            <th data-sort="width" tabindex="0" role="button" aria-label="Sort by Confidence Width">Conf</th>
            <th>Injury</th>
            ${compareEnabled && hasComparison ? `<th style="width:28px"></th>` : ''}
          </tr>
        </thead>
        <tbody id="projBody"></tbody>
      </table>
    </div>
    </div>
    <div class="player-cards-grid" id="projCards"></div>
    <div id="paginationControls" style="display:flex; justify:space-between; align-items:center; margin-top:16px; flex-wrap:wrap; gap:8px"></div>
  `;

  // Toggle compare
  const tgl = root.querySelector('#toggleCompare');
  if (tgl) tgl.addEventListener('click', ()=>{ compareEnabled = !compareEnabled; renderProjections(root); });

  // Toggle RoS / Weekly
  const rosTgl = root.querySelector('#toggleRos');
  if (rosTgl) rosTgl.addEventListener('click', ()=>{ rosMode = !rosMode; renderProjections(root); });

  // Week picker (weekly mode only) — independent per-week model output,
  // not the same season-average snapshot repeated across every week.
  root.querySelectorAll('[data-proj-week]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const w = Number(btn.getAttribute('data-proj-week'));
      selectedWeek = w === selectedWeek ? null : w;
      currentPage = 1;
      renderProjections(root);
    });
  });

  // Edge filter
  root.querySelectorAll('[data-edge]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      edgeFilter = btn.getAttribute('data-edge');
      currentPage = 1;
      renderTable();
      // update active states
      root.querySelectorAll('[data-edge]').forEach(b=>{
        const e = b.getAttribute('data-edge');
        if (e === edgeFilter) { b.classList.add('active'); if(e==='BUY') { b.style.background='var(--emerald-dim)'; b.style.borderColor='rgba(16,185,129,0.35)'; b.style.color='var(--emerald)'; } else if(e==='SELL'){ b.style.background='var(--crimson-dim)'; b.style.borderColor='rgba(239,68,68,0.35)'; b.style.color='var(--crimson)'; } else { b.style.background=''; b.style.borderColor=''; b.style.color=''; } }
        else { b.classList.remove('active'); b.style.background=''; b.style.borderColor=''; b.style.color=''; }
      });
    });
  });

  const local = root.querySelector('#localSearch');
  if (local) {
    local.value = currentQuery;
    local.addEventListener('input', debounce(()=>{ currentQuery = local.value; currentPage = 1; if(g) g.value = currentQuery; renderTable(); syncHash(); }, 150));
  }
  root.querySelectorAll('[data-chip]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const chip = btn.getAttribute('data-chip');
      const has = currentQuery.includes(chip);
      currentQuery = has ? currentQuery.replace(chip,'').replace(/\s{2,}/g,' ').trim() : (currentQuery ? `${currentQuery} ${chip}` : chip);
      currentPage = 1;
      if(local) local.value = currentQuery;
      if(g) g.value = currentQuery;
      renderTable(); syncHash();
    });
  });

  let sortKey = 'projected_points', sortDir = -1, userSorted = false;
  root.querySelectorAll('th[data-sort]').forEach(th=>{
    th.style.cursor = 'pointer';
    const triggerSort = ()=>{
      const k = th.getAttribute('data-sort');
      if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = k==='player_name' ? 1 : -1; }
      userSorted = true;
      currentPage = 1;
      renderTable();
      updateSortToggleLabel();
    };
    th.addEventListener('click', triggerSort);
    th.addEventListener('keydown', e=>{ if(e.key === 'Enter' || e.key === ' ') { e.preventDefault(); triggerSort(); }});
  });
  function updateSortToggleLabel(){
    const btn = root.querySelector('#toggleProjSortDir');
    if (!btn) return;
    const dirLabel = sortDir===-1 ? 'Highest → Lowest' : 'Lowest → Highest';
    btn.textContent = `↕ ${dirLabel}`;
    btn.title = `Currently ${dirLabel} by ${sortKey}: click to flip`;
  }
  root.querySelector('#toggleProjSortDir')?.addEventListener('click', ()=>{
    sortDir *= -1;
    userSorted = true;
    currentPage = 1;
    renderTable();
    updateSortToggleLabel();
  });
  updateSortToggleLabel();

  function filteredWithEdge(base) {
    // Audit 22.0: tag roster membership for "My Roster" chip filter
    for (const p of base) {
      p._onRoster = rosterPlayerIds.has(String(p.player_id));
    }
    let rows = filterPlayers(base, currentQuery);
    // Edge filter works on server-computed edges with or without market
    // columns showing (deployments without market data force compare off).
    if (hasComparison && edgeFilter !== 'ALL' && (compareEnabled || !hasMarketPts)) {
      rows = rows.filter(p => (p.edge || 'NEUTRAL') === edgeFilter);
    }
    return rows;
  }

  function getSortVal(p, key) {
    let v = p[key];
    if ((v == null || v === '' || v === '—') && key === 'projected_points') v = p.point_estimate;
    if (v == null || v === '' || v === '—' || v === '–' || v === '-') return null;
    if (typeof v === 'number') return isNaN(v) ? null : v;
    const str = String(v).trim();
    const num = Number(str);
    if (!isNaN(num) && str !== '') return num;
    return str.toLowerCase();
  }

  function renderTable() {
    let rows = filteredWithEdge(allPlayers);
    // sort — default view demotes off-depth-chart players first, then
    // healthy QB backups (demote, don't remove); any explicit user sort
    // stays pure.
    const aheadMap = userSorted ? null : buildAheadMap(allPlayers);
    rows = [...rows].sort((a,b)=>{
      if (!userSorted) {
        const tier = relevanceTier(a, {}, aheadMap) - relevanceTier(b, {}, aheadMap);
        if (tier !== 0) return tier;
        const qb = backupDemote(a, {}, aheadMap) - backupDemote(b, {}, aheadMap);
        if (qb !== 0) return qb;
      }
      const av = getSortVal(a, sortKey);
      const bv = getSortVal(b, sortKey);
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (typeof av === 'number' && typeof bv === 'number') {
        return (av - bv) * sortDir;
      }
      return String(av).localeCompare(String(bv)) * sortDir;
    });

    // Update th aria-sort attributes
    root.querySelectorAll('th[data-sort]').forEach(th => {
      const k = th.getAttribute('data-sort');
      if (k === sortKey) {
        th.setAttribute('aria-sort', sortDir === 1 ? 'ascending' : 'descending');
      } else {
        th.removeAttribute('aria-sort');
      }
    });

    const totalCount = rows.length;
    const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;

    const startIndex = (currentPage - 1) * PAGE_SIZE;
    const endIndex = Math.min(startIndex + PAGE_SIZE, totalCount);
    const pagedRows = rows.slice(startIndex, endIndex);

    const countLabel = root.querySelector('#countLabel');
    if (countLabel) {
      if (totalCount === 0) {
        countLabel.textContent = `0 players`;
      } else {
        countLabel.textContent = `Showing ${startIndex + 1}–${endIndex} of ${totalCount} players${totalCount !== allPlayers.length ? ` (filtered from ${allPlayers.length})` : ''}${hasComparison && edgeFilter !== 'ALL' ? ` · ${edgeFilter} only` : ''}`;
      }
    }

    const tbody = root.querySelector('#projBody');
    const colSpan = compareEnabled && hasComparison ? 15 : 9;
    if (!pagedRows.length) {
      tbody.innerHTML = `<tr><td colspan="${colSpan}"><div class="empty">No matches for <code class="inline">${escapeHtml(currentQuery || '—')}</code>${edgeFilter !== 'ALL' ? ` with edge ${edgeFilter}` : ''}. Try <code class="inline">pos:WR</code> or clear filters.</div></td></tr>`;
    } else {
      tbody.innerHTML = pagedRows.map(p=>{
        const pos = p.position || p.position_group || 'UNK';
        const proj = Number(p.projected_points ?? p.point_estimate ?? 0);
        // why no /2: width is HALF-width (unified 2026-09-09); the (high-low)
        // fallback derives from a full span, so it halves. Floor matches src.
        const low = Number(p.projection_lower ?? p.lower_bound ?? Math.max(0, proj - (p.width ?? 5)));
        const high = Number(p.projection_upper ?? p.upper_bound ?? proj + (p.width ?? 5));
        const width = Number(p.width ?? p.projection_width ?? (high - low) / 2);
        const market = p.market_points != null ? Number(p.market_points).toFixed(1) : '—';
        const ecr = p.fp_ecr != null ? `#${p.fp_ecr}${p.fp_ecr_pos ? ` (#${p.fp_ecr_pos} ${pos})` : ''}${p.fp_tier ? ` <span style="background:var(--violet-dim); color:var(--violet); border:1px solid rgba(168,85,247,0.18); border-radius:999px; padding:1px 5px; font:700 10px ui-monospace, SFMono-Regular,monospace">T${p.fp_tier}</span>` : ''}` : '—';
        const adp = p.fp_adp != null ? `#${p.fp_adp}` : '—';
        const edgeCell = compareEnabled && hasComparison ? edgeBadge(p.edge) : '';
        const tColor = getTeamColor(p.team);
        const teamPill = p.team ? `<span class="badge" style="background:${tColor}1f; color:${tColor}; border:1px solid ${tColor}3d; font-weight:700">${teamLogo(p.team, 14)} ${escapeHtml(p.team)}</span>` : '—';
        const rowAccent = p.edge === 'BUY' ? 'var(--emerald)' : p.edge === 'SELL' ? 'var(--crimson)' : tColor;
        const expandBtn = compareEnabled && hasComparison ? `<button class="chip" data-expand="${p.player_id}" aria-label="Show stat deltas for ${escapeHtml(p.player_name)}" style="padding:4px 8px; font-size:11px">▶</button>` : '';
        const mainRow = `
          <tr data-team="${p.team || ''}" data-pid="${p.player_id}" class="clickable-row" style="cursor:pointer; --team-accent:${rowAccent}; ${p.edge==='BUY' ? 'background:rgba(16,185,129,0.04)' : p.edge==='SELL' ? 'background:rgba(239,68,68,0.04)' : ''}">
            <td><div class="player-cell">${playerAvatar(p, 32)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name || p.player_id)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '—')} ${p.model_pos_rank ? `<span style="color:var(--text-faint)">· #${p.model_pos_rank} ${pos}</span>` : ''}</div></div></div></td>
            <td>${posBadge(pos)}</td>
            <td>${teamPill}</td>
            <td class="mono" style="font-weight:700; color:var(--amber)">${proj.toFixed(1)}</td>
            ${compareEnabled && hasComparison ? `
            <td class="mono" style="color:var(--sky)">${market}</td>
            <td>${deltaPtsBadge(p.delta_points)}</td>
            <td class="mono" style="font-size:11px; color:var(--text-muted)">${ecr}</td>
            <td>${deltaRankBadge(p.delta_rank)}</td>
            <td class="mono" style="font-size:11px; color:var(--text-muted)">${adp}</td>
            <td>${edgeCell}</td>
            ` : ''}
            <td>${intervalBar({ point: proj, low, high, width, min: 0, max: 35 })}</td>
            <td>${windBadge(p.wind_mph)}</td>
            <td>${confBadge(width)}</td>
            <td>${injuryBadge(p.injury_status)} ${p.trending ? `<span class="badge" style="background:var(--sky-dim); color:var(--sky); margin-left:6px">↗ trending</span>`:''}</td>
            ${compareEnabled && hasComparison ? `<td>${expandBtn}</td>` : ''}
          </tr>
        `;
        // stat deltas hidden row
        if (compareEnabled && hasComparison && p.stat_deltas && p.stat_deltas.length) {
          const statRows = p.stat_deltas.filter(s => s.market != null || s.model != null).slice(0,7).map(s=>`
            <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; padding:4px 0; border-bottom:1px solid rgba(var(--text-rgb,0,0,0),0.06)">
              <span class="mono" style="font-size:11px; color:var(--text-muted); min-width:64px">${s.label}</span>
              ${statDeltaBar(s.model, s.market, s.delta)}
            </div>
          `).join('');
          const opp = p.opponent_team ? `vs ${p.opponent_team}` : '';
          return mainRow + `<tr class="expand-panel" data-expand-panel="${p.player_id}" style="display:none; background:var(--surface-raised)"><td colspan="${colSpan}" style="padding:12px 12px 12px 48px"><div style="display:flex; flex-direction:column; gap:6px"><div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap"><span class="kicker">Stat deltas: Model vs Market</span><span class="mono" style="font-size:11px; color:var(--text-faint)">${escapeHtml(p.player_name)} ${opp} · <span style="color:var(--amber)">amber=Model</span> <span style="color:var(--sky)">, blue=Market</span></span></div>${statRows || `<span class="mono" style="font-size:11px; color:var(--text-faint)">No market stats for this player yet (preseason).</span>`}<div class="mono" style="font-size:11px; color:var(--text-faint); margin-top:6px">${p.fp_ecr != null || p.fp_adp != null ? `FP ECR #${p.fp_ecr ?? '—'} ${p.fp_ecr_pos ? `(pos #${p.fp_ecr_pos})` : ''} · ADP #${p.fp_adp ?? '—'} · ` : ''}Model #${p.model_overall_rank ?? '—'} (pos #${p.model_pos_rank ?? '—'})${p.delta_rank != null ? ` · ΔRk ${(p.delta_rank > 0 ? '+' : '')+p.delta_rank}` : ''}${p.search_rank != null || p.depth_order != null ? ` · Sleeper #${p.search_rank ?? '—'}${p.depth_order != null ? ` (${p.depth_position || p.position} ${p.depth_order})` : ''}` : ''}</div></div></td></tr>`;
        }
        return mainRow;
      }).join('');
      // bind expand toggles
      tbody.querySelectorAll('[data-expand]').forEach(btn=>{
        btn.addEventListener('click', (e)=>{
          e.stopPropagation();
          const pid = btn.getAttribute('data-expand');
          const panel = tbody.querySelector(`[data-expand-panel="${pid}"]`);
          if (!panel) return;
          const isOpen = panel.style.display !== 'none';
          panel.style.display = isOpen ? 'none' : 'table-row';
          btn.textContent = isOpen ? '▶' : '▼';
        });
      });
    }

    const cardsGrid = root.querySelector('#projCards');
    if (cardsGrid) {
      cardsGrid.innerHTML = pagedRows.map(p => {
        const baseCard = playerCard(p, { showInterval: true, showTeamLogo: true });
        if (!compareEnabled || !hasComparison) return baseCard;
        // inject comparison footer into card string (after pc-details)
        const marketLine = p.market_points != null ? `<span class="mono" style="font-size:11px; color:var(--text-muted)">Market ${Number(p.market_points).toFixed(1)} · <span style="color:${Number(p.delta_points) > 0.5 ? 'var(--emerald)' : Number(p.delta_points) < -0.5 ? 'var(--crimson)' : 'var(--text-muted)'}">${p.delta_points > 0 ? '+' : ''}${Number(p.delta_points).toFixed(1)}</span></span>` : '';
        const rankLine = p.fp_ecr ? `ECR #${p.fp_ecr} · Δ ${p.delta_rank != null ? (p.delta_rank>0?'+':'')+p.delta_rank : '—'}` : (p.search_rank != null || p.depth_order != null ? `Sleeper #${p.search_rank ?? '—'}${p.depth_order != null ? ` (${p.depth_position || p.position} ${p.depth_order})` : ''}` : 'ECR —');
        const edgeHtml = edgeBadge(p.edge);
        // Insert before closing card div
        return baseCard.replace('</div>\n', `  <div style="margin-top:8px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding-top:8px; border-top:1px solid var(--border)">${marketLine ? `<span class="mono" style="font-size:11px; color:var(--text-muted)">${marketLine}</span>` : ''}<span class="mono" style="font-size:11px; color:var(--text-muted)">${rankLine}</span><span class="spacer"></span>${edgeHtml}</div></div>\n`);
      }).join('');
    }

    root.querySelectorAll('[data-pid]').forEach(el => {
      if (el.classList.contains('expand-panel')) return;
      el.style.cursor = 'pointer';
      el.addEventListener('click', (e) => {
        if (e.target.closest('[data-expand]')) return;
        const pid = el.getAttribute('data-pid');
        const targetPlayer = allPlayers.find(p => String(p.player_id) === String(pid));
        if (targetPlayer) {
          openPlayerModal(targetPlayer, root);
        }
      });
    });

    // Render pagination controls
    const pag = root.querySelector('#paginationControls');
    if (pag) {
      if (totalPages <= 1) {
        pag.innerHTML = '';
      } else {
        pag.innerHTML = `
          <div style="font:400 13px "Helvetica Neue", Helvetica,sans-serif; color:var(--text-muted)">
            Page <strong>${currentPage}</strong> of <strong>${totalPages}</strong>
          </div>
          <div style="display:flex; gap:6px">
            <button class="chip" id="firstPageBtn" ${currentPage === 1 ? 'disabled style="opacity:0.4; cursor:not-allowed"' : ''}>« First</button>
            <button class="chip" id="prevPageBtn" ${currentPage === 1 ? 'disabled style="opacity:0.4; cursor:not-allowed"' : ''}>‹ Prev</button>
            <button class="chip" id="nextPageBtn" ${currentPage === totalPages ? 'disabled style="opacity:0.4; cursor:not-allowed"' : ''}>Next ›</button>
            <button class="chip" id="lastPageBtn" ${currentPage === totalPages ? 'disabled style="opacity:0.4; cursor:not-allowed"' : ''}>Last »</button>
          </div>
        `;
        pag.querySelector('#firstPageBtn')?.addEventListener('click', ()=>{ if (currentPage > 1) { currentPage = 1; renderTable(); } });
        pag.querySelector('#prevPageBtn')?.addEventListener('click', ()=>{ if (currentPage > 1) { currentPage--; renderTable(); } });
        pag.querySelector('#nextPageBtn')?.addEventListener('click', ()=>{ if (currentPage < totalPages) { currentPage++; renderTable(); } });
        pag.querySelector('#lastPageBtn')?.addEventListener('click', ()=>{ if (currentPage < totalPages) { currentPage = totalPages; renderTable(); } });
      }
    }
  }

  function syncHash(){
    const base = 'projections';
    location.hash = currentQuery ? `${base}?q=${encodeURIComponent(currentQuery)}` : base;
  }

  renderTable();
}

function debounce(fn, ms=150){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a), ms); }; }
