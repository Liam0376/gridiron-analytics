import { fetchRoster, fetchTrade, fetchComparison } from '../api.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { computeVbdParams, vbdAuction, vbdAuctionUncapped } from '../components/vbdAuction.js';
import { escapeHtml } from '../lib/escape.js';

export async function renderTrade(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  let selectedA = params.get('team_a') || '1';
  let selectedB = params.get('team_b') || '2';

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Trade</h1>
      <p>Select two teams, pick the players being traded on each side, and analyze Model weekly &amp; ROS trade impact.</p>
    </div>

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-body row align-center" style="gap:16px; flex-wrap:wrap">
        <div style="flex:1; min-width:220px">
          <label class="micro faint" style="display:block; margin-bottom:6px">Team A (Sending Package)</label>
          <select id="selectTeamA" class="search-mini" style="width:100%; padding:8px 12px; font:500 13px "Helvetica Neue", Helvetica, sans-serif; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:8px">
            <option value="">Loading teams…</option>
          </select>
        </div>
        
        <div class="mono faint" style="font-size:18px; font-weight:700; padding-top:16px">⇄</div>

        <div style="flex:1; min-width:220px">
          <label class="micro faint" style="display:block; margin-bottom:6px">Team B (Receiving Package)</label>
          <select id="selectTeamB" class="search-mini" style="width:100%; padding:8px 12px; font:500 13px "Helvetica Neue", Helvetica, sans-serif; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:8px">
            <option value="">Loading teams…</option>
          </select>
        </div>
      </div>
    </div>

    <!-- Live Trade Analysis Banner -->
    <div id="tradeSummaryBanner" class="reveal in" style="margin-top:16px"></div>

    <!-- Dual Roster Checkbox Columns -->
    <div class="grid grid-2 reveal in" style="margin-top:16px">
      <div class="card">
        <div class="card-header row align-between">
          <h3 id="teamAHeader">Team A Roster</h3>
          <span class="micro faint" id="teamASub">0 players selected</span>
        </div>
        <div class="card-body" id="teamARoster" style="padding:0">
          <div class="empty">Loading roster…</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header row align-between">
          <h3 id="teamBHeader">Team B Roster</h3>
          <span class="micro faint" id="teamBSub">0 players selected</span>
        </div>
        <div class="card-body" id="teamBRoster" style="padding:0">
          <div class="empty">Loading roster…</div>
        </div>
      </div>
    </div>

    <div class="card reveal in" style="margin-top:20px; background:var(--surface-raised)">
      <div class="card-header row align-between">
        <h3>Trade VBD</h3>
        <button class="btn btn-primary" id="runVbdBtn">Evaluate</button>
      </div>
      <div class="card-body" id="vbdResult">
        <div class="faint" style="font-size:12px">Click Evaluate for full roster VBD.</div>
      </div>
    </div>
  `;

  const selA = root.querySelector('#selectTeamA');
  const selB = root.querySelector('#selectTeamB');
  const summaryBanner = root.querySelector('#tradeSummaryBanner');
  const rosterAEl = root.querySelector('#teamARoster');
  const rosterBEl = root.querySelector('#teamBRoster');
  const headerA = root.querySelector('#teamAHeader');
  const headerB = root.querySelector('#teamBHeader');
  const subA = root.querySelector('#teamASub');
  const subB = root.querySelector('#teamBSub');
  const vbdBtn = root.querySelector('#runVbdBtn');
  const vbdRes = root.querySelector('#vbdResult');

  const rosterCache = new Map();
  let rosterDataA = null;
  let rosterDataB = null;
  const selectedPidsA = new Set();
  const selectedPidsB = new Set();

  // VOR $ unification — lazy VBD params from comparison (mirrors roster/team/matchups)
  let vbdParams = null;
  let vbdFetchPromise = null;
  async function ensureVbdParams() {
    if (vbdParams) return vbdParams;
    if (vbdFetchPromise) return vbdFetchPromise;
    vbdFetchPromise = (async () => {
      try {
        const comp = await fetchComparison({ limit: 800 });
        const players = comp?.players || [];
        if (players.length) {
          vbdParams = computeVbdParams(players);
        }
      } catch (_) {
        vbdParams = null;
      }
      return vbdParams;
    })();
    return vbdFetchPromise;
  }

  // Populate Team Selectors
  try {
    const baseData = await fetchRoster();
    const allTeamsList = baseData?.allTeams || baseData?.leagueRosters || [];
    if (allTeamsList.length > 0) {
      selA.innerHTML = allTeamsList.map(t => `<option value="${t.roster_id || t.owner_id}" ${String(t.roster_id || t.owner_id) === String(selectedA) ? 'selected' : ''}>${escapeHtml(t.team_name || t.display_name || `Team ${t.roster_id}`)} (${escapeHtml(t.owner_name || t.display_name || '')})</option>`).join('');
      selB.innerHTML = allTeamsList.map(t => `<option value="${t.roster_id || t.owner_id}" ${String(t.roster_id || t.owner_id) === String(selectedB) ? 'selected' : ''}>${escapeHtml(t.team_name || t.display_name || `Team ${t.roster_id}`)} (${escapeHtml(t.owner_name || t.display_name || '')})</option>`).join('');
    }
  } catch (e) {
    console.error('Failed to load team list:', e);
  }

  async function getRosterData(rosterId) {
    const key = String(rosterId);
    if (rosterCache.has(key)) return rosterCache.get(key);
    const data = await fetchRoster({ roster_id: key });
    rosterCache.set(key, data);
    return data;
  }

  async function loadRoster(side) {
    const isA = side === 'A';
    const rosterId = isA ? selA.value : selB.value;
    const targetEl = isA ? rosterAEl : rosterBEl;
    const targetHeader = isA ? headerA : headerB;
    const targetSet = isA ? selectedPidsA : selectedPidsB;

    if (!rosterId) return;

    if (!rosterCache.has(String(rosterId))) {
      targetEl.innerHTML = `<div class="empty">Loading team roster…</div>`;
    }

    const data = await getRosterData(rosterId);
    if (isA) rosterDataA = data;
    else rosterDataB = data;

    const teamName = data?.teamMeta?.team_name || data?.teamMeta?.owner_name || `Team ${rosterId}`;
    targetHeader.textContent = `${teamName} (${isA ? 'Sending' : 'Receiving'})`;

    renderRosterList(targetEl, fullRoster(data), side, targetSet);
    updateSubcounts();
    renderTradeVerdict();
  }

  function updateSubcounts() {
    subA.textContent = `${selectedPidsA.size} player${selectedPidsA.size === 1 ? '' : 's'} selected`;
    subB.textContent = `${selectedPidsB.size} player${selectedPidsB.size === 1 ? '' : 's'} selected`;
  }

  function renderRosterList(container, players, side, selectedSet) {
    if (!players || players.length === 0) {
      container.innerHTML = `<div class="empty">No roster players found</div>`;
      return;
    }

    container.innerHTML = `
      <div style="display:flex; flex-direction:column">
        ${players.map(p => {
          const pid = String(p.player_id || p.id);
          const isChecked = selectedSet.has(pid);
          const gridironPts = Number(p.gridiron_points ?? p.model_points ?? p.projected_points ?? 0).toFixed(1);
          const rosPts = Number(p.model_season_points ?? (gridironPts * 17)).toFixed(0);
          const auctionPrice = p.auction_price_paid ?? p.auction ?? p.marketAuction ?? 0;

          return `
            <label class="row align-between" style="padding:10px 14px; cursor:pointer; background:${isChecked ? 'var(--surface-raised)' : 'transparent'}; border-bottom:1px solid var(--border); transition:background 0.15s; border-left:3px solid ${getTeamColor((p.team||'').toUpperCase())}">
              <div class="row align-center" style="gap:10px">
                <input type="checkbox" class="trade-check" data-side="${side}" data-pid="${pid}" ${isChecked ? 'checked' : ''} style="width:16px; height:16px; cursor:pointer" />
                ${playerAvatar(p, 28)}
                <div>
                  <div class="row align-center" style="gap:6px">
                    <strong style="font-size:13px">${escapeHtml(p.player_name || p.full_name || pid)}</strong>
                    ${posBadge(p.position)}
                    ${p.injury_status ? injuryBadge(p.injury_status) : ''}
                  </div>
                  <div class="micro faint" style="margin-top:2px; display:flex; align-items:center; gap:4px">
                    <span class="slot-tag" style="font-size:10px; font-weight:700; letter-spacing:0.3px; padding:1px 5px; border-radius:4px; background:${p.slot && p.slot !== 'BENCH' && p.slot !== 'IR' ? 'rgba(56,189,248,0.12); color:var(--sky); border:1px solid rgba(56,189,248,0.25)' : p.slot === 'IR' ? 'rgba(244,63,94,0.12); color:var(--crimson); border:1px solid rgba(244,63,94,0.25)' : 'rgba(148,163,184,0.12); color:var(--text-muted); border:1px solid rgba(148,163,184,0.2)'}">${escapeHtml(p.slot || (p.position && !p.team ? 'IR' : 'BENCH'))}</span>
                    <span>Draft Cost: $${auctionPrice}</span> · ${teamLogo(p.team, 14)} <span>${p.team || 'FA'} ${p.opponent_team ? `vs ${p.opponent_team}` : ''}</span>
                  </div>
                </div>
              </div>
              <div style="text-align:right">
                <div class="mono" style="font-weight:700; font-size:13px; color:var(--accent)">${gridironPts} <span class="micro faint">pts/wk</span></div>
                <div class="micro faint mono">${rosPts} pts ROS</div>
              </div>
            </label>
          `;
        }).join('')}
      </div>
    `;

    container.querySelectorAll('.trade-check').forEach(chk => {
      chk.addEventListener('change', (e) => {
        const pid = e.target.dataset.pid;
        const targetSet = e.target.dataset.side === 'A' ? selectedPidsA : selectedPidsB;
        if (e.target.checked) targetSet.add(pid);
        else targetSet.delete(pid);
        updateSubcounts();
        renderTradeVerdict();
      });
    });
  }

  async function renderTradeVerdict() {
    // Ensure VBD params for $ VOR pricing (lazily fetched once)
    await ensureVbdParams();

    const listA = fullRoster(rosterDataA).filter(p => selectedPidsA.has(String(p.player_id || p.id)));
    const listB = fullRoster(rosterDataB).filter(p => selectedPidsB.has(String(p.player_id || p.id)));

    const nameA = rosterDataA?.teamMeta?.team_name || `Team A`;
    const nameB = rosterDataB?.teamMeta?.team_name || `Team B`;

    if (listA.length === 0 && listB.length === 0) {
      summaryBanner.innerHTML = `
        <div class="alert alert-info" style="font-size:13px">
          Check players in <strong>${escapeHtml(nameA)}</strong> and <strong>${escapeHtml(nameB)}</strong> rosters above to calculate trade model impact.
        </div>
      `;
      return;
    }

    // VOR $ logic: for each selected player, use p.auction or vbdAuction(model_season_points) or vbdAuctionUncapped
    const dollarsFor = (p) => {
      if (!p) return 0;
      if (p.auction != null && Number(p.auction) !== 0) return Number(p.auction);
      if (p.gridironAuction != null && Number(p.gridironAuction) !== 0) return Number(p.gridironAuction);
      const pos = (p.position || '').toUpperCase();
      const season = Number(p.model_season_points ?? p.modelSeasonPoints ?? ((p.gridiron_points ?? p.model_points ?? p.projected_points ?? 0) * 17));
      if (vbdParams) {
        const capped = vbdAuction(season, pos, vbdParams);
        const uncapped = vbdAuctionUncapped(season, pos, vbdParams);
        // p.auction fallback already handled; prefer capped for starters, uncapped bench true value when capped collapses to $1
        if (capped > 1) return capped;
        if (uncapped > 0) return Math.max(capped, uncapped);
        return capped;
      }
      // Fallback if params not ready: use paid price or $1 bench
      return Number(p.auction_price_paid ?? p.auction ?? 1);
    };

    const sumA = listA.reduce((s, p) => s + dollarsFor(p), 0);
    const sumB = listB.reduce((s, p) => s + dollarsFor(p), 0);

    // Team A gives listA and receives listB — net $ VOR ROS for Team A
    const netA = sumB - sumA;

    let verdict = 'EVEN / FAIR TRADE';
    let verdictColor = 'var(--text-muted)';
    let verdictBg = 'var(--surface-raised)';

    if (netA >= 8) {
      verdict = `WIN FOR ${nameA.toUpperCase()}`;
      verdictColor = 'var(--emerald)';
      verdictBg = 'rgba(16,185,129,0.1)';
    } else if (netA >= 5) {
      verdict = `LEAN TO ${nameA.toUpperCase()}`;
      verdictColor = 'var(--emerald)';
      verdictBg = 'rgba(16,185,129,0.07)';
    } else if (netA <= -8) {
      verdict = `WIN FOR ${nameB.toUpperCase()}`;
      verdictColor = 'var(--amber)';
      verdictBg = 'rgba(245,158,11,0.1)';
    } else if (netA <= -5) {
      verdict = `LEAN TO ${nameB.toUpperCase()}`;
      verdictColor = 'var(--amber)';
      verdictBg = 'rgba(245,158,11,0.07)';
    }

    summaryBanner.innerHTML = `
      <div class="card" style="border-left:4px solid ${verdictColor}; background:${verdictBg}">
        <div class="card-body">
          <div class="row align-between align-center" style="flex-wrap:wrap; gap:12px">
            <div>
              <div class="micro faint" style="text-transform:uppercase; letter-spacing:0.5px">Trade verdict — $ VOR ROS</div>
              <h2 style="margin:2px 0 0; color:${verdictColor}">${escapeHtml(verdict)}</h2>
            </div>
            <div class="row" style="gap:24px; flex-wrap:wrap">
              <div class="stat">
                <div class="stat-value mono ${netA >= 0 ? 'text-ok' : 'text-bad'}" style="font-size:20px">
                  ${netA >= 0 ? '+' : ''}$${netA.toFixed(0)}
                </div>
                <div class="stat-label">${escapeHtml(nameA)} Net $ VOR ROS</div>
              </div>
              <div class="stat">
                <div class="stat-value mono" style="font-size:20px">$${sumA} vs $${sumB}</div>
                <div class="stat-label">$ VOR Traded · $${sumA} vs $${sumB}</div>
              </div>
            </div>
          </div>

          <div class="divider" style="margin:14px 0"></div>

          <div class="grid grid-2" style="font-size:12px">
            <div>
              <strong style="color:var(--text)">${escapeHtml(nameA)} Gives ($${sumA} $ VOR ROS):</strong>
              ${listA.length ? listA.map(p => {
                const d = dollarsFor(p);
                return `
                <div class="row align-between" style="padding:3px 0">
                  <span>${escapeHtml(p.player_name)} (${p.position})</span>
                  <span class="mono faint">$${d} $ VOR</span>
                </div>
              `}).join('') : '<div class="faint">No players selected</div>'}
            </div>
            <div>
              <strong style="color:var(--text)">${escapeHtml(nameB)} Gives ($${sumB} $ VOR ROS):</strong>
              ${listB.length ? listB.map(p => {
                const d = dollarsFor(p);
                return `
                <div class="row align-between" style="padding:3px 0">
                  <span>${escapeHtml(p.player_name)} (${p.position})</span>
                  <span class="mono faint">$${d} $ VOR</span>
                </div>
              `}).join('') : '<div class="faint">No players selected</div>'}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  async function runVbdEval() {
    vbdRes.innerHTML = `<div class="empty">Running positional VBD analysis…</div>`;
    try {
      const data = await fetchTrade(selA.value, selB.value);
      if (!data) {
        vbdRes.innerHTML = `<div class="alert alert-warn">Trade evaluation returned no result.</div>`;
        return;
      }

      vbdRes.innerHTML = `
        <div class="row align-between" style="margin-bottom:12px">
          <div>
            <div class="micro faint">Recommendation</div>
            <strong style="font-size:15px; color:var(--accent)">${escapeHtml(data.winner || data.recommendation || '—')}</strong>
          </div>
          <div class="mono" style="font-size:13px">
            Diff: <span style="color:var(--amber); font-weight:700">${Number(data.value_difference ?? 0).toFixed(1)}</span> VBD pts ROS
          </div>
        </div>
        <div class="faint" style="font-size:12px">${escapeHtml(data.recommendation || '')}</div>
      `;
    } catch (e) {
      vbdRes.innerHTML = `<div class="alert alert-bad">Trade evaluation failed. See console.</div>`;
    }
  }

  selA.addEventListener('change', () => {
    selectedPidsA.clear();
    loadRoster('A');
  });
  selB.addEventListener('change', () => {
    selectedPidsB.clear();
    loadRoster('B');
  });

  vbdBtn.addEventListener('click', runVbdEval);

  // Initial load
  await Promise.all([loadRoster('A'), loadRoster('B')]);
}

function fullRoster(data) {
  if (!data) return [];
  return [
    ...(data.starters || []),
    ...(Array.isArray(data.bench) ? data.bench : []),
    ...(Array.isArray(data.reserve) ? data.reserve : []),
  ];
}
