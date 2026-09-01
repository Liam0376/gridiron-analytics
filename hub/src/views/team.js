// hub/src/views/team.js — Team Hub Executive Command Center
import { fetchRoster, fetchComparison } from '../api.js';
import { getSelectedTeamId, setSelectedTeamId, renderTeamSelector, bindTeamSelector } from '../components/teamSelector.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { openPlayerModal } from '../components/playerModal.js';
import { computeVbdParams, vbdAuction, vbdAuctionUncapped } from '../components/vbdAuction.js';

export async function renderTeam(root) {
  const selectedId = getSelectedTeamId();

  // Load selected team roster data, full league rosters, and market consensus
  const [rosterData, compData] = await Promise.all([
    fetchRoster({ roster_id: selectedId }),
    fetchComparison({ limit: 800 }).catch(() => ({ players: [] })),
  ]);

  const leagueRosters = rosterData.leagueRosters || rosterData.allTeams || [];
  const teamMeta = rosterData.teamMeta || rosterData.team_info || {};

  // Build lookup map for market comparison data
  const compMap = new Map();
  (compData.players || []).forEach(c => {
    if (c.player_id) compMap.set(String(c.player_id), c);
    if (c.player_name) compMap.set(c.player_name.toLowerCase(), c);
  });
  // Compute dynamic VBD auction params from comparison data (mirrors comparison.py + auction.js)
  const vbdParams = computeVbdParams(compData.players || []);

  // Helper to enrich player objects with rich data
  const enrichPlayer = (p, defaultSlot = 'BENCH') => {
    const pid = String(p.player_id || '');
    const pname = (p.player_name || p.name || pid).toLowerCase();
    const c = compMap.get(pid) || compMap.get(pname) || {};

    const weekly = Number(p.projected_points ?? c.projected_points ?? c.weekly ?? 0);
    const season = Number(c.ros ?? c.marketRos ?? (weekly * 17));
    const width = Number(p.width ?? c.width ?? 5.0);
    const lower = Number(p.projection_lower ?? p.lower ?? (weekly - width / 2));
    const upper = Number(p.projection_upper ?? p.upper ?? (weekly + width / 2));

    const pos = (p.position || p.position_group || 'UNK').toUpperCase();
    const modelSeason = Number(p.model_season_points ?? c.model_season_points ?? (p._neutral_points != null ? p._neutral_points * 17 : weekly * 17));
    // Dynamic VBD: capped $1 bench, plus uncapped true VOR $ for tooltip
    const gridironAuction = Number(p.gridironAuction ?? c.auction ?? (c.model_season_points != null ? vbdAuction(Number(c.model_season_points), pos, vbdParams) : vbdAuction(modelSeason, pos, vbdParams)) ?? 1);
    const gridironUncapped = Number(c.auctionUncapped ?? (c.model_season_points != null ? vbdAuctionUncapped(Number(c.model_season_points), pos, vbdParams) : vbdAuctionUncapped(modelSeason, pos, vbdParams)) ?? gridironAuction);
    // Market $ = VBD market auction or actual paid price (paid takes precedence for drafted players)
    const marketVbd = c.market_season_points != null ? vbdAuction(Number(c.market_season_points), pos, vbdParams) : null;
    const marketUncapped = c.marketAuctionUncapped ?? (c.market_season_points != null ? vbdAuctionUncapped(Number(c.market_season_points), pos, vbdParams) : null);
    const marketAuction = Number(p.auction_price_paid ?? p.marketAuction ?? c.marketAuction ?? marketVbd ?? Math.max(1, Math.round(gridironAuction * 0.9)));
    const replPts = vbdParams.replPts[pos] ?? 0;
    const vor = Math.max(0, modelSeason - replPts);
    const deltaAuction = gridironAuction - marketAuction;

    const slot = p.slot || defaultSlot;
    const ecr = c.fp_ecr ?? p.fp_ecr ?? null;
    const ecrPos = c.fp_ecr_pos ?? p.fp_ecr_pos ?? null;
    const adp = c.fp_adp ?? p.fp_adp ?? null;
    const tier = c.fp_tier ?? c.tier ?? p.tier ?? null;
    const edge = (p.edge || c.edge || 'NEUTRAL').toUpperCase();
    const status = p.injury_status || c.injury_status || null;

    let rec = 'START';
    if (slot.startsWith('BN') || slot === 'BENCH' || slot === 'IR') {
      rec = weekly >= 12.0 ? 'POTENTIAL START' : 'BENCH';
    } else {
      rec = width > 7.0 ? 'TOSS-UP' : weekly >= 10.0 ? 'CONFIDENT' : 'RISK';
    }

    const passYd = Math.round(c.market_season_stats?.passing_yards ?? (p.pass_yd ? p.pass_yd * 17 : (pos === 'QB' ? weekly * 16.5 * 17 : 0)));
    const rushYd = Math.round(c.market_season_stats?.rushing_yards ?? (p.rush_yd ? p.rush_yd * 17 : (pos === 'RB' ? weekly * 5.2 * 17 : pos === 'QB' ? weekly * 1.4 * 17 : 0)));
    const recYd = Math.round(c.market_season_stats?.receiving_yards ?? (p.rec_yd ? p.rec_yd * 17 : ((pos === 'WR' || pos === 'TE') ? weekly * 5.6 * 17 : pos === 'RB' ? weekly * 2.1 * 17 : 0)));
    const recs = Math.round(c.market_season_stats?.receptions ?? (p.receptions ? p.receptions * 17 : ((pos === 'WR' || pos === 'TE') ? weekly * 0.46 * 17 : pos === 'RB' ? weekly * 0.28 * 17 : 0)));
    const tds = Number((c.market_season_stats?.total_tds ?? (weekly * 0.52 * 17 / 10)).toFixed(1));

    return {
      ...p,
      player_id: pid,
      player_name: p.player_name || p.name || pid,
      position: pos,
      team: (p.team || '').toUpperCase(),
      opponent_team: p.opponent_team || '',
      weekly,
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
      ecr,
      ecrPos,
      adp,
      tier,
      edge,
      injury_status: status,
      slot,
      recommendation: rec,
      season_pass_yd: passYd,
      season_rush_yd: rushYd,
      season_rec_yd: recYd,
      season_rec: recs,
      season_tds: tds,
    };
  };

  // Map 10 starter slots explicitly (QB, RB1, RB2, WR1, WR2, TE, FLEX1, FLEX2, K, DEF)
  const rawStarters = rosterData.starters || rosterData.myRoster || [];
  const rawBench = rosterData.bench || [];
  const rawReserve = rosterData.reserve || [];

  const starterSlotLabels = ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX1', 'FLEX2', 'K', 'DEF'];
  const posCounts = { QB: 0, RB: 0, WR: 0, TE: 0, FLEX: 0, K: 0, DEF: 0 };

  const starters = rawStarters.map((p, idx) => {
    const pos = (p.position || 'UNK').toUpperCase();
    let slot = starterSlotLabels[idx] || `STARTER ${idx + 1}`;
    if (pos === 'QB') {
      posCounts.QB++;
      slot = posCounts.QB === 1 ? 'QB' : `FLEX${++posCounts.FLEX}`;
    } else if (pos === 'RB') {
      posCounts.RB++;
      slot = posCounts.RB <= 2 ? `RB${posCounts.RB}` : `FLEX${++posCounts.FLEX}`;
    } else if (pos === 'WR') {
      posCounts.WR++;
      slot = posCounts.WR <= 2 ? `WR${posCounts.WR}` : `FLEX${++posCounts.FLEX}`;
    } else if (pos === 'TE') {
      posCounts.TE++;
      slot = posCounts.TE === 1 ? 'TE' : `FLEX${++posCounts.FLEX}`;
    } else if (pos === 'K') {
      slot = 'K';
    } else if (pos === 'DEF') {
      slot = 'DEF';
    }
    return enrichPlayer({ ...p, slot }, slot);
  });

  const bench = rawBench.map((p, i) => enrichPlayer({ ...p, slot: `BN${i + 1}` }, `BN${i + 1}`));
  const reserve = rawReserve.map((p, i) => enrichPlayer({ ...p, slot: `IR${i + 1}` }, `IR${i + 1}`));
  const allPlayers = [...starters, ...bench, ...reserve];

  // Fetch all 12 rosters concurrently to calculate true League Rank
  let rankText = '#— of 12';
  try {
    const allRostersData = await Promise.all(
      leagueRosters.map(t => fetchRoster({ roster_id: t.roster_id }).catch(() => null))
    );
    const rankedTeams = allRostersData
      .filter(Boolean)
      .map(rd => {
        const teamStarters = rd.starters || rd.myRoster || [];
        const fpts = teamStarters.reduce((s, p) => s + Number(p.projected_points || 0), 0);
        return { roster_id: String(rd.teamMeta?.roster_id || rd.team_info?.roster_id || ''), fpts };
      })
      .sort((a, b) => b.fpts - a.fpts);

    const myRankIdx = rankedTeams.findIndex(t => String(t.roster_id) === String(selectedId));
    if (myRankIdx !== -1) {
      rankText = `#${myRankIdx + 1} of 12`;
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
              ${teamMeta.avatar_url
                ? `<img src="${teamMeta.avatar_url}" alt="${escapeHtml(teamMeta.display_name)}" class="owner-img" />`
                : `<div class="owner-avatar-fallback">${escapeHtml((teamMeta.display_name || teamMeta.owner_name || 'T').charAt(0).toUpperCase())}</div>`}
            </div>
            <div>
              <div class="team-title-row">
                <h1 class="team-name">${escapeHtml(teamMeta.team_name || teamMeta.display_name || 'Team Hub')}</h1>
                <span class="badge badge-owner">Owner: @${escapeHtml(teamMeta.display_name || teamMeta.owner_name || 'user')}</span>
                <span class="badge badge-amber mono" style="font-size:12px; font-weight:700">Rank ${rankText}</span>
              </div>
              <div class="team-sub-row faint" style="margin-top:4px">
                Sleeper Roster #${teamMeta.roster_id || selectedId} · 12-Team Full PPR · 2 FLEX
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
            <span class="kicker">Total Gridiron $ VOR</span>
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
            <span class="kicker">Starter Projected FPTS</span>
            <div class="mono kpi-val" style="color:var(--amber)">${totalStarterFPTS.toFixed(1)} <span class="kpi-unit">pts/wk</span></div>
            <span class="micro faint">17-Game: ~${totalSeasonProj.toFixed(0)} pts</span>
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
          <span class="badge ${tossups.length ? 'badge-amber' : 'badge-emerald'}" style="font-size:12px">START/SIT TOSS-UP ADVISOR</span>
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
            <table>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Player</th>
                  <th>Matchup</th>
                  <th style="color:var(--amber)">Projected FPTS (Wk/17G)</th>
                  <th style="color:var(--amber)">Gridiron $</th>
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
            <table>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Player</th>
                  <th>Matchup</th>
                  <th style="color:var(--amber)">Projected FPTS (Wk/17G)</th>
                  <th style="color:var(--amber)">Gridiron $</th>
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
              <table>
                <thead>
                  <tr>
                    <th>Slot</th>
                    <th>Player</th>
                    <th>Matchup</th>
                    <th>Projected FPTS</th>
                    <th>Gridiron $</th>
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

  // Bind Player Row & Card Clicks to open Draftea Player Detail Modal
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

  let statText = '—';
  if (p.position === 'QB') statText = `${p.season_pass_yd} PassYd · ${p.season_tds} TD`;
  else if (p.position === 'RB') statText = `${p.season_rush_yd} RushYd · ${p.season_rec_yd} RecYd · ${p.season_tds} TD`;
  else if (p.position === 'WR' || p.position === 'TE') statText = `${p.season_rec_yd} RecYd · ${p.season_rec} Rec · ${p.season_tds} TD`;
  else statText = `${p.season_tds} TD`;

  return `
    <tr data-player-id="${escapeHtml(p.player_id)}" data-team="${p.team || ''}" class="clickable-row" style="cursor:pointer; --team-accent:${getTeamColor((p.team||'').toUpperCase())}">
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
      <td class="mono"><span class="badge badge-amber" title="${p.gridironUncapped!=null && p.gridironUncapped!==p.gridironAuction ? `True VOR $${p.gridironUncapped}` : ''}">$${p.gridironAuction}${p.gridironUncapped!=null && p.gridironUncapped!==p.gridironAuction ? ` <span class="micro faint">($${p.gridironUncapped})</span>` : ''}</span></td>
      <td class="mono"><span class="badge badge-sky" title="${p.marketUncapped!=null && p.marketUncapped!==p.marketAuction ? `True $${p.marketUncapped}` : ''}">$${p.marketAuction}${p.marketUncapped!=null && p.marketUncapped!==p.marketAuction ? ` <span class="micro faint">($${p.marketUncapped})</span>` : ''}</span></td>
      <td class="mono ${deltaCls}">${deltaSign}$${p.deltaAuction}</td>
      <td><span class="badge ${edgeCls}">${p.edge}</span></td>
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
        <span class="badge badge-amber mono" style="font-size:13px" title="${p.gridironUncapped!==p.gridironAuction ? `True $${p.gridironUncapped}`:''}">$${p.gridironAuction}${p.gridironUncapped!==p.gridironAuction ? `<span style="font-size:10px; color:var(--text-faint)"> ($${p.gridironUncapped})</span>`:''}</span>
      </div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px; margin-bottom:8px" class="mono">
        <div><span class="faint">Gridiron:</span> <strong style="color:var(--amber)">${p.weekly.toFixed(1)} wk</strong></div>
        <div><span class="faint">Market:</span> <span style="color:var(--sky)">$${p.marketAuction}${p.marketUncapped!==p.marketAuction ? `<span style="font-size:10px; color:var(--text-faint)"> ($${p.marketUncapped})</span>`:''}</span></div>
        <div><span class="faint">ECR:</span> ${p.ecr ? `#${p.ecr}` : '—'}</div>
        <div><span class="faint">Edge:</span> <strong style="color:${p.edge==='BUY'?'var(--emerald)':p.edge==='SELL'?'var(--crimson)':'var(--text-muted)'}">${p.edge}</strong></div>
      </div>
      <div>${intervalBar({ point: p.weekly, low: p.lower, high: p.upper, width: p.width, min: 0, max: 35 })}</div>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}
