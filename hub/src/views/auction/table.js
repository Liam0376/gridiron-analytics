// hub/src/views/auction/table.js — auction board table + cards + modals + sorting.
// Receives already-computed `allRanked`, `filteredPlayers`, view-state and returns DOM nodes / HTML.

import { posBadge } from '../../components/badges.js';
import { playerAvatar } from '../../components/playerAvatar.js';
import { teamLogo } from '../../components/teamLogo.js';
import { playerCard } from '../../components/playerCard.js';
import { getTeamColor } from '../../components/teamColors.js';
import { edgeBadgeAuction, deltaSeasonBadge } from '../../lib/auctionMath.js';
import { saveDraftState } from './state.js';
import { trapFocus } from '../../lib/focusTrap.js';
import { escapeHtml, escapeAttr } from '../../lib/escape.js';
import { openPlayerModal } from '../../components/playerModal.js';

const ALLOWED_SORT = new Set([
  'player_name','position','weekly','ros','marketRos','deltaRos',
  'fp_ecr','fp_adp','statsguy_rank','vor','auction','marketAuction',
  'deltaAuction','edge_score','tier',
]);

export function parseSort(params) {
  const sortKey = ALLOWED_SORT.has(params.get('sort')) ? params.get('sort') : 'auction';
  const sortDir = params.get('dir') === '1' ? 1 : -1;
  return { sortKey, sortDir };
}

export function sortPlayers(list, sortKey, sortDir) {
  return [...list].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
    if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * sortDir;
    return String(av).localeCompare(String(bv)) * sortDir;
  });
}

// Build the sortable <th> HTML with aria-sort reflecting current sort state.
function ariaFor(key, sortKey, sortDir) {
  if (sortKey !== key) return 'none';
  return sortDir === -1 ? 'descending' : 'ascending';
}

function sortableTh(key, label, sortKey, sortDir, extraStyle = '') {
  const arrow = sortKey === key ? (sortDir === -1 ? '▼' : '▲') : '↕';
  const aria = ariaFor(key, sortKey, sortDir);
  return `<th data-sort="${key}" tabindex="0" role="button" aria-label="Sort by ${label}" aria-sort="${aria}" style="cursor:pointer${extraStyle ? ';' + extraStyle : ''}">${label} ${arrow}</th>`;
}

// Build full table headers (Model only vs with comparison toggle).
export function tableHeaders(showCompare, sortKey, sortDir) {
  const compareHeaders = showCompare ? `
    ${sortableTh('weekly', 'Model Wk', sortKey, sortDir, 'color:var(--amber); border-bottom:2px solid var(--amber)')}
    ${sortableTh('ros', 'Model Season (17g)', sortKey, sortDir, 'color:var(--amber); border-bottom:2px solid var(--amber)')}
    ${sortableTh('marketRos', 'Market Season (17g)', sortKey, sortDir, 'color:var(--sky); border-bottom:2px solid var(--sky)')}
    ${sortableTh('deltaRos', 'Season Δ', sortKey, sortDir, 'border-bottom:2px solid var(--border)')}
    ${sortableTh('fp_ecr', 'ECR', sortKey, sortDir)}
    ${sortableTh('fp_adp', 'ADP', sortKey, sortDir)}
    ${sortableTh('statsguy_rank', 'StatsGuy', sortKey, sortDir, 'color:var(--violet)')}
  ` : `
    ${sortableTh('weekly', 'Model Wk', sortKey, sortDir)}
    ${sortableTh('ros', 'Season (17g)', sortKey, sortDir)}
  `;

  const marketCols = showCompare ? `
    ${sortableTh('marketAuction', 'Market $', sortKey, sortDir, 'color:var(--sky)')}
    ${sortableTh('deltaAuction', 'Δ $', sortKey, sortDir)}
    ${sortableTh('edge_score', 'Edge', sortKey, sortDir)}
  ` : '';

  return `
    <th style="width:32px">#</th>
    ${sortableTh('player_name', 'Player', sortKey, sortDir)}
    ${sortableTh('position', 'Pos', sortKey, sortDir)}
    ${compareHeaders}
    ${sortableTh('vor', 'VOR', sortKey, sortDir)}
    ${sortableTh('auction', 'Model $', sortKey, sortDir, 'color:var(--amber)')}
    ${marketCols}
    <th>Interval</th>
    ${sortableTh('tier', 'T', sortKey, sortDir)}
    <th>Draft</th>
  `;
}

// Render the table body (top 120) + mobile card grid.
export function tableBody(filteredPlayers, showCompare, escapeHtml) {
  const rows = filteredPlayers.slice(0, 120).map((p, i) => `
    <tr style="${p.isDrafted ? 'opacity:0.35; text-decoration:line-through' : ''};--team-accent:${getTeamColor((p.team || '').toUpperCase())}; ${p.edge === 'BUY' ? 'background:rgba(16,185,129,0.06)' : p.edge === 'SELL' ? 'background:rgba(239,68,68,0.06)' : ''}" data-pid="${p.player_id}" data-team="${p.team || ''}">
      <td class="mono-muted" style="font-size:11px">${i + 1}</td>
      <td>
        <div class="player-cell">${playerAvatar(p, 28)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '')}${p.opponent_team ? ' vs ' + escapeHtml(p.opponent_team) : ''}</div></div></div>
      </td>
      <td>${posBadge(p.position)}</td>
      <td class="mono" style="color:var(--amber)">${p.weekly.toFixed(1)}</td>
      <td class="mono" style="font-weight:700">${p.ros.toFixed(0)}</td>
      ${showCompare ? `
        <td class="mono" style="color:var(--sky)">${p.marketRos != null ? p.marketRos.toFixed(0) : '—'}</td>
        <td>${deltaSeasonBadge(p.deltaRos)}</td>
        <td class="mono" style="font-size:11px; color:var(--text-muted)">${p.fp_ecr != null ? `#${p.fp_ecr}${p.fp_tier ? ` <span style="background:var(--violet-dim); color:var(--violet); border:1px solid rgba(168,85,247,0.18); border-radius:999px; padding:1px 5px; font:700 10px ui-monospace, SFMono-Regular,monospace">T${p.fp_tier}</span>` : ''}` : '—'}</td>
        <td class="mono" style="font-size:11px; color:var(--text-muted)">${p.fp_adp != null ? '#' + p.fp_adp : '—'}</td>
        <td class="mono" style="font-size:11px; color:var(--violet)">${p.statsguy_rank != null ? `#${p.statsguy_rank} <span style="color:var(--text-faint)">(${p.statsguy_value.toFixed(0)})</span>` : '—'}</td>
      ` : ''}
      <td class="mono" style="color:${p.vor > 30 ? '#10B981' : p.vor > 15 ? 'var(--amber)' : 'var(--text-muted)'}">+${p.vor.toFixed(0)}</td>
      <td><span class="badge" style="background:${p.auction >= 15 ? '#16A34A' : p.auction >= 5 ? 'var(--amber-dim)' : 'var(--surface-raised)'}; color:${p.auction >= 15 ? 'white' : p.auction >= 5 ? 'var(--amber)' : 'var(--text-muted)'}; border:1px solid ${p.auction >= 15 ? '#16A34A' : 'var(--border)'}">$${p.auction}</span></td>
      ${showCompare ? `<td class="mono" style="color:var(--sky)"><span class="badge" style="background:var(--sky-dim); color:var(--sky); border:1px solid rgba(56,189,248,0.2)">$${p.marketAuction}</span></td><td class="mono" style="font-weight:700; color:${p.deltaAuction > 4 ? 'var(--emerald)' : p.deltaAuction < -4 ? 'var(--crimson)' : 'var(--text-muted)'}">${p.deltaAuction > 0 ? '+' : ''}$${p.deltaAuction}</td>` : ''}
      ${showCompare ? `<td>${edgeBadgeAuction(p.edge)}</td>` : ''}
      <td class="mono-muted" style="font-size:11px">${(p.ros - p.widthRos).toFixed(0)}–${(p.ros + p.widthRos).toFixed(0)}</td>
      <td class="faint" style="font:600 11px Helvetica Neue, Helvetica,sans-serif">T${p.tier}</td>
      <td>
        <div style="display:flex; gap:4px; align-items:center">
          <button class="btn btn-ghost btn-sm focusBtn" data-pid="${p.player_id}" title="Focus for live advice" style="font-size:11px; padding:2px 6px">👁</button>
          ${p.isDrafted
            ? `<span class="micro faint">${p.draftedBy === 'me' ? 'Mine' : 'Taken'}${p.draftedPrice ? ' $' + p.draftedPrice : ''}</span>`
            : `<button class="btn btn-ghost btn-sm draftBtn" data-pid="${p.player_id}" data-name="${escapeHtml(p.player_name)}" data-val="${p.auction}" style="font-size:11px; padding:2px 8px">Draft</button>`
          }
        </div>
      </td>
    </tr>
  `).join('');

  const cards = filteredPlayers.filter(p => !p.isDrafted).slice(0, 50).map(p => {
    const base = playerCard(p, { showDraftBtn: true, showTeamLogo: true });
    if (!showCompare) return base;
    const seasonDelta = p.deltaRos != null
      ? `<span class="mono" style="font-size:10px; color:${Number(p.deltaRos) > 8 ? 'var(--emerald)' : Number(p.deltaRos) < -8 ? 'var(--crimson)' : 'var(--text-faint)'}">${Number(p.deltaRos) > 0 ? '+' : ''}${Number(p.deltaRos).toFixed(0)} season Δ</span>`
      : `<span class="mono" style="font-size:10px; color:var(--text-faint)">season Δ —</span>`;
    return base.replace(
      '</div>\\n',
      `  <div style="margin-top:8px; display:flex; gap:6px; align-items:center; flex-wrap:wrap; padding-top:8px; border-top:1px solid var(--border)"><button class="btn btn-ghost btn-sm focusBtn" data-pid="${p.player_id}" title="Focus for live advice" style="font-size:11px; padding:2px 6px">👁</button><span class="mono" style="font-size:10px; color:var(--text-muted)">Mkt ${p.marketRos != null ? p.marketRos.toFixed(0) : '—'}</span>${seasonDelta}<span class="spacer"></span>${edgeBadgeAuction(p.edge)}</div></div>\\n`
    );
  }).join('');

  return { rows, cards };
}

// Wire all table-area event handlers. Each one re-renders the view via `rerender`.
export function bindTableEvents(root, allRanked, filteredPlayers, showCompare, state, escapeHtml, rerender) {
  root.querySelector('#copyModelVsMarketCsv')?.addEventListener('click', () => {
    let list = filteredPlayers;
    if (showCompare) list = list.filter(p => (p.edge || 'NEUTRAL') !== 'NEUTRAL' || true);
    const rows = [['rank','player','pos','team','model_wk','model_season','market_season','season_delta','fp_ecr','fp_adp','vor','auction','edge']];
    list.slice(0, 150).forEach((p, i) => {
      rows.push([i + 1, `"${p.player_name}"`, p.position, p.team, p.weekly.toFixed(1), p.ros.toFixed(1), p.marketRos != null ? p.marketRos.toFixed(1) : '', p.deltaRos != null ? p.deltaRos.toFixed(1) : '', p.fp_ecr ?? '', p.fp_adp ?? '', p.vor.toFixed(1), p.auction, p.edge]);
    });
    const csv = rows.map(r => r.join(',')).join('\n');
    navigator.clipboard.writeText(csv);
    const b = root.querySelector('#copyModelVsMarketCsv');
    if (b) { const t = b.textContent; b.textContent = 'Copied'; setTimeout(() => b.textContent = t, 1200); }
  });

  // Sort header clicks
  root.querySelectorAll('[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.getAttribute('data-sort');
      const p = new URLSearchParams(location.hash.split('?')[1] || '');
      const curKey = p.get('sort') || 'auction';
      const curDir = p.get('dir') === '1' ? 1 : -1;
      let nextDir = -1;
      if (curKey === key) nextDir = curDir * -1;
      else nextDir = (key === 'player_name' ? 1 : -1);
      p.set('sort', key);
      p.set('dir', String(nextDir));
      location.hash = 'auction?' + p.toString();
    });
    th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); th.click(); } });
  });

  root.querySelector('#toggleSortDir')?.addEventListener('click', () => {
    const p = new URLSearchParams(location.hash.split('?')[1] || '');
    const curDir = p.get('dir') === '1' ? 1 : -1;
    p.set('sort', p.get('sort') || 'auction');
    p.set('dir', String(curDir * -1));
    location.hash = 'auction?' + p.toString();
  });

  // Draft buttons (rows + cards)
  root.querySelectorAll('.draftBtn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pid = btn.dataset.pid;
      const name = btn.dataset.name;
      const suggestedVal = btn.dataset.val;
      showDraftModal(root, pid, name, suggestedVal, state, allRanked, escapeHtml, rerender);
    });
  });

  // Focus buttons
  root.querySelectorAll('.focusBtn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pid = btn.dataset.pid;
      const p = new URLSearchParams(location.hash.split('?')[1] || '');
      p.set('focus', pid);
      location.hash = 'auction?' + p.toString();
    });
  });

  // Player cell click → modal
  root.querySelectorAll('.player-cell, [data-pid]').forEach(el => {
    if (el.classList.contains('draftBtn')) return;
    el.style.cursor = 'pointer';
    el.title = 'Open Draftea-style player details';
    el.addEventListener('click', (e) => {
      if (e.target.closest('.draftBtn')) return;
      const tr = el.closest('[data-pid]') || el;
      const pid = tr?.dataset.pid || tr?.getAttribute('data-pid');
      if (!pid) return;
      const pl = allRanked.find(p => String(p.player_id) === String(pid));
      if (pl) openPlayerModal(pl, root);
    });
  });

  // Copy CSV (full board)
  root.querySelector('#copyAuction')?.addEventListener('click', () => {
    let list = filteredPlayers;
    const csvPlayers = list.filter(p => !p.isDrafted);
    const csv = ['rank,player,pos,team,weekly,ros,vor,auction,market_season,season_delta,fp_ecr,fp_adp,edge,interval,tier']
      .concat(csvPlayers.slice(0, 120).map((p, i) =>
        `${i + 1},"${p.player_name}",${p.position},${p.team},${p.weekly.toFixed(1)},${p.ros.toFixed(1)},${p.vor.toFixed(1)},${p.auction},${p.marketRos != null ? p.marketRos.toFixed(0) : ''},${p.deltaRos != null ? p.deltaRos.toFixed(0) : ''},${p.fp_ecr ?? ''},${p.fp_adp ?? ''},${p.edge},${(p.ros - p.widthRos).toFixed(0)}-${(p.ros + p.widthRos).toFixed(0)},T${p.tier}`
      )).join('\n');
    navigator.clipboard.writeText(csv);
    const b = root.querySelector('#copyAuction');
    if (b) { b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy CSV', 1200); }
  });
}

// Draft modal — ME/Other toggle + price input. Updates state.drafted + state.myRoster.
export function showDraftModal(root, pid, name, suggestedVal, state, allRanked, escapeHtml, rerender) {
  const existing = root.querySelector('#draftModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'draftModal';
  modal.style.cssText = 'position:fixed; inset:0; z-index:1000; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.6)';
  modal.innerHTML = `
    <div style="background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; min-width:300px; max-width:400px">
      <h3 style="margin:0 0 16px 0">${escapeHtml(name)}</h3>
      <div style="margin-bottom:12px">
        <label style="font:500 13px Helvetica Neue, Helvetica,sans-serif; color:var(--text-muted)">Price paid</label>
        <input type="number" id="draftPrice" value="${suggestedVal}" min="1" max="200" style="width:100%; background:var(--surface-raised); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:8px; font-size:16px; margin-top:4px">
      </div>
      <div style="margin-bottom:16px">
        <label style="font:500 13px Helvetica Neue, Helvetica,sans-serif; color:var(--text-muted)">Who got them?</label>
        <div style="display:flex; gap:8px; margin-top:8px">
          <button class="btn btn-sm draftWho" data-who="me" style="flex:1; background:var(--color-accent); color:white">Me</button>
          <button class="btn btn-sm btn-ghost draftWho" data-who="other" style="flex:1">Other team</button>
        </div>
      </div>
      <div style="display:flex; gap:8px; justify-content:flex-end">
        <button class="btn btn-ghost btn-sm" id="draftCancel">Cancel</button>
      </div>
    </div>
  `;
  root.appendChild(modal);

  modal.querySelector('#draftCancel').addEventListener('click', () => modal.remove());
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

  modal.querySelectorAll('.draftWho').forEach(btn => {
    btn.addEventListener('click', () => {
      const who = btn.dataset.who;
      const price = Number(modal.querySelector('#draftPrice').value) || 1;
      state.drafted[pid] = { by: who, price };
      if (who === 'me' && !state.myRoster.includes(pid)) state.myRoster.push(pid);
      saveDraftState(state);
      modal.remove();
      rerender();
    });
  });
}