// hub/src/views/auction.js — orchestrator. Public API: renderAuction(root).
// Split from a 940-line monolith on 2026-09-01:
//   - lib/auctionMath.js     pure math (VBD, replacement, $/VOR)
//   - views/auction/state.js localStorage draft state
//   - views/auction/bidAdvice.js  live bid advice
//   - views/auction/table.js table render + sort + modals

import { fetchProjections, fetchComparison } from '../api.js';
import { posBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { trapFocus } from '../lib/focusTrap.js';
import { escapeHtml, escapeAttr } from '../lib/escape.js';
import {
  BUDGET,
  SEASON_GAMES,
  edgeBadgeAuction,
  deltaSeasonBadge,
  computeAuctionMath,
  mergeComparisonPlayers,
} from '../lib/auctionMath.js';
import { loadDraftState, resetDraftState } from './auction/state.js';
import { liveAdviceFor } from './auction/bidAdvice.js';
import { tableHeaders, tableBody, bindTableEvents, showDraftModal, parseSort, sortPlayers } from './auction/table.js';

export async function renderAuction(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const budget = Number(params.get('budget') || BUDGET);
  const focusPid = params.get('focus') || null;

  const [data, compRaw] = await Promise.all([
    fetchProjections({}),
    fetchComparison({ limit: 800 }).catch(() => ({ players: [], count: 0, fetched_at: null, meta: {} })),
  ]);
  let players = data.players || [];
  mergeComparisonPlayers(players, compRaw);

  if (!players.length) {
    root.innerHTML = `
      <div class="hero reveal in"><h1>Auction Draft</h1><p>No projection data. Run start.sh to populate.</p></div>`;
    return;
  }

  const compById = new Map((compRaw.players || []).map(c => [String(c.player_id), c]));
  const compByNamePos = new Map();
  for (const c of (compRaw.players || [])) {
    const key = `${(c.player_name || '').toLowerCase().replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim()}|${(c.position || '').toUpperCase()}`;
    compByNamePos.set(key, c);
  }

  const hasComparison = compById.size > 0;
  let compareAuctionEnabled = hasComparison;
  try {
    const v = localStorage.getItem('ffba-auction-compare');
    if (v === '0') compareAuctionEnabled = false;
    if (v === '1' && hasComparison) compareAuctionEnabled = true;
  } catch (_) {
    // localStorage unavailable in private mode
  }

  const state = loadDraftState();

  const math = computeAuctionMath(players, compRaw, compById, compByNamePos, state, { budget });
  const {
    rosPlayers, allRanked, posGroups, posBudget, flexBudget, nominationTargets,
    myRosterPlayers, myRosterCount, mySpent, myRemaining, maxBid, slotsLeft,
    draftedCount, availablePlayers, budget: usedBudget,
  } = math;

  const buyCount = [...compById.values()].filter(c => c.edge === 'BUY').length;
  const sellCount = [...compById.values()].filter(c => c.edge === 'SELL').length;
  const marketCovered = [...compById.values()].filter(c => c.market_season_points != null || c.market_points != null).length;

  const activePos = params.get('pos') || 'ALL';
  const auctionEdge = params.get('edge') || 'ALL';
  const { sortKey: auctionSortKey, sortDir: auctionSortDir } = parseSort(params);

  let filteredPlayers = activePos === 'ALL'
    ? [...availablePlayers]
    : availablePlayers.filter(p => (p.position || '').toUpperCase() === activePos);
  if (hasComparison && compareAuctionEnabled && auctionEdge !== 'ALL') {
    filteredPlayers = filteredPlayers.filter(p => (p.edge || 'NEUTRAL') === auctionEdge);
  }
  filteredPlayers = sortPlayers(filteredPlayers, auctionSortKey, auctionSortDir);

  const focusedPlayer = focusPid ? allRanked.find(p => String(p.player_id) === String(focusPid)) : null;
  const myNeeds = math.myNeeds;
  const liveAdvice = focusedPlayer ? liveAdviceFor(focusedPlayer, state, myRemaining, maxBid, myNeeds, slotsLeft) : null;

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Auction Draft <span class="badge" style="background:var(--color-accent,#16A34A); color:white; margin-left:8px; vertical-align:middle">$${usedBudget}</span></h1>
      <p>Market season projections · ECR/ADP tiers.</p>
    </div>

    ${hasComparison ? `
    <div class="kpi-row reveal in" style="margin-top:12px">
      <div class="kpi-card" style="border-left:3px solid var(--emerald)">
        <div class="kpi-label">BUY edges — season</div>
        <div class="kpi-value" style="color:var(--emerald)">${buyCount}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill good" style="width:${Math.min(100, Math.round((buyCount / Math.max(1, Math.min(40, compById.size / 6))) * 100))}%"></div></div>
        <div class="micro faint" style="font-size:11px; margin-top:6px">Model season ≥ +51 pts vs FantasyPros season (or rank ≥12 better than ECR)</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--crimson)">
        <div class="kpi-label">SELL flags — overpriced</div>
        <div class="kpi-value" style="color:var(--crimson)">${sellCount}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill bad" style="width:${Math.min(100, Math.round((sellCount / Math.max(1, Math.min(40, compById.size / 6))) * 100))}%"></div></div>
        <div class="micro faint" style="font-size:11px; margin-top:6px">FantasyPros season ≥ +51 pts vs Model · avoid paying sticker</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--sky)">
        <div class="kpi-label">Market coverage (season)</div>
        <div class="kpi-value" style="color:var(--sky)">${marketCovered} / ${compById.size}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill" style="background:var(--sky); width:${Math.round((marketCovered / Math.max(1, compById.size)) * 100)}%"></div></div>
        <div class="micro faint" style="font-size:11px; margin-top:6px">FantasyPros season projections (596, YDS/TDS) + ECR 519/ADP 695 CSVs · Sleeper weekly fallback 98 starters</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--amber)">
        <div class="kpi-label">Auction vs Market</div>
        <div class="kpi-value" style="font-size:14px; line-height:1.2">VOR $ from Model<br><span style="font:600 11px Helvetica Neue, Helvetica,sans-serif; color:var(--text-muted); letter-spacing:0.04em; text-transform:uppercase">$${usedBudget} × ${math.posGroups.length} teams · ${compareAuctionEnabled ? 'Market Δ shown' : 'toggle Market to see Δ'}</span></div>
        <div style="display:flex; gap:6px; margin-top:8px"><button class="chip ${compareAuctionEnabled ? 'active' : ''}" id="toggleAuctionCompare" style="font-size:11px">${compareAuctionEnabled ? '✓ Market + ECR on' : 'Show Market + ECR'}</button><button class="chip" id="copyModelVsMarketCsv" style="font-size:11px">Copy Model vs Market CSV</button></div>
      </div>
    </div>
    ` : `<div class="alert alert-info reveal in" style="margin-top:12px">Market comparison not loaded. Showing model only.</div>`}

    <div class="card reveal in" style="margin-top:12px; border-left:3px solid var(--crimson); background: linear-gradient(90deg, rgba(239,68,68,0.08), transparent)">
      <div class="card-body" style="display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:10px 12px">
        <span class="kicker" style="color:var(--crimson)">● Draft Live</span>
        <span id="draftCountdown" class="mono" style="font-size:18px; font-weight:700; color:var(--crimson)">60:00</span>
        <span class="micro faint">until draft — board frozen to FP season 596 + Week 10 model • <span class="mono" style="color:var(--text-muted)">VOR $200/12</span></span>
        <span style="flex:1"></span>
        <button class="chip" id="fullscreenAuction" title="Fullscreen draft board (F)">⛶ Fullscreen</button>
        <button class="chip" id="printAuction" title="Print board (⌘P)">⎙ Print</button>
        <button class="chip" id="resetCountdown" title="Reset 60-min timer">↺ Reset 60m</button>
      </div>
    </div>

    <div class="kpi-row reveal in" style="margin-top:12px">
      <div class="kpi-card">
        <div class="kpi-label">My Budget</div>
        <div class="kpi-value mono" style="color:${myRemaining > 50 ? 'var(--color-accent)' : myRemaining > 20 ? 'var(--amber)' : 'var(--crimson)'}">$${myRemaining}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill ${myRemaining > 100 ? 'good' : myRemaining > 30 ? 'ok' : 'bad'}" style="width:${(myRemaining / usedBudget * 100).toFixed(0)}%"></div></div>
        <div class="micro faint">spent $${mySpent} / $${usedBudget}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Max Bid</div>
        <div class="kpi-value mono">$${Math.max(0, maxBid)}</div>
        <div class="micro faint">${slotsLeft} roster slots left</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">My Roster</div>
        <div class="kpi-value mono">${myRosterCount}/14</div>
        <div class="micro faint">${myRosterPlayers.map(p => (p.position || '').toUpperCase()).join(', ') || 'empty'}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Draft Progress</div>
        <div class="kpi-value mono">${draftedCount}/${12 * 14}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill ok" style="width:${(draftedCount / (12 * 14) * 100).toFixed(0)}%"></div></div>
        <div class="micro faint">${availablePlayers.length} available</div>
      </div>
    </div>

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Budget Allocation</h3><span class="kicker">recommended spend by position</span></div>
      <div class="card-body" style="display:flex; gap:12px; flex-wrap:wrap">
        ${posGroups.map(pos => {
          const b = posBudget[pos];
          const spent = myRosterPlayers.filter(p => (p.position || '').toUpperCase() === pos).reduce((s, p) => s + (state.drafted[p.player_id]?.price || 0), 0);
          return `<div style="flex:1; min-width:100px; text-align:center; padding:8px; background:var(--surface-raised); border-radius:8px; border:1px solid var(--border)">
            ${posBadge(pos)}
            <div class="mono" style="font-size:18px; margin:4px 0; color:${pos === 'K' || pos === 'DEF' ? 'var(--text-muted)' : 'var(--text)'}">$${b.recommended}</div>
            <div class="micro faint">${b.slots} slot${b.slots > 1 ? 's' : ''} · $${b.perSlot}/slot</div>
            ${spent > 0 ? `<div class="micro" style="color:var(--amber)">spent $${spent}</div>` : ''}
          </div>`;
        }).join('')}
        <div style="flex:1; min-width:100px; text-align:center; padding:8px; background:var(--surface-raised); border-radius:8px; border:1px solid var(--border)">
          <span class="badge" style="background:var(--amber-dim); color:var(--amber)">FLEX</span>
          <div class="mono" style="font-size:18px; margin:4px 0">$${Math.max(0, flexBudget)}</div>
          <div class="micro faint">2 slots, split RB/WR/TE</div>
        </div>
      </div>
    </div>

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Nomination Strategy</h3><span class="kicker">nominate these to drain opponents</span></div>
      <div class="card-body" style="font:400 13px Helvetica Neue, Helvetica,sans-serif; color:var(--text-muted); line-height:1.6">
        <div class="alert alert-ok" style="margin-bottom:12px">Nominate players at positions you've filled (or don't need yet). Force opponents to spend early while you save budget for YOUR targets. <strong>Prefer high Market $ but lower Model $</strong> — let others overpay where Market is hot but Model is cool (SELL).</div>
        <div style="display:flex; gap:8px; flex-wrap:wrap">
          ${nominationTargets.map(p => `
            <div style="padding:6px 10px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; display:flex; align-items:center; gap:6px; ${p.edge === 'BUY' ? 'border-left:3px solid var(--emerald)' : p.edge === 'SELL' ? 'border-left:3px solid var(--crimson)' : ''}">
              ${playerAvatar(p, 24)}
              ${posBadge(p.position)}
              <strong style="font:600 12px Helvetica Neue, Helvetica,sans-serif">${escapeHtml(p.player_name)}</strong>
              ${teamLogo(p.team, 14)}
              <span class="badge" style="background:var(--amber-dim); color:var(--amber)">$${p.auction}</span>
              ${compareAuctionEnabled && hasComparison ? edgeBadgeAuction(p.edge) : ''}
              ${compareAuctionEnabled && p.marketRos != null ? `<span class="mono" style="font-size:10px; color:var(--text-faint)">mkt ${(Number(p.marketRos)).toFixed(0)}</span>` : ''}
            </div>
          `).join('')}
        </div>
        ${nominationTargets.length === 0 ? '<div class="micro faint">Fill some roster spots first to generate nomination targets.</div>' : ''}
      </div>
    </div>

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Draft Strategy</h3><span class="kicker">$200 auction</span></div>
      <div class="card-body" style="font:400 13px Helvetica Neue, Helvetica,sans-serif; color:var(--text-muted); line-height:1.6">
        <ol style="margin:0; padding-left:18px">
          <li><strong>Stars &amp; Scrubs:</strong> Spend 60-70% ($150-175) on 4-5 elite starters. Your 2-FLEX league means 7 RB/WR/TE start — premium on volume backs and target hogs.</li>
          <li><strong>Model &gt; Market = value:</strong> Filter <code class="inline">BUY</code> in Auction to see where Model season total beats Market season by ≥51 pts — bid up to Model $ there.</li>
          <li><strong>K/DEF = $1 always.</strong> MAE on kickers is 4+ pts — pure noise. Stream them.</li>
          <li><strong>$1 bench:</strong> Fill bench last at $1. Waiver wire value &gt; draft bench value in 12-team.</li>
          <li><strong>Nominate positions you've filled</strong> — prefer SELL-flagged players so opponents burn cash where you're cold.</li>
        </ol>
      </div>
    </div>

    ${myRosterCount > 0 ? `
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>My Drafted Players</h3>
        <button class="btn btn-ghost btn-sm" id="clearDraft" style="color:var(--crimson)">Reset Draft</button>
      </div>
      <div class="table-wrap" style="border:0; border-radius:0">
        <table>
          <thead><tr><th aria-sort="none">Player</th><th aria-sort="none">Pos</th><th aria-sort="none">Paid</th><th aria-sort="none">Value</th><th aria-sort="none">+/-</th>${compareAuctionEnabled && hasComparison ? '<th aria-sort="none">Season Δ</th><th aria-sort="none">Edge</th>' : ''}</tr></thead>
          <tbody>
            ${myRosterPlayers.map(p => {
              const paid = state.drafted[p.player_id]?.price || 0;
              const diff = p.auction - paid;
              return `<tr data-team="${p.team || ''}" style="--team-accent:${getTeamColor((p.team || '').toUpperCase())}; ${p.edge === 'BUY' ? 'background:rgba(16,185,129,0.06)' : p.edge === 'SELL' ? 'background:rgba(239,68,68,0.06)' : ''}">
                <td><div class="player-cell">${playerAvatar(p, 28)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '')}</div></div></div></td>
                <td>${posBadge(p.position)}</td>
                <td class="mono">$${paid}</td>
                <td class="mono">$${p.auction}</td>
                <td class="mono" style="color:${diff > 0 ? '#10B981' : diff < 0 ? 'var(--crimson)' : 'var(--text-muted)'}">${diff > 0 ? '+' : ''}${diff}</td>
                ${compareAuctionEnabled && hasComparison ? `<td>${deltaSeasonBadge(p.deltaRos)}</td><td>${edgeBadgeAuction(p.edge)}</td>` : ''}
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>` : ''}

    <div class="card reveal in" id="liveAuctionCard" style="margin-top:16px; ${focusedPlayer ? `border-left:3px solid ${liveAdvice.color}; background: linear-gradient(90deg, ${liveAdvice.color}14, transparent)` : ''}">
      <div class="card-header"><h3 style="color:${focusedPlayer ? liveAdvice.color : 'var(--text-muted)'}">${focusedPlayer ? `On the Block — ${escapeHtml(focusedPlayer.player_name)}` : 'Live Auction — select the player being auctioned'}</h3><span class="kicker">${focusedPlayer ? liveAdvice.title : 'Click 👁 to focus a row'}</span>${focusedPlayer ? `<button class="chip" id="clearFocus" style="margin-left:auto">✕ Clear</button>` : ''}</div>
      <div class="card-body" style="display:flex; flex-direction:column; gap:12px">
        ${focusedPlayer ? `
        <div style="display:flex; gap:16px; flex-wrap:wrap; align-items:center">
          <div style="display:flex; align-items:center; gap:12px; flex:1; min-width:260px">${playerAvatar(focusedPlayer, 56)}<div><div style="font:700 16px Helvetica Neue, Helvetica,sans-serif; display:flex; gap:8px; align-items:center; flex-wrap:wrap">${escapeHtml(focusedPlayer.player_name)} ${posBadge(focusedPlayer.position)} ${teamLogo(focusedPlayer.team, 20)} <span class="mono" style="font-size:11px; color:var(--text-muted)">T${focusedPlayer.fp_tier ?? focusedPlayer.tier} · ECR #${focusedPlayer.fp_ecr ?? '—'} · ADP #${focusedPlayer.fp_adp ?? '—'}${focusedPlayer.statsguy_value != null ? ` · <span style="color:var(--violet)">SG ${focusedPlayer.statsguy_value.toFixed(0)} (#${focusedPlayer.statsguy_rank})</span>` : ''}</span></div><div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:2px">Model ${focusedPlayer.weekly.toFixed(1)} wk → <span style="color:var(--amber); font-weight:700">${focusedPlayer.ros.toFixed(0)} season</span> · Market <span style="color:var(--sky); font-weight:700">${focusedPlayer.marketRos != null ? focusedPlayer.marketRos.toFixed(0) : '—'}</span> · Δ ${focusedPlayer.deltaRos != null ? (Number(focusedPlayer.deltaRos) > 0 ? '+' : '') + Number(focusedPlayer.deltaRos).toFixed(0) : '—'} · VOR +${focusedPlayer.vor.toFixed(0)} · <span style="color:var(--amber)">$${focusedPlayer.auction} val</span></div></div></div>
          <div style="display:flex; flex-direction:column; gap:6px; align-items:flex-end">
            <span class="badge" style="background:${focusedPlayer.edge === 'BUY' ? 'var(--emerald-dim)' : 'var(--crimson-dim)'}; color:${focusedPlayer.edge === 'BUY' ? 'var(--emerald)' : 'var(--crimson)'}; font-size:12px; padding:6px 10px">${focusedPlayer.edge} ${deltaSeasonBadge(focusedPlayer.deltaRos)}</span>
            ${focusedPlayer.statsguy_value != null ? `<span class="mono" style="font-size:11px; color:var(--violet)">StatsGuy market #${focusedPlayer.statsguy_rank} · ${focusedPlayer.statsguy_value.toFixed(0)}/10000</span>` : '<span class="mono" style="font-size:11px; color:var(--text-faint)">StatsGuy — no rank</span>'}
          </div>
        </div>
        <div class="alert" style="background:${liveAdvice.color}14; border:1px solid ${liveAdvice.color}33; color:var(--text)"><strong style="color:${liveAdvice.color}">${liveAdvice.title}</strong> — ${liveAdvice.text}</div>
        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; font:500 11px Helvetica Neue, Helvetica,sans-serif">
          <span class="kicker">Cap</span> <span class="mono" style="font-size:18px; font-weight:700; color:${liveAdvice.color}">$${liveAdvice.cap}</span> <span class="micro faint">(max $${maxBid} · $${myRemaining} left · ${slotsLeft} slots)</span>
          <span style="flex:1"></span>
          <button class="btn btn-primary btn-sm" data-pid="${focusedPlayer.player_id}" id="liveDraftBtn">Draft ${escapeHtml(focusedPlayer.player_name)} for $${liveAdvice.cap}</button>
          <button class="btn btn-ghost btn-sm" data-pid="${focusedPlayer.player_id}" id="livePassBtn">Pass — nominate next</button>
        </div>
        ` : `<div class="micro faint">Search a name, then click <span class="mono" style="background:var(--surface-raised); padding:2px 6px; border-radius:6px">👁 Focus</span> on the row.</div>
          <div style="display:flex; gap:8px; margin-top:4px"><input id="liveSearch" placeholder="Search player to focus…" style="flex:1; background:var(--surface-raised); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:8px; font:400 13px Helvetica Neue, Helvetica,sans-serif" /></div>
        `}
      </div>
    </div>

    <div class="responsive-view">
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header">
        <h3>Auction Board — ${activePos === 'ALL' ? 'All Positions' : activePos} ${auctionEdge !== 'ALL' ? `· ${auctionEdge}` : ''}</h3>
        <div class="row" style="gap:8px; flex-wrap:wrap">
          ${['ALL', ...posGroups].map(pos => `
            <button class="btn btn-sm ${activePos === pos ? '' : 'btn-ghost'} posFilter" data-pos="${pos}" style="${activePos === pos ? 'background:var(--color-accent); color:white' : ''}">${pos}</button>
          `).join('')}
          ${hasComparison ? `
            <span style="border-left:1px solid var(--border); margin:0 4px"></span>
            ${['ALL', 'BUY', 'SELL'].map(e => `<button class="btn btn-sm ${auctionEdge === e ? '' : 'btn-ghost'} edgeFilter" data-edge="${e}" style="${auctionEdge === e ? (e === 'BUY' ? 'background:var(--emerald); color:white' : e === 'SELL' ? 'background:var(--crimson); color:white' : 'background:var(--color-accent); color:white') : ''}">${e === 'ALL' ? 'All' : e === 'BUY' ? '▲ BUY' : '▼ SELL'}</button>`).join('')}
          ` : ''}
          <span style="border-left:1px solid var(--border); margin:0 4px"></span>
          <button class="btn btn-ghost btn-sm" id="copyAuction">Copy CSV</button>
          <label class="faint" style="font:500 12px Helvetica Neue, Helvetica,sans-serif">
            <input type="checkbox" id="hideDrafted" ${params.get('hide') === '1' ? 'checked' : ''}> hide drafted
          </label>
        </div>
      </div>
      ${compareAuctionEnabled && hasComparison ? `
      <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; padding:8px 12px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; margin-bottom:10px; font:500 11px Helvetica Neue, Helvetica,sans-serif; line-height:1.4">
        <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--amber); border-radius:2px; display:inline-block"></span> <strong style="color:var(--amber)">Model</strong> · Wk ×17 = season</span>
        <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--sky); border-radius:2px; display:inline-block"></span> <strong style="color:var(--sky)">Market</strong> · FantasyPros season projections (596, full YDS/TDS) + Sleeper weekly fallback</span>
        <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--emerald); border-radius:2px; display:inline-block"></span> BUY = Model ≥ +51 pts vs Market (3/wk)</span>
        <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--crimson); border-radius:2px; display:inline-block"></span> SELL = Market ≥ +51 pts vs Model</span>
        <span class="mono" style="color:var(--text-faint); margin-left:auto">ECR 519 / ADP 695 via CSVs — full, not sparse</span>
      </div>
      ` : ''}
      <div class="card" style="padding:8px 12px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; display:flex; gap:8px; flex-wrap:wrap; align-items:center">
        <span class="kicker">Sort</span>
        <span class="mono" style="font-size:11px; color:var(--text-muted)">Click header to sort — </span>
        <button class="chip ${auctionSortKey === 'auction' ? 'active' : ''}" data-sort="auction" title="Sort by Auction $">Auction $ ${auctionSortKey === 'auction' ? (auctionSortDir === -1 ? '▼ Highest → Lowest' : '▲ Lowest → Highest') : '↕'}</button>
        <button class="chip ${auctionSortKey === 'ros' ? 'active' : ''}" data-sort="ros">Model season ${auctionSortKey === 'ros' ? (auctionSortDir === -1 ? '▼' : '▲') : '↕'}</button>
        ${compareAuctionEnabled && hasComparison ? `<button class="chip ${auctionSortKey === 'marketRos' ? 'active' : ''}" data-sort="marketRos">Market Season ${auctionSortKey === 'marketRos' ? (auctionSortDir === -1 ? '▼' : '▲') : '↕'}</button><button class="chip ${auctionSortKey === 'deltaRos' ? 'active' : ''}" data-sort="deltaRos">Δ ${auctionSortKey === 'deltaRos' ? (auctionSortDir === -1 ? '▼' : '▲') : '↕'}</button>` : ''}
        <button class="chip" id="toggleSortDir" title="Flip highest↔lowest">↕ ${auctionSortDir === -1 ? 'Highest → Lowest' : 'Lowest → Highest'}</button>
        <span class="mono" style="font-size:11px; color:var(--text-faint); margin-left:auto">Click headers to sort</span>
      </div>
      <div class="table-wrap" style="border:0; border-radius:0; overflow-x:auto; margin-top:10px">
        <table style="width:100%; table-layout:fixed;">
          <thead>
            <tr>
              ${tableHeaders(compareAuctionEnabled && hasComparison, auctionSortKey, auctionSortDir)}
            </tr>
          </thead>
          <tbody>
            ${(() => {
              let list = filteredPlayers;
              if (hasComparison && compareAuctionEnabled && auctionEdge !== 'ALL') {
                list = list.filter(p => (p.edge || 'NEUTRAL') === auctionEdge);
              }
              const { rows } = tableBody(list, compareAuctionEnabled && hasComparison, escapeHtml);
              return rows;
            })()}
          </tbody>
        </table>
      </div>
    </div>
    </div>
    <div class="player-cards-grid" id="auctionCards">
      ${(() => {
        let list = filteredPlayers.filter(p => !p.isDrafted);
        if (hasComparison && compareAuctionEnabled && auctionEdge !== 'ALL') list = list.filter(p => (p.edge || 'NEUTRAL') === auctionEdge);
        const { cards } = tableBody(list, compareAuctionEnabled && hasComparison, escapeHtml);
        return cards;
      })()}
    </div>
    <div id="playerDetailModal" style="display:none; position:fixed; inset:0; z-index:1000; background:rgba(0,0,0,0.7); backdrop-filter:blur(8px); align-items:center; justify-content:center; padding:16px"><div id="playerDetailContent" style="background:var(--surface); border:1px solid var(--border); border-radius:16px; max-width:640px; width:100%; max-height:90vh; overflow:auto"></div></div>
  `;

  // --- Event handlers (view-level, not table-level) ---

  root.querySelector('#toggleAuctionCompare')?.addEventListener('click', () => {
    const next = !compareAuctionEnabled;
    try { localStorage.setItem('ffba-auction-compare', next ? '1' : '0'); } catch (_) {
      // localStorage unavailable in private mode
    }
    renderAuction(root);
  });

  // Draft countdown (60 min, persists in localStorage so reloads keep time)
  const countdownEl = root.querySelector('#draftCountdown');
  if (countdownEl) {
    const STORAGE_KEY = 'ffba-draft-target';
    let target = Number(localStorage.getItem(STORAGE_KEY) || 0);
    if (!target || target < Date.now()) {
      target = Date.now() + 60 * 60 * 1000;
      try { localStorage.setItem(STORAGE_KEY, String(target)); } catch (_) {
        // localStorage unavailable in private mode
      }
    }
    const tick = () => {
      const remain = Math.max(0, target - Date.now());
      const m = Math.floor(remain / 60000);
      const s = Math.floor((remain % 60000) / 1000);
      countdownEl.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
      countdownEl.style.color = remain < 5 * 60 * 1000 ? 'var(--crimson)' : remain < 15 * 60 * 1000 ? 'var(--amber)' : 'var(--crimson)';
      if (remain === 0) countdownEl.textContent = '00:00 — Draft now';
    };
    tick();
    if (root._draftInterval) clearInterval(root._draftInterval);
    root._draftInterval = setInterval(tick, 1000);
    root.querySelector('#resetCountdown')?.addEventListener('click', () => {
      const nt = Date.now() + 60 * 60 * 1000;
      try { localStorage.setItem(STORAGE_KEY, String(nt)); } catch (_) {
        // localStorage unavailable in private mode
      }
      target = nt;
      tick();
    });
  }

  root.querySelector('#fullscreenAuction')?.addEventListener('click', () => {
    const el = root.querySelector('.table-wrap');
    if (document.fullscreenElement) document.exitFullscreen?.();
    else el?.requestFullscreen?.();
  });
  root.querySelector('#printAuction')?.addEventListener('click', () => window.print());

  // Position + edge filters
  root.querySelectorAll('.posFilter').forEach(btn => {
    btn.addEventListener('click', () => {
      const pos = btn.dataset.pos;
      const p = new URLSearchParams(location.hash.split('?')[1] || '');
      if (pos === 'ALL') p.delete('pos');
      else p.set('pos', pos);
      location.hash = 'auction?' + p.toString();
    });
  });
  root.querySelectorAll('.edgeFilter').forEach(btn => {
    btn.addEventListener('click', () => {
      const e = btn.dataset.edge;
      const p = new URLSearchParams(location.hash.split('?')[1] || '');
      if (e === 'ALL') p.delete('edge');
      else p.set('edge', e);
      location.hash = 'auction?' + p.toString();
    });
  });

  // Hide drafted toggle
  root.querySelector('#hideDrafted')?.addEventListener('change', e => {
    const p = new URLSearchParams(location.hash.split('?')[1] || '');
    if (e.target.checked) p.set('hide', '1');
    else p.delete('hide');
    location.hash = 'auction?' + p.toString();
  });

  // Live Auction focus
  root.querySelector('#clearFocus')?.addEventListener('click', () => {
    const p = new URLSearchParams(location.hash.split('?')[1] || '');
    p.delete('focus');
    location.hash = 'auction?' + p.toString();
  });
  const liveSearch = root.querySelector('#liveSearch');
  if (liveSearch) {
    liveSearch.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const q = liveSearch.value.trim().toLowerCase();
        if (!q) return;
        const m = allRanked.find(pl => pl.player_name.toLowerCase().includes(q) && !pl.isDrafted) || allRanked.find(pl => pl.player_name.toLowerCase().includes(q));
        if (m) {
          const p = new URLSearchParams(location.hash.split('?')[1] || '');
          p.set('focus', m.player_id);
          location.hash = 'auction?' + p.toString();
        }
      }
    });
  }
  root.querySelector('#liveDraftBtn')?.addEventListener('click', () => {
    const pid = root.querySelector('#liveDraftBtn')?.dataset.pid;
    if (!pid) return;
    const pl = allRanked.find(p => String(p.player_id) === String(pid));
    if (!pl) return;
    const cap = liveAdvice ? liveAdvice.cap : pl.auction;
    showDraftModal(root, pid, pl.player_name, cap, state, allRanked, escapeHtml, () => renderAuction(root));
  });
  root.querySelector('#livePassBtn')?.addEventListener('click', () => {
    const p = new URLSearchParams(location.hash.split('?')[1] || '');
    p.delete('focus');
    location.hash = 'auction?' + p.toString();
  });

  // Reset draft
  root.querySelector('#clearDraft')?.addEventListener('click', () => {
    if (confirm('Clear all drafted players?')) {
      resetDraftState();
      location.hash = 'auction';
    }
  });

  // Table-area events (sort, draft buttons, modals, copy)
  bindTableEvents(root, allRanked, filteredPlayers, compareAuctionEnabled && hasComparison, state, escapeHtml, () => renderAuction(root));
}