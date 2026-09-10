// hub/src/views/props.js — forebet-style week board: market-consensus game
// predictions + a per-game player-props popup (model fair lines, no book
// line / manual entry — that whole flow was removed per user request).
// Read-only (GET on :8000). RG copy rule: never "LOCK".
import { fetchGamePredictions, fetchPropsBoard } from '../api.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { teamLogo } from '../components/teamLogo.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { getTeamColor } from '../components/teamColors.js';
import { escapeHtml, escapeAttr } from '../lib/escape.js';
import { trapFocus } from '../lib/focusTrap.js';

function winPctChip(pct, isFavorite) {
  const bg = isFavorite ? 'var(--emerald-dim)' : 'var(--surface-raised)';
  const fg = isFavorite ? 'var(--emerald)' : 'var(--text-muted)';
  return `<span class="mono" style="background:${bg}; color:${fg}; border-radius:6px; padding:2px 6px; font-weight:700">${Math.round(pct * 100)}%</span>`;
}

function gameStatusChip(final) {
  const bg = final ? 'var(--surface-raised)' : 'var(--sky-dim, var(--surface-raised))';
  const fg = final ? 'var(--text-muted)' : 'var(--sky, var(--text))';
  return `<span class="badge" style="background:${bg}; color:${fg}; border:1px solid var(--border)">${final ? 'FINAL' : 'UPCOMING'}</span>`;
}

const MARKET_LABELS = {
  passing_yards: 'Pass Yds', passing_tds: 'Pass TD', rushing_yards: 'Rush Yds',
  receiving_yards: 'Rec Yds', receptions: 'Rec', carries: 'Carries', anytime_td: 'Any TD',
};

function marketChipHtml(r) {
  const label = MARKET_LABELS[r.market] || r.market;
  const isPoisson = r.market === 'anytime_td';
  const fair = isPoisson ? `${(Number(r.p_yes) * 100).toFixed(0)}%` : Number(r.fair_line).toFixed(1);
  const actual = isPoisson
    ? (r.actual_p_yes == null ? null : (r.actual_p_yes > 0 ? 'YES' : 'NO'))
    : (r.actual == null ? null : Number(r.actual).toFixed(1));
  const sigmaSuffix = !isPoisson && r.sigma != null ? ` <span style="color:var(--text-faint); font-weight:400">±${Number(r.sigma).toFixed(1)}</span>` : '';
  const actualRow = actual == null ? '' : `
        <div style="margin-top:3px; padding-top:3px; border-top:1px dashed var(--border)">
          <span style="font-size:9px; color:var(--text-faint); text-transform:uppercase">Actual</span>
          <span class="mono" style="font-weight:700; font-size:13px; color:var(--emerald); margin-left:4px">${actual}</span>
        </div>`;
  return `
      <div style="background:var(--surface-raised); border-radius:8px; padding:6px 8px; min-width:76px">
        <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; letter-spacing:.03em">${escapeHtml(label)}</div>
        <div class="mono" style="font-weight:700; font-size:14px">${fair}${sigmaSuffix}</div>
        ${actualRow}
      </div>`;
}

function propsPlayerCard(p) {
  const pos = (p.position || 'UNK').toUpperCase();
  const team = p.team || '';
  const unavailable = p.available === false;
  return `
    <div class="player-card-v2" data-pid="${escapeAttr(p.playerId)}" style="--team-accent:${getTeamColor(team)}; ${unavailable ? 'opacity:.6' : ''}">
      <div class="pc-header">
        ${playerAvatar({ player_id: p.playerId, sleeper_id: p.sleeperId, player_name: p.name, position: pos, team }, 44)}
        <div class="pc-info">
          <div class="pc-name">${escapeHtml(p.name)}</div>
          <div class="pc-meta">${posBadge(pos)} ${teamLogo(team, 16)} ${escapeHtml(team)}</div>
        </div>
      </div>
      <div class="pc-badges" style="margin-top:6px">${injuryBadge(p.injuryStatus)}</div>
      ${unavailable ? `<div style="margin-top:4px; font-size:11px; color:var(--amber)">Projection may be stale — player is not expected to play.</div>` : ''}
      <div class="pc-details" style="flex-wrap:wrap; gap:6px; margin-top:8px">
        ${p.rows.map(marketChipHtml).join('')}
      </div>
    </div>`;
}

function groupBoardPlayers(boardPlayers) {
  const byPlayer = new Map();
  for (const r of boardPlayers) {
    if (!byPlayer.has(r.player_id)) {
      byPlayer.set(r.player_id, {
        playerId: r.player_id, sleeperId: r.sleeper_id, name: r.player_name,
        position: r.position, team: r.team, injuryStatus: r.injury_status,
        available: r.available, rows: [],
      });
    }
    byPlayer.get(r.player_id).rows.push(r);
  }
  return [...byPlayer.values()];
}

// --- Game props popup -------------------------------------------------
// Fetched on demand when a game row is clicked (not tied to the page's
// hash/render cycle) — a lightweight modal, not another inline section.

let gamePropsModalRoot = null;

function closeGamePropsModal() {
  if (gamePropsModalRoot) { gamePropsModalRoot.innerHTML = ''; }
}

async function openGamePropsModal(triggerEl, teamsKey, week) {
  if (!gamePropsModalRoot) {
    gamePropsModalRoot = document.createElement('div');
    gamePropsModalRoot.id = 'gamePropsModalRoot';
    document.body.appendChild(gamePropsModalRoot);
  }
  const label = teamsKey.replace(',', ' @ ');
  gamePropsModalRoot.innerHTML = `
    <div class="player-modal-backdrop" id="gamePropsBackdrop">
      <div class="player-modal-card card" role="dialog" aria-modal="true" aria-label="Player props for ${escapeAttr(label)}" tabindex="-1" style="max-width:920px">
        <button class="modal-close-btn" id="gamePropsCloseBtn" aria-label="Close">✕</button>
        <h3 style="margin:0 0 12px">${escapeHtml(label)}</h3>
        <div id="gamePropsBody" style="font-size:13px; color:var(--text-muted)">Loading…</div>
      </div>
    </div>`;
  const backdrop = gamePropsModalRoot.querySelector('#gamePropsBackdrop');
  const card = gamePropsModalRoot.querySelector('.player-modal-card');
  requestAnimationFrame(() => requestAnimationFrame(() => { backdrop.classList.add('show'); card.classList.add('show'); }));

  let releaseFocus = () => {};
  const close = () => {
    try { releaseFocus(); } catch (_) {}
    closeGamePropsModal();
  };
  releaseFocus = trapFocus(card, triggerEl, close);
  gamePropsModalRoot.querySelector('#gamePropsCloseBtn').addEventListener('click', close);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });

  let boardPayload;
  try {
    boardPayload = await fetchPropsBoard({ teams: teamsKey, week });
  } catch (_) {
    boardPayload = { players: [], meta: { cold: true } };
  }
  const players = groupBoardPlayers((boardPayload && boardPayload.players) || []);
  const body = gamePropsModalRoot.querySelector('#gamePropsBody');
  if (!body) return; // closed while fetching
  body.innerHTML = players.length ? `
    <div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:10px">
      ${players.map(propsPlayerCard).join('')}
    </div>
    <div style="margin-top:10px; font-size:11px; color:var(--text-faint)">
      Fair = model projection median for this stat. "Actual" appears once that week's real box score has posted.
      Injury status is fetched live — a flagged player's projection may not reflect their real availability.
    </div>` : `<div style="padding:8px 0">No projected players found for this game/week.</div>`;
}

export async function renderProps(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const week = params.get('week') ? Number(params.get('week')) : null;

  let gamesPayload;
  try {
    gamesPayload = await fetchGamePredictions({ week });
  } catch (_) {
    gamesPayload = { games: [], meta: { cold: true } };
  }
  const games = (gamesPayload && gamesPayload.games) || [];
  const gamesCold = Boolean(gamesPayload && gamesPayload.meta && gamesPayload.meta.cold);
  const currentWeek = (gamesPayload.meta && gamesPayload.meta.week) || week || '';

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Props</h1>
      <p>Market-consensus game predictions. Click a game for player props.</p>
    </div>

    <div class="card reveal in" role="note" aria-label="Responsible gambling notice"
         style="margin-top:12px; border-left:4px solid var(--amber)">
      <div class="card-body" style="font-size:13px; color:var(--text)">
        <strong>Entertainment only.</strong> Predictions are uncertain estimates, not guarantees.
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
                  return `
                  <tr class="props-game-row" data-teams="${escapeAttr(teamsKey)}" tabindex="0" role="button"
                      style="cursor:pointer" title="Click to browse this game's player props">
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
            Final games show the actual score in place of the prediction.
          </div>` : `
          <div style="padding:20px; font-size:13px; color:var(--text-muted)">
            No schedule loaded for this week yet.
          </div>`}
      </div>
    </div>`;
  bindWeekPicker(root, currentWeek);
  bindGameRows(root, currentWeek);
}

function bindWeekPicker(root, currentWeek) {
  root.querySelectorAll('[data-week]').forEach(btn => {
    btn.addEventListener('click', () => {
      const w = btn.getAttribute('data-week');
      location.hash = `props${w ? `?week=${w}` : ''}`;
    });
  });
}

function bindGameRows(root, currentWeek) {
  root.querySelectorAll('.props-game-row').forEach(row => {
    const open = () => openGamePropsModal(row, row.getAttribute('data-teams'), currentWeek);
    row.addEventListener('click', open);
    row.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  });
}
