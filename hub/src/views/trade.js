import { fetchRoster, fetchTrade, fetchComparison, fetchMeta, fetchDraftInfo } from '../api.js';
import { getLeagueEcon } from '../lib/league.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { computeVbdParams, vbdAuction, vbdAuctionUncapped } from '../components/vbdAuction.js';
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
  const depthEl = root.querySelector('#tradeDepth');

  const rosterCache = new Map();
  let rosterDataA = null;
  let rosterDataB = null;
  const selectedPidsA = new Set();
  const selectedPidsB = new Set();
  // Expanded player rows (gauges/detail) survive roster re-renders.
  // Keyed `side:pid`; renderRosterList re-applies open state from this set.
  const expandedPids = new Set();

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
          // why league-aware: $/VOR scales with teams/budget/roster.
          const league = await getLeagueEcon(fetchMeta, fetchDraftInfo).catch(() => null);
          vbdParams = computeVbdParams(players, league);
        }
      } catch (_) {
        vbdParams = null;
      }
      return vbdParams;
    })();
    return vbdFetchPromise;
  }

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
  // why token match, not substring: 'ir' matches 'first', 'd' matches
  // anything. Mirrors backend calculate_rest_of_season_value discounts
  // (questionable 0.85, doubtful/out 0.60) plus IR-family DNP statuses.
  function injuryMult(status) {
    const toks = String(status || '').toLowerCase().split(/[^a-z]+/).filter(Boolean);
    if (toks.includes('questionable')) return 0.85;
    if (toks.some((t) => ['doubtful', 'out', 'ir', 'pup', 'nfi', 'suspended'].includes(t))) return 0.6;
    return 1.0;
  }
  // why ?? 1 on null AND <= 0: parent emits null for unknown (ros row
  // missing); FantasyHub defaults to 0 for the same case. Both mean
  // "unknown", never "no games left" for display purposes — discounting on
  // unknown invents precision, and zeroing on it blanks the banner. ROS
  // sums exclude such players instead (see rosStats).
  function remWeight(p) {
    if (p.remaining_games == null) return 1;
    const n = Number(p.remaining_games);
    if (!Number.isFinite(n) || n <= 0) return 1;
    return Math.min(1, n / 17);
  }
  // ROS stat totals for a selected package. Players without known remaining
  // games (null on parent, 0-default on FantasyHub) are EXCLUDED from sums
  // (counted in excluded) — never scaled by invented weeks.
  // Returns { tot, excluded }.
  function rosStats(list) {
    const tot = { pass_yd: 0, pass_td: 0, rush_yd: 0, rush_td: 0, rec: 0, rec_yd: 0, rec_td: 0 };
    let excluded = 0;
    for (const p of list) {
      const rem = Number(p.remaining_games);
      if (p.remaining_games == null || !Number.isFinite(rem) || rem <= 0) { excluded++; continue; }
      const g = perGameAvgs(p);
      const w = Number(p.remaining_games);
      tot.pass_yd += g.proj_pass_yd * w; tot.pass_td += g.proj_pass_td * w;
      tot.rush_yd += g.proj_rush_yd * w; tot.rush_td += g.proj_rush_td * w;
      tot.rec += g.proj_rec * w; tot.rec_yd += g.proj_rec_yd * w;
      tot.rec_td += g.proj_rec_td * w;
    }
    return { tot, excluded };
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
    renderTradeVerdict();
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
        renderTradeVerdict();
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

  // ROS stat-impact summary for the verdict banner. Values are per-game
  // season averages scaled by remaining_games (rosStats) — the honest
  // week-agnostic impact of the packages. No $ slot invention here: unequal
  // counts show as a directional note; exact waiver value comes from the
  // server Evaluate below (shadow-gated).
  function tradeStatImpactHtml(listA, listB, nameA, nameB) {
    const ra = rosStats(listA), rb = rosStats(listB);
    const f0 = (v) => (Math.round(v)).toLocaleString('en-US');
    const f1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
    const rows = [
      ['Pass', 'pass_yd', 'pass_td', f0, f1],
      ['Rush', 'rush_yd', 'rush_td', f0, f1],
      ['Rec', 'rec_yd', 'rec_td', f0, f1],
    ].map(([label, yk, tk, fy, ft]) => {
      const ay = ra.tot[yk], at = ra.tot[tk], by = rb.tot[yk], bt = rb.tot[tk];
      const dy = by - ay, dt = bt - at;
      const cls = (v) => v > 0 ? 'text-ok' : (v < 0 ? 'text-bad' : 'faint');
      return `<div class="row align-between mono" style="padding:2px 0; font-size:12px">`
        + `<span class="faint" style="width:44px">${label}</span>`
        + `<span>${fy(ay)} yd · ${ft(at)} TD</span>`
        + `<span class="faint">→</span>`
        + `<span>${fy(by)} yd · ${ft(bt)} TD</span>`
        + `<span class="${cls(dy)}" style="min-width:110px; text-align:right">${dy >= 0 ? '+' : ''}${fy(dy)} yd · ${dt >= 0 ? '+' : ''}${ft(dt)} TD</span></div>`;
    }).join('');
    const excl = ra.excluded + rb.excluded;
    // Slot counts: directional only. A sends m, receives n → gains m-n slots.
    const na = listA.length, nb = listB.length;
    const slotNote = na === nb
      ? `Even player count (${na} ↔ ${nb}) — no open slots change hands.`
      : (na > nb
        ? `${escapeHtml(nameA)} sends ${na}, receives ${nb} — gains ${na - nb} open slot${na - nb > 1 ? 's' : ''}. See Evaluate below for waiver value.`
        : `${escapeHtml(nameB)} sends ${nb}, receives ${na} — gains ${nb - na} open slot${nb - na > 1 ? 's' : ''}. See Evaluate below for waiver value.`);
    // Confidence from mean interval width (heuristic bands, labeled as such).
    const widths = [...listA, ...listB].map((p) => Number(p.width)).filter((w) => Number.isFinite(w));
    const avgW = widths.length ? widths.reduce((s, w) => s + w, 0) / widths.length : NaN;
    const conf = !Number.isFinite(avgW) ? '' : (avgW >= 7
      ? `<span style="color:var(--amber)">Low confidence — wide intervals (avg width ${avgW.toFixed(1)})</span>`
      : (avgW <= 5
        ? `<span style="color:var(--emerald)">High confidence — tight intervals (avg width ${avgW.toFixed(1)})</span>`
        : `<span class="faint">Medium confidence (avg width ${avgW.toFixed(1)})</span>`));
    return `<div style="font-size:12px">`
      + `<div class="micro faint" style="text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px">ROS stat impact — ${escapeHtml(nameA)} gives ↔ ${escapeHtml(nameB)} gives (net for ${escapeHtml(nameA)})</div>`
      + rows
      + (excl ? `<div class="micro faint" style="margin-top:4px">ROS excludes ${excl} player${excl > 1 ? 's' : ''} with unknown schedule data.</div>` : '')
      + `<div class="micro" style="margin-top:6px">${slotNote}</div>`
      + (conf ? `<div class="micro" style="margin-top:2px">${conf}</div>` : '')
      + `</div>`;
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
    // why discount AFTER capped/uncapped selection (not on season input):
    // pre-scaling pushes starters under `capped > 1` into the uncapped bench
    // floor, which re-inflates them (compression, not discount) and
    // double-penalizes via the /17 inside uncapped. p.modelAuction branch
    // removed (dead on raw roster — only exists post-enrichPlayer, which
    // trade.js never calls); modelSeasonPoints camelCase removed (server
    // sends snake_case, so it always fell to the *17 fallback).
    const dollarsFor = (p) => {
      if (!p) return 0;
      let base;
      // why auction_value fallback: FantasyHub items carry auction_value and
      // ros instead of auction/model_season_points. Same alias chain as rows.
      const auc = Number(p.auction ?? p.auction_value);
      if ((p.auction ?? p.auction_value) != null && Number.isFinite(auc) && auc !== 0) {
        base = auc;
      } else {
        const pos = (p.position || '').toUpperCase();
        const season = Number(p.model_season_points ?? p.ros ?? ((p.model_points ?? p.projected_points ?? p.weekly ?? 0) * 17));
        if (vbdParams) {
          const capped = vbdAuction(season, pos, vbdParams);
          const uncapped = vbdAuctionUncapped(season, pos, vbdParams);
          // prefer capped for starters, uncapped bench true value when capped collapses to $1
          if (capped > 1) base = capped;
          else if (uncapped > 0) base = Math.max(capped, uncapped);
          else base = capped;
        } else {
          // Fallback if params not ready: use paid price or $1 bench
          base = Number(p.auction_price_paid ?? p.amount_paid ?? p.auction ?? p.auction_value ?? 1);
        }
      }
      // why finite-choke: server numerics can arrive as non-numeric strings;
      // one NaN base poisons the whole side sum → NaN verdict. Floor to 0.
      const val = base * injuryMult(p.injury_status) * remWeight(p);
      return Number.isFinite(val) ? Math.max(0, val) : 0;
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
      <div class="card" style="border-top:1px solid ${verdictColor}; background:${verdictBg}">
        <div class="card-body">
          <div class="row align-between align-center" style="flex-wrap:wrap; gap:12px">
            <div>
              <div class="micro faint" style="text-transform:uppercase; letter-spacing:0.5px">Trade verdict: $ VOR ROS</div>
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

          ${tradeStatImpactHtml(listA, listB, nameA, nameB)}

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
      // why pass checked packages: the server scopes slot math to traded_a/b
      // (full rosters would measure bench depth, not open slots). Hub
      // fallback ignores these params harmlessly.
      const data = await fetchTrade(selA.value, selB.value, {
        tradedA: [...selectedPidsA], tradedB: [...selectedPidsB],
      });
      if (!data) {
        vbdRes.innerHTML = `<div class="alert alert-warn">Trade evaluation returned no result.</div>`;
        return;
      }
      const slotBlock = tradeSlotHtml(data);

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
        ${slotBlock}
      `;
    } catch (e) {
      vbdRes.innerHTML = `<div class="alert alert-bad">Trade evaluation failed. See console.</div>`;
    }
  }

  // Server slot context for the Evaluate panel. Present only when the model
  // backend answered with package params (hub fallback lacks these keys —
  // skip silently, never render undefined).
  function tradeSlotHtml(data) {
    const ga = Number(data.slots_gained_a ?? 0), gb = Number(data.slots_gained_b ?? 0);
    if (!ga && !gb) return '';
    const ua = Number(data.slot_uplift_a ?? 0), ub = Number(data.slot_uplift_b ?? 0);
    const na = Array.isArray(data.slot_waiver_a) ? data.slot_waiver_a : [];
    const nb = Array.isArray(data.slot_waiver_b) ? data.slot_waiver_b : [];
    const rule = data.slot_rule === 'experimental' ? 'experimental' : 'baseline';
    const line = (side, gained, uplift, names) => gained
      ? `<div style="padding:2px 0">Team ${escapeHtml(side)} gains ${gained} open slot${gained > 1 ? 's' : ''}`
        + (names.length ? ` — waiver: ${names.map((n) => escapeHtml(String(n))).join(', ')}` : '')
        + ` (+${uplift.toFixed(1)} pts ROS marginal uplift)</div>`
      : '';
    return `<div class="divider" style="margin:12px 0"></div>`
      + `<div style="font-size:12px"><div class="micro faint" style="text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px">`
      + `Roster slots <span class="faint">(${escapeHtml(rule)}${rule === 'baseline' ? ' — informational, not in verdict' : ' — folded into verdict'})</span></div>`
      + line('A', ga, ua, na) + line('B', gb, ub, nb) + `</div>`;
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
