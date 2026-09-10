// hub/src/views/props.js — Player props: model fair lines vs manual book lines.
// Read-only reads (GET /props/edges on :8000); manual entry POSTs to the
// MODEL directly (hub proxy never writes — isolation contract). Never shows
// "LOCK" — chips read VALUE / TRACKING / NO EDGE (RG copy rule).
import { fetchPropEdges, fetchGamePredictions, fetchPropsBoard, postPropLine } from '../api.js';
import { posBadge } from '../components/badges.js';
import { teamLogo } from '../components/teamLogo.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { getTeamColor } from '../components/teamColors.js';
import { escapeHtml } from '../lib/escape.js';

const MARKETS = [
  'passing_yards', 'passing_tds', 'rushing_yards',
  'receiving_yards', 'receptions', 'anytime_td',
];
const SIDES = ['over', 'under', 'yes', 'no'];

function edgeChip(decision) {
  const d = String(decision || 'NO EDGE');
  // why explicit TRACKING branch (trend sign-off): the API now emits it for
  // uncalibrated markets that clear the math — amber, never green. Unknown
  // stays amber too (both mean "not endorsed"); only VALUE is green.
  const kind = d === 'VALUE' ? 'value' : (d === 'TRACKING' || d.startsWith('NO EDGE (unknown)')) ? 'watch' : 'none';
  const bg = kind === 'value' ? 'var(--emerald-dim)' : kind === 'watch' ? 'var(--amber-dim)' : 'var(--surface-raised)';
  const fg = kind === 'value' ? 'var(--emerald)' : kind === 'watch' ? 'var(--amber)' : 'var(--text-muted)';
  return `<span class="badge" style="background:${bg}; color:${fg}; border:1px solid var(--border)">${escapeHtml(d)}</span>`;
}

function shadowChip(status, calibration) {
  const label = status === 'trusted' ? 'shadow ✓' : 'tracking';
  const cal = calibration && calibration !== 'edges_on' ? ` · cal: ${calibration}` : '';
  return `<span class="mono" style="font-size:11px; color:var(--text-faint)">${escapeHtml(label)}${escapeHtml(cal)}</span>`;
}

function fmtLine(e) {
  if (e.side === 'yes' || e.side === 'no') return escapeHtml(e.side.toUpperCase());
  const line = e.book_line == null ? '—' : Number(e.book_line).toFixed(1);
  return `${escapeHtml(e.side)} ${line}`;
}

function fmtPrice(p) {
  if (p == null) return '—';
  const n = Number(p);
  return n > 0 ? `+${n}` : `${n}`;
}

function winPctChip(pct, isFavorite) {
  const bg = isFavorite ? 'var(--emerald-dim)' : 'var(--surface-raised)';
  const fg = isFavorite ? 'var(--emerald)' : 'var(--text-muted)';
  return `<span class="mono" style="background:${bg}; color:${fg}; border-radius:6px; padding:2px 6px; font-weight:700">${Math.round(pct * 100)}%</span>`;
}

const MARKET_LABELS = {
  passing_yards: 'Pass Yds', passing_tds: 'Pass TD', rushing_yards: 'Rush Yds',
  receiving_yards: 'Rec Yds', receptions: 'Rec', anytime_td: 'Any TD',
};

function propsPlayerCard(p, edgeByKey) {
  const pos = (p.position || 'UNK').toUpperCase();
  const team = p.team || '';
  const marketChips = p.rows.map(r => {
    const edge = edgeByKey.get(`${r.player_id}:${r.market}`);
    const label = MARKET_LABELS[r.market] || r.market;
    const value = r.market === 'anytime_td'
      ? `${(Number(r.p_yes) * 100).toFixed(0)}%`
      : Number(r.fair_line).toFixed(1);
    const sigmaSuffix = r.sigma == null ? '' : ` <span style="color:var(--text-faint); font-weight:400">±${Number(r.sigma).toFixed(1)}</span>`;
    const yourLine = edge ? `<div style="margin-top:2px">${edgeChip(edge.decision)} <span class="mono" style="font-size:10px; color:var(--text-faint)">${fmtLine(edge)} @ ${fmtPrice(edge.book_price)}</span></div>` : '';
    return `
      <div style="background:var(--surface-raised); border-radius:8px; padding:6px 8px; min-width:76px">
        <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; letter-spacing:.03em">${escapeHtml(label)}</div>
        <div class="mono" style="font-weight:700; font-size:14px">${value}${sigmaSuffix}</div>
        ${yourLine}
      </div>`;
  }).join('');

  return `
    <div class="player-card-v2" data-pid="${escapeHtml(p.playerId)}" style="--team-accent:${getTeamColor(team)}">
      <div class="pc-header">
        ${playerAvatar({ player_id: p.playerId, player_name: p.name, position: pos, team }, 44)}
        <div class="pc-info">
          <div class="pc-name">${escapeHtml(p.name)}</div>
          <div class="pc-meta">${posBadge(pos)} ${teamLogo(team, 16)} ${escapeHtml(team)}</div>
        </div>
      </div>
      <div class="pc-details" style="flex-wrap:wrap; gap:6px; margin-top:8px">
        ${marketChips}
      </div>
    </div>`;
}

function renderGameProps(boardPlayers, edges, selectedTeams) {
  const edgeByKey = new Map(edges.map(e => [`${e.player_id}:${e.market}`, e]));
  const byPlayer = new Map();
  for (const r of boardPlayers) {
    if (!byPlayer.has(r.player_id)) byPlayer.set(r.player_id, { playerId: r.player_id, name: r.player_name, position: r.position, team: r.team, rows: [] });
    byPlayer.get(r.player_id).rows.push(r);
  }
  const players = [...byPlayer.values()];
  return `
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Game props · ${escapeHtml(selectedTeams.replace(',', ' @ '))}</h3><span class="kicker">${players.length ? `${players.length} players` : 'no props'}</span></div>
      <div class="card-body">
        ${players.length ? `
          <div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:10px">
            ${players.map(p => propsPlayerCard(p, edgeByKey)).join('')}
          </div>
          <div style="margin-top:10px; font-size:11px; color:var(--text-faint)">
            Fair = model projection median for this stat, no book line needed. A colored chip under a stat means you've manually entered a book line for it (Add a book line, below).
          </div>` : `
          <div style="padding:20px; font-size:13px; color:var(--text-muted)">
            No projected players found for this game/week.
          </div>`}
      </div>
    </div>`;
}

function gameStatusChip(final) {
  const bg = final ? 'var(--surface-raised)' : 'var(--sky-dim, var(--surface-raised))';
  const fg = final ? 'var(--text-muted)' : 'var(--sky, var(--text))';
  return `<span class="badge" style="background:${bg}; color:${fg}; border:1px solid var(--border)">${final ? 'FINAL' : 'UPCOMING'}</span>`;
}

export async function renderProps(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const week = params.get('week') ? Number(params.get('week')) : null;
  const selectedTeams = params.get('teams') || '';

  let payload;
  let gamesPayload;
  let boardPayload;
  try {
    [payload, gamesPayload, boardPayload] = await Promise.all([
      fetchPropEdges({ week }),
      fetchGamePredictions({ week }),
      selectedTeams ? fetchPropsBoard({ teams: selectedTeams, week }) : Promise.resolve({ players: [], meta: {} }),
    ]);
  } catch (_) {
    payload = { edges: [], meta: { cold: true } };
    gamesPayload = { games: [], meta: { cold: true } };
    boardPayload = { players: [], meta: {} };
  }
  const edges = payload.edges || [];
  const cold = Boolean(payload.meta && payload.meta.cold);
  const games = (gamesPayload && gamesPayload.games) || [];
  const gamesCold = Boolean(gamesPayload && gamesPayload.meta && gamesPayload.meta.cold);
  const boardPlayers = (boardPayload && boardPayload.players) || [];
  const currentWeek = (payload.meta && payload.meta.week) || week || '';
  const needsCalibrationNote = edges.some(e => e.calibration_verdict !== 'edges_on')
    || edges.some(e => e.shadow_status !== 'trusted');

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Props</h1>
      <p>Model fair lines vs your book lines. Edges are tracked estimates, not tips.</p>
      <details style="margin-top:8px" aria-label="How props edges work">
        <summary style="cursor:pointer; font-weight:600" title="Toggle props explainer">How edges work</summary>
        <p style="margin-top:8px">Fair line = stat-projection median (<code class="inline">stat_projector.py</code>). Edge needs model−book ≥ 5pp <em>and</em> EV ≥ +4%/unit, non-empty history, and is labeled by shadow state (20 resolved) + 2025 calibration. Only <code class="inline">passing_yards</code> earned edge labels in 2025 calibration — but a 2024 rerun did not confirm it (coverage 0.714 vs 0.757), so treat even that as provisional until live shadow data adjudicates. The rest stay tracking.</p>
      </details>
    </div>

    <div class="card reveal in" role="note" aria-label="Responsible gambling notice"
         style="margin-top:12px; border-left:4px solid var(--amber)">
      <div class="card-body" style="font-size:13px; color:var(--text)">
        <strong>Entertainment only.</strong> Props carry vig — books price both sides below fair.
        Model edges are uncertain estimates from heuristic sigmas, not predictions of profit.
        Never bet more than you can afford to lose.
      </div>
    </div>

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-body">
        <div class="filters week-picker-scroll" style="overflow-x:auto; flex-wrap:nowrap; max-width:100%; padding-bottom:4px">
          ${Array.from({length:18},(_,i)=>i+1).map(w=>`<button class="chip ${String(w)===String(currentWeek)?'active':''}" data-week="${w}" title="Show week ${w}" style="flex-shrink:0">${w}</button>`).join('')}
        </div>
      </div>
    </div>

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Week ${escapeHtml(String(currentWeek || ''))} games</h3><span class="kicker">${games.length ? `${games.length} games · market consensus` : gamesCold ? 'model cold' : 'no schedule'}</span></div>
      <div class="card-body" style="padding:0">
        ${gamesCold ? `
          <div style="padding:20px; font-size:13px; color:var(--text-muted)">
            Model cache is cold — run <code class="inline">POST /refresh</code> (Dashboard → Sync) to load the schedule.
          </div>` : games.length ? `
          <div class="responsive-view">
            <div class="table-wrap" style="border:0; border-radius:0"><table>
              <thead><tr><th>Matchup</th><th>Win %</th><th>Predicted score</th><th>Status</th></tr></thead>
              <tbody>
                ${games.map(g => {
                  const homeFav = g.home_win_prob >= g.away_win_prob;
                  const teamsKey = `${g.away_team},${g.home_team}`;
                  const isSelected = selectedTeams === teamsKey;
                  return `
                  <tr class="props-game-row" data-teams="${escapeHtml(teamsKey)}"
                      style="cursor:pointer; ${isSelected ? 'background:var(--surface-raised)' : ''}"
                      title="Click to browse this game's player props" ${isSelected ? 'aria-selected="true"' : ''}>
                    <td>
                      <div style="display:flex; align-items:center; gap:6px">${teamLogo(g.away_team, 20)}<span style="font-weight:${homeFav ? 400 : 700}">${escapeHtml(g.away_team || '')}</span></div>
                      <div style="display:flex; align-items:center; gap:6px; margin-top:2px">${teamLogo(g.home_team, 20)}<span style="font-weight:${homeFav ? 700 : 400}">${escapeHtml(g.home_team || '')}</span></div>
                    </td>
                    <td class="mono">
                      <div>${winPctChip(g.away_win_prob, !homeFav)}</div>
                      <div style="margin-top:4px">${winPctChip(g.home_win_prob, homeFav)}</div>
                    </td>
                    <td class="mono">
                      ${g.final ? `<span style="font-weight:700">${g.actual_away_score}</span>` : `${Number(g.predicted_away_score).toFixed(1)}`}<br>
                      ${g.final ? `<span style="font-weight:700">${g.actual_home_score}</span>` : `${Number(g.predicted_home_score).toFixed(1)}`}
                    </td>
                    <td>${gameStatusChip(g.final)}</td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table></div>
          </div>
          <div style="padding:10px 16px; font-size:11px; color:var(--text-faint)">
            Win% and predicted score are real market consensus (spread/total/moneyline, devigged) — not this app's own model.
          </div>` : `
          <div style="padding:20px; font-size:13px; color:var(--text-muted)">
            No schedule loaded for this week yet.
          </div>`}
      </div>
    </div>

    ${selectedTeams ? renderGameProps(boardPlayers, edges, selectedTeams) : ''}

    ${needsCalibrationNote && !cold ? `
    <div class="card reveal in" style="margin-top:12px">
      <div class="card-body" style="font-size:12px; color:var(--text-muted)">
        Model-implied, partially uncalibrated — some markets are below 20 resolved shadow samples
        or failed 2025 calibration gates. Those rows read TRACKING until they earn it.
        Kicker props excluded v1 (thinnest coverage).
      </div>
    </div>` : ``}

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Edge board</h3><span class="kicker">${edges.length ? `${edges.length} lines` : cold ? 'model cold' : 'no lines'}</span></div>
      <div class="card-body" style="padding:0">
        ${cold ? `
          <div style="padding:20px; font-size:13px; color:var(--text-muted)">
            Model cache is cold — run <code class="inline">POST /refresh</code> (Dashboard → Sync),
            then enter book lines below. Lines can be stored while cold; edges compute after refresh.
          </div>` : edges.length ? `
          <div class="responsive-view">
            <div class="table-wrap" style="border:0; border-radius:0"><table>
              <thead><tr><th aria-sort="none">Player</th><th aria-sort="none">Market</th><th aria-sort="none">Fair</th><th aria-sort="none">Book</th><th aria-sort="none">P(model)</th><th aria-sort="none">Edge</th><th aria-sort="none">EV/u</th><th aria-sort="none">Status</th></tr></thead>
              <tbody>
                ${edges.map(e => `
                  <tr>
                    <td><span style="font-weight:700">${escapeHtml(e.player_name || e.player_id || '')}</span> ${posBadge(e.position)}<br><span class="mono" style="font-size:11px; color:var(--text-faint)">${escapeHtml(e.team || '')} · ${escapeHtml(e.book || 'manual')}</span></td>
                    <td style="font-size:12px">${escapeHtml(e.market || '')}</td>
                    <td class="mono">${e.fair_line == null ? '—' : Number(e.fair_line).toFixed(1)}${e.sigma == null ? '' : `<br><span style="font-size:11px; color:var(--text-faint)">±${Number(e.sigma).toFixed(1)}</span>`}</td>
                    <td class="mono">${fmtLine(e)} @ ${fmtPrice(e.book_price)}</td>
                    <td class="mono">${e.p_model == null ? '—' : Number(e.p_model).toFixed(2)}</td>
                    <td class="mono">${e.edge_pp == null ? '—' : (Number(e.edge_pp) >= 0 ? '+' : '') + (Number(e.edge_pp) * 100).toFixed(1) + 'pp'}</td>
                    <td class="mono">${e.ev_per_unit == null ? '—' : (Number(e.ev_per_unit) >= 0 ? '+' : '') + (Number(e.ev_per_unit) * 100).toFixed(1) + '%'}</td>
                    <td>${edgeChip(e.decision)}<br>${shadowChip(e.shadow_status, e.calibration_verdict)}</td>
                  </tr>`).join('')}
              </tbody>
            </table></div>
          </div>` : `
          <div style="padding:20px; font-size:13px; color:var(--text-muted)">
            No book lines stored yet — add your first line below. Lines are manual-only (no odds feed, $0 rule).
          </div>`}
      </div>
    </div>

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Add a book line</h3><span class="kicker">manual entry → model :8000</span></div>
      <div class="card-body">
        <form id="props-form" style="display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px" aria-label="Add a book line">
          <label style="font-size:12px">Player ID <input name="player_id" required maxlength="64" placeholder="2544" style="width:100%; min-height:44px"></label>
          <label style="font-size:12px">Market <select name="market" style="width:100%; min-height:44px">${MARKETS.map(m => `<option value="${m}">${m}</option>`).join('')}</select></label>
          <label style="font-size:12px">Side <select name="side" style="width:100%; min-height:44px">${SIDES.map(s => `<option value="${s}">${s}</option>`).join('')}</select></label>
          <label style="font-size:12px">Line <input name="line" type="number" step="0.5" placeholder="over/under only" style="width:100%; min-height:44px"></label>
          <label style="font-size:12px">Price <input name="price" type="number" step="1" required placeholder="-110" style="width:100%; min-height:44px"></label>
          <label style="font-size:12px">Book <input name="book" maxlength="32" placeholder="manual" style="width:100%; min-height:44px"></label>
          <label style="font-size:12px">Week <input name="week" type="number" min="1" max="18" required placeholder="5" style="width:100%; min-height:44px"></label>
          <div style="grid-column:1/-1; display:flex; gap:10px; align-items:center">
            <button type="submit" style="border:1px solid var(--border-active); background:var(--primary); color:var(--text-inverse); border-radius:12px; padding:8px 16px; min-height:44px; font:600 13px Helvetica, Arial, sans-serif; cursor:pointer">Store line</button>
            <span id="props-form-msg" class="mono" style="font-size:12px" role="status" aria-live="polite"></span>
          </div>
        </form>
      </div>
    </div>`;
  bindPropsForm(root);
  bindWeekPicker(root, currentWeek);
  bindGameRows(root, currentWeek, selectedTeams);
}

function bindWeekPicker(root, currentWeek) {
  root.querySelectorAll('[data-week]').forEach(btn => {
    btn.addEventListener('click', () => {
      const w = btn.getAttribute('data-week');
      location.hash = `props${w ? `?week=${w}` : ''}`;
    });
  });
}

function bindGameRows(root, currentWeek, selectedTeams) {
  root.querySelectorAll('.props-game-row').forEach(row => {
    row.addEventListener('click', () => {
      const teamsKey = row.getAttribute('data-teams');
      // toggle: clicking the already-selected game closes the board back out
      const next = teamsKey === selectedTeams ? '' : teamsKey;
      const params = new URLSearchParams();
      if (currentWeek) params.set('week', String(currentWeek));
      if (next) params.set('teams', next);
      const qs = params.toString();
      location.hash = `props${qs ? `?${qs}` : ''}`;
    });
  });
}

function bindPropsForm(root) {
  const form = root.querySelector('#props-form');
  if (!form) return;
  const msg = root.querySelector('#props-form-msg');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(form);
    const market = String(fd.get('market') || '');
    const side = String(fd.get('side') || '');
    const lineRaw = String(fd.get('line') || '').trim();
    const isPoisson = market === 'anytime_td';
    // why mirror API validation client-side: instant feedback, but the
    // server re-validates (422) — client checks are convenience, not trust.
    if (!isPoisson && (side === 'yes' || side === 'no')) {
      msg.textContent = 'Over/under markets take side over/under.';
      msg.style.color = 'var(--crimson)';
      return;
    }
    if (isPoisson && (side === 'over' || side === 'under')) {
      msg.textContent = 'anytime_td takes side yes/no.';
      msg.style.color = 'var(--crimson)';
      return;
    }
    if (!isPoisson && !lineRaw) {
      msg.textContent = 'Over/under requires a line.';
      msg.style.color = 'var(--crimson)';
      return;
    }
    if (isPoisson && lineRaw) {
      msg.textContent = 'anytime_td takes no line.';
      msg.style.color = 'var(--crimson)';
      return;
    }
    const body = {
      player_id: String(fd.get('player_id') || '').trim(),
      market, side,
      price: Number(fd.get('price')),
      book: String(fd.get('book') || '').trim() || 'manual',
      week: Number(fd.get('week')),
    };
    if (lineRaw) body.line = Number(lineRaw);
    msg.textContent = 'Storing…';
    msg.style.color = 'var(--text-muted)';
    try {
      const res = await postPropLine(body);
      const edge = res.edge;
      msg.textContent = edge
        ? `Stored. Edge: ${edge.decision} (P=${Number(edge.p_model).toFixed(2)}, EV=${(Number(edge.ev_per_unit) * 100).toFixed(1)}%/u).`
        : `Stored. ${(res.note || 'Edge computes after refresh.').replace(/</g, '')}`;
      msg.style.color = 'var(--emerald)';
      // Simplest honest refresh: re-render the tab (edges cache was invalidated).
      renderProps(root);
    } catch (err) {
      msg.textContent = `Not stored: ${String(err && err.message || err).slice(0, 160)}`;
      msg.style.color = 'var(--crimson)';
    }
  });
}
