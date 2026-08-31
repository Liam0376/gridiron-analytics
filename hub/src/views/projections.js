import { fetchProjections, fetchComparison } from '../api.js';
import { filterPlayers } from '../search.js';
import { posBadge, injuryBadge, windBadge, confBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { playerCard } from '../components/playerCard.js';
import { getTeamColor } from '../components/teamColors.js';

let allPlayers = [];
let compById = new Map();
let comparisonMeta = null;
let currentQuery = '';
let currentPage = 1;
let compareEnabled = true;
let edgeFilter = 'ALL'; // ALL | BUY | SELL
const PAGE_SIZE = 50;

function edgeBadge(edge) {
  if (edge === 'BUY') return `<span class="badge" style="background:var(--emerald-dim); color:var(--emerald); border:1px solid rgba(16,185,129,0.22)">▲ BUY</span>`;
  if (edge === 'SELL') return `<span class="badge" style="background:var(--crimson-dim); color:var(--crimson); border:1px solid rgba(239,68,68,0.22)">▼ SELL</span>`;
  return `<span class="badge" style="background:rgba(255,255,255,0.06); color:var(--text-faint); border:1px solid var(--border)">—</span>`;
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
  return `<div style="display:flex; align-items:center; gap:6px; min-width:160px"><span class="mono" style="font-size:11px; min-width:44px; text-align:right">${model.toFixed(1)}</span><div style="flex:1; height:4px; background:rgba(255,255,255,0.08); border-radius:999px; position:relative; overflow:hidden"><div style="position:absolute; left:0; top:0; bottom:0; width:${pctM}%; background:var(--amber); opacity:0.9; border-radius:999px"></div><div style="position:absolute; left:0; top:0; bottom:0; width:${pctK}%; background:var(--sky); opacity:0.35; border-radius:999px"></div></div><span class="mono" style="font-size:11px; color:var(--text-muted); min-width:36px">${market.toFixed(1)}</span><span class="mono" style="font-size:11px; color:${dColor}; font-weight:700; min-width:36px; text-align:right">${delta > 0 ? '+' : ''}${delta.toFixed(1)}</span></div>`;
}

export async function renderProjections(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  currentQuery = params.get('q') || document.getElementById('globalSearch')?.value || '';
  currentPage = 1;

  const data = await fetchProjections({});
  allPlayers = data.players || [];
  const meta = data.meta || {};

  // Fetch market comparison in parallel (free, $0; graceful degrade if no DB table yet)
  let compRaw = { players: [], count: 0, meta: {}, fetched_at: null };
  try { compRaw = await fetchComparison({ limit: 800 }); } catch { compRaw = { players: [], count: 0, meta: {}, fetched_at: null }; }
  compById = new Map((compRaw.players || []).map(c => [String(c.player_id), c]));
  comparisonMeta = compRaw;

  // Enrich allPlayers with comparison fields (model vs market + ECR/ADP)
  const hasComparison = compById.size > 0;
  if (hasComparison) {
    for (const p of allPlayers) {
      const c = compById.get(String(p.player_id));
      if (c) {
        p.market_points = c.market_points;
        p.delta_points = c.delta_points;
        p.model_overall_rank = c.model_overall_rank;
        p.model_pos_rank = c.model_pos_rank;
        p.fp_ecr = c.fp_ecr;
        p.fp_ecr_pos = c.fp_ecr_pos;
        p.fp_adp = c.fp_adp;
        p.delta_rank = c.delta_rank;
        p.delta_pos_rank = c.delta_pos_rank;
        p.edge = c.edge;
        p.edge_score = c.edge_score;
        p.stat_deltas = c.stat_deltas;
        // prefer model_points from comparison (weekly projection) if present
        if (c.model_points != null) {
          p.projected_points = c.model_points;
          p.point_estimate = c.model_points;
        }
      } else {
        p.market_points = null; p.delta_points = null; p.edge = 'NEUTRAL'; p.stat_deltas = [];
      }
    }
  }

  // sync global search
  const g = document.getElementById('globalSearch');
  if (g && !g.dataset.bound) {
    g.dataset.bound = '1';
    g.addEventListener('input', debounce(()=>{ currentQuery = g.value; currentPage = 1; updateTable(); syncHash(); }, 150));
    g.addEventListener('keydown', e=>{ if(e.key==='/' && document.activeElement!==g){ e.preventDefault(); g.focus(); }});
  }
  if (g) g.value = currentQuery;

  // Compute BUY/SELL counts for header
  const buyCount = [...compById.values()].filter(c => c.edge === 'BUY').length;
  const sellCount = [...compById.values()].filter(c => c.edge === 'SELL').length;
  const marketCovered = [...compById.values()].filter(c => c.market_points != null).length;

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Projections</h1>
      <p>Searchable, sortable source of truth. <span class="mono" style="color:var(--amber)">Model</span> is <code class="inline">calculate_projection</code> + <code class="inline">FLEX ×1.05</code> + <code class="inline">wind&gt;15 → −0.02/mph (QB/WR/K)</code>. Bar shows estimated range (conformal-seeded, position &amp; star-scaled — not a formal 80% guarantee). Overlapping bars = toss-up.</p>
    </div>

    ${hasComparison ? `
    <div class="kpi-row reveal in" style="margin-top:4px">
      <div class="kpi-card" style="border-left:3px solid var(--emerald)">
        <div class="kpi-label">BUY edges — market sleeping</div>
        <div class="kpi-value" style="color:var(--emerald)">${buyCount}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill good" style="width:${Math.min(100, Math.round((buyCount/ Math.max(1, Math.min(40, compById.size/6)))*100))}%"></div></div>
        <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:6px">Model rank ≥12 better than FP ECR or +3.0 pts vs Sleeper market</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--crimson)">
        <div class="kpi-label">SELL flags — market overvalued</div>
        <div class="kpi-value" style="color:var(--crimson)">${sellCount}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill bad" style="width:${Math.min(100, Math.round((sellCount/ Math.max(1, Math.min(40, compById.size/6)))*100))}%"></div></div>
        <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:6px">Market rank ≥12 higher or −3.0 pts vs model</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--sky)">
        <div class="kpi-label">Market coverage · Sleeper + FantasyPros</div>
        <div class="kpi-value" style="color:var(--sky)">${marketCovered} / ${compById.size}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill" style="background:var(--sky); width:${Math.round((marketCovered/Math.max(1, compById.size))*100)}%"></div></div>
        <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:6px">Sleeper pts+stats keyed by gsis_id · FP ECR/ADP via name+team+pos</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--amber)">
        <div class="kpi-label">Comparison source</div>
        <div class="kpi-value" style="font-size:14px; line-height:1.3">Model vs Market<br><span style="font:600 11px 'Fira Sans',sans-serif; color:var(--text-muted); letter-spacing:0.04em; text-transform:uppercase">${compRaw.fetched_at ? new Date(compRaw.fetched_at).toLocaleString() : 'DB snapshot'} · ${compById.size} ranked</span></div>
        <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:6px">Free, local — Sleeper projections + FP free ECR/ADP</div>
      </div>
    </div>
    <div class="card reveal in" style="margin-top:8px; border-left:3px solid var(--amber)">
      <div class="card-body" style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; justify-content:space-between">
        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center">
          <span class="kicker">Compare vs Market</span>
          <button class="chip ${compareEnabled ? 'active' : ''}" id="toggleCompare">${compareEnabled ? '✓ Market + ECR visible' : 'Show Market & ECR'}</button>
          <div style="display:flex; gap:6px; margin-left:8px; flex-wrap:wrap">
            <button class="chip ${edgeFilter==='ALL' ? 'active' : ''}" data-edge="ALL">All (${compById.size})</button>
            <button class="chip ${edgeFilter==='BUY' ? 'active' : ''}" data-edge="BUY" style="${edgeFilter==='BUY' ? 'background:var(--emerald-dim); border-color:rgba(16,185,129,0.35); color:var(--emerald)' : ''}">▲ BUY (${buyCount})</button>
            <button class="chip ${edgeFilter==='SELL' ? 'active' : ''}" data-edge="SELL" style="${edgeFilter==='SELL' ? 'background:var(--crimson-dim); border-color:rgba(239,68,68,0.35); color:var(--crimson)' : ''}">▼ SELL (${sellCount})</button>
          </div>
        </div>
        <span class="mono" style="font-size:11px; color:var(--text-faint)">Click row ▶ to see stat deltas (pass/rush/rec yds, TDs). Preseason: Sleeper pts empty until Week 1 publish — rank delta (ECR) works now.</span>
      </div>
    </div>
    ` : `<div class="alert alert-info reveal in" style="margin-top:8px">Market comparison warming up — run refresh to populate Sleeper projections (pts+stats) + FantasyPros ECR/ADP. Until then this table shows Gridiron model only. Free sources: Sleeper <code class="inline">/projections/nfl/regular/{season}/{week}</code> + FantasyPros <code class="inline">/players?show=pos_rank</code> (both $0).</div>`}

    <div class="card reveal in" style="margin-top:12px">
      <div class="card-body" style="display:flex; flex-direction:column; gap:12px">
        <div class="row">
          <label class="search-mini" style="flex:1; min-width:260px">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            <input id="localSearch" placeholder="Try:  pos:WR wind>15  or  healthy:true  — chips: pos, team, opp, proj, wind, interval, trending" autocomplete="off" />
          </label>
          <span class="kicker" id="countLabel" style="white-space:nowrap"></span>
        </div>
        <div class="filters" id="quickChips">
          <button class="chip" data-chip="pos:QB">QB</button>
          <button class="chip" data-chip="pos:RB">RB</button>
          <button class="chip" data-chip="pos:WR">WR</button>
          <button class="chip" data-chip="pos:TE">TE</button>
          <button class="chip" data-chip="healthy:true">Healthy</button>
          <button class="chip" data-chip="trending:true">Trending</button>
          <button class="chip" data-chip="wind>15">Wind &gt;15</button>
          <button class="chip" data-chip="interval<3">Tight (±&lt;3)</button>
        </div>
        ${meta.cold ? `<div class="alert alert-warn">Cache cold — showing DB snapshot or start-sit fallback. Run <code class="inline">curl -X POST http://127.0.0.1:8000/refresh</code> or start <code class="inline">hub/server.py</code>.</div>` : ``}
        ${!allPlayers.length ? `<div class="alert alert-info">No projections yet. In-season you will see 300+ players here. For now this table shows demo/empty state — search still works once data lands.</div>` : ``}
      </div>
    </div>

    <div class="responsive-view">
    ${compareEnabled && hasComparison ? `
    <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; padding:8px 12px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; margin-bottom:10px; font:500 11px 'Fira Sans',sans-serif; line-height:1.4">
      <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--amber); border-radius:2px; display:inline-block"></span> <strong style="color:var(--amber)">Gridiron</strong> Model · weekly PPR (×17 for Auction)</span>
      <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--sky); border-radius:2px; display:inline-block"></span> <strong style="color:var(--sky)">Sleeper</strong> Market · free Sleeper projections</span>
      <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--emerald); border-radius:2px; display:inline-block"></span> BUY = Model ≥ +3 pts / ≥12 ranks better</span>
      <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--crimson); border-radius:2px; display:inline-block"></span> SELL = Market ≥ +3 / 12 better</span>
      <span class="mono" style="color:var(--text-faint); margin-left:auto">FP ECR/ADP sparse on free tier — Market pts primary</span>
    </div>
    ` : ''}
    <div class="table-wrap sticky-player reveal in" style="margin-top:16px">
      <table id="projTable" style="min-width:${compareEnabled && hasComparison ? '1180px' : '760px'}">
        <thead>
          <tr>
            <th data-sort="player_name" tabindex="0" role="button" aria-label="Sort by Player">Player</th>
            <th data-sort="position" tabindex="0" role="button" aria-label="Sort by Position">Pos</th>
            <th data-sort="team" tabindex="0" role="button" aria-label="Sort by Team">Team</th>
            <th data-sort="projected_points" tabindex="0" role="button" aria-label="Sort by Gridiron Model Points" style="${compareEnabled && hasComparison ? 'color:var(--amber); border-bottom:2px solid var(--amber)' : ''}">Gridiron<br><span style="font:600 10px 'Fira Sans',sans-serif; color:${compareEnabled && hasComparison ? 'var(--amber)' : 'var(--text-faint)'}; opacity:0.7">Model</span></th>
            ${compareEnabled && hasComparison ? `
            <th data-sort="market_points" tabindex="0" role="button" aria-label="Sort by Sleeper Market Points" style="color:var(--sky); border-bottom:2px solid var(--sky)">Market<br><span style="font:600 10px 'Fira Sans',sans-serif; color:var(--sky); opacity:0.7">Sleeper</span></th>
            <th data-sort="delta_points" tabindex="0" role="button" aria-label="Sort by Points Delta" style="border-bottom:2px solid var(--border)">Δ<br><span style="font:600 10px 'Fira Sans',sans-serif; color:var(--text-faint)">Grid−Mkt</span></th>
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
    <div class="player-cards-grid" id="projCards"></div>
    </div>
    <div id="paginationControls" style="display:flex; justify:space-between; align-items:center; margin-top:16px; flex-wrap:wrap; gap:8px"></div>
  `;

  // Toggle compare
  const tgl = root.querySelector('#toggleCompare');
  if (tgl) tgl.addEventListener('click', ()=>{ compareEnabled = !compareEnabled; renderProjections(root); });

  // Edge filter
  root.querySelectorAll('[data-edge]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      edgeFilter = btn.getAttribute('data-edge');
      currentPage = 1;
      updateTable();
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
    local.addEventListener('input', debounce(()=>{ currentQuery = local.value; currentPage = 1; if(g) g.value = currentQuery; updateTable(); syncHash(); }, 150));
  }
  root.querySelectorAll('[data-chip]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const chip = btn.getAttribute('data-chip');
      const has = currentQuery.includes(chip);
      currentQuery = has ? currentQuery.replace(chip,'').replace(/\s{2,}/g,' ').trim() : (currentQuery ? `${currentQuery} ${chip}` : chip);
      currentPage = 1;
      if(local) local.value = currentQuery;
      if(g) g.value = currentQuery;
      updateTable(); syncHash();
    });
  });

  let sortKey = 'projected_points', sortDir = -1;
  root.querySelectorAll('th[data-sort]').forEach(th=>{
    th.style.cursor = 'pointer';
    const triggerSort = ()=>{
      const k = th.getAttribute('data-sort');
      if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = k==='player_name' ? 1 : -1; }
      currentPage = 1;
      updateTable();
    };
    th.addEventListener('click', triggerSort);
    th.addEventListener('keydown', e=>{ if(e.key === 'Enter' || e.key === ' ') { e.preventDefault(); triggerSort(); }});
  });

  function filteredWithEdge(base) {
    let rows = filterPlayers(base, currentQuery);
    if (compareEnabled && hasComparison && edgeFilter !== 'ALL') {
      rows = rows.filter(p => (p.edge || 'NEUTRAL') === edgeFilter);
    }
    return rows;
  }

  function updateTable() {
    let rows = filteredWithEdge(allPlayers);
    // sort
    rows = [...rows].sort((a,b)=>{
      const av = a[sortKey] ?? a.point_estimate ?? (a[sortKey]==='market_points' ? -1 : '');
      const bv = b[sortKey] ?? b.point_estimate ?? (b[sortKey]==='market_points' ? -1 : '');
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
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
        const low = Number(p.projection_lower ?? p.lower_bound ?? proj - (p.width ?? 5)/2);
        const high = Number(p.projection_upper ?? p.upper_bound ?? proj + (p.width ?? 5)/2);
        const width = Number(p.width ?? p.projection_width ?? (high - low));
        const market = p.market_points != null ? Number(p.market_points).toFixed(1) : '—';
        const ecr = p.fp_ecr != null ? `#${p.fp_ecr}${p.fp_ecr_pos ? ` (#${p.fp_ecr_pos} ${pos})` : ''}${p.fp_tier ? ` <span style="background:var(--violet-dim); color:var(--violet); border:1px solid rgba(168,85,247,0.18); border-radius:999px; padding:1px 5px; font:700 10px 'JetBrains Mono',monospace">T${p.fp_tier}</span>` : ''}` : '—';
        const adp = p.fp_adp != null ? `#${p.fp_adp}` : '—';
        const edgeCell = compareEnabled && hasComparison ? edgeBadge(p.edge) : '';
        const rowAccent = p.edge === 'BUY' ? 'var(--emerald)' : p.edge === 'SELL' ? 'var(--crimson)' : getTeamColor(p.team);
        const expandBtn = compareEnabled && hasComparison ? `<button class="chip" data-expand="${p.player_id}" aria-label="Show stat deltas for ${escapeHtml(p.player_name)}" style="padding:4px 8px; font-size:11px">▶</button>` : '';
        const mainRow = `
          <tr data-team="${p.team || ''}" data-pid="${p.player_id}" style="--team-accent:${rowAccent}; ${p.edge==='BUY' ? 'background:rgba(16,185,129,0.04)' : p.edge==='SELL' ? 'background:rgba(239,68,68,0.04)' : ''}">
            <td><div class="player-cell">${playerAvatar(p, 32)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name || p.player_id)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '—')} ${p.model_pos_rank ? `<span style="color:var(--text-faint)">· #${p.model_pos_rank} ${pos}</span>` : ''}</div></div></div></td>
            <td>${posBadge(pos)}</td>
            <td class="mono" style="font-size:12px">${escapeHtml(p.team || '—')}</td>
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
            <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.04)">
              <span class="mono" style="font-size:11px; color:var(--text-muted); min-width:64px">${s.label}</span>
              ${statDeltaBar(s.model, s.market, s.delta)}
            </div>
          `).join('');
          const opp = p.opponent_team ? `vs ${p.opponent_team}` : '';
          return mainRow + `<tr class="expand-panel" data-expand-panel="${p.player_id}" style="display:none; background:var(--surface-raised)"><td colspan="${colSpan}" style="padding:12px 12px 12px 48px"><div style="display:flex; flex-direction:column; gap:6px"><div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap"><span class="kicker">Stat deltas — Model vs Market</span><span class="mono" style="font-size:11px; color:var(--text-faint)">${escapeHtml(p.player_name)} ${opp} · <span style="color:var(--amber)">amber=Model</span> <span style="color:var(--sky)">· blue=Market</span></span></div>${statRows || `<span class="mono" style="font-size:11px; color:var(--text-faint)">No market stats for this player yet (preseason).</span>`}<div class="mono" style="font-size:11px; color:var(--text-faint); margin-top:6px">FP ECR #${p.fp_ecr ?? '—'} ${p.fp_ecr_pos ? `(pos #${p.fp_ecr_pos})` : ''} · ADP #${p.fp_adp ?? '—'} · Model #${p.model_overall_rank ?? '—'} (pos #${p.model_pos_rank ?? '—'}) · ΔRk ${p.delta_rank != null ? (p.delta_rank > 0 ? '+' : '')+p.delta_rank : '—'}</div></div></td></tr>`;
        }
        return mainRow;
      }).join('');
      // bind expand toggles
      tbody.querySelectorAll('[data-expand]').forEach(btn=>{
        btn.addEventListener('click', ()=>{
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
        const marketLine = p.market_points != null ? `Market ${Number(p.market_points).toFixed(1)} · <span style="color:${Number(p.delta_points) > 0.5 ? 'var(--emerald)' : Number(p.delta_points) < -0.5 ? 'var(--crimson)' : 'var(--text-muted)'}">${p.delta_points > 0 ? '+' : ''}${Number(p.delta_points).toFixed(1)}</span>` : `Market —`;
        const rankLine = p.fp_ecr ? `ECR #${p.fp_ecr} · Δ ${p.delta_rank != null ? (p.delta_rank>0?'+':'')+p.delta_rank : '—'}` : 'ECR —';
        const edgeHtml = edgeBadge(p.edge);
        // Insert before closing card div
        return baseCard.replace('</div>\n', `  <div style="margin-top:8px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding-top:8px; border-top:1px solid var(--border)"><span class="mono" style="font-size:11px; color:var(--text-muted)">${marketLine}</span><span class="mono" style="font-size:11px; color:var(--text-muted)">${rankLine}</span><span class="spacer"></span>${edgeHtml}</div></div>\n`);
      }).join('');
    }

    // Render pagination controls
    const pag = root.querySelector('#paginationControls');
    if (pag) {
      if (totalPages <= 1) {
        pag.innerHTML = '';
      } else {
        pag.innerHTML = `
          <div style="font:400 13px 'Fira Sans',sans-serif; color:var(--text-muted)">
            Page <strong>${currentPage}</strong> of <strong>${totalPages}</strong>
          </div>
          <div style="display:flex; gap:6px">
            <button class="chip" id="firstPageBtn" ${currentPage === 1 ? 'disabled style="opacity:0.4; cursor:not-allowed"' : ''}>« First</button>
            <button class="chip" id="prevPageBtn" ${currentPage === 1 ? 'disabled style="opacity:0.4; cursor:not-allowed"' : ''}>‹ Prev</button>
            <button class="chip" id="nextPageBtn" ${currentPage === totalPages ? 'disabled style="opacity:0.4; cursor:not-allowed"' : ''}>Next ›</button>
            <button class="chip" id="lastPageBtn" ${currentPage === totalPages ? 'disabled style="opacity:0.4; cursor:not-allowed"' : ''}>Last »</button>
          </div>
        `;
        pag.querySelector('#firstPageBtn')?.addEventListener('click', ()=>{ if (currentPage > 1) { currentPage = 1; updateTable(); } });
        pag.querySelector('#prevPageBtn')?.addEventListener('click', ()=>{ if (currentPage > 1) { currentPage--; updateTable(); } });
        pag.querySelector('#nextPageBtn')?.addEventListener('click', ()=>{ if (currentPage < totalPages) { currentPage++; updateTable(); } });
        pag.querySelector('#lastPageBtn')?.addEventListener('click', ()=>{ if (currentPage < totalPages) { currentPage = totalPages; updateTable(); } });
      }
    }
  }

  function syncHash(){
    const base = 'projections';
    location.hash = currentQuery ? `${base}?q=${encodeURIComponent(currentQuery)}` : base;
  }

  updateTable();
}

function debounce(fn, ms=150){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a), ms); }; }
function escapeHtml(s){ return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'); }
