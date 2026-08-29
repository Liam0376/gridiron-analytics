import { fetchProjections } from '../api.js';
import { filterPlayers } from '../search.js';
import { posBadge, injuryBadge, windBadge, confBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';

let allPlayers = [];
let currentQuery = '';

export async function renderProjections(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  currentQuery = params.get('q') || document.getElementById('globalSearch')?.value || '';

  const data = await fetchProjections({});
  allPlayers = data.players || [];
  const meta = data.meta || {};

  // sync global search
  const g = document.getElementById('globalSearch');
  if (g && !g.dataset.bound) {
    g.dataset.bound = '1';
    g.addEventListener('input', debounce(()=>{ currentQuery = g.value; updateTable(); syncHash(); }, 150));
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

    <div class="table-wrap sticky-player reveal in" style="margin-top:16px">
      <table id="projTable">
        <thead>
          <tr>
            <th data-sort="player_name">Player</th>
            <th data-sort="position">Pos</th>
            <th data-sort="team">Team</th>
            <th data-sort="opponent_team">Opp</th>
            <th data-sort="projected_points">Proj</th>
            <th>Interval</th>
            <th data-sort="wind_mph">Wind</th>
            <th data-sort="width">Conf</th>
            <th>Injury</th>
          </tr>
        </thead>
        <tbody id="projBody"></tbody>
      </table>
    </div>
  `;

  const local = root.querySelector('#localSearch');
  if (local) {
    local.value = currentQuery;
    local.addEventListener('input', debounce(()=>{ currentQuery = local.value; if(g) g.value = currentQuery; updateTable(); syncHash(); }, 150));
  }
  root.querySelectorAll('[data-chip]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const chip = btn.getAttribute('data-chip');
      const has = currentQuery.includes(chip);
      currentQuery = has ? currentQuery.replace(chip,'').replace(/\s{2,}/g,' ').trim() : (currentQuery ? `${currentQuery} ${chip}` : chip);
      if(local) local.value = currentQuery;
      if(g) g.value = currentQuery;
      updateTable(); syncHash();
    });
  });

  let sortKey = 'projected_points', sortDir = -1;
  root.querySelectorAll('th[data-sort]').forEach(th=>{
    th.style.cursor = 'pointer';
    th.addEventListener('click', ()=>{
      const k = th.getAttribute('data-sort');
      if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = k==='player_name' ? 1 : -1; }
      updateTable();
    });
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
    const countLabel = root.querySelector('#countLabel');
    if (countLabel) countLabel.textContent = `${rows.length} / ${allPlayers.length} players`;
    const tbody = root.querySelector('#projBody');
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="9"><div class="empty">No matches for <code class="inline">${escapeHtml(currentQuery || '—')}</code>. Try <code class="inline">pos:WR</code> or clear filters.</div></td></tr>`;
      return;
    }
    tbody.innerHTML = rows.slice(0,300).map(p=>{
      const pos = p.position || p.position_group || 'UNK';
      const proj = Number(p.projected_points ?? p.point_estimate ?? 0);
      const low = Number(p.projection_lower ?? p.lower_bound ?? proj - (p.width ?? 5)/2);
      const high = Number(p.projection_upper ?? p.upper_bound ?? proj + (p.width ?? 5)/2);
      const width = Number(p.width ?? p.projection_width ?? (high - low));
      return `
        <tr>
          <td><strong>${escapeHtml(p.player_name || p.player_id)}</strong><div class="micro faint">${escapeHtml(p.player_id || '')}</div></td>
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

  function syncHash(){
    const base = 'projections';
    location.hash = currentQuery ? `${base}?q=${encodeURIComponent(currentQuery)}` : base;
  }

  updateTable();
}

function debounce(fn, ms=150){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a), ms); }; }
function escapeHtml(s){ return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'); }
