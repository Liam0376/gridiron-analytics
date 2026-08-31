// hub/src/views/team.js — Team Hub Data-Dense Dashboard
import { fetchRoster, fetchComparison } from '../api.js';
import { getSelectedTeamId, setSelectedTeamId, renderTeamSelector, bindTeamSelector } from '../components/teamSelector.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';

let modalPlayer = null;

export async function renderTeam(root) {
  const selectedId = getSelectedTeamId();

  // Load roster data and market comparison concurrently
  const [rosterData, compData] = await Promise.all([
    fetchRoster({ roster_id: selectedId }),
    fetchComparison({ limit: 800 }).catch(() => ({ players: [] })),
  ]);

  const rawStarters = rosterData.starters || rosterData.myRoster || [];
  const rawBench = rosterData.bench || [];
  const rawReserve = rosterData.reserve || [];
  const teamMeta = rosterData.teamMeta || {};
  const leagueRosters = rosterData.leagueRosters || [];

  // Build lookup map for market comparison data
  const compMap = new Map();
  (compData.players || []).forEach(c => {
    if (c.player_id) compMap.set(String(c.player_id), c);
    if (c.player_name) compMap.set(c.player_name.toLowerCase(), c);
  });

  // Enrich player objects
  const enrichPlayer = (p, defaultSlot = 'BENCH') => {
    const pid = String(p.player_id || '');
    const pname = (p.player_name || p.name || pid).toLowerCase();
    const c = compMap.get(pid) || compMap.get(pname) || {};

    const weekly = Number(p.projected_points ?? c.projected_points ?? c.weekly ?? 0);
    const season = Number(c.ros ?? c.marketRos ?? (weekly * 17));
    const width = Number(p.width ?? c.width ?? 5.0);
    const lower = Number(p.projection_lower ?? (weekly - width / 2));
    const upper = Number(p.projection_upper ?? (weekly + width / 2));

    const vor = Number(c.vor ?? Math.max(0, season - 100));
    const gridironAuction = Number(c.auction ?? Math.max(1, Math.round(vor * 0.25)));
    const marketAuction = Number(c.market_auction ?? c.marketAuction ?? Math.max(1, Math.round(gridironAuction * 0.9)));
    const deltaAuction = gridironAuction - marketAuction;

    const slot = p.slot || defaultSlot;
    const ecr = c.fp_ecr ?? p.fp_ecr ?? null;
    const ecrPos = c.fp_ecr_pos ?? p.fp_ecr_pos ?? null;
    const adp = c.fp_adp ?? p.fp_adp ?? null;
    const tier = c.fp_tier ?? c.tier ?? p.tier ?? null;
    const edge = (c.edge || 'NEUTRAL').toUpperCase();
    const status = p.injury_status || c.injury_status || null;

    let rec = 'START';
    if (slot.startsWith('BN') || slot === 'BENCH' || slot === 'IR') {
      rec = weekly >= 12.0 ? 'BENCH (POTENTIAL START)' : 'BENCH';
    } else {
      rec = width > 7.0 ? 'TOSS-UP' : weekly >= 10.0 ? 'START' : 'SIT RISK';
    }

    return {
      ...p,
      player_id: pid,
      player_name: p.player_name || p.name || pid,
      position: (p.position || p.position_group || 'UNK').toUpperCase(),
      team: (p.team || '').toUpperCase(),
      opponent_team: p.opponent_team || '',
      weekly,
      season,
      width,
      lower,
      upper,
      vor,
      gridironAuction,
      marketAuction,
      deltaAuction,
      ecr,
      ecrPos,
      adp,
      tier,
      edge,
      injury_status: status,
      slot,
      recommendation: rec,
      stats: c.stats || p.stats || {},
      pass_yd: c.pass_yd ?? p.pass_yd ?? (p.position === 'QB' ? weekly * 12 : 0),
      rush_yd: c.rush_yd ?? p.rush_yd ?? (p.position === 'RB' ? weekly * 4 : 0),
      rec_yd: c.rec_yd ?? p.rec_yd ?? (p.position === 'WR' || p.position === 'TE' ? weekly * 4.5 : 0),
      tds: c.tds ?? p.tds ?? (weekly / 7.5),
    };
  };

  const starters = rawStarters.map((p, i) => enrichPlayer(p, `SLOT ${i + 1}`));
  const bench = rawBench.map(p => enrichPlayer(p, 'BENCH'));
  const reserve = rawReserve.map(p => enrichPlayer(p, 'IR'));
  const allPlayers = [...starters, ...bench, ...reserve];

  // Team Hero KPIs
  const totalGridironValue = allPlayers.reduce((sum, p) => sum + p.gridironAuction, 0);
  const totalMarketValue = allPlayers.reduce((sum, p) => sum + p.marketAuction, 0);
  const totalSeasonProj = starters.reduce((sum, p) => sum + p.season, 0);
  const totalWeeklyProj = starters.reduce((sum, p) => sum + p.weekly, 0);

  // Position Strength Calculation
  const getPosStrength = (pos) => {
    const posPts = starters.filter(p => p.position === pos).reduce((sum, p) => sum + p.weekly, 0);
    if (pos === 'QB') return posPts >= 18 ? { label: 'STRONG', cls: 'emerald' } : posPts >= 14 ? { label: 'SOLID', cls: 'amber' } : { label: 'WEAK', cls: 'crimson' };
    if (pos === 'RB') return posPts >= 26 ? { label: 'STRONG', cls: 'emerald' } : posPts >= 18 ? { label: 'SOLID', cls: 'amber' } : { label: 'WEAK', cls: 'crimson' };
    if (pos === 'WR') return posPts >= 30 ? { label: 'STRONG', cls: 'emerald' } : posPts >= 20 ? { label: 'SOLID', cls: 'amber' } : { label: 'WEAK', cls: 'crimson' };
    if (pos === 'TE') return posPts >= 11 ? { label: 'STRONG', cls: 'emerald' } : posPts >= 7 ? { label: 'SOLID', cls: 'amber' } : { label: 'WEAK', cls: 'crimson' };
    return { label: 'NEUTRAL', cls: 'faint' };
  };

  const qbStr = getPosStrength('QB');
  const rbStr = getPosStrength('RB');
  const wrStr = getPosStrength('WR');
  const teStr = getPosStrength('TE');

  // Bye Week Matrix
  const byeMap = {};
  allPlayers.forEach(p => {
    const bye = p.bye_week || p.bye || null;
    if (bye) byeMap[bye] = (byeMap[bye] || 0) + 1;
  });
  const byeWeeks = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14];

  root.innerHTML = `
    <div class="team-hub-header reveal in">
      <div class="team-hero-card card">
        <div class="team-hero-top">
          <div class="team-owner-info">
            <div class="team-owner-avatar">
              ${teamMeta.avatar_url
                ? `<img src="${teamMeta.avatar_url}" alt="${escapeHtml(teamMeta.display_name)}" class="owner-img" />`
                : `<div class="owner-avatar-fallback">${escapeHtml((teamMeta.display_name || 'T').charAt(0).toUpperCase())}</div>`}
            </div>
            <div>
              <div class="team-title-row">
                <h1 class="team-name">${escapeHtml(teamMeta.team_name || teamMeta.display_name || 'Team Hub')}</h1>
                <span class="badge badge-owner">Owner: @${escapeHtml(teamMeta.display_name || 'user')}</span>
              </div>
              <div class="team-sub-row faint">
                Sleeper Roster #${teamMeta.roster_id || selectedId} · 12-Team Full PPR · 2 FLEX
              </div>
            </div>
          </div>
          <div class="team-selector-header-box">
            <span class="kicker">Switch Team</span>
            ${renderTeamSelector(leagueRosters, selectedId)}
          </div>
        </div>

        <div class="team-kpi-grid">
          <div class="kpi-card">
            <span class="kicker">Gridiron Roster $</span>
            <span class="mono kpi-val" style="color:var(--amber)">$${totalGridironValue}</span>
            <span class="micro faint">Sum of VOR $ values</span>
          </div>
          <div class="kpi-card">
            <span class="kicker">Market Consensus $</span>
            <span class="mono kpi-val" style="color:var(--sky)">$${totalMarketValue}</span>
            <span class="micro ${totalGridironValue >= totalMarketValue ? 'text-good' : 'text-bad'}">
              ${totalGridironValue >= totalMarketValue ? '+' : ''}$${totalGridironValue - totalMarketValue} vs Market
            </span>
          </div>
          <div class="kpi-card">
            <span class="kicker">Season Proj. Points</span>
            <span class="mono kpi-val">${totalSeasonProj.toFixed(0)} <span class="kpi-unit">pts</span></span>
            <span class="micro faint">~${totalWeeklyProj.toFixed(1)} pts/wk</span>
          </div>
          <div class="kpi-card">
            <span class="kicker">Position Strength</span>
            <div class="pos-strength-badges">
              <span class="badge badge-${qbStr.cls}">QB: ${qbStr.label}</span>
              <span class="badge badge-${rbStr.cls}">RB: ${rbStr.label}</span>
              <span class="badge badge-${wrStr.cls}">WR: ${wrStr.label}</span>
              <span class="badge badge-${teStr.cls}">TE: ${teStr.label}</span>
            </div>
          </div>
        </div>

        <div class="bye-matrix-row">
          <span class="kicker">Bye Week Matrix:</span>
          <div class="bye-pills">
            ${byeWeeks.map(w => {
              const count = byeMap[w] || 0;
              return `<span class="bye-pill ${count > 0 ? 'active' : ''}" title="Week ${w}: ${count} player(s) on bye">W${w}: <strong>${count}</strong></span>`;
            }).join('')}
          </div>
        </div>
      </div>
    </div>

    <!-- Starters Section -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header">
        <div>
          <h3>Starters (${starters.length})</h3>
          <span class="kicker">Click any player cell to open detailed breakdown modal</span>
        </div>
        <span class="badge badge-amber mono">${totalWeeklyProj.toFixed(1)} Wk Pts</span>
      </div>
      <div class="card-body" style="padding:0">
        <div class="responsive-view">
          <div class="table-wrap" style="border:0; border-radius:0">
            <table>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Player</th>
                  <th>Opponent</th>
                  <th style="color:var(--amber)">Gridiron Wk/Season</th>
                  <th style="color:var(--amber)">Gridiron $</th>
                  <th style="color:var(--sky)">Market $</th>
                  <th>Δ $</th>
                  <th>ECR (Pos)</th>
                  <th>ADP</th>
                  <th>Tier</th>
                  <th>Edge</th>
                  <th>Interval</th>
                  <th>Status</th>
                  <th>Recommendation</th>
                </tr>
              </thead>
              <tbody>
                ${starters.map(p => renderPlayerRow(p)).join('')}
              </tbody>
            </table>
          </div>
          <div class="player-cards-grid" style="padding:12px">
            ${starters.map(p => renderPlayerCardItem(p)).join('')}
          </div>
        </div>
      </div>
    </div>

    <!-- Bench Section -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header">
        <div>
          <h3>Bench (${bench.length})</h3>
          <span class="kicker">Depth &amp; upside reserves</span>
        </div>
      </div>
      <div class="card-body" style="padding:0">
        <div class="responsive-view">
          <div class="table-wrap" style="border:0; border-radius:0">
            <table>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Player</th>
                  <th>Opponent</th>
                  <th style="color:var(--amber)">Gridiron Wk/Season</th>
                  <th style="color:var(--amber)">Gridiron $</th>
                  <th style="color:var(--sky)">Market $</th>
                  <th>Δ $</th>
                  <th>ECR (Pos)</th>
                  <th>ADP</th>
                  <th>Tier</th>
                  <th>Edge</th>
                  <th>Interval</th>
                  <th>Status</th>
                  <th>Recommendation</th>
                </tr>
              </thead>
              <tbody>
                ${bench.map(p => renderPlayerRow(p)).join('')}
              </tbody>
            </table>
          </div>
          <div class="player-cards-grid" style="padding:12px">
            ${bench.map(p => renderPlayerCardItem(p)).join('')}
          </div>
        </div>
      </div>
    </div>

    <!-- IR / Reserve Section -->
    ${reserve.length ? `
      <div class="card reveal in" style="margin-top:16px">
        <div class="card-header">
          <div>
            <h3>IR / Reserve (${reserve.length})</h3>
            <span class="kicker">Injured reserve slots</span>
          </div>
        </div>
        <div class="card-body" style="padding:0">
          <div class="responsive-view">
            <div class="table-wrap" style="border:0; border-radius:0">
              <table>
                <thead>
                  <tr>
                    <th>Slot</th>
                    <th>Player</th>
                    <th>Opponent</th>
                    <th>Gridiron Wk</th>
                    <th>Gridiron $</th>
                    <th>Market $</th>
                    <th>Δ $</th>
                    <th>ECR</th>
                    <th>Interval</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  ${reserve.map(p => renderPlayerRow(p, true)).join('')}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    ` : ''}

    <div id="playerModalContainer"></div>
  `;

  // Bind Team Selector
  bindTeamSelector((newTeamId) => {
    renderTeam(root);
  });

  // Bind Player Cell Clicks (opens Draftea-style Modal)
  root.querySelectorAll('[data-player-id]').forEach(el => {
    el.addEventListener('click', () => {
      const pid = el.getAttribute('data-player-id');
      const targetPlayer = allPlayers.find(p => String(p.player_id) === String(pid));
      if (targetPlayer) {
        openPlayerModal(targetPlayer, root);
      }
    });
  });
}

function renderPlayerRow(p, isReserve = false) {
  const deltaCls = p.deltaAuction > 0 ? 'text-good' : p.deltaAuction < 0 ? 'text-bad' : 'faint';
  const deltaSign = p.deltaAuction > 0 ? '+' : '';
  const edgeCls = p.edge === 'BUY' ? 'badge-emerald' : p.edge === 'SELL' ? 'badge-crimson' : 'badge-faint';
  const confLabel = p.width < 3 ? 'HIGH' : p.width < 6 ? 'MED' : 'WIDE';
  const confCls = p.width < 3 ? 'badge-emerald' : p.width < 6 ? 'badge-amber' : 'badge-faint';

  return `
    <tr data-player-id="${escapeHtml(p.player_id)}" class="clickable-row" style="cursor:pointer">
      <td class="micro faint mono">${escapeHtml(p.slot)}</td>
      <td>
        <div class="player-cell">
          ${playerAvatar(p, 32)}
          <div class="player-cell-info">
            <div class="player-cell-name">${escapeHtml(p.player_name)} ${posBadge(p.position)}</div>
            <div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '—')}</div>
          </div>
        </div>
      </td>
      <td class="micro faint">${escapeHtml(p.opponent_team || '—')}</td>
      <td class="mono">
        <span style="color:var(--amber); font-weight:700">${p.weekly.toFixed(1)}</span>
        <span class="micro faint"> / ${p.season.toFixed(0)}</span>
      </td>
      <td class="mono"><span class="badge badge-amber">$${p.gridironAuction}</span></td>
      <td class="mono"><span class="badge badge-sky">$${p.marketAuction}</span></td>
      <td class="mono ${deltaCls}">${deltaSign}$${p.deltaAuction}</td>
      <td class="mono micro">${p.ecr ? `#${p.ecr}${p.ecrPos ? ` (${p.position}${p.ecrPos})` : ''}` : '—'}</td>
      <td class="mono micro faint">${p.adp ? `#${p.adp}` : '—'}</td>
      <td>${p.tier ? `<span class="badge badge-violet">T${p.tier}</span>` : '—'}</td>
      <td><span class="badge ${edgeCls}">${p.edge}</span></td>
      <td>
        ${intervalBar({ point: p.weekly, low: p.lower, high: p.upper, width: p.width, min: 0, max: 35 })}
        <span class="badge ${confCls} micro" style="margin-left:4px">${confLabel}</span>
      </td>
      <td>${injuryBadge(p.injury_status)}</td>
      ${!isReserve ? `<td class="mono micro faint">${escapeHtml(p.recommendation)}</td>` : ''}
    </tr>
  `;
}

function renderPlayerCardItem(p) {
  return `
    <div class="player-card clickable-card" data-player-id="${escapeHtml(p.player_id)}" style="cursor:pointer">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px">
        <div style="display:flex; align-items:center; gap:8px">
          ${playerAvatar(p, 36)}
          <div>
            <div style="font-weight:700; color:var(--text)">${escapeHtml(p.player_name)}</div>
            <div style="font-size:11px; color:var(--text-muted); display:flex; gap:4px; align-items:center">
              ${posBadge(p.position)} · ${teamLogo(p.team, 14)} ${escapeHtml(p.team || '')} vs ${escapeHtml(p.opponent_team || '—')}
            </div>
          </div>
        </div>
        <span class="badge badge-amber mono" style="font-size:13px">$${p.gridironAuction}</span>
      </div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px; margin-bottom:8px" class="mono">
        <div><span class="faint">Gridiron:</span> <strong style="color:var(--amber)">${p.weekly.toFixed(1)} wk</strong></div>
        <div><span class="faint">Market:</span> <span style="color:var(--sky)">$${p.marketAuction}</span></div>
        <div><span class="faint">ECR:</span> ${p.ecr ? `#${p.ecr}` : '—'}</div>
        <div><span class="faint">Edge:</span> <strong style="color:${p.edge==='BUY'?'var(--emerald)':p.edge==='SELL'?'var(--crimson)':'var(--text-muted)'}">${p.edge}</strong></div>
      </div>
      <div>${intervalBar({ point: p.weekly, low: p.lower, high: p.upper, width: p.width, min: 0, max: 35 })}</div>
    </div>
  `;
}

// Draftea-Style Player Detail Modal
function openPlayerModal(p, root) {
  const container = root.querySelector('#playerModalContainer');
  if (!container) return;

  modalPlayer = p;
  const isPasser = p.position === 'QB';

  container.innerHTML = `
    <div class="player-modal-backdrop" id="modalBackdrop">
      <div class="player-modal-card card reveal in" role="dialog" aria-modal="true" aria-labelledby="modalPlayerName">
        <button class="modal-close-btn" id="modalCloseBtn" aria-label="Close modal">✕</button>

        <div class="modal-header-hero">
          ${playerAvatar(p, 72)}
          <div class="modal-title-box">
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
              <h2 id="modalPlayerName" style="margin:0; font-size:22px">${escapeHtml(p.player_name)}</h2>
              ${posBadge(p.position)}
              ${teamLogo(p.team, 22)}
              <span class="mono faint" style="font-size:12px">${escapeHtml(p.team)} vs ${escapeHtml(p.opponent_team || 'TBD')}</span>
            </div>
            <div style="margin-top:4px; display:flex; gap:8px; align-items:center; flex-wrap:wrap">
              ${injuryBadge(p.injury_status)}
              ${p.tier ? `<span class="badge badge-violet">Tier ${p.tier}</span>` : ''}
              <span class="badge ${p.edge === 'BUY' ? 'badge-emerald' : p.edge === 'SELL' ? 'badge-crimson' : 'badge-faint'}">${p.edge} EDGE</span>
              <span class="mono faint micro">ECR #${p.ecr ?? '—'} · ADP #${p.adp ?? '—'}</span>
            </div>
          </div>
        </div>

        <div class="modal-values-grid">
          <div class="modal-val-card">
            <span class="kicker">Gridiron Model $</span>
            <span class="mono val-large" style="color:var(--amber)">$${p.gridironAuction}</span>
            <span class="micro faint">${p.weekly.toFixed(1)} projected pts/wk</span>
          </div>
          <div class="modal-val-card">
            <span class="kicker">Market Consensus $</span>
            <span class="mono val-large" style="color:var(--sky)">$${p.marketAuction}</span>
            <span class="micro faint">60% FP + 40% SG consensus</span>
          </div>
          <div class="modal-val-card">
            <span class="kicker">Value Delta (Δ $)</span>
            <span class="mono val-large ${p.deltaAuction > 0 ? 'text-good' : p.deltaAuction < 0 ? 'text-bad' : 'faint'}">
              ${p.deltaAuction > 0 ? '+' : ''}$${p.deltaAuction}
            </span>
            <span class="micro faint">${p.deltaAuction > 0 ? 'Underpriced (BUY)' : p.deltaAuction < 0 ? 'Overpriced (SELL)' : 'Fair Price'}</span>
          </div>
        </div>

        <div class="modal-section" style="margin-top:16px">
          <span class="kicker">Projection Interval &amp; Floor/Ceiling</span>
          <div style="margin-top:8px">
            ${intervalBar({ point: p.weekly, low: p.lower, high: p.upper, width: p.width, min: 0, max: 35 })}
          </div>
          <div style="display:flex; justify-content:space-between; margin-top:6px; font-size:11px" class="mono faint">
            <span>Floor: ${p.lower.toFixed(1)} pts</span>
            <span>Target: ${p.weekly.toFixed(1)} pts</span>
            <span>Ceiling: ${p.upper.toFixed(1)} pts</span>
          </div>
        </div>

        <div class="modal-section" style="margin-top:16px">
          <span class="kicker">Stat Breakdown (Weekly Projected Averages)</span>
          <div class="stat-bars-container" style="margin-top:8px; display:flex; flex-direction:column; gap:8px">
            ${isPasser ? renderStatBar('Pass YDS', p.pass_yd, 350, '#38BDF8', 'yds') : ''}
            ${renderStatBar('Rush YDS', p.rush_yd, 150, '#10B981', 'yds')}
            ${!isPasser ? renderStatBar('Rec YDS', p.rec_yd, 150, '#F59E0B', 'yds') : ''}
            ${renderStatBar('TDs (Total)', p.tds, 3, '#A855F7', 'TD')}
          </div>
        </div>

        <div class="modal-footer" style="margin-top:20px; display:flex; justify-content:flex-end">
          <button class="btn btn-ghost" id="modalDismissBtn">Close</button>
        </div>
      </div>
    </div>
  `;

  // Bind close events
  const close = () => { container.innerHTML = ''; modalPlayer = null; };
  root.querySelector('#modalCloseBtn')?.addEventListener('click', close);
  root.querySelector('#modalDismissBtn')?.addEventListener('click', close);
  root.querySelector('#modalBackdrop')?.addEventListener('click', (e) => {
    if (e.target.id === 'modalBackdrop') close();
  });
}

function renderStatBar(label, value, maxVal, color, unit) {
  const val = Number(value || 0);
  const pct = Math.max(2, Math.min(100, (val / maxVal) * 100));

  return `
    <div class="stat-bar-row">
      <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:2px" class="mono">
        <span class="faint">${label}</span>
        <strong style="color:${color}">${val.toFixed(1)} ${unit}</strong>
      </div>
      <div class="stat-bar-track" style="height:8px; background:rgba(255,255,255,0.06); border-radius:4px; overflow:hidden">
        <div class="stat-bar-fill" style="width:${pct}%; height:100%; background:${color}; border-radius:4px"></div>
      </div>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}
