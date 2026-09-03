// hub/src/views/roster.js — League Directory & Roster Matrix
import { fetchRoster, fetchRostersFull, fetchComparison } from '../api.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { userAvatar } from '../components/userAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { openPlayerModal } from '../components/playerModal.js';
import { computeVbdParams } from '../components/vbdAuction.js';
import { enrichPlayer } from '../lib/enrichPlayer.js';
import { assignStarterSlots } from '../lib/slots.js';
import { escapeHtml, escapeAttr, safeAvatarUrl } from '../lib/escape.js';

let selectedTeamAId = '1';
let selectedTeamBId = '2';
let inspectorMode = 'single'; // 'single' or 'compare'

export async function renderRoster(root) {
  // Bulk-first: single /rosters-full pass avoids 12x N+1 fan-out; fallback to legacy.
  const bulkData = await fetchRostersFull().catch(() => null);
  const bulkRosters = bulkData?.rosters || bulkData?.teams || null;
  // Fetch initial base data to get all team listings
  const baseRosterData = bulkData || await fetchRoster({ roster_id: '1' });
  const allTeamMetas = baseRosterData.leagueRosters || baseRosterData.allTeams || [];

  if (allTeamMetas.length && !allTeamMetas.some(t => String(t.roster_id) === String(selectedTeamAId))) {
    selectedTeamAId = String(allTeamMetas[0].roster_id);
  }
  if (allTeamMetas.length > 1 && !allTeamMetas.some(t => String(t.roster_id) === String(selectedTeamBId))) {
    selectedTeamBId = String(allTeamMetas[1].roster_id);
  }

  // Market comparison + bulk rosters concurrently (2 fetches, not 13).
  const [bulkOrAll, compData] = await Promise.all([
    (async () => {
      if (bulkRosters && typeof bulkRosters === 'object') {
        // Normalize bulk map to per-team rData array aligned with allTeamMetas.
        return allTeamMetas.map(meta => {
          const rid = String(meta.roster_id);
          const full = bulkRosters[rid] || bulkRosters[Number(rid)] || null;
          if (!full) return null;
          return {
            starters: full.starters || [],
            bench: full.bench || [],
            reserve: full.reserve || [],
            myRoster: full.starters || [],
            teamMeta: full.team_info || full.teamMeta || meta,
            team_info: full.team_info || full.teamMeta || meta,
          };
        });
      }
      // Fallback: legacy N+1 fan-out.
      return Promise.all(allTeamMetas.map(t => fetchRoster({ roster_id: t.roster_id }).catch(() => null)));
    })(),
    fetchComparison({ limit: 800 }).catch(() => ({ players: [] })),
  ]);
  const allRosters = bulkOrAll;

  // Build lookup map for market comparison data
  const compMap = new Map();
  (compData.players || []).forEach(c => {
    if (c.player_id) compMap.set(String(c.player_id), c);
    if (c.player_name) compMap.set(c.player_name.toLowerCase(), c);
  });
  const vbdParams = computeVbdParams(compData.players || []);
  const slotOpts = { vbdParams, compPlayers: compData.players || [] };

  const buildTeamRecord = (rData, metaFallback) => {
    if (!rData) return null;
    const meta = rData.teamMeta || rData.team_info || metaFallback || {};
    const rawStarters = rData.starters || rData.myRoster || [];
    const rawBench = rData.bench || [];
    const rawReserve = rData.reserve || [];

    const { starters, bench } = assignStarterSlots(rawStarters, rawBench, slotOpts);
    const reserve = rawReserve.map((p, i) =>
      enrichPlayer({ ...p, slot: `IR${i + 1}` }, null, { ...slotOpts, defaultSlot: `IR${i + 1}` })
    );
    const allPlayers = [...starters, ...bench, ...reserve];

    const starterFPTS = starters.reduce((s, p) => s + p.weekly, 0);
    const totalGridiron = allPlayers.reduce((s, p) => s + p.gridironAuction, 0);
    const totalMarket = allPlayers.reduce((s, p) => s + p.marketAuction, 0);
    const deltaTotal = totalGridiron - totalMarket;

    // Top player by projected points or Gridiron $
    const topPlayer = [...allPlayers].sort((a, b) => b.weekly - a.weekly)[0] || null;

    // Determine weakest position group
    const posSums = { QB: 0, RB: 0, WR: 0, TE: 0 };
    starters.forEach(p => {
      if (posSums[p.position] !== undefined) posSums[p.position] += p.weekly;
    });

    // Ratio to benchmark expectations
    const benchRatios = {
      QB: posSums.QB / 16.0,
      RB: posSums.RB / 22.0,
      WR: posSums.WR / 26.0,
      TE: posSums.TE / 9.0,
    };
    let weakestPos = 'TE';
    let minRatio = 999;
    Object.entries(benchRatios).forEach(([pos, ratio]) => {
      if (ratio < minRatio) {
        minRatio = ratio;
        weakestPos = pos;
      }
    });

    return {
      roster_id: String(meta.roster_id || ''),
      owner_name: meta.display_name || meta.owner_name || meta.team_name || `Team ${meta.roster_id}`,
      team_name: meta.team_name || meta.display_name || `Team ${meta.roster_id}`,
      avatar_url: meta.avatar_url || null,
      starters,
      bench,
      reserve,
      allPlayers,
      starterFPTS,
      totalGridiron,
      totalMarket,
      deltaTotal,
      topPlayer,
      weakestPos: `${weakestPos} (${posSums[weakestPos].toFixed(1)} pts)`,
    };
  };

  const processedTeams = allRosters
    .map((rd, i) => buildTeamRecord(rd, allTeamMetas[i]))
    .filter(Boolean);

  // Sort all 12 teams by Starter FPTS descending to create the Financial & Power Leaderboard
  processedTeams.sort((a, b) => b.starterFPTS - a.starterFPTS);

  // Attach Leaderboard Rank #1 - #12
  processedTeams.forEach((t, index) => {
    t.rank = index + 1;
  });

  const teamA = processedTeams.find(t => t.roster_id === selectedTeamAId) || processedTeams[0];
  const teamB = processedTeams.find(t => t.roster_id === selectedTeamBId) || (processedTeams[1] || processedTeams[0]);

  root.innerHTML = `
    <!-- Header Hero -->
    <div class="hero reveal in">
      <h1>League directory</h1>
      <p>12-team financial &amp; power leaderboard with side-by-side roster inspector.</p>
    </div>

    <!-- 12-Team Financial & Power Leaderboard -->
    <div class="card reveal in" style="margin-top:8px">
      <div class="card-header">
        <div>
          <h3>12-Team Financial &amp; Power Leaderboard</h3>
          <span class="kicker">Ranked by starter projected pts &amp; Model $</span>
        </div>
        <span class="badge badge-amber mono" aria-live="polite">${processedTeams.length} League Teams</span>
      </div>
      <div class="card-body" style="padding:0">
        <div class="table-wrap" style="border:0; border-radius:0">
          <table aria-label="League leaderboard">
            <caption class="sr-only">12-team financial and power leaderboard</caption>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Roster ID</th>
                <th>Team &amp; Owner</th>
                <th style="color:var(--amber)">Starter Projected FPTS</th>
                <th style="color:var(--emerald)">Total Model $</th>
                <th style="color:var(--sky)">Market Consensus $</th>
                <th>Δ $ Edge</th>
                <th>Top Player</th>
                <th>Weakest Position</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${processedTeams.map(t => renderLeaderboardRow(t, selectedTeamAId)).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Side-by-Side Team Roster Inspector Section -->
    <div class="card reveal in" style="margin-top:20px" id="inspectorSection">
      <div class="card-header" style="flex-wrap:wrap">
        <div>
          <h3>Side-by-Side Team Roster Inspector</h3>
          <span class="kicker">Inspect and compare full starters, bench, and position strength</span>
        </div>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
          <div class="filters">
            <button class="chip ${inspectorMode === 'single' ? 'active' : ''}" id="btnModeSingle">Single Team View</button>
            <button class="chip ${inspectorMode === 'compare' ? 'active' : ''}" id="btnModeCompare">Side-by-Side Compare</button>
          </div>
        </div>
      </div>
      <div class="card-body">
        <!-- Team Selectors Bar -->
        <div style="display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:16px; background:var(--surface-raised); padding:12px; border-radius:10px; border:1px solid var(--border); flex-wrap:wrap">
          <div style="display:flex; align-items:center; gap:10px">
            <span class="mono" style="font-weight:700; font-size:12px; color:var(--amber)">TEAM A:</span>
            <select id="selectTeamA" class="team-select-dropdown">
              ${processedTeams.map(t => `<option value="${t.roster_id}" ${t.roster_id === selectedTeamAId ? 'selected' : ''}>#${t.rank} ${escapeHtml(t.team_name)} (@${escapeHtml(t.owner_name)})</option>`).join('')}
            </select>
          </div>

          ${inspectorMode === 'compare' ? `
            <div style="display:flex; align-items:center; gap:10px">
              <span class="mono" style="font-weight:700; font-size:12px; color:var(--sky)">TEAM B:</span>
              <select id="selectTeamB" class="team-select-dropdown">
                ${processedTeams.map(t => `<option value="${t.roster_id}" ${t.roster_id === selectedTeamBId ? 'selected' : ''}>#${t.rank} ${escapeHtml(t.team_name)} (@${escapeHtml(t.owner_name)})</option>`).join('')}
              </select>
            </div>
          ` : ''}
        </div>

        <!-- Inspector View Content -->
        ${inspectorMode === 'single' ? renderSingleTeamInspector(teamA) : renderCompareTeamsInspector(teamA, teamB)}
      </div>
    </div>

    <div id="playerModalContainer"></div>
  `;

  // Bind Leaderboard row inspection clicks
  root.querySelectorAll('[data-inspect-id]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      selectedTeamAId = btn.getAttribute('data-inspect-id');
      renderRoster(root);
      const inspector = root.querySelector('#inspectorSection');
      if (inspector) inspector.scrollIntoView({ behavior: 'smooth' });
    });
  });

  // Bind Mode buttons
  root.querySelector('#btnModeSingle')?.addEventListener('click', () => {
    inspectorMode = 'single';
    renderRoster(root);
  });
  root.querySelector('#btnModeCompare')?.addEventListener('click', () => {
    inspectorMode = 'compare';
    renderRoster(root);
  });

  // Bind Dropdowns
  root.querySelector('#selectTeamA')?.addEventListener('change', (e) => {
    selectedTeamAId = e.target.value;
    renderRoster(root);
  });
  root.querySelector('#selectTeamB')?.addEventListener('change', (e) => {
    selectedTeamBId = e.target.value;
    renderRoster(root);
  });

  // Bind Player Clicks to open Draftea Modal (mouse + keyboard)
  root.querySelectorAll('[data-player-id]').forEach(el => {
    const openForEl = () => {
      const pid = el.getAttribute('data-player-id');
      let targetPlayer = null;
      processedTeams.forEach(t => {
        const found = t.allPlayers.find(p => String(p.player_id) === String(pid));
        if (found) targetPlayer = found;
      });
      if (targetPlayer) {
        openPlayerModal(targetPlayer, root);
      }
    };
    el.addEventListener('click', openForEl);
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openForEl();
      }
    });
  });
}

function renderLeaderboardRow(t, selectedId) {
  const isSelected = t.roster_id === selectedId;
  const deltaCls = t.deltaTotal > 0 ? 'text-good' : t.deltaTotal < 0 ? 'text-bad' : 'faint';
  const deltaSign = t.deltaTotal > 0 ? '+' : '';

  return `
    <tr class="clickable-row ${isSelected ? 'selected-row' : ''}" style="cursor:pointer; ${isSelected ? 'background:rgba(245,158,11,0.06);' : ''}">
      <td class="mono" style="font-weight:700">
        <span class="badge ${t.rank <= 3 ? 'badge-emerald' : t.rank <= 8 ? 'badge-amber' : 'badge-faint'}">#${t.rank}</span>
      </td>
      <td class="mono micro faint">Roster #${escapeHtml(t.roster_id)}</td>
      <td>
        <div class="player-cell">
          ${userAvatar(t, 32)}
          <div class="player-cell-info">
            <div class="player-cell-name" style="font-weight:700">${escapeHtml(t.team_name)}</div>
            <div class="player-cell-sub">@${escapeHtml(t.owner_name)}</div>
          </div>
        </div>
      </td>
      <td class="mono" style="font-size:14px; font-weight:700; color:var(--amber)">
        ${t.starterFPTS.toFixed(1)} <span class="micro faint">pts/wk</span>
      </td>
      <td class="mono"><span class="badge badge-emerald">$${t.totalGridiron}</span></td>
      <td class="mono"><span class="badge badge-sky">$${t.totalMarket}</span></td>
      <td class="mono ${deltaCls}">${deltaSign}$${t.deltaTotal}</td>
      <td>
        ${t.topPlayer ? `
          <div style="display:flex; align-items:center; gap:6px" class="mono micro">
            ${playerAvatar(t.topPlayer, 24)}
            <span>${escapeHtml(t.topPlayer.player_name)} (${t.topPlayer.position}, $${t.topPlayer.gridironAuction})</span>
          </div>
        ` : '—'}
      </td>
      <td class="mono micro text-bad">${escapeHtml(t.weakestPos)}</td>
      <td>
        <button class="btn btn-ghost btn-sm" data-inspect-id="${escapeHtml(t.roster_id)}">Inspect</button>
      </td>
    </tr>
  `;
}

function renderSingleTeamInspector(team) {
  if (!team) return '<div class="empty">No team selected.</div>';

  return `
    <div class="reveal in">
      <!-- Team Summary Hero Bar -->
      <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:10px; margin-bottom:16px">
        <div class="kpi-card">
          <span class="kicker">Team Rank</span>
          <div class="mono kpi-val" style="color:var(--amber)">#${team.rank} of 12</div>
          <span class="micro faint">Roster ID #${team.roster_id}</span>
        </div>
        <div class="kpi-card">
          <span class="kicker">Starter Projected FPTS</span>
          <div class="mono kpi-val" style="color:var(--amber)">${team.starterFPTS.toFixed(1)} pts/wk</div>
          <span class="micro faint">10 Active Starters</span>
        </div>
        <div class="kpi-card">
          <span class="kicker">Model $ VOR</span>
          <div class="mono kpi-val" style="color:var(--emerald)">$${team.totalGridiron}</div>
          <span class="micro faint">Market $${team.totalMarket}</span>
        </div>
        <div class="kpi-card">
          <span class="kicker">Weakest Position</span>
          <div class="mono kpi-val text-bad" style="font-size:16px; margin-top:6px">${escapeHtml(team.weakestPos)}</div>
          <span class="micro faint">Needs Upgrade</span>
        </div>
      </div>

      <!-- Starters Table -->
      <div class="table-wrap" style="margin-bottom:16px">
        <table aria-label="Team starters">
          <caption class="sr-only">Team starters with projections</caption>
          <thead>
            <tr>
              <th>Slot</th>
              <th>Player</th>
              <th>Matchup</th>
              <th style="color:var(--amber)">Model pts/wk</th>
              <th style="color:var(--emerald)">Model $</th>
              <th style="color:var(--sky)">Market $</th>
              <th>Δ $</th>
              <th>Edge</th>
              <th>ECR</th>
              <th>Conformal Interval</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${team.starters.map(p => renderInspectorPlayerRow(p)).join('')}
          </tbody>
        </table>
      </div>

      <!-- Bench Table -->
      <div style="margin-top:12px">
        <span class="kicker" style="display:block; margin-bottom:8px">Bench &amp; Reserves (${team.bench.length + team.reserve.length})</span>
        <div class="table-wrap">
          <table aria-label="Bench and reserves">
            <caption class="sr-only">Bench and reserve players</caption>
            <thead>
              <tr>
                <th>Slot</th>
                <th>Player</th>
                <th>Matchup</th>
<th style="color:var(--amber)">Model pts/wk</th>
              <th style="color:var(--emerald)">Model $</th>
              <th style="color:var(--sky)">Market $</th>
              <th>Δ $</th>
              <th>Edge</th>
              <th>ECR</th>
              <th>Conformal Interval</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${[...team.bench, ...team.reserve].map(p => renderInspectorPlayerRow(p)).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

function renderCompareTeamsInspector(teamA, teamB) {
  if (!teamA || !teamB) return '<div class="empty">Select two teams to compare.</div>';

  // Compare position strengths head-to-head
  const getPosSum = (team, pos) => {
    return team.starters.filter(p => p.position === pos || (pos === 'WR' && p.slot.startsWith('FLEX') && p.position === 'WR') || (pos === 'RB' && p.slot.startsWith('FLEX') && p.position === 'RB')).reduce((s, p) => s + p.weekly, 0);
  };

  const positions = ['QB', 'RB', 'WR', 'TE'];

  return `
    <div class="reveal in">
      <!-- Head to Head Summary Cards -->
      <div style="display:grid; grid-template-columns:1fr 80px 1fr; gap:12px; align-items:center; margin-bottom:16px; background:var(--surface-raised); padding:16px; border-radius:12px; border:1px solid var(--border)">
        <!-- Team A -->
        <div style="display:flex; align-items:center; gap:12px">
          <div class="player-avatar" style="width:44px; height:44px">
            ${teamA.avatar_url && safeAvatarUrl(teamA.avatar_url) ? `<img src="${escapeAttr(safeAvatarUrl(teamA.avatar_url))}" />` : `<div class="player-avatar-fallback" style="background:var(--amber)">${escapeHtml(teamA.owner_name).charAt(0)}</div>`}
          </div>
          <div>
            <div style="font-weight:700; font-size:16px">${escapeHtml(teamA.team_name)}</div>
            <div class="mono micro faint">Rank #${teamA.rank} · ${teamA.starterFPTS.toFixed(1)} FPTS · $${teamA.totalGridiron}</div>
          </div>
        </div>

        <!-- VS Badge -->
        <div style="text-align:center">
          <span class="badge badge-amber mono" style="font-size:14px">VS</span>
        </div>

        <!-- Team B -->
        <div style="display:flex; align-items:center; justify-content:flex-end; gap:12px">
          <div style="text-align:right">
            <div style="font-weight:700; font-size:16px">${escapeHtml(teamB.team_name)}</div>
            <div class="mono micro faint">Rank #${teamB.rank} · ${teamB.starterFPTS.toFixed(1)} FPTS · $${teamB.totalGridiron}</div>
          </div>
          <div class="player-avatar" style="width:44px; height:44px">
            ${teamB.avatar_url && safeAvatarUrl(teamB.avatar_url) ? `<img src="${escapeAttr(safeAvatarUrl(teamB.avatar_url))}" />` : `<div class="player-avatar-fallback" style="background:var(--sky)">${escapeHtml(teamB.owner_name).charAt(0)}</div>`}
          </div>
        </div>
      </div>

      <!-- Positional Comparison Heatmap Grid -->
      <div style="margin-bottom:16px">
        <span class="kicker" style="display:block; margin-bottom:8px">Position-by-Position FPTS Advantage</span>
        <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:10px">
          ${positions.map(pos => {
            const sumA = getPosSum(teamA, pos);
            const sumB = getPosSum(teamB, pos);
            const diff = sumA - sumB;
            const winner = diff > 0 ? teamA.team_name : diff < 0 ? teamB.team_name : 'EVEN';
            const winnerCls = diff > 0 ? 'color:var(--amber)' : diff < 0 ? 'color:var(--sky)' : 'color:var(--text-muted)';
            return `
              <div style="background:var(--surface-raised); border:1px solid var(--border); border-radius:10px; padding:10px; text-align:center">
                <span class="mono" style="font-weight:700; font-size:12px; color:var(--text-faint)">${pos} POSITION</span>
                <div style="display:flex; justify-content:space-around; margin:6px 0; font-size:14px" class="mono">
                  <strong style="color:var(--amber)">${sumA.toFixed(1)}</strong>
                  <span class="faint">vs</span>
                  <strong style="color:var(--sky)">${sumB.toFixed(1)}</strong>
                </div>
                <span class="micro" style="font-weight:700; ${winnerCls}">
                  ${diff !== 0 ? `${winner} +${Math.abs(diff).toFixed(1)}` : 'EVEN'}
                </span>
              </div>
            `;
          }).join('')}
        </div>
      </div>

      <!-- Slot Matchup Table — slot-aligned (QB vs QB, RB1 vs RB1, etc.) -->
      <div class="table-wrap">
        <table aria-label="Slot comparison">
          <caption class="sr-only">Head-to-head slot comparison</caption>
          <thead>
            <tr>
              <th style="color:var(--amber)">${escapeHtml(teamA.team_name)} Starter</th>
              <th>Slot</th>
              <th style="color:var(--sky)">${escapeHtml(teamB.team_name)} Starter</th>
              <th>Advantage</th>
            </tr>
          </thead>
          <tbody>
            ${(() => {
              const slotOrder = ['QB','RB1','RB2','WR1','WR2','TE','FLEX1','FLEX2','K','DEF'];
              const bySlotA = new Map(teamA.starters.map(p=>[p.slot,p]));
              const bySlotB = new Map(teamB.starters.map(p=>[p.slot,p]));
              const extra = [...new Set([...teamA.starters.map(p=>p.slot), ...teamB.starters.map(p=>p.slot)])].filter(s=>!slotOrder.includes(s));
              return [...slotOrder, ...extra].map(slot => {
                const pA = bySlotA.get(slot) || null;
                const pB = bySlotB.get(slot) || null;
                if (!pA && !pB) return '';
                const ptsA = pA ? pA.weekly : 0;
                const ptsB = pB ? pB.weekly : 0;
                const diff = ptsA - ptsB;
                const advCls = diff > 0 ? 'text-good' : diff < 0 ? 'text-bad' : 'faint';
                const advSign = diff > 0 ? '+' : '';
                return `
                  <tr>
                    <td>
                      ${pA ? `
                        <div class="player-cell data-player-id="${escapeHtml(pA.player_id)}" style="cursor:pointer" data-player-id="${escapeHtml(pA.player_id)}" tabindex="0" role="button" aria-label="Open details for ${escapeAttr(pA.player_name || pA.player_id)}">
                          ${playerAvatar(pA, 32)}
                          <div>
                            <div style="font-weight:700">${escapeHtml(pA.player_name)} ${posBadge(pA.position)}</div>
                            <div class="mono micro" style="color:var(--amber)">${pA.weekly.toFixed(1)} pts · $${pA.gridironAuction}</div>
                          </div>
                        </div>
                      ` : '—'}
                    </td>
                    <td class="mono micro faint" style="font-weight:700; text-align:center">${escapeHtml(slot)}</td>
                    <td>
                      ${pB ? `
                        <div class="player-cell" style="cursor:pointer" data-player-id="${escapeHtml(pB.player_id)}" tabindex="0" role="button" aria-label="Open details for ${escapeAttr(pB.player_name || pB.player_id)}">
                          ${playerAvatar(pB, 32)}
                          <div>
                            <div style="font-weight:700">${escapeHtml(pB.player_name)} ${posBadge(pB.position)}</div>
                            <div class="mono micro" style="color:var(--sky)">${pB.weekly.toFixed(1)} pts · $${pB.gridironAuction}</div>
                          </div>
                        </div>
                      ` : '—'}
                    </td>
                    <td class="mono ${advCls}" style="font-weight:700">
                      ${advSign}${diff.toFixed(1)} pts
                    </td>
                  </tr>
                `;
              }).join('');
            })()}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderInspectorPlayerRow(p) {
  const deltaCls = p.deltaAuction > 0 ? 'text-good' : p.deltaAuction < 0 ? 'text-bad' : 'faint';
  const deltaSign = p.deltaAuction > 0 ? '+' : '';
  const edgeCls = p.edge === 'BUY' ? 'badge-emerald' : p.edge === 'SELL' ? 'badge-crimson' : 'badge-faint';
  const edgeIcon = p.edge === 'BUY' ? '▲ ' : p.edge === 'SELL' ? '▼ ' : '';

  return `
    <tr data-player-id="${escapeHtml(p.player_id)}" data-team="${p.team || ''}" class="clickable-row" tabindex="0" role="button" aria-label="Open details for ${escapeAttr(p.player_name || p.player_id)}" style="cursor:pointer; --team-accent:${getTeamColor((p.team||'').toUpperCase())}">
      <td class="micro faint mono" style="font-weight:700">${escapeHtml(p.slot)}</td>
      <td>
        <div class="player-cell">
          ${playerAvatar(p, 32)}
          <div class="player-cell-info">
            <div class="player-cell-name">${escapeHtml(p.player_name)} ${posBadge(p.position)}</div>
            <div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '—')}</div>
          </div>
        </div>
      </td>
      <td class="micro faint">${escapeHtml(p.team)} vs ${escapeHtml(p.opponent_team || 'TBD')}</td>
      <td class="mono" style="font-weight:700; color:var(--amber)">${p.weekly.toFixed(1)}</td>
      <td class="mono"><span class="badge badge-amber" title="${p.gridironUncapped!=null && p.gridironUncapped!==p.gridironAuction ? `Uncapped $${p.gridironUncapped}`:''}">$${p.gridironAuction}${p.gridironUncapped!=null && p.gridironUncapped!==p.gridironAuction ? ` <span class="micro faint">($${p.gridironUncapped})</span>`:''}</span></td>
      <td class="mono"><span class="badge badge-sky" title="${p.marketUncapped!=null && p.marketUncapped!==p.marketAuction ? `Uncapped $${p.marketUncapped}`:''}">$${p.marketAuction}${p.marketUncapped!=null && p.marketUncapped!==p.marketAuction ? ` <span class="micro faint">($${p.marketUncapped})</span>`:''}</span></td>
      <td class="mono ${deltaCls}">${deltaSign}$${p.deltaAuction}</td>
      <td><span class="badge ${edgeCls}" aria-label="${escapeAttr(p.edge)}">${edgeIcon}${p.edge}</span></td>
      <td class="mono micro">${p.ecr ? `#${p.ecr}` : '—'}</td>
      <td>
        ${intervalBar({ point: p.weekly, low: p.lower, high: p.upper, width: p.width, min: 0, max: 35 })}
      </td>
      <td>${injuryBadge(p.injury_status)}</td>
    </tr>
  `;
}
