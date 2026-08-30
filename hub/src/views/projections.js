import { fetchProjections } from '../api.js';
import { filterPlayers } from '../search.js';
import { posBadge, injuryBadge, windBadge, confBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { playerCard } from '../components/playerCard.js';
import { getTeamColor } from '../components/teamColors.js';

let allPlayers = [];
let currentQuery = '';
let currentPage = 1;
const PAGE_SIZE = 50;

export async function renderProjections(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  currentQuery = params.get('q') || document.getElementById('globalSearch')?.value || '';
  currentPage = 1;

  const data = await fetchProjections({});
  allPlayers = data.players || [];
  const meta = data.meta || {};

  // sync global search
  const g = document.getElementById('globalSearch');
  if (g && !g.dataset.bound) {
    g.dataset.bound = '1';
    g.addEventListener('input', debounce(()=>{ currentQuery = g.value; currentPage = 1; updateTable(); syncHash(); }, 150));
    g.addEventListener('keydown', e=>{ if(e.key==='/' && document.activeElement!==g){ e.preventDefault(); g.focus(); }});
  }
  if (g) g.value = currentQuery;

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Projections</h1>
      <p>Searchable, sortable source of truth. <span class="mono" style="color:var(--amber)">Point</span> is <code class="inline">calculate_projection</code> + <code class="inline">FLEX ×1.05</code> + <code class="inline">wind&gt;15 → −0.02/mph (QB/WR/K)</code>. Bar shows estimated range (conformal-seeded, position &amp; star-scaled — not a formal 80% guarantee). Overlapping bars = toss-up.</p>
    </div>

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
    <div class="table-wrap sticky-player reveal in" style="margin-top:16px">
      <table id="projTable">
        <thead>
          <tr>
            <th data-sort="player_name" tabindex="0" role="button" aria-label="Sort by Player">Player</th>
            <th data-sort="position" tabindex="0" role="button" aria-label="Sort by Position">Pos</th>
            <th data-sort="team" tabindex="0" role="button" aria-label="Sort by Team">Team</th>
            <th data-sort="opponent_team" tabindex="0" role="button" aria-label="Sort by Opponent">Opp</th>
            <th data-sort="projected_points" tabindex="0" role="button" aria-label="Sort by Projected Points">Proj</th>
            <th>Interval</th>
            <th data-sort="wind_mph" tabindex="0" role="button" aria-label="Sort by Wind Speed">Wind</th>
            <th data-sort="width" tabindex="0" role="button" aria-label="Sort by Confidence Width">Conf</th>
            <th>Injury</th>
          </tr>
        </thead>
        <tbody id="projBody"></tbody>
      </table>
    </div>
    <div class="player-cards-grid" id="projCards"></div>
    </div>
    <div id="paginationControls" style="display:flex; justify:space-between; align-items:center; margin-top:16px; flex-wrap:wrap; gap:8px"></div>
  `;

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

  function updateTable() {
    let rows = filterPlayers(allPlayers, currentQuery);
    // sort
    rows = [...rows].sort((a,b)=>{
      const av = a[sortKey] ?? a.point_estimate ?? '';
      const bv = b[sortKey] ?? b.point_estimate ?? '';
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
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
        countLabel.textContent = `Showing ${startIndex + 1}–${endIndex} of ${totalCount} players${totalCount !== allPlayers.length ? ` (filtered from ${allPlayers.length})` : ''}`;
      }
    }

    const tbody = root.querySelector('#projBody');
    if (!pagedRows.length) {
      tbody.innerHTML = `<tr><td colspan="9"><div class="empty">No matches for <code class="inline">${escapeHtml(currentQuery || '—')}</code>. Try <code class="inline">pos:WR</code> or clear filters.</div></td></tr>`;
    } else {
      tbody.innerHTML = pagedRows.map(p=>{
        const pos = p.position || p.position_group || 'UNK';
        const proj = Number(p.projected_points ?? p.point_estimate ?? 0);
        const low = Number(p.projection_lower ?? p.lower_bound ?? proj - (p.width ?? 5)/2);
        const high = Number(p.projection_upper ?? p.upper_bound ?? proj + (p.width ?? 5)/2);
        const width = Number(p.width ?? p.projection_width ?? (high - low));
        return `
          <tr data-team="${p.team || ''}" style="--team-accent:${getTeamColor(p.team)}">
            <td><div class="player-cell">${playerAvatar(p, 32)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name || p.player_id)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '—')}</div></div></div></td>
            <td>${posBadge(pos)}</td>
            <td class="mono" style="font-size:12px">${escapeHtml(p.team || '—')}</td>
            <td class="mono" style="font-size:12px">${escapeHtml(p.opponent_team || '—')}</td>
            <td class="mono">${proj.toFixed(1)}</td>
            <td>${intervalBar({ point: proj, low, high, width, min: 0, max: 35 })}</td>
            <td>${windBadge(p.wind_mph)}</td>
            <td>${confBadge(width)}</td>
            <td>${injuryBadge(p.injury_status)} ${p.trending ? `<span class="badge" style="background:var(--sky-dim); color:var(--sky); margin-left:6px">↗ trending</span>`:''}</td>
          </tr>
        `;
      }).join('');
    }

    const cardsGrid = root.querySelector('#projCards');
    if (cardsGrid) {
      cardsGrid.innerHTML = pagedRows.map(p => playerCard(p, { showInterval: true, showTeamLogo: true })).join('');
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
