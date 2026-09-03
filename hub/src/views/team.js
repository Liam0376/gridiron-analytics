// hub/src/views/team.js — Team Hub Executive Command Center
import { fetchRoster, fetchRostersFull, fetchComparison } from '../api.js';
import { getSelectedTeamId, setSelectedTeamId, renderTeamSelector, bindTeamSelector } from '../components/teamSelector.js';import { posBadge, injuryBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { openPlayerModal } from '../components/playerModal.js';
import { computeVbdParams } from '../components/vbdAuction.js';
import { assignStarterSlots } from '../lib/slots.js';
import { enrichPlayer } from '../lib/enrichPlayer.js';
import { escapeHtml, escapeAttr, safeAvatarUrl } from '../lib/escape.js';

export async function renderTeam(root) {
  // Bulk-first: single /rosters-full pass; single-fetch only when bulk misses (no N+1).
  const bulkData = await fetchRostersFull().catch(() => null);
  const bulkRosters = bulkData?.rosters || bulkData?.teams || null;
  const bulkLeagueRosters = bulkData?.leagueRosters || bulkData?.allTeams || [];

  // Derive selected team from stored value or leagueRosters[0] — no hardcoded id.
  let selectedId = getSelectedTeamId();
  if (!selectedId && bulkLeagueRosters.length) {
    selectedId = String(bulkLeagueRosters[0].roster_id);
    setSelectedTeamId(selectedId);
  }

  // Resolve rosterData from bulk when available; otherwise single-fetch.
  let rosterData = null;
  if (bulkRosters && selectedId && (bulkRosters[selectedId] || bulkRosters[Number(selectedId)])) {
    const full = bulkRosters[selectedId] || bulkRosters[Number(selectedId)];
    rosterData = {
      starters: full.starters || [],
      bench: full.bench || [],
      reserve: full.reserve || [],
      myRoster: full.starters || [],
      teamMeta: full.team_info || full.teamMeta || {},
      team_info: full.team_info || full.teamMeta || {},
      leagueRosters: bulkLeagueRosters,
      allTeams: bulkLeagueRosters,
    };
  } else {
    rosterData = await fetchRoster(selectedId ? { roster_id: selectedId } : {}).catch(() => ({ starters: [], bench: [], reserve: [], leagueRosters: [], allTeams: [] }));
    if (!selectedId) {
      const lr = rosterData.leagueRosters || rosterData.allTeams || [];
      if (lr.length) {
        selectedId = String(lr[0].roster_id);
        setSelectedTeamId(selectedId);
      }
    }
  }

  const compData = await fetchComparison({ limit: 800 }).catch(() => ({ players: [] }));

  const leagueRosters = (bulkLeagueRosters.length ? bulkLeagueRosters : (rosterData.leagueRosters || rosterData.allTeams || []));
  const teamMeta = rosterData.teamMeta || rosterData.team_info || {};

  // Build lookup map for market comparison data
  const compMap = new Map();
  (compData.players || []).forEach(c => {
    if (c.player_id) compMap.set(String(c.player_id), c);
    if (c.player_name) compMap.set(c.player_name.toLowerCase(), c);
  });
  // Compute dynamic VBD auction params from comparison data (mirrors comparison.py + auction.js)
  const vbdParams = computeVbdParams(compData.players || []);
  const slotOpts = { vbdParams, compPlayers: compData.players || [] };

  const rawStarters = rosterData.starters || rosterData.myRoster || [];
  const rawBench = rosterData.bench || [];
  const rawReserve = rosterData.reserve || [];

  const { starters, bench: rawBenchEnriched } = assignStarterSlots(rawStarters, rawBench, slotOpts);
  // IR/reserve not part of canonical starter/bench ordering — enrich inline with same opts.
  const reserve = rawReserve.map((p, i) =>
    enrichPlayer({ ...p, slot: `IR${i + 1}` }, null, { ...slotOpts, defaultSlot: `IR${i + 1}` })
  );
  const bench = rawBenchEnriched;
  const allPlayers = [...starters, ...bench, ...reserve];

  // League rank via single bulk pass (no N+1 fan-out); graceful fallback when bulk misses.
  let rankText = '#— of 12';
  try {
    if (bulkRosters && typeof bulkRosters === 'object') {
      const rankedTeams = Object.entries(bulkRosters)
        .map(([rid, full]) => {
          const teamStarters = full?.starters || full?.myRoster || [];
          const fpts = teamStarters.reduce((s, p) => s + Number(p.projected_points || 0), 0);
          const meta = full?.team_info || full?.teamMeta || {};
          return { roster_id: String(meta.roster_id || rid || ''), fpts };
        })
        .sort((a, b) => b.fpts - a.fpts);
      const myRankIdx = rankedTeams.findIndex(t => String(t.roster_id) === String(selectedId));
      if (myRankIdx !== -1) {
        rankText = `#${myRankIdx + 1} of 12`;
      }
    } else if (Array.isArray(bulkData?.league_leaderboard) && bulkData.league_leaderboard.length) {
      const idx = bulkData.league_leaderboard.findIndex(e => String(e.roster_id) === String(selectedId));
      if (idx !== -1) rankText = `#${idx + 1} of 12`;
    } else if (Array.isArray(rosterData.league_leaderboard) && rosterData.league_leaderboard.length) {
      const idx = rosterData.league_leaderboard.findIndex(e => String(e.roster_id) === String(selectedId));
      if (idx !== -1) rankText = `#${idx + 1} of 12`;
    }
  } catch (_) {}

  // Executive Header Metrics
  const totalGridironValue = allPlayers.reduce((sum, p) => sum + p.gridironAuction, 0);
  const totalMarketValue = allPlayers.reduce((sum, p) => sum + p.marketAuction, 0);
  const totalStarterFPTS = starters.reduce((sum, p) => sum + p.weekly, 0);
  const totalSeasonProj = starters.reduce((sum, p) => sum + p.season, 0);

  // Position Strength Heatmap calculation
  const getPosStrength = (pos) => {
    const posStarters = starters.filter(p => p.position === pos || (pos === 'WR' && p.slot.startsWith('FLEX') && p.position === 'WR') || (pos === 'RB' && p.slot.startsWith('FLEX') && p.position === 'RB'));
    const totalPts = posStarters.reduce((sum, p) => sum + p.weekly, 0);
    const count = posStarters.length || 1;
    const avg = totalPts / count;

    let label = 'SOLID';
    let cls = 'badge-amber';
    if (pos === 'QB') {
      if (totalPts >= 18) { label = 'ELITE'; cls = 'badge-emerald'; }
      else if (totalPts < 14) { label = 'WEAK'; cls = 'badge-crimson'; }
    } else if (pos === 'RB') {
      if (totalPts >= 24) { label = 'STRONG'; cls = 'badge-emerald'; }
      else if (totalPts < 16) { label = 'WEAK'; cls = 'badge-crimson'; }
    } else if (pos === 'WR') {
      if (totalPts >= 28) { label = 'STRONG'; cls = 'badge-emerald'; }
      else if (totalPts < 18) { label = 'WEAK'; cls = 'badge-crimson'; }
    } else if (pos === 'TE') {
      if (totalPts >= 11) { label = 'STRONG'; cls = 'badge-emerald'; }
      else if (totalPts < 7) { label = 'WEAK'; cls = 'badge-crimson'; }
    }
    return { pos, totalPts: totalPts.toFixed(1), avg: avg.toFixed(1), count: posStarters.length, label, cls };
  };

  const posHeatmap = [
    getPosStrength('QB'),
    getPosStrength('RB'),
    getPosStrength('WR'),
    getPosStrength('TE'),
  ];

  // Bye Week Matrix (Weeks 5 - 14)
  const byeWeeks = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14];
  const byeMap = {};
  allPlayers.forEach(p => {
    const bye = p.bye_week || p.bye || null;
    if (bye) byeMap[bye] = (byeMap[bye] || 0) + 1;
  });

  // Start/Sit Toss-up Advisor Calculation
  // Close decisions where a bench player's ceiling (upper) overlaps with a starter's floor (lower)
  const tossups = [];
  bench.forEach(b => {
    if (b.weekly < 5.0) return; // ignore minor bench filler
    starters.forEach(s => {
      const isPosMatch = b.position === s.position || (['RB', 'WR', 'TE'].includes(b.position) && s.slot.startsWith('FLEX'));
      if (isPosMatch && b.upper >= s.lower) {
        const overlap = Number((b.upper - s.lower).toFixed(1));
        tossups.push({
          benchPlayer: b,
          starterPlayer: s,
          overlap,
          advice: `Bench ${b.player_name} (${b.position}) ceiling (${b.upper.toFixed(1)} pts) overlaps Starter ${s.player_name} (${s.slot}) floor (${s.lower.toFixed(1)} pts).`,
        });
      }
    });
  });

  tossups.sort((a, b) => b.overlap - a.overlap);

  root.innerHTML = `
    <!-- Executive Command Center Header -->
    <div class="team-hub-header reveal in">
      <div class="team-hero-card card" style="border-left:4px solid var(--amber)">
        <div class="team-hero-top">
          <div class="team-owner-info">
            <div class="team-owner-avatar">
              ${(() => { const av = safeAvatarUrl(teamMeta.avatar_url); return av ? `<img src="${escapeAttr(av)}" alt="${escapeHtml(teamMeta.display_name)}" class="owner-img" />` : `<div class="owner-avatar-fallback">${escapeHtml((teamMeta.display_name || teamMeta.owner_name || 'T').charAt(0).toUpperCase())}</div>`; })()}
            </div>
            <div>
              <div class="team-title-row">
                <h1 class="team-name">${escapeHtml(teamMeta.team_name || teamMeta.display_name || 'Team Hub')}</h1>
                <span class="badge badge-owner">Owner: @${escapeHtml(teamMeta.display_name || teamMeta.owner_name || 'user')}</span>
                <span class="badge badge-amber mono" style="font-size:12px; font-weight:700" aria-live="polite">Rank ${rankText}</span>
              </div>
              <div class="team-sub-row faint" style="margin-top:4px">
                Roster #${teamMeta.roster_id || selectedId} · 12-team PPR · 2 FLEX
              </div>
            </div>
          </div>
          <div class="team-selector-header-box">
            <span class="kicker" style="display:block; margin-bottom:4px">Switch Team</span>
            ${renderTeamSelector(leagueRosters, selectedId)}
          </div>
        </div>

        <!-- Executive Financial & Power KPI Grid -->
        <div class="team-kpi-grid">
          <div class="kpi-card">
            <span class="kicker">Roster Rank</span>
            <div class="mono kpi-val" style="color:var(--amber)">${rankText}</div>
            <span class="micro faint">12-Team Starter FPTS Leaderboard</span>
          </div>
          <div class="kpi-card">
            <span class="kicker">Total Model $</span>
            <div class="mono kpi-val" style="color:var(--emerald)">$${totalGridironValue}</div>
            <span class="micro faint">Sum of VBD auction values</span>
          </div>
          <div class="kpi-card">
            <span class="kicker">Total Market Consensus $</span>
            <div class="mono kpi-val" style="color:var(--sky)">$${totalMarketValue}</div>
            <div class="micro ${totalGridironValue >= totalMarketValue ? 'text-good' : 'text-bad'}">
              ${totalGridironValue >= totalMarketValue ? '+' : ''}$${totalGridironValue - totalMarketValue} Value Edge
            </div>
          </div>
          <div class="kpi-card">
            <span class="kicker">Starter pts/wk</span>
            <div class="mono kpi-val" style="color:var(--amber)">${totalStarterFPTS.toFixed(1)} <span class="kpi-unit">pts/wk</span></div>
            <span class="micro faint">17-Game: ${totalSeasonProj.toFixed(0)} pts</span>
          </div>
        </div>

        <!-- Position Group Heatmap & Bye Week Matrix -->
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-top:12px; padding-top:12px; border-top:1px solid var(--border)">
          <div>
            <span class="kicker" style="display:block; margin-bottom:6px">Position Group Strength Heatmap</span>
            <div style="display:flex; gap:8px; flex-wrap:wrap">
              ${posHeatmap.map(ph => `
                <div style="background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; padding:6px 10px; flex:1; min-width:80px">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px">
                    <span class="mono" style="font-weight:700; font-size:12px">${ph.pos}</span>
                    <span class="badge ${ph.cls} micro">${ph.label}</span>
                  </div>
                  <div class="mono" style="font-size:13px; font-weight:700; color:var(--text)">${ph.totalPts} <span class="micro faint">pts</span></div>
                </div>
              `).join('')}
            </div>
          </div>

          <div>
            <span class="kicker" style="display:block; margin-bottom:6px">Bye Week Distribution Matrix</span>
            <div class="bye-pills">
              ${byeWeeks.map(w => {
                const count = byeMap[w] || 0;
                const cls = count >= 3 ? 'badge-crimson' : count > 0 ? 'active' : '';
                return `<span class="bye-pill ${cls}" title="Week ${w}: ${count} player(s) on bye">W${w}: <strong>${count}</strong></span>`;
              }).join('')}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Start/Sit Toss-up Advisor Card -->
    <div class="card reveal in" style="margin-top:16px; border:1px solid ${tossups.length ? 'rgba(245,158,11,0.35)' : 'var(--border)'}; background:${tossups.length ? 'rgba(245,158,11,0.03)' : 'var(--surface)'}">
      <div class="card-header" style="border-bottom:1px solid ${tossups.length ? 'rgba(245,158,11,0.2)' : 'var(--border)'}">
        <div style="display:flex; align-items:center; gap:8px">
          <span class="badge ${tossups.length ? 'badge-amber' : 'badge-emerald'}" style="font-size:12px">Start/Sit Advisor</span>
          <span class="micro faint">${tossups.length ? `${tossups.length} Ceiling-Over-Floor Decision(s)` : 'Optimal Lineup Configured'}</span>
        </div>
      </div>
      <div class="card-body" style="padding:12px">
        ${tossups.length ? `
          <div style="display:flex; flex-direction:column; gap:8px">
            ${tossups.slice(0, 3).map(t => `
              <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; background:var(--surface-raised); border:1px solid var(--border); border-radius:10px; padding:10px 12px; flex-wrap:wrap">
                <div style="display:flex; align-items:center; gap:12px">
                  <div style="display:flex; align-items:center; gap:6px">
                    ${playerAvatar(t.benchPlayer, 32)}
                    <div>
                      <span class="mono" style="font-weight:700; color:var(--amber); font-size:12px">[BENCH] ${escapeHtml(t.benchPlayer.player_name)}</span>
                      <div class="micro faint">${posBadge(t.benchPlayer.position)} · ${t.benchPlayer.weekly.toFixed(1)} pts (Ceiling: <strong style="color:var(--emerald)">${t.benchPlayer.upper.toFixed(1)}</strong>)</div>
                    </div>
                  </div>
                  <span class="mono text-bad" style="font-weight:700; font-size:13px">VS</span>
                  <div style="display:flex; align-items:center; gap:6px">
                    ${playerAvatar(t.starterPlayer, 32)}
                    <div>
                      <span class="mono" style="font-weight:700; font-size:12px">[${escapeHtml(t.starterPlayer.slot)}] ${escapeHtml(t.starterPlayer.player_name)}</span>
                      <div class="micro faint">${posBadge(t.starterPlayer.position)} · ${t.starterPlayer.weekly.toFixed(1)} pts (Floor: <strong style="color:var(--crimson)">${t.starterPlayer.lower.toFixed(1)}</strong>)</div>
                    </div>
                  </div>
                </div>
                <div style="display:flex; align-items:center; gap:8px">
                  <span class="badge badge-amber mono">Ceiling Overlap: +${t.overlap} pts</span>
                </div>
              </div>
            `).join('')}
          </div>
        ` : `
          <div style="display:flex; align-items:center; gap:10px; color:var(--emerald)" class="mono micro">
            <span>✓ No bench player ceiling overlaps with a starter's floor. Your starter configuration maximizes point expectation.</span>
          </div>
        `}
      </div>
    </div>

    <!-- Starters Table & Cards -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header">
        <div>
          <h3>Starters (${starters.length} Slots)</h3>
          <span class="kicker">10 Starter Slots · Click any player row or card to open detail breakdown</span>
        </div>
        <span class="badge badge-amber mono" style="font-size:13px; font-weight:700">${totalStarterFPTS.toFixed(1)} Wk Pts</span>
      </div>
      <div class="card-body" style="padding:0">
        <div class="responsive-view">
          <div class="table-wrap" style="border:0; border-radius:0">
            <table aria-label="Starters">
              <caption class="sr-only">Starting lineup with projections and auction values</caption>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Player</th>
                  <th>Matchup</th>
                  <th style="color:var(--amber)">Projected FPTS (Wk/17G)</th>
                  <th style="color:var(--amber)">Model $</th>
                  <th style="color:var(--sky)">Market $</th>
                  <th>Δ $</th>
                  <th>Edge</th>
                  <th>ECR</th>
                  <th>ADP</th>
                  <th>Tier</th>
                  <th>Conformal Interval</th>
                  <th>17G Stat Totals</th>
                  <th>Status</th>
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

    <!-- Bench Table & Cards -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header">
        <div>
          <h3>Bench Roster (${bench.length} Players)</h3>
          <span class="kicker">Depth &amp; upside reserves</span>
        </div>
      </div>
      <div class="card-body" style="padding:0">
        <div class="responsive-view">
          <div class="table-wrap" style="border:0; border-radius:0">
            <table aria-label="Bench roster">
              <caption class="sr-only">Bench players with projections and auction values</caption>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Player</th>
                  <th>Matchup</th>
                  <th style="color:var(--amber)">Projected FPTS (Wk/17G)</th>
                  <th style="color:var(--amber)">Model $</th>
                  <th style="color:var(--sky)">Market $</th>
                  <th>Δ $</th>
                  <th>Edge</th>
                  <th>ECR</th>
                  <th>ADP</th>
                  <th>Tier</th>
                  <th>Conformal Interval</th>
                  <th>17G Stat Totals</th>
                  <th>Status</th>
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

    <!-- IR / Reserve Table & Cards -->
    ${reserve.length ? `
      <div class="card reveal in" style="margin-top:16px">
        <div class="card-header">
          <div>
            <h3>Injured Reserve (${reserve.length} Players)</h3>
            <span class="kicker">IR reserve slots</span>
          </div>
        </div>
        <div class="card-body" style="padding:0">
          <div class="responsive-view">
            <div class="table-wrap" style="border:0; border-radius:0">
              <table aria-label="Injured reserve">
                <caption class="sr-only">Injured reserve players</caption>
                <thead>
                  <tr>
                    <th>Slot</th>
                    <th>Player</th>
                    <th>Matchup</th>
                    <th>Projected FPTS</th>
                    <th>Model $</th>
                    <th>Market $</th>
                    <th>Δ $</th>
                    <th>Edge</th>
                    <th>ECR</th>
                    <th>Conformal Interval</th>
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
  bindTeamSelector(() => {
    renderTeam(root);
  });

  // Bind Player Row & Card Clicks to open Draftea Player Detail Modal (mouse + keyboard)
  root.querySelectorAll('[data-player-id]').forEach(el => {
    const openForEl = () => {
      const pid = el.getAttribute('data-player-id');
      const targetPlayer = allPlayers.find(p => String(p.player_id) === String(pid));
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

function renderPlayerRow(p, isReserve = false) {
  const deltaCls = p.deltaAuction > 0 ? 'text-good' : p.deltaAuction < 0 ? 'text-bad' : 'faint';
  const deltaSign = p.deltaAuction > 0 ? '+' : '';
  const edgeCls = p.edge === 'BUY' ? 'badge-emerald' : p.edge === 'SELL' ? 'badge-crimson' : 'badge-faint';
  const edgeIcon = p.edge === 'BUY' ? '▲ ' : p.edge === 'SELL' ? '▼ ' : '';

  let statText = '—';
  if (p.position === 'QB') statText = `${p.season_pass_yd} PassYd · ${p.season_tds} TD`;
  else if (p.position === 'RB') statText = `${p.season_rush_yd} RushYd · ${p.season_rec_yd} RecYd · ${p.season_tds} TD`;
  else if (p.position === 'WR' || p.position === 'TE') statText = `${p.season_rec_yd} RecYd · ${p.season_rec} Rec · ${p.season_tds} TD`;
  else statText = `${p.season_tds} TD`;

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
      <td class="mono">
        <span style="color:var(--amber); font-weight:700">${p.weekly.toFixed(1)}</span>
        <span class="micro faint"> / ${p.season.toFixed(0)}</span>
      </td>
      <td class="mono"><span class="badge badge-amber" title="${p.gridironUncapped!=null && p.gridironUncapped!==p.gridironAuction ? `Uncapped VOR $${p.gridironUncapped}` : ''}">$${p.gridironAuction}${p.gridironUncapped!=null && p.gridironUncapped!==p.gridironAuction ? ` <span class="micro faint">($${p.gridironUncapped})</span>` : ''}</span></td>
      <td class="mono"><span class="badge badge-sky" title="${p.marketUncapped!=null && p.marketUncapped!==p.marketAuction ? `Uncapped $${p.marketUncapped}` : ''}">$${p.marketAuction}${p.marketUncapped!=null && p.marketUncapped!==p.marketAuction ? ` <span class="micro faint">($${p.marketUncapped})</span>` : ''}</span></td>
      <td class="mono ${deltaCls}">${deltaSign}$${p.deltaAuction}</td>
      <td><span class="badge ${edgeCls}" aria-label="${escapeAttr(p.edge)}">${edgeIcon}${p.edge}</span></td>
      <td class="mono micro">${p.ecr ? `#${p.ecr}${p.ecrPos ? ` (${p.ecrPos})` : ''}` : '—'}</td>
      <td class="mono micro faint">${p.adp ? `#${p.adp}` : '—'}</td>
      <td>${p.tier ? `<span class="badge badge-violet">T${p.tier}</span>` : '—'}</td>
      <td>
        ${intervalBar({ point: p.weekly, low: p.lower, high: p.upper, width: p.width, min: 0, max: 35 })}
      </td>
      <td class="mono micro faint">${escapeHtml(statText)}</td>
      <td>${injuryBadge(p.injury_status)}</td>
    </tr>
  `;
}

function renderPlayerCardItem(p) {
  return `
    <div class="player-card clickable-card" data-player-id="${escapeHtml(p.player_id)}" tabindex="0" role="button" aria-label="Open details for ${escapeAttr(p.player_name || p.player_id)}" style="cursor:pointer">
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
        <span class="badge badge-amber mono" style="font-size:13px" title="${p.gridironUncapped!==p.gridironAuction ? `Uncapped $${p.gridironUncapped}`:''}">$${p.gridironAuction}${p.gridironUncapped!==p.gridironAuction ? `<span style="font-size:10px; color:var(--text-faint)"> ($${p.gridironUncapped})</span>`:''}</span>
      </div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px; margin-bottom:8px" class="mono">
        <div><span class="faint">Model:</span> <strong style="color:var(--amber)">${p.weekly.toFixed(1)} wk</strong></div>
        <div><span class="faint">Market:</span> <span style="color:var(--sky)">$${p.marketAuction}${p.marketUncapped!==p.marketAuction ? `<span style="font-size:10px; color:var(--text-faint)"> ($${p.marketUncapped})</span>`:''}</span></div>
        <div><span class="faint">ECR:</span> ${p.ecr ? `#${p.ecr}` : '—'}</div>
        <div><span class="faint">Edge:</span> <strong style="color:${p.edge==='BUY'?'var(--emerald)':p.edge==='SELL'?'var(--crimson)':'var(--text-muted)'}">${p.edge==='BUY'?'▲ ':p.edge==='SELL'?'▼ ':''}${p.edge}</strong></div>
      </div>
      <div>${intervalBar({ point: p.weekly, low: p.lower, high: p.upper, width: p.width, min: 0, max: 35 })}</div>
    </div>
  `;
}
