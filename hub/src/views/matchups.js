import { fetchMatchups, fetchRoster, fetchComparison } from '../api.js';
import { posBadge, injuryBadge, windBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { userAvatar } from '../components/userAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { intervalBar } from '../components/intervalBar.js';
import { openPlayerModal } from '../components/playerModal.js';
import { computeVbdParams, vbdAuction, vbdAuctionUncapped } from '../components/vbdAuction.js';

// Matchup detail modal state (no inline expand — opens popup)

export async function renderMatchups(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const week = params.get('week') ? Number(params.get('week')) : null;

  const data = await fetchMatchups({ week });
  const currentWeek = data.week ?? week ?? '';
  const league = data.leagueMatchups || [];
  const slate = data.nflSlate || [];

  // Group league matchups by matchup_id to get head-to-head pairs
  const matchupPairs = new Map();
  league.forEach(m => {
    const mid = m.matchup_id;
    if (mid == null) return;
    if (!matchupPairs.has(mid)) matchupPairs.set(mid, []);
    matchupPairs.get(mid).push(m);
  });

  // Fetch all 12 rosters + comparison data for enrichment
  let allTeamMetas = [];
  let processedTeams = new Map();
  let compMap = new Map();

  if (matchupPairs.size > 0) {
    const baseData = await fetchRoster({ roster_id: '1' });
    allTeamMetas = baseData.leagueRosters || baseData.allTeams || [];

    const [allRosters, compData] = await Promise.all([
      Promise.all(allTeamMetas.map(t => fetchRoster({ roster_id: t.roster_id }).catch(() => null))),
      fetchComparison({ limit: 800 }).catch(() => ({ players: [] })),
    ]);

    (compData.players || []).forEach(c => {
      if (c.player_id) compMap.set(String(c.player_id), c);
      if (c.player_name) compMap.set(c.player_name.toLowerCase(), c);
    });
    const vbdParams = computeVbdParams(compData.players || []);

    allRosters.forEach((rData, i) => {
      if (!rData) return;
      const meta = rData.teamMeta || rData.team_info || allTeamMetas[i] || {};
      const rid = String(meta.roster_id || allTeamMetas[i]?.roster_id || '');
      // Adaptive slot assignment — mirrors team.js/roster.js so QB/RB/WR/TE/FLEX counts are correct
      const posCountsM = { QB: 0, RB: 0, WR: 0, TE: 0, FLEX: 0 };
      const starterSlotLabels = ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX1', 'FLEX2', 'K', 'DEF'];
      const starters = (rData.starters || rData.myRoster || []).map((p, idx) => {
        const pos = (p.position || 'UNK').toUpperCase();
        let slot = starterSlotLabels[idx] || `S${idx+1}`;
        if (pos === 'QB') {
          posCountsM.QB++;
          slot = posCountsM.QB === 1 ? 'QB' : `FLEX${++posCountsM.FLEX}`;
        } else if (pos === 'RB') {
          posCountsM.RB++;
          slot = posCountsM.RB <= 2 ? `RB${posCountsM.RB}` : `FLEX${++posCountsM.FLEX}`;
        } else if (pos === 'WR') {
          posCountsM.WR++;
          slot = posCountsM.WR <= 2 ? `WR${posCountsM.WR}` : `FLEX${++posCountsM.FLEX}`;
        } else if (pos === 'TE') {
          posCountsM.TE++;
          slot = posCountsM.TE === 1 ? 'TE' : `FLEX${++posCountsM.FLEX}`;
        } else if (pos === 'K') slot = 'K';
        else if (pos === 'DEF') slot = 'DEF';
        return enrichPlayer(p, compMap, slot, vbdParams);
      });
      const bench = (rData.bench || []).map((p, i) => enrichPlayer(p, compMap, `BN${i+1}`, vbdParams));
      const starterFPTS = starters.reduce((s, p) => s + p.weekly, 0);
      const totalGridiron = [...starters, ...bench].reduce((s, p) => s + p.gridironAuction, 0);
      const totalMarket = [...starters, ...bench].reduce((s, p) => s + p.marketAuction, 0);

      processedTeams.set(rid, {
        roster_id: rid,
        owner_name: meta.display_name || meta.owner_name || `Team ${rid}`,
        team_name: meta.team_name || meta.display_name || `Team ${rid}`,
        avatar_url: meta.avatar_url || null,
        starters,
        bench,
        starterFPTS,
        totalGridiron,
        totalMarket,
      });
    });
  }

  // Build NFL slate lookup by team
  const slateByTeam = new Map();
  slate.forEach(g => {
    slateByTeam.set((g.home_team || g.home || '').toUpperCase(), g);
    slateByTeam.set((g.away_team || g.away || '').toUpperCase(), g);
  });

  const weekPicker = `
    <div class="row" style="gap:8px">
      <span class="kicker">Week</span>
      <div class="filters">
        ${Array.from({length:18},(_,i)=>i+1).map(w=>`<button class="chip ${String(w)===String(currentWeek)?'active':''}" data-week="${w}">${w}</button>`).join('')}
        <button class="chip" data-week="">All</button>
      </div>
    </div>
  `;

  const sortedPairs = [...matchupPairs.entries()].sort((a, b) => a[0] - b[0]);

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Matchups <span class="badge" style="background:var(--color-primary); color:white; vertical-align:middle">Week ${currentWeek || '—'}</span></h1>
      <p>Head-to-head fantasy matchups with Gridiron model predictions vs market consensus. Click any matchup for full slot-by-slot breakdown.</p>
    </div>
    <div class="card reveal in" style="margin-top:12px">
      <div class="card-body">${weekPicker}</div>
    </div>

    <div style="display:flex; flex-direction:column; gap:16px; margin-top:12px">
      ${sortedPairs.length > 0 ? sortedPairs.map(([mid, rosters]) => {
        const teamA = processedTeams.get(String(rosters[0]?.roster_id)) || null;
        const teamB = rosters[1] ? processedTeams.get(String(rosters[1]?.roster_id)) || null : null;
        return renderMatchupCard(teamA, teamB, mid, rosters, slateByTeam);
      }).join('') : `<div class="card reveal in"><div class="empty">No matchups loaded for week ${currentWeek || '—'}. Start the backend server and refresh data.</div></div>`}
    </div>

    <!-- NFL Slate -->
    <div class="card reveal in" style="margin-top:24px">
      <div class="card-header"><h3>NFL Slate</h3><span class="kicker">${slate.length ? `${slate.length} games` : 'no data'}</span></div>
      <div class="card-body" style="padding:0">
        ${slate.length ? `
          <div class="table-wrap" style="border:0; border-radius:0"><table>
            <thead><tr><th>Game</th><th>Stadium</th><th>Time</th><th>Spread</th><th>O/U</th><th>Wind</th><th>Precip</th></tr></thead>
            <tbody>
              ${slate.map(g=>`
                <tr>
                  <td><div class="matchup-game">${teamLogo(g.away_team || g.away, 20)} <span class="mono">${g.away_team || g.away || '—'}</span> <span class="faint">@</span> ${teamLogo(g.home_team || g.home, 20)} <span class="mono">${g.home_team || g.home || '—'}</span></div></td>
                  <td class="faint">${escapeHtml(g.stadium || '—')}</td>
                  <td class="micro" style="color:var(--text-muted)">${escapeHtml(g.gameday || '')} ${escapeHtml(g.gametime || '')}</td>
                  <td class="mono">${g.spread_line != null ? g.spread_line : '—'}</td>
                  <td class="mono">${g.total_line != null ? g.total_line : '—'}</td>
                  <td>${windBadge(g.wind_mph)}</td>
                  <td class="mono" style="font-size:12px">${g.precip_prob != null ? `${g.precip_prob}%` : '—'}</td>
                </tr>
              `).join('')}
            </tbody>
          </table></div>
        ` : `<div class="empty">No NFL schedule for week ${currentWeek || '—'}.</div>`}
      </div>
    </div>
  `;

  // Week picker bindings
  root.querySelectorAll('[data-week]').forEach(btn => {
    btn.addEventListener('click', () => {
      const w = btn.getAttribute('data-week');
      location.hash = `matchups${w ? `?week=${w}` : ''}`;
    });
  });

  // Matchup card click → open modal with full breakdown
  root.querySelectorAll('[data-matchup-id]').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('[data-player-id]')) return;
      const mid = Number(card.getAttribute('data-matchup-id'));
      const pair = sortedPairs.find(([m]) => m === mid);
      if (!pair) return;
      const [, rosters] = pair;
      const teamA = processedTeams.get(String(rosters[0]?.roster_id)) || null;
      const teamB = rosters[1] ? processedTeams.get(String(rosters[1]?.roster_id)) || null : null;
      if (teamA) openMatchupModal(teamA, teamB, mid, slateByTeam, root, processedTeams);
    });
  });

  // Player click → player modal
  root.querySelectorAll('[data-player-id]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const pid = el.getAttribute('data-player-id');
      let found = null;
      processedTeams.forEach(t => {
        const p = [...t.starters, ...t.bench].find(p => String(p.player_id) === pid);
        if (p) found = p;
      });
      if (found) openPlayerModal(found, root);
    });
  });
}

function renderMatchupCard(teamA, teamB, matchupId, rawRosters, slateByTeam) {
  if (!teamA) {
    return `<div class="card reveal in"><div class="empty">Matchup ${matchupId}: Missing roster data</div></div>`;
  }

  const ptsA = teamA.starterFPTS;
  const ptsB = teamB ? teamB.starterFPTS : 0;
  const totalWidth = Math.sqrt(
    teamA.starters.reduce((s, p) => s + p.width * p.width, 0) +
    (teamB ? teamB.starters.reduce((s, p) => s + p.width * p.width, 0) : 0)
  ) || 10;
  const spread = ptsA - ptsB;
  const winProbA = teamB ? Math.round(100 * normalCdf(spread / totalWidth)) : 100;
  const winProbB = 100 - winProbA;

  return `
    <div class="card reveal in matchup-card" data-matchup-id="${matchupId}" style="cursor:pointer">
      <div class="card-header">
        <div style="display:flex; align-items:center; gap:8px">
          <span class="badge badge-faint mono">Match ${matchupId}</span>
          <span class="micro faint">Click for full breakdown</span>
        </div>
        ${winProbA !== winProbB ? `<span class="badge ${winProbA > winProbB ? 'badge-emerald' : 'badge-sky'}" style="font-size:11px">${winProbA > winProbB ? escapeHtml(teamA.team_name) : escapeHtml(teamB?.team_name || '—')} favored</span>` : ''}
      </div>
      <div class="card-body" style="padding:0">
        <!-- Summary Bar -->
        <div style="display:grid; grid-template-columns:1fr auto 1fr; align-items:center; padding:16px; gap:12px">
          <!-- Team A -->
          <div style="display:flex; align-items:center; gap:10px">
            ${userAvatar(teamA, 40)}
            <div>
              <div style="font-weight:700; font-size:15px">${escapeHtml(teamA.team_name)}</div>
              <div class="micro faint">@${escapeHtml(teamA.owner_name)}</div>
            </div>
          </div>

          <!-- Center: Score + Win Prob -->
          <div style="text-align:center; min-width:160px">
            <div style="display:flex; align-items:baseline; justify-content:center; gap:12px">
              <span class="mono" style="font-size:22px; font-weight:800; color:var(--amber)">${ptsA.toFixed(1)}</span>
              <span class="faint" style="font-size:14px">vs</span>
              <span class="mono" style="font-size:22px; font-weight:800; color:var(--sky)">${ptsB.toFixed(1)}</span>
            </div>
            <div style="font-size:11px; margin-top:4px">
              <span class="mono" style="color:${winProbA >= 50 ? 'var(--emerald)' : 'var(--text-muted)'}">${winProbA}%</span>
              <span class="faint" style="margin:0 4px">—</span>
              <span class="mono" style="color:${winProbB >= 50 ? 'var(--emerald)' : 'var(--text-muted)'}">${winProbB}%</span>
            </div>
            <!-- Win prob bar -->
            <div style="height:4px; border-radius:2px; background:var(--surface-raised); margin-top:6px; overflow:hidden; display:flex">
              <div style="width:${winProbA}%; background:var(--amber); border-radius:2px 0 0 2px"></div>
              <div style="width:${winProbB}%; background:var(--sky); border-radius:0 2px 2px 0"></div>
            </div>
          </div>

          <!-- Team B -->
          <div style="display:flex; align-items:center; justify-content:flex-end; gap:10px">
            <div style="text-align:right">
              <div style="font-weight:700; font-size:15px">${escapeHtml(teamB?.team_name || '—')}</div>
              <div class="micro faint">@${escapeHtml(teamB?.owner_name || '—')}</div>
            </div>
            ${teamB ? userAvatar(teamB, 40) : ''}
          </div>
        </div>

        <!-- Financial Summary -->
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:0; border-top:1px solid var(--border)">
          <div style="padding:8px 16px; display:flex; gap:16px; align-items:center; border-right:1px solid var(--border)">
            <span class="micro faint">Gridiron $</span>
            <span class="badge badge-amber mono">$${teamA.totalGridiron}</span>
            <span class="micro faint">Market $</span>
            <span class="badge badge-sky mono">$${teamA.totalMarket}</span>
          </div>
          <div style="padding:8px 16px; display:flex; gap:16px; align-items:center; justify-content:flex-end">
            <span class="micro faint">Gridiron $</span>
            <span class="badge badge-amber mono">$${teamB?.totalGridiron || 0}</span>
            <span class="micro faint">Market $</span>
            <span class="badge badge-sky mono">$${teamB?.totalMarket || 0}</span>
          </div>
        </div>

      </div>
    </div>
  `;
}

function openMatchupModal(teamA, teamB, matchupId, slateByTeam, root, processedTeams) {
  let container = document.getElementById('matchupModalContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'matchupModalContainer';
    document.body.appendChild(container);
  }

  const ptsA = teamA.starterFPTS;
  const ptsB = teamB ? teamB.starterFPTS : 0;
  const totalWidth = Math.sqrt(
    teamA.starters.reduce((s, p) => s + p.width * p.width, 0) +
    (teamB ? teamB.starters.reduce((s, p) => s + p.width * p.width, 0) : 0)
  ) || 10;
  const spread = ptsA - ptsB;
  const winProbA = teamB ? Math.round(100 * normalCdf(spread / totalWidth)) : 100;
  const winProbB = 100 - winProbA;
  const factors = gatherFactors(teamA, teamB, slateByTeam);

  container.innerHTML = `
    <div class="matchup-modal-backdrop" id="matchupModalBackdrop">
      <div class="matchup-modal-card card reveal in" role="dialog" aria-modal="true">
        <button class="modal-close-btn" id="matchupCloseBtn" aria-label="Close modal">✕</button>

        <!-- Header: Team vs Team -->
        <div style="display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:16px; padding-bottom:16px; border-bottom:1px solid var(--border)">
          <div style="display:flex; align-items:center; gap:10px">
            ${userAvatar(teamA, 48)}
            <div>
              <div style="font-weight:700; font-size:17px">${escapeHtml(teamA.team_name)}</div>
              <div class="micro faint">@${escapeHtml(teamA.owner_name)}</div>
            </div>
          </div>
          <div style="text-align:center; min-width:140px">
            <div style="display:flex; align-items:baseline; justify-content:center; gap:12px">
              <span class="mono" style="font-size:26px; font-weight:800; color:var(--amber)">${ptsA.toFixed(1)}</span>
              <span class="faint" style="font-size:14px">vs</span>
              <span class="mono" style="font-size:26px; font-weight:800; color:var(--sky)">${ptsB.toFixed(1)}</span>
            </div>
            <div style="font-size:11px; margin-top:4px">
              <span class="mono" style="color:${winProbA >= 50 ? 'var(--emerald)' : 'var(--text-muted)'}">${winProbA}%</span>
              <span class="faint" style="margin:0 4px">—</span>
              <span class="mono" style="color:${winProbB >= 50 ? 'var(--emerald)' : 'var(--text-muted)'}">${winProbB}%</span>
            </div>
            <div style="height:4px; border-radius:2px; background:var(--surface-raised); margin-top:6px; overflow:hidden; display:flex">
              <div style="width:${winProbA}%; background:var(--amber)"></div>
              <div style="width:${winProbB}%; background:var(--sky)"></div>
            </div>
          </div>
          <div style="display:flex; align-items:center; justify-content:flex-end; gap:10px">
            <div style="text-align:right">
              <div style="font-weight:700; font-size:17px">${escapeHtml(teamB?.team_name || '—')}</div>
              <div class="micro faint">@${escapeHtml(teamB?.owner_name || '—')}</div>
            </div>
            ${teamB ? userAvatar(teamB, 48) : ''}
          </div>
        </div>

        <!-- Financial comparison -->
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:0; margin-top:12px; border:1px solid var(--border); border-radius:10px; overflow:hidden">
          <div style="padding:10px 16px; display:flex; gap:12px; align-items:center; background:var(--surface-raised); border-right:1px solid var(--border)">
            <span class="micro faint">Gridiron $</span>
            <span class="badge badge-amber mono">$${teamA.totalGridiron}</span>
            <span class="micro faint">Market $</span>
            <span class="badge badge-sky mono">$${teamA.totalMarket}</span>
          </div>
          <div style="padding:10px 16px; display:flex; gap:12px; align-items:center; justify-content:flex-end; background:var(--surface-raised)">
            <span class="micro faint">Gridiron $</span>
            <span class="badge badge-amber mono">$${teamB?.totalGridiron || 0}</span>
            <span class="micro faint">Market $</span>
            <span class="badge badge-sky mono">$${teamB?.totalMarket || 0}</span>
          </div>
        </div>

        <!-- Slot-by-slot breakdown -->
        ${renderExpandedMatchup(teamA, teamB, factors)}

        <div style="margin-top:16px; display:flex; justify-content:flex-end">
          <button class="btn btn-ghost" id="matchupDismissBtn">Close</button>
        </div>
      </div>
    </div>
  `;

  const close = () => {
    container.innerHTML = '';
    document.removeEventListener('keydown', handleKey);
  };
  const handleKey = (e) => { if (e.key === 'Escape') close(); };

  document.getElementById('matchupCloseBtn')?.addEventListener('click', close);
  document.getElementById('matchupDismissBtn')?.addEventListener('click', close);
  document.getElementById('matchupModalBackdrop')?.addEventListener('click', (e) => {
    if (e.target.id === 'matchupModalBackdrop') close();
  });
  document.addEventListener('keydown', handleKey);

  // Player clicks inside modal
  container.querySelectorAll('[data-player-id]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const pid = el.getAttribute('data-player-id');
      let found = null;
      processedTeams.forEach(t => {
        const p = [...t.starters, ...t.bench].find(p => String(p.player_id) === pid);
        if (p) found = p;
      });
      if (found) openPlayerModal(found, root);
    });
  });
}

function renderExpandedMatchup(teamA, teamB, factors) {
  // Canonical slot order — ensures QB vs QB, RB1 vs RB1, etc., regardless of roster array order
  const slotOrder = ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX1', 'FLEX2', 'K', 'DEF'];
  const bySlotA = new Map(teamA.starters.map(p => [p.slot, p]));
  const bySlotB = new Map((teamB?.starters || []).map(p => [p.slot, p]));
  // Include any non-canonical slots (e.g., extra FLEX3) after canonical
  const extraSlots = [...new Set([...teamA.starters.map(p=>p.slot), ...(teamB?.starters||[]).map(p=>p.slot)])].filter(s => !slotOrder.includes(s));

  return `
    <!-- Slot-by-Slot Breakdown -->
    <div style="border-top:1px solid var(--border)">
      <div class="table-wrap" style="border:0; border-radius:0">
        <table style="min-width:900px">
          <thead>
            <tr>
              <th style="width:30%">${escapeHtml(teamA.team_name)}</th>
              <th style="text-align:center; width:5%">Slot</th>
              <th style="width:30%; text-align:right">${escapeHtml(teamB?.team_name || '—')}</th>
              <th style="text-align:center; width:10%">Edge</th>
              <th style="text-align:center; width:25%">Intervals</th>
            </tr>
          </thead>
          <tbody>
            ${[...slotOrder, ...extraSlots].map(slot => {
              const pA = bySlotA.get(slot) || null;
              const pB = bySlotB.get(slot) || null;
              // Only render rows where at least one team has that slot
              if (!pA && !pB) return '';
              return renderSlotRow(pA, pB, slot);
            }).join('')}
            <tr style="background:var(--surface-raised); font-weight:700">
              <td>
                <div style="display:flex; align-items:center; gap:8px; padding:4px 0">
                  <span class="mono" style="font-size:16px; color:var(--amber)">${teamA.starterFPTS.toFixed(1)} pts</span>
                </div>
              </td>
              <td style="text-align:center" class="mono micro faint">TOTAL</td>
              <td style="text-align:right">
                <span class="mono" style="font-size:16px; color:var(--sky)">${teamB ? teamB.starterFPTS.toFixed(1) : '0.0'} pts</span>
              </td>
              <td style="text-align:center">
                <span class="mono" style="font-weight:800; color:${teamA.starterFPTS >= (teamB?.starterFPTS || 0) ? 'var(--emerald)' : 'var(--crimson)'}">
                  ${teamA.starterFPTS >= (teamB?.starterFPTS || 0) ? '+' : ''}${(teamA.starterFPTS - (teamB?.starterFPTS || 0)).toFixed(1)}
                </span>
              </td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    ${factors.length > 0 ? `
      <!-- Key Factors & Insights -->
      <div style="border-top:1px solid var(--border); padding:12px 16px">
        <span class="kicker" style="display:block; margin-bottom:8px">Key Factors &amp; Insights</span>
        <div style="display:flex; flex-wrap:wrap; gap:8px">
          ${factors.map(f => `
            <div style="display:inline-flex; align-items:center; gap:6px; padding:6px 10px; background:${f.bg}; border:1px solid ${f.border}; border-radius:8px; font-size:12px; color:${f.color}">
              <span style="font-size:14px">${f.icon}</span>
              <span>${escapeHtml(f.text)}</span>
            </div>
          `).join('')}
        </div>
      </div>
    ` : ''}
  `;
}

function renderSlotRow(pA, pB, slotLabel) {
  const slot = pA?.slot || pB?.slot || slotLabel || `S?`;
  const diffPts = (pA?.weekly || 0) - (pB?.weekly || 0);
  const edgeCls = diffPts > 2 ? 'color:var(--emerald)' : diffPts < -2 ? 'color:var(--crimson)' : 'color:var(--text-muted)';
  const teamColorA = pA ? getTeamColor((pA.team || '').toUpperCase()) : 'transparent';
  const teamColorB = pB ? getTeamColor((pB.team || '').toUpperCase()) : 'transparent';

  return `
    <tr style="--team-accent:${teamColorA}">
      <td>
        ${pA ? `
          <div class="player-cell" data-player-id="${escapeHtml(pA.player_id)}" style="cursor:pointer">
            ${playerAvatar(pA, 30)}
            <div class="player-cell-info">
              <div class="player-cell-name">${escapeHtml(pA.player_name)} ${posBadge(pA.position)}</div>
              <div style="display:flex; gap:8px; align-items:center; margin-top:2px">
                <span class="mono" style="font-weight:700; color:var(--amber); font-size:13px">${pA.weekly.toFixed(1)}</span>
                ${pA.marketWeekly != null && pA.marketWeekly !== pA.weekly ? `<span class="micro faint">mkt ${pA.marketWeekly.toFixed(1)}</span>` : ''}
                <span class="micro faint">${teamLogo(pA.team, 12)} ${escapeHtml(pA.team)} vs ${escapeHtml(pA.opponent_team || 'TBD')}</span>
              </div>
              <div style="display:flex; gap:6px; align-items:center; margin-top:2px">
                <span class="badge badge-amber mono" style="font-size:10px; padding:1px 5px" title="${pA.gridironUncapped!=null && pA.gridironUncapped!==pA.gridironAuction ? `True $${pA.gridironUncapped}`:''}">$${pA.gridironAuction}${pA.gridironUncapped!=null && pA.gridironUncapped!==pA.gridironAuction ? `<span style="font-size:9px; color:var(--text-faint)"> ($${pA.gridironUncapped})</span>`:''}</span>
                <span class="badge badge-sky mono" style="font-size:10px; padding:1px 5px" title="${pA.marketUncapped!=null && pA.marketUncapped!==pA.marketAuction ? `True $${pA.marketUncapped}`:''}">$${pA.marketAuction}${pA.marketUncapped!=null && pA.marketUncapped!==pA.marketAuction ? `<span style="font-size:9px; color:var(--text-faint)"> ($${pA.marketUncapped})</span>`:''}</span>
                ${pA.injury_status ? injuryBadge(pA.injury_status) : ''}
                ${pA.wind_mph > 15 ? `<span class="micro" style="color:var(--crimson)">${Math.round(pA.wind_mph)}mph</span>` : ''}
              </div>
            </div>
          </div>
        ` : '<span class="faint">Empty</span>'}
      </td>
      <td class="mono micro faint" style="text-align:center; font-weight:700">${escapeHtml(pA?.slot || pB?.slot || `S${idx+1}`)}</td>
      <td style="text-align:right">
        ${pB ? `
          <div class="player-cell" data-player-id="${escapeHtml(pB.player_id)}" style="cursor:pointer; justify-content:flex-end">
            <div class="player-cell-info" style="text-align:right">
              <div class="player-cell-name">${posBadge(pB.position)} ${escapeHtml(pB.player_name)}</div>
              <div style="display:flex; gap:8px; align-items:center; justify-content:flex-end; margin-top:2px">
                <span class="micro faint">${escapeHtml(pB.opponent_team || 'TBD')} vs ${escapeHtml(pB.team)} ${teamLogo(pB.team, 12)}</span>
                ${pB.marketWeekly != null && pB.marketWeekly !== pB.weekly ? `<span class="micro faint">mkt ${pB.marketWeekly.toFixed(1)}</span>` : ''}
                <span class="mono" style="font-weight:700; color:var(--sky); font-size:13px">${pB.weekly.toFixed(1)}</span>
              </div>
              <div style="display:flex; gap:6px; align-items:center; justify-content:flex-end; margin-top:2px">
                ${pB.wind_mph > 15 ? `<span class="micro" style="color:var(--crimson)">${Math.round(pB.wind_mph)}mph</span>` : ''}
                ${pB.injury_status ? injuryBadge(pB.injury_status) : ''}
                <span class="badge badge-sky mono" style="font-size:10px; padding:1px 5px" title="${pB.marketUncapped!=null && pB.marketUncapped!==pB.marketAuction ? `True $${pB.marketUncapped}`:''}">$${pB.marketAuction}${pB.marketUncapped!=null && pB.marketUncapped!==pB.marketAuction ? `<span style="font-size:9px; color:var(--text-faint)"> ($${pB.marketUncapped})</span>`:''}</span>
                <span class="badge badge-amber mono" style="font-size:10px; padding:1px 5px" title="${pB.gridironUncapped!=null && pB.gridironUncapped!==pB.gridironAuction ? `True $${pB.gridironUncapped}`:''}">$${pB.gridironAuction}${pB.gridironUncapped!=null && pB.gridironUncapped!==pB.gridironAuction ? `<span style="font-size:9px; color:var(--text-faint)"> ($${pB.gridironUncapped})</span>`:''}</span>
              </div>
            </div>
            ${playerAvatar(pB, 30)}
          </div>
        ` : '<span class="faint" style="float:right">Empty</span>'}
      </td>
      <td style="text-align:center">
        <span class="mono" style="font-weight:700; ${edgeCls}; font-size:12px">
          ${diffPts > 0 ? '+' : ''}${diffPts.toFixed(1)}
        </span>
      </td>
      <td style="text-align:center">
        <div style="display:flex; gap:4px; align-items:center; justify-content:center">
          ${pA ? `<div style="flex:1; max-width:80px">${intervalBar({ point: pA.weekly, low: pA.lower, high: pA.upper, width: pA.width, min: 0, max: 30 })}</div>` : ''}
          ${pB ? `<div style="flex:1; max-width:80px">${intervalBar({ point: pB.weekly, low: pB.lower, high: pB.upper, width: pB.width, min: 0, max: 30 })}</div>` : ''}
        </div>
      </td>
    </tr>
  `;
}

function enrichPlayer(p, compMap, defaultSlot, vbdParams) {
  const pid = String(p.player_id || '');
  const pname = (p.player_name || p.name || pid).toLowerCase();
  const c = compMap.get(pid) || compMap.get(pname) || {};

  const weekly = Number(p.projected_points ?? c.projected_points ?? c.weekly ?? 0);
  const season = Number(c.ros ?? c.marketRos ?? (weekly * 17));
  const width = Number(p.width ?? c.width ?? 5.0);
  const lower = Number(p.projection_lower ?? p.lower ?? (weekly - width / 2));
  const upper = Number(p.projection_upper ?? p.upper ?? (weekly + width / 2));

  const pos = (p.position || p.position_group || 'UNK').toUpperCase();
  // Dynamic VBD: capped $1 bench + uncapped true VOR for tooltip
  const modelSeason = Number(p.model_season_points ?? c.model_season_points ?? (weekly * 17));
  const gridironAuction = (() => {
    if (vbdParams && c.model_season_points != null) return vbdAuction(Number(c.model_season_points), pos, vbdParams);
    if (vbdParams) return vbdAuction(modelSeason, pos, vbdParams);
    if (c.auction != null) return Number(c.auction);
    return Math.max(1, Math.round(Math.max(0, modelSeason - 100) * 0.25));
  })();
  const gridironUncapped = c.auctionUncapped ?? (vbdParams ? vbdAuctionUncapped(c.model_season_points ?? modelSeason, pos, vbdParams) : gridironAuction);
  const marketVbd = vbdParams && c.market_season_points != null ? vbdAuction(Number(c.market_season_points), pos, vbdParams) : null;
  const marketUncapped = c.marketAuctionUncapped ?? (vbdParams && c.market_season_points != null ? vbdAuctionUncapped(Number(c.market_season_points), pos, vbdParams) : null);
  const marketAuction = Number(p.auction_price_paid ?? p.marketAuction ?? c.marketAuction ?? marketVbd ?? Math.max(1, Math.round(gridironAuction * 0.9)));
  const replPts = vbdParams?.replPts[pos] ?? 100;
  const vor = Math.max(0, modelSeason - replPts);
  const deltaAuction = gridironAuction - marketAuction;

  // Market weekly projection (from comparison/consensus if available)
  const marketWeekly = Number(c.market_season_points ? c.market_season_points / 17 : (c.projected_points ?? weekly));

  const slot = p.slot || defaultSlot || 'BENCH';
  const edge = (p.edge || c.edge || 'NEUTRAL').toUpperCase();
  const status = p.injury_status || c.injury_status || null;
  const windMph = Number(p.wind_speed_mph ?? p.wind_mph ?? 0);

  return {
    ...p,
    player_id: pid,
    player_name: p.player_name || p.name || pid,
    position: (p.position || p.position_group || 'UNK').toUpperCase(),
    team: (p.team || '').toUpperCase(),
    opponent_team: p.opponent_team || '',
    weekly,
    marketWeekly,
    season,
    width,
    lower,
    upper,
    vor,
    gridironAuction,
    gridironUncapped,
    marketAuction,
    marketUncapped,
    deltaAuction,
    edge,
    injury_status: status,
    slot,
    wind_mph: windMph,
  };
}

function getSlotLabel(p, idx) {
  const pos = (p.position || 'UNK').toUpperCase();
  const labels = ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX1', 'FLEX2', 'K', 'DEF'];
  return labels[idx] || pos;
}

function gatherFactors(teamA, teamB, slateByTeam) {
  const factors = [];

  const checkWeather = (team, label) => {
    team.starters.forEach(p => {
      if (p.wind_mph > 15) {
        factors.push({
          icon: '💨', text: `${p.player_name} (${label}): ${Math.round(p.wind_mph)}mph wind`,
          bg: 'rgba(239,68,68,0.08)', border: 'rgba(239,68,68,0.2)', color: 'var(--crimson)'
        });
      }
    });
  };

  const checkInjuries = (team, label) => {
    team.starters.forEach(p => {
      if (p.injury_status && p.injury_status !== 'Active') {
        const statusMap = { 'Questionable': '⚠️', 'Doubtful': '🔴', 'Out': '❌', 'IR': '🏥' };
        factors.push({
          icon: statusMap[p.injury_status] || '⚠️',
          text: `${p.player_name} (${label}): ${p.injury_status}`,
          bg: 'rgba(245,158,11,0.08)', border: 'rgba(245,158,11,0.2)', color: 'var(--amber)'
        });
      }
    });
  };

  const checkEdges = (team, label) => {
    const buys = team.starters.filter(p => p.edge === 'BUY');
    const sells = team.starters.filter(p => p.edge === 'SELL');
    if (buys.length > 0) {
      factors.push({
        icon: '📈', text: `${label} has ${buys.length} BUY-rated starter${buys.length > 1 ? 's' : ''}: ${buys.map(p => p.player_name).join(', ')}`,
        bg: 'rgba(16,185,129,0.08)', border: 'rgba(16,185,129,0.2)', color: 'var(--emerald)'
      });
    }
    if (sells.length > 0) {
      factors.push({
        icon: '📉', text: `${label} has ${sells.length} SELL-rated starter${sells.length > 1 ? 's' : ''}: ${sells.map(p => p.player_name).join(', ')}`,
        bg: 'rgba(239,68,68,0.08)', border: 'rgba(239,68,68,0.2)', color: 'var(--crimson)'
      });
    }
  };

  const checkValueEdge = (teamA, teamB) => {
    const deltaA = teamA.totalGridiron - teamA.totalMarket;
    const deltaB = (teamB?.totalGridiron || 0) - (teamB?.totalMarket || 0);
    if (Math.abs(deltaA) > 10 || Math.abs(deltaB) > 10) {
      const betterValue = deltaA > deltaB ? teamA.team_name : teamB?.team_name || '—';
      factors.push({
        icon: '💰', text: `${betterValue} has better Gridiron $ value edge (Δ$${Math.abs(deltaA - deltaB)})`,
        bg: 'rgba(56,189,248,0.08)', border: 'rgba(56,189,248,0.2)', color: 'var(--sky)'
      });
    }
  };

  checkInjuries(teamA, teamA.team_name);
  if (teamB) checkInjuries(teamB, teamB.team_name);
  checkWeather(teamA, teamA.team_name);
  if (teamB) checkWeather(teamB, teamB.team_name);
  checkEdges(teamA, teamA.team_name);
  if (teamB) checkEdges(teamB, teamB.team_name);
  if (teamB) checkValueEdge(teamA, teamB);

  return factors;
}

function normalCdf(x) {
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
  const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x) / Math.SQRT2;
  const t = 1.0 / (1.0 + p * x);
  const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
  return 0.5 * (1.0 + sign * y);
}

function escapeHtml(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}
