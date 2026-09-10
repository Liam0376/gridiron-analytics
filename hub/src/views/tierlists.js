import { fetchProjections, fetchComparison } from '../api.js';
import { buildTiers } from '../tierlist.js';
import { posBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { escapeHtml } from '../lib/escape.js';
import { openPlayerModal } from '../components/playerModal.js';
import { backupDemote, buildAheadMap } from '../lib/relevance.js';

const POSITIONS = ['QB','RB','WR','TE','FLEX'];

export async function renderTierlists(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const pos = (params.get('pos') || 'WR').toUpperCase();
  const gap = Number(params.get('gap') || 2.0);
  const cap = Number(params.get('cap') || 6);
  const view = (params.get('view') || 'week').toLowerCase(); // week | season

  const [data, compData] = await Promise.all([
    fetchProjections({}), fetchComparison({ limit: 2000 }).catch(() => ({ players: [] })),
  ]);
  let players = data.players || [];
  // why merge (user-caught live bug, 2026-09-10): without this, opening a
  // player card here fell to playerModal.js's $1/0 honest-empty floor
  // instead of the real season-stat/auction data that already exists —
  // same fix as projections.js (93b7b91/d910ac1).
  const compById = new Map((compData.players || []).map(c => [String(c.player_id), c]));
  for (const p of players) {
    const c = compById.get(String(p.player_id));
    if (c) {
      p.market_season_stats = c.market_season_stats || null;
      p.auction = c.auction;
      p.gridironAuction = c.auction;
      p.marketAuction = c.marketAuction;
      p.vor = c.vor;
    }
  }

  // Season view: ROS = weekly × remaining weeks (week 10 → 9 games left incl. week 10 to 18)
  // Uses live 2026 schedule week from meta (preseason 0 → assume week 10 for demo)
  if (view === 'season') {
    const remaining = 9; // weeks 10-18 inclusive
    players = players.map(p => ({
      ...p,
      projected_points: Number(p.projected_points ?? 0) * remaining,
      point_estimate: Number(p.point_estimate ?? 0) * remaining,
      projection_lower: Number(p.projection_lower ?? p.lower_bound ?? 0) * remaining,
      projection_upper: Number(p.projection_upper ?? p.upper_bound ?? 0) * remaining,
      width: Number(p.width ?? 5) * Math.sqrt(remaining), // variance scales sqrt(n)
      ros_weeks: remaining,
    }));
  }

  // FLEX = RB/WR/TE only
  if (pos === 'FLEX') players = players.filter(p => ['RB','WR','TE'].includes((p.position||p.position_group||'').toUpperCase()));
  else players = players.filter(p => (p.position||p.position_group||'').toUpperCase() === pos);

  const tiers = buildTiers(players, { gap, cap });
  // why member-order only (user decision 2026-09-10): tier cuts are math
  // (gap/cap on point estimates) and stay untouched — but within a tier, a
  // healthy backup lists after genuine options. Display order only.
  const aheadMap = buildAheadMap(players);
  const ptsOf = (p) => Number(p.projected_points ?? p.point_estimate ?? 0) || 0;
  for (const tier of tiers) {
    tier.sort((a, b) => (backupDemote(a, {}, aheadMap) - backupDemote(b, {}, aheadMap)) || (ptsOf(b) - ptsOf(a)));
  }

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Tiers <span class="badge" style="background:var(--color-primary); color:white; margin-left:8px; vertical-align:middle">${view==='season' ? 'SEASON ROS' : 'WEEK 10'}</span></h1>
      <p>Deterministic tiers by point estimate.</p>
      <details style="margin-top:8px" aria-label="How tiering works">
        <summary style="cursor:pointer; font-weight:600" title="Toggle tiering explainer">How tiering works</summary>
        <p style="margin-top:8px">Deterministic: sorted by <code class="inline">point_estimate</code> then cut when gap &gt; <code class="inline">max(${gap}, 0.7×median width)</code> or tier hits <code class="inline">cap=${cap}</code>. No LLM. <strong>Week</strong> = next game (star-aware ±${view==='season'?'~15-35':'~6-10'}). <strong>Season</strong> = ROS ` + (view==='season' ? `9 games (weeks 10-18) × weekly, width ×√9` : `weekly`) + `: switch to <strong>FLEX</strong> for your 2-FLEX board (RB/WR/TE <code class="inline">×1.05</code>).</p>
      </details>
    </div>
    <div class="card reveal in" style="margin-top:12px">
      <div class="card-body row">
        <div class="filters">
          <button class="chip ${view==='week'?'active':''}" data-view="week">Week</button>
          <button class="chip ${view==='season'?'active':''}" data-view="season">Season ROS</button>
          <span class="divider" style="width:1px; height:24px; background:var(--border); margin:0 4px"></span>
          ${POSITIONS.map(p=>`<button class="chip ${p===pos?'active':''}" data-pos="${p}">${p}</button>`).join('')}
        </div>
        <div class="spacer"></div>
        <label class="faint" style="font:500 12px "Helvetica Neue", Helvetica, sans-serif">gap <input id="gapInput" type="number" step="0.5" min="0.5" max="6" value="${gap}" style="width:64px; background:var(--surface-raised); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:6px 8px; margin-left:6px"></label>
        <label class="faint" style="font:500 12px "Helvetica Neue", Helvetica, sans-serif; margin-left:8px">cap <input id="capInput" type="number" step="1" min="3" max="12" value="${cap}" style="width:64px; background:var(--surface-raised); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:6px 8px; margin-left:6px"></label>
        <button class="btn btn-ghost btn-sm" id="copyMd" title="Copy tiers as markdown">Copy markdown</button>
      </div>
    </div>

    ${!players.length ? `<div class="card reveal in" style="margin-top:16px"><div class="empty">No players for <strong>${pos}</strong> yet. Refresh in-season or check <code class="inline">Projections</code>: tiering needs <code class="inline">projected_points</code>.</div></div>` :
      `<div style="margin-top:16px; display:flex; flex-direction:column; gap:12px">
        ${tiers.map((tier, idx)=>{
          const pts = tier.map(p=>Number(p.projected_points ?? p.point_estimate ?? 0) || 0);
          const hi = Math.max(...pts), lo = Math.min(...pts);
          return `
          <div class="tier reveal in">
            <div class="tier-head"><strong style="color:${tierColor(idx)}">Tier ${idx+1}</strong><span class="micro faint">${tier.length} players · ${hi.toFixed(1)} → ${lo.toFixed(1)} pts</span></div>
            <div class="tier-body">
              ${tier.map(p=>`
                <div class="player-card" data-pid="${escapeHtml(p.player_id || '')}" style="--team-accent:${getTeamColor((p.team||'').toUpperCase())}; border-top:1px solid var(--team-accent); background:linear-gradient(90deg, color-mix(in srgb, var(--team-accent) 7%, var(--surface-raised)) 0%, var(--surface-raised) 50%); cursor:pointer">
                  <div class="row" style="gap:8px">${playerAvatar(p, 28)} <div style="flex:1; min-width:0"><div class="row" style="gap:6px">${posBadge(p.position || p.position_group)} <span class="name">${escapeHtml(p.player_name || p.player_id)}</span></div><div class="meta">${teamLogo(p.team, 14)} ${escapeHtml(p.team||'—')} vs ${escapeHtml(p.opponent_team||'—')} · ${p.wind_mph ? `${Number(p.wind_mph).toFixed(0)} mph` : '—'}</div></div></div>
                  <div class="pts">${Number(p.projected_points ?? p.point_estimate ?? 0).toFixed(1)} <span style="font:500 11px ui-monospace, SFMono-Regular, monospace; color:var(--text-muted)">±${Number(p.width ?? 5).toFixed(1)}</span></div>
                </div>
              `).join('')}
            </div>
          </div>
        `}).join('')}
       </div>`
    }
  `;

  root.querySelectorAll('[data-pid]').forEach(el => {
    el.addEventListener('click', () => {
      const pid = el.getAttribute('data-pid');
      const found = players.find(p => String(p.player_id) === String(pid));
      if (found) openPlayerModal(found, root);
    });
  });

  root.querySelectorAll('[data-pos]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const p = btn.getAttribute('data-pos');
      location.hash = `tierlists?pos=${p}&gap=${gap}&cap=${cap}&view=${view}`;
    });
  });
  root.querySelectorAll('[data-view]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const v = btn.getAttribute('data-view');
      location.hash = `tierlists?pos=${pos}&gap=${gap}&cap=${cap}&view=${v}`;
    });
  });
  const gapInput = root.querySelector('#gapInput');
  const capInput = root.querySelector('#capInput');
  function sync(){ location.hash = `tierlists?pos=${pos}&gap=${Number(gapInput.value)||2}&cap=${Number(capInput.value)||6}&view=${view}`; }
  gapInput?.addEventListener('change', sync);
  capInput?.addEventListener('change', sync);
  root.querySelector('#copyMd')?.addEventListener('click', ()=>{
    const md = tiers.map((t,i)=>`### Tier ${i+1}\n` + t.map(p=>`- ${p.player_name || p.player_id} (${p.position || p.position_group}) - ${Number(p.projected_points ?? 0).toFixed(1)} pts`).join('\n')).join('\n\n');
    navigator.clipboard.writeText(md || 'No tiers yet');
    const btn = root.querySelector('#copyMd');
    if(btn){ btn.textContent='Copied'; setTimeout(()=>btn.textContent='Copy markdown', 1200); }
  });
}

function tierColor(i){ const cols=['var(--amber)','var(--sky)','var(--emerald)','var(--violet)','var(--pos-k)','var(--pos-def)']; return cols[i % cols.length]; }
