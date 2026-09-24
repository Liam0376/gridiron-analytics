import { fetchRoster, fetchTrade } from '../api.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { statGaugesRow } from '../components/statGauges.js';
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
          <select id="selectTeamA" class="search-mini" title="Select Team A" style="width:100%; padding:8px 12px; font:500 13px "Helvetica Neue", Helvetica, sans-serif; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:8px">
            <option value="">Loading teams…</option>
          </select>
        </div>
        
        <div class="mono faint" style="font-size:18px; font-weight:700; padding-top:16px">⇄</div>

        <div style="flex:1; min-width:220px">
          <label class="micro faint" style="display:block; margin-bottom:6px">Team B (Receiving Package)</label>
          <select id="selectTeamB" class="search-mini" title="Select Team B" style="width:100%; padding:8px 12px; font:500 13px "Helvetica Neue", Helvetica, sans-serif; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:8px">
            <option value="">Loading teams…</option>
          </select>
        </div>
      </div>
    </div>

    <!-- Live Trade Analysis Banner -->
    <div id="tradeSummaryBanner" class="reveal in" style="margin-top:16px"></div>

    <!-- Dual Roster Columns — always side by side, internal scroll -->
    <div class="trade-cols reveal in" style="margin-top:16px">
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

    <!-- Post-trade depth (position groups after the hypothetical swap) -->
    <div id="tradeDepth" class="reveal in" style="margin-top:16px"></div>
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
  const depthEl = root.querySelector('#tradeDepth');

  const rosterCache = new Map();
  let rosterDataA = null;
  let rosterDataB = null;
  const selectedPidsA = new Set();
  const selectedPidsB = new Set();
  // Expanded player rows (gauges/detail) survive roster re-renders.
  // Keyed `side:pid`; renderRosterList re-applies open state from this set.
  const expandedPids = new Set();
  // Verdict auto-grades (debounced) on every pick change — one server
  // eval covers packages, market and slot credit, so the old $ banner
  // and the Evaluate button are gone.
  let verdictTimer = null;

  // -- Trade stat helpers (client-side only, no new endpoints) --
  // Two roster shapes: parent hub items carry full-SEASON stat totals
  // (pass_yds, rush_yds, ...) while FantasyHub items carry native WEEKLY
  // proj_* fields. Prefer native weeklies when present; otherwise divide
  // season totals by 17 for an honest per-game average labeled "avg" —
  // never presented as model weeklies (no weekly stat source exists on
  // the parent; weekly_projections persists points only, pipeline frozen).
  const _num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
  function perGameAvgs(p) {
    if (p.proj_pass_yd != null || p.proj_rush_yd != null
        || p.proj_rec_yd != null || p.proj_rec != null) {
      return {
        proj_pass_yd: _num(p.proj_pass_yd), proj_pass_td: _num(p.proj_pass_td),
        proj_rush_yd: _num(p.proj_rush_yd), proj_rush_td: _num(p.proj_rush_td),
        proj_rec: _num(p.proj_rec), proj_rec_yd: _num(p.proj_rec_yd),
        proj_rec_td: _num(p.proj_rec_td),
      };
    }
    return {
      proj_pass_yd: _num(p.pass_yds) / 17, proj_pass_td: _num(p.pass_tds) / 17,
      proj_rush_yd: _num(p.rush_yds) / 17, proj_rush_td: _num(p.rush_tds) / 17,
      proj_rec: _num(p.receptions) / 17, proj_rec_yd: _num(p.rec_yds) / 17,
      proj_rec_td: _num(p.rec_tds) / 17,
    };
  }
  function statPreview(p) {
    const pos = (p.position || '').toUpperCase();
    const g = perGameAvgs(p);
    const f1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
    const f2 = (v) => (Math.round(v * 100) / 100).toFixed(2);
    if (pos === 'QB') return `${f1(g.proj_pass_yd)} PaYd · ${f2(g.proj_pass_td)} PaTD · ${f1(g.proj_rush_yd)} RuYd avg`;
    if (pos === 'RB') return `${f1(g.proj_rush_yd)} RuYd · ${f2(g.proj_rush_td)} RuTD · ${f1(g.proj_rec)} Rec avg`;
    if (pos === 'WR' || pos === 'TE') return `${f1(g.proj_rec)} Rec · ${f1(g.proj_rec_yd)} RecYd avg`;
    return '';
  }
  // Expandable row detail: per-game stat gauges + interval + matchup line.
  // why Number() coerce: statGauge interpolates into title/aria-label
  // unescaped — only finite numbers may pass, never raw strings.
  function tradeDetailHtml(p) {
    const pos = (p.position || '').toUpperCase();
    const g = perGameAvgs(p);
    const gauges = statGaugesRow(pos, {
      proj_pass_yd: g.proj_pass_yd || null, proj_pass_td: g.proj_pass_td || null,
      proj_rush_yd: g.proj_rush_yd || null, proj_rush_td: g.proj_rush_td || null,
      proj_rec: g.proj_rec || null, proj_rec_yd: g.proj_rec_yd || null,
      proj_rec_td: g.proj_rec_td || null, proj_fgm: null, proj_xpm: null,
    });
    const pts = Number(p.model_points ?? p.projected_points ?? p.weekly ?? 0);
    const lo = Number(p.projection_lower ?? p.lower ?? Math.max(0, pts - 5));
    const hi = Number(p.projection_upper ?? p.upper ?? pts + 5);
    const w = Number(p.width ?? (hi - lo) / 2);
    const opp = p.opponent_team ? `vs ${escapeHtml(String(p.opponent_team))}` : 'no game';
    const inj = p.injury_status ? ` · ${escapeHtml(String(p.injury_status))}` : '';
    const rem = p.remaining_games == null ? 'sched unknown' : `${escapeHtml(String(p.remaining_games))} games left`;
    return `${gauges}<div class="micro mono faint" style="margin-top:8px; text-align:center">`
      + `Range ${lo.toFixed(1)} – ${hi.toFixed(1)} (width ${w.toFixed(1)}) · ${opp}${inj} · ${rem}</div>`;
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
    queueVerdict();
    renderDepth();
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
          const modelPts = Number(p.model_points ?? p.projected_points ?? p.weekly ?? 0).toFixed(1);
          const rosPts = Number(p.model_season_points ?? p.ros ?? (modelPts * 17)).toFixed(0);
          const auctionPrice = p.auction_price_paid ?? p.auction ?? p.marketAuction ?? 0;
          const preview = statPreview(p);
          const expKey = `${side}:${pid}`;
          const isOpen = expandedPids.has(expKey);

          return `
            <label class="row align-between" style="padding:10px 14px; cursor:pointer; background:${isChecked ? 'var(--surface-raised)' : 'transparent'}; border-bottom:1px solid var(--border); transition:background 0.15s; border-top:1px solid ${getTeamColor((p.team||'').toUpperCase())}">
              <div class="row align-center" style="gap:10px">
                <input type="checkbox" class="trade-check" data-side="${side}" data-pid="${pid}" ${isChecked ? 'checked' : ''} title="Select ${escapeHtml(p.player_name || p.full_name || pid)} for trade" style="width:16px; height:16px; cursor:pointer" />
                <span style="width:8px; height:8px; border-radius:50%; background:${getTeamColor((p.team||'').toUpperCase())}; flex-shrink:0" aria-hidden="true"></span>
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
                  ${preview ? `<div class="micro mono faint" style="margin-top:2px">${escapeHtml(preview)}</div>` : ''}
                </div>
              </div>
              <div style="text-align:right">
                <div class="mono" style="font-weight:700; font-size:13px; color:var(--accent)">${modelPts} <span class="micro faint">pts/wk</span></div>
                <div class="micro faint mono">${rosPts} pts ROS</div>
                <button class="trade-expand" data-side="${side}" data-pid="${escapeHtml(pid)}" title="Show projected stats" style="margin-top:4px; font-size:11px; background:transparent; color:var(--text-muted); border:1px solid var(--border); border-radius:6px; padding:1px 8px; cursor:pointer">${isOpen ? '▾ stats' : '▸ stats'}</button>
              </div>
            </label>
            <div class="trade-detail" data-side="${side}" data-pid="${escapeHtml(pid)}" style="display:${isOpen ? 'block' : 'none'}; padding:10px 14px; border-bottom:1px solid var(--border); background:var(--surface-raised)">
              ${tradeDetailHtml(p)}
            </div>
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
        queueVerdict();
        renderDepth();
      });
    });

    // why preventDefault + stopPropagation: the expander lives inside the
    // row <label>, where any click would otherwise toggle the checkbox too.
    container.querySelectorAll('.trade-expand').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const key = `${btn.dataset.side}:${btn.dataset.pid}`;
        const panel = container.querySelector(`.trade-detail[data-side="${btn.dataset.side}"][data-pid="${btn.dataset.pid}"]`);
        if (expandedPids.has(key)) {
          expandedPids.delete(key);
          btn.innerHTML = '▸ stats';
          if (panel) panel.style.display = 'none';
        } else {
          expandedPids.add(key);
          btn.innerHTML = '▾ stats';
          if (panel) panel.style.display = 'block';
        }
      });
    });
  }

  // Post-trade depth: position groups after the hypothetical swap, so
  // "does this leave me thin at RB" is answered visually. Slot-agnostic
  // grouping (counts + weekly totals), no slot recompute — kept players +
  // incoming (➕) per group; sent players listed dimmed (➖) for reference.
  const POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'FLEX', 'K', 'DEF'];
  function depthSideHtml(data, sentSet, incoming, teamName) {
    if (!data) return '';
    // why finite-choke here too: NaN weekly poisons sort order and renders
    // as "NaN" via toFixed. Same _num discipline as the banner helpers.
    const pw = (p) => {
      // why p.weekly last: FantasyHub roster items carry weekly/ros instead
      // of model_points/model_season_points. Same chain everywhere.
      const n = Number(p.model_points ?? p.projected_points ?? p.weekly ?? 0);
      return Number.isFinite(n) ? n : 0;
    };
    const sentIds = sentSet || new Set();
    const incomingIds = new Set((incoming || []).map((p) => String(p.player_id || p.id)));
    const groups = {};
    for (const p of fullRoster(data)) {
      const pos = (p.position || 'UNK').toUpperCase();
      (groups[pos] = groups[pos] || []).push(p);
    }
    for (const p of (incoming || [])) {
      const pos = (p.position || 'UNK').toUpperCase();
      (groups[pos] = groups[pos] || []).push({ ...p, _incoming: true });
    }
    const keys = Object.keys(groups).sort((a, b) => {
      const ia = POS_ORDER.indexOf(a), ib = POS_ORDER.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    const groupsHtml = keys.map((pos) => {
      const members = groups[pos].slice().sort((x, y) => pw(y) - pw(x));
      const kept = members.filter((p) => !p._incoming && !sentIds.has(String(p.player_id || p.id)));
      const wk = kept.reduce((s, p) => s + pw(p), 0);
      const cards = members.map((p) => {
        const pid = String(p.player_id || p.id);
        const isIn = p._incoming || incomingIds.has(pid);
        const isOut = !isIn && sentIds.has(pid);
        const state = isIn ? 'in' : isOut ? 'out' : 'kept';
        return `<div class="depth-card depth-${state}">
          ${playerAvatar(p, 34)}
          <div style="flex:1; min-width:0">
            <div class="depth-name">${escapeHtml(p.player_name || pid)}</div>
            <div class="micro faint">${posBadge(pos)} · <span class="mono">${pw(p).toFixed(1)}</span></div>
          </div>
          <span class="depth-tag">${isIn ? 'IN' : isOut ? 'OUT' : ''}</span>
        </div>`;
      }).join('');
      return `<div class="depth-group">
        <div class="depth-group-head"><strong>${escapeHtml(pos)}</strong><span class="faint"> · ${kept.length} kept · ${wk.toFixed(1)}/wk</span></div>
        <div class="depth-cards">${cards}</div>
      </div>`;
    }).join('');
    return `<div><div class="depth-team">${escapeHtml(teamName)} <span class="faint">post-trade</span></div>${groupsHtml}</div>`;
  }
  function renderDepth() {
    if (!depthEl) return;
    if (!rosterDataA && !rosterDataB) { depthEl.innerHTML = ''; return; }
    const listA = fullRoster(rosterDataA).filter((p) => selectedPidsA.has(String(p.player_id || p.id)));
    const listB = fullRoster(rosterDataB).filter((p) => selectedPidsB.has(String(p.player_id || p.id)));
    if (!listA.length && !listB.length) { depthEl.innerHTML = ''; return; }
    const nameA = rosterDataA?.teamMeta?.team_name || 'Team A';
    const nameB = rosterDataB?.teamMeta?.team_name || 'Team B';
    depthEl.innerHTML = `<div class="card"><div class="card-body">`
      + `<div class="micro faint" style="text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px">Post-trade depth by position</div>`
      + `<div class="grid grid-2" style="font-size:12px">`
      + depthSideHtml(rosterDataA, selectedPidsA, listB, nameA)
      + depthSideHtml(rosterDataB, selectedPidsB, listA, nameB)
      + `</div></div></div>`;
  }

  // Single auto-grading verdict (debounced). One server eval covers
  // packages, market and slot credit — the old $ banner, stat soup and
  // Evaluate button are gone.
  function queueVerdict() {
    clearTimeout(verdictTimer);
    verdictTimer = setTimeout(loadVerdict, 400);
  }
  async function loadVerdict() {
    const nameA = rosterDataA?.teamMeta?.team_name || 'Team A';
    const nameB = rosterDataB?.teamMeta?.team_name || 'Team B';
    if (!selectedPidsA.size && !selectedPidsB.size) {
      summaryBanner.innerHTML = `<div class="alert alert-info" style="font-size:13px">`
        + `Tick players on both sides to grade the trade.</div>`;
      return;
    }
    summaryBanner.innerHTML = `<div class="card"><div class="card-body"><div class="empty" style="padding:8px">Grading trade…</div></div></div>`;
    let data = null;
    try {
      data = await fetchTrade(selA.value, selB.value, {
        tradedA: [...selectedPidsA], tradedB: [...selectedPidsB],
      });
    } catch (_) { /* fall through to honest-empty */ }
    if (!data || data.cold) {
      summaryBanner.innerHTML = `<div class="alert alert-warn" style="font-size:13px">Couldn\u2019t grade this trade right now.</div>`;
      return;
    }
    summaryBanner.innerHTML = verdictHtml(data, nameA, nameB,
      fullRoster(rosterDataA).filter(p => selectedPidsA.has(String(p.player_id || p.id))),
      fullRoster(rosterDataB).filter(p => selectedPidsB.has(String(p.player_id || p.id))));
  }
  // Plain-language verdict: who wins, the weekly exchange, market check,
  // slot credit. No $ VOR, no stat tables. Package rows come from the
  // server when it evaluated picks, else from the local roster objects
  // (legacy model-backend shape carries no packages key).
  function verdictHtml(data, nameA, nameB, listA = [], listB = []) {
    const headline = data.winner === 'Even' ? 'Fair trade' : `${data.winner} wins the trade`;
    const ma = data.market_a != null ? Number(data.market_a).toLocaleString('en-US') : null;
    const mb = data.market_b != null ? Number(data.market_b).toLocaleString('en-US') : null;
    const toRow = (p) => ({
      player_id: p.player_id || p.id, sleeper_id: p.sleeper_id || null,
      player_name: p.player_name || p.full_name, position: p.position,
      team: p.team, weekly: Number(p.model_points ?? p.projected_points ?? p.weekly ?? 0),
      market: p.auction ?? p.marketAuction ?? null,
    });
    const rowsA = (data.packages?.a?.length ? data.packages.a : listA.map(toRow));
    const rowsB = (data.packages?.b?.length ? data.packages.b : listB.map(toRow));
    // One coherent unit everywhere: weekly points, summed from the same
    // rows shown below (the old subline mixed VOR/wk in and matched nothing).
    const sumWk = (rows) => rows.reduce((s, p) => s + Number(p.weekly ?? 0), 0);
    const givesWk = sumWk(rowsA).toFixed(1);
    const getsWk = sumWk(rowsB).toFixed(1);
    const modelD = Number(data.value_difference ?? 0);
    const marketD = (ma != null && mb != null) ? (Number(data.market_b) - Number(data.market_a)) : null;
    const marketRel = (marketD != null && (Number(data.market_a) + Number(data.market_b)) > 0)
      ? Math.abs(marketD) / (Number(data.market_a) + Number(data.market_b)) : 0;
    const disagree = marketD != null && Math.abs(modelD) >= 20 && marketRel >= 0.10
      && ((modelD > 0) !== (marketD > 0));
    const pkgRow = (pl) => `
      <div class="mini-row">
        ${playerAvatar(pl, 28)}
        <div style="flex:1; min-width:0">
          <div class="mini-name">${escapeHtml(pl.player_name || '')}</div>
          <div class="micro faint">${posBadge(pl.position)} ${teamLogo(pl.team, 12)}</div>
        </div>
        <div style="text-align:right">
          <div class="mono" style="font-weight:700; font-size:13px">${Number(pl.weekly ?? 0).toFixed(1)}<span class="micro faint">/wk</span></div>
          ${pl.market != null ? `<div class="micro faint">mkt ${Number(pl.market).toLocaleString('en-US')}</div>` : ''}
        </div>
      </div>`;
    const s = data.slots;
    const credit = (side, gained, cval, names) => {
      if (!gained) return '';
      const fill = names && names.length ? ` — adds ${names.map((n) => escapeHtml(String(n))).join(', ')}` : '';
      return `<div class="micro" style="margin-top:4px">+${gained} bench spot${gained > 1 ? 's' : ''} for ${escapeHtml(side)}${fill} <span class="faint">(+${Number(cval).toFixed(0)} ROS)</span></div>`;
    };
    return `<div class="card"><div class="card-body">
      <div class="kicker">Trade verdict</div>
      <h2 class="verdict-headline">${escapeHtml(headline)}</h2>
      <div class="micro faint" style="margin-bottom:8px">${escapeHtml(nameA)} gives ${givesWk}/wk · gets ${getsWk}/wk${ma && mb ? ` · market ${ma} vs ${mb}` : ''}</div>
      ${disagree ? `<div class="alert alert-warn" style="font-size:12px; margin-bottom:8px">Model and market disagree here — the model likes the ${modelD > 0 ? 'incoming' : 'outgoing'} side, real leagues pay more for the other. Trust the market on stars, the model on depth.</div>` : ''}
      <div class="signal-cols">
        <div><div class="kicker" style="margin-bottom:4px">${escapeHtml(nameA)} gives</div>${rowsA.map(pkgRow).join('') || '<div class="empty">—</div>'}</div>
        <div><div class="kicker" style="margin-bottom:4px">${escapeHtml(nameB)} gives</div>${rowsB.map(pkgRow).join('') || '<div class="empty">—</div>'}</div>
      </div>
      ${s ? credit(nameA, s.gained_a, s.credit_a_ros, s.fill_a) + credit(nameB, s.gained_b, s.credit_b_ros, s.fill_b) : ''}
    </div></div>`;
  }

  selA.addEventListener('change', () => {
    selectedPidsA.clear();
    loadRoster('A');
  });
  selB.addEventListener('change', () => {
    selectedPidsB.clear();
    loadRoster('B');
  });

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
