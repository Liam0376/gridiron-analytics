// hub/src/components/playerModal.js — Draftea Player Detail Modal
import { playerAvatar } from './playerAvatar.js';
import { posBadge, injuryBadge } from './badges.js';
import { teamLogo } from './teamLogo.js';
import { intervalBar } from './intervalBar.js';
import { escapeHtml, escapeAttr } from '../lib/escape.js';
import { trapFocus } from '../lib/focusTrap.js';

export function openPlayerModal(p, root = document.getElementById('app') || document.body) {
  // Capture trigger for focus return before DOM mutation.
  const triggerEl = (document.activeElement instanceof HTMLElement) ? document.activeElement : null;
  let container = document.getElementById('playerModalContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'playerModalContainer';
    document.body.appendChild(container);
  }

  const isPasser = p.position === 'QB';
  const isRunner = p.position === 'RB' || p.position === 'QB';
  const isReceiver = p.position === 'WR' || p.position === 'TE' || p.position === 'RB';

  const weekly = Number(p.weekly ?? p.projected_points ?? 0);
  const seasonPts = Number(p.season ?? (weekly * 17));
  // why ±5.0 fallback with halved width derivation (data-viz sign-off): width
  // is HALF-width everywhere since unification — the old ±2.5 drew half the
  // band its own width number claimed. Unenriched = less info = wider band.
  const lower = Number(p.lower ?? p.projection_lower ?? Math.max(0, weekly - 5.0));
  const upper = Number(p.upper ?? p.projection_upper ?? (weekly + 5.0));
  const width = Number(p.width ?? (upper - lower) / 2);

  // why $1 floor, not weekly * 2.2 (user-caught live bug, 2026-09-10): the
  // old fallback guessed auction $ straight from weekly fantasy points with
  // a flat constant — ignoring position and replacement level entirely. A
  // QB15 (below the QB12 replacement line in a 1-QB league) got $55/$50
  // instead of the real backend-computed $19/$8 (VOR-based, in
  // comparison/_model.py, already correct — just not forwarded here). $1
  // matches the backend's own floor for a below-replacement player instead
  // of fabricating a number.
  const gridironAuction = Number(p.gridironAuction ?? p.auction ?? 1);
  // why no gridiron fallback: market consensus (FantasyPros) is absent in
  // deployments without a market data source. Falling back to the model
  // value fabricates agreement (delta always $0) — null renders N/A.
  const marketAuctionRaw = p.marketAuction ?? p.market_auction;
  const marketAuction = marketAuctionRaw != null ? Number(marketAuctionRaw) : null;
  const deltaAuction = p.deltaAuction ?? (marketAuction != null ? (gridironAuction - marketAuction) : null);
  const edge = (p.edge || 'NEUTRAL').toUpperCase();
  const edgeIcon = edge === 'BUY' ? '▲ ' : edge === 'SELL' ? '▼ ' : '';

  // 17-game stat projections
  // why no ratio-guess fallback (user-caught live bug, 2026-09-10): this
  // used to estimate season yards from weekly FANTASY POINTS times a
  // made-up "yards per point" constant times 17 games (e.g.
  // weekly * 16.5 * 17 for QBs) — nonsense math, not a yardage model. A
  // ~25pt/week QB projected to 7043 season passing yards, ~1500 over the
  // NFL record. Same honesty rule as is_empty_projection elsewhere: no
  // real season-stat data means show 0, never a fabricated number.
  const mss = p.market_season_stats || {};
  const passYds = Math.round(p.season_pass_yd ?? mss.passing_yards ?? 0);
  const rushYds = Math.round(p.season_rush_yd ?? mss.rushing_yards ?? 0);
  const recYds = Math.round(p.season_rec_yd ?? mss.receiving_yards ?? 0);
  const recs = Math.round(p.season_rec ?? mss.receptions ?? 0);
  // why sum three fields, not a "total_tds" key: the backend only ever
  // emits passing_tds/rushing_tds/receiving_tds separately (see
  // _SEASON_STAT_KEYS in comparison/_model.py) — a "total_tds" key never
  // exists, so reading it directly silently showed 0 TDs on every card.
  const tds = Number((p.season_tds ?? ((mss.passing_tds || 0) + (mss.rushing_tds || 0) + (mss.receiving_tds || 0))).toFixed(1));

  // Recommendation logic
  let adviceTitle = 'START';
  let adviceCls = 'alert-ok';
  let adviceText = '';

  const slot = String(p.slot || 'BENCH').toUpperCase();

  if (slot === 'IR') {
    adviceTitle = 'On IR';
    adviceCls = 'alert-bad';
    adviceText = `${p.player_name} is on Injured Reserve. Monitor medical reports prior to activating.`;
  } else if (slot.startsWith('BN') || slot === 'BENCH') {
    if (weekly >= 12.0) {
      adviceTitle = 'Strong bench — consider starting';
      adviceCls = 'alert-warn';
      adviceText = `Strong bench projection (${weekly.toFixed(1)} pts/wk, ceiling ${upper.toFixed(1)} pts). Compare floor/ceiling with your starting FLEX slots before kickoff.`;
    } else {
      adviceTitle = 'BENCH DEPTH';
      adviceCls = 'alert-info';
      adviceText = `Solid depth piece (${weekly.toFixed(1)} pts/wk). Hold on bench for bye week coverage and favorable matchup switches.`;
    }
  } else {
    if (width > 7.0) {
      adviceTitle = 'Wide range — check matchup';
      adviceCls = 'alert-warn';
      adviceText = `High variance player (Floor ${lower.toFixed(1)} pts / Ceiling ${upper.toFixed(1)} pts). Monitor game script and weather before lock.`;
    } else if (weekly < 9.0) {
      adviceTitle = 'LOW FLOOR STARTER';
      adviceCls = 'alert-bad';
      adviceText = `Projected below tier average (${weekly.toFixed(1)} pts/wk). Search waiver/trade lab for potential upgrades.`;
    } else {
      adviceTitle = 'CONFIDENT STARTER';
      adviceCls = 'alert-ok';
      adviceText = `Strong starter signal (${weekly.toFixed(1)} pts/wk, ${edge} Edge). High confidence target for Week lineup.`;
    }
  }

  container.innerHTML = `
    <div class="player-modal-backdrop" id="modalBackdrop">
      <div class="player-modal-card card" role="dialog" aria-modal="true" tabindex="-1" aria-labelledby="modalPlayerName">
        <button class="modal-close-btn" id="modalCloseBtn" aria-label="Close modal">✕</button>

        <!-- Centered Header Hero -->
        <div style="display:flex; flex-direction:column; align-items:center; text-align:center; padding-bottom:16px; border-bottom:1px solid var(--border)">
          <div style="margin-bottom:12px">
            ${playerAvatar(p, 72)}
          </div>
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:center">
            <h2 id="modalPlayerName" style="margin:0; font-size:22px; font-weight:700">${escapeHtml(p.player_name)}</h2>
            ${posBadge(p.position)}
            ${teamLogo(p.team, 22)}
          </div>
          <div style="margin-top:6px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:center">
            <span class="mono faint micro">${escapeHtml(p.team || 'NFL')} vs ${escapeHtml(p.opponent_team || 'TBD')}</span>
            ${injuryBadge(p.injury_status)}
            ${p.tier ? `<span class="badge badge-violet">Tier ${p.tier}</span>` : ''}
            <span class="badge ${edge === 'BUY' ? 'badge-emerald' : edge === 'SELL' ? 'badge-crimson' : 'badge-faint'}" aria-label="${escapeAttr(edge)}">${edgeIcon}${edge} EDGE</span>
            <span class="mono faint micro">${p.ecr != null || p.adp != null ? `ECR #${p.ecr ?? '—'} · ADP #${p.adp ?? '—'} · ` : ''}Sleeper #${p.search_rank ?? '—'}${p.depth_order != null ? ` (${p.depth_position || p.position} ${p.depth_order})` : ''}</span>
          </div>
        </div>

        <!-- Market vs Model Comparison Cards -->
        <div class="modal-values-grid" style="margin-top:16px">
          <div class="modal-val-card">
            <span class="kicker">Model $</span>
            <span class="mono val-large" style="color:var(--amber)">$${gridironAuction}</span>
            <span class="micro faint">${weekly.toFixed(1)} projected pts/wk</span>
          </div>
          ${marketAuction != null ? `
          <div class="modal-val-card">
            <span class="kicker">Market Consensus $</span>
            <span class="mono val-large" style="color:var(--sky)">$${marketAuction}</span>
            <span class="micro faint">FP ECR &amp; ADP Consensus</span>
          </div>
          <div class="modal-val-card">
            <span class="kicker">Value Delta (Δ $)</span>
            <span class="mono val-large ${deltaAuction > 0 ? 'text-good' : deltaAuction < 0 ? 'text-bad' : 'faint'}">
              ${deltaAuction != null ? `${deltaAuction > 0 ? '+' : ''}$${deltaAuction}` : '—'}
            </span>
            <span class="micro faint">${deltaAuction > 0 ? 'Model Overweight (BUY)' : deltaAuction < 0 ? 'Model Underweight (SELL)' : deltaAuction == null ? 'No market comparison' : 'Fair Market Price'}</span>
          </div>` : ''}
        </div>

        <!-- Projection Confidence Interval & Floor/Ceiling -->
        <div class="modal-section" style="margin-top:16px; background:var(--surface-raised); padding:12px; border-radius:10px; border:1px solid var(--border)">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
            <span class="kicker">Conformal Confidence Interval (Floor / Ceiling)</span>
            <span class="badge badge-amber micro">Width: ${width.toFixed(1)} pts</span>
          </div>
          <div>
            ${intervalBar({ point: weekly, low: lower, high: upper, width: width, min: 0, max: 35 })}
          </div>
          <div style="display:flex; justify-content:space-between; margin-top:8px; font-size:12px" class="mono">
            <span><span class="faint">Floor:</span> <strong style="color:var(--crimson)">${lower.toFixed(1)} pts</strong></span>
            <span><span class="faint">Target:</span> <strong style="color:var(--amber)">${weekly.toFixed(1)} pts</strong></span>
            <span><span class="faint">Ceiling:</span> <strong style="color:var(--emerald)">${upper.toFixed(1)} pts</strong></span>
          </div>
        </div>

        <!-- 17-Game Stat Breakdown Bars -->
        <div class="modal-section" style="margin-top:16px">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
            <span class="kicker">17-Game Projected Stat Totals</span>
            <span class="mono micro faint">Season Proj: ${seasonPts.toFixed(0)} pts</span>
          </div>
          <div style="display:flex; flex-direction:column; gap:8px">
            ${isPasser ? renderStatBar('Passing Yards', passYds, 4800, '#38BDF8', 'YDS') : ''}
            ${isRunner ? renderStatBar('Rushing Yards', rushYds, 1600, '#10B981', 'YDS') : ''}
            ${isReceiver ? renderStatBar('Receiving Yards', recYds, 1600, '#F59E0B', 'YDS') : ''}
            ${isReceiver ? renderStatBar('Receptions', recs, 130, '#38BDF8', 'REC') : ''}
            ${renderStatBar('Total Touchdowns', tds, 20, '#A855F7', 'TD')}
          </div>
        </div>

        <!-- Start/Sit Advisor Recommendation -->
        <div class="alert ${adviceCls}" style="margin-top:16px">
          <div style="display:flex; flex-direction:column; gap:4px; width:100%">
            <div style="font-weight:700; font-size:12px; letter-spacing:0.04em">${adviceTitle}</div>
            <div style="font-size:12px; line-height:1.4">${escapeHtml(adviceText)}</div>
          </div>
        </div>

        <div style="margin-top:20px; display:flex; justify-content:flex-end">
          <button class="btn btn-ghost" id="modalDismissBtn">Close</button>
        </div>
      </div>
    </div>
  `;

  const card = container.querySelector('.player-modal-card');
  const backdrop = container.querySelector('#modalBackdrop');
  // Choreographed enter: backdrop opacity + card translateY/scale (CSS handles timing).
  if (backdrop && card) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        backdrop.classList.add('show');
        card.classList.add('show');
      });
    });
  }
  // close defined before trapFocus so Escape can invoke full close (not just release).
  let releaseFocus = () => {};
  let closing = false;
  const close = () => {
    if (closing) return;
    closing = true;
    try { releaseFocus(); } catch (_) {}
    const done = () => {
      container.innerHTML = '';
      // Focus return is handled by trapFocus.release(), but ensure fallback
      // if trigger is still in the document and focus landed on body.
      if (triggerEl && typeof triggerEl.focus === 'function' && document.contains(triggerEl)) {
        if (!document.activeElement || document.activeElement === document.body) {
          triggerEl.focus();
        }
      }
    };
    const b = container.querySelector('#modalBackdrop');
    const c = container.querySelector('.player-modal-card');
    if (!b || !c) { done(); return; }
    b.classList.add('closing');
    c.classList.add('closing');
    let finished = false;
    const finish = () => { if (!finished) { finished = true; done(); } };
    // Prefer transitionend on the card; rAF/timeout fallback guarantees cleanup.
    c.addEventListener('transitionend', finish, { once: true });
    requestAnimationFrame(() => { setTimeout(finish, 200); });
  };
  releaseFocus = trapFocus(card, triggerEl, close);

  // NOTE: container lives under document.body (not #app), so query container
  // directly — root.querySelector would be null when root is #app (P0-1).
  container.querySelector('#modalCloseBtn')?.addEventListener('click', close);
  container.querySelector('#modalDismissBtn')?.addEventListener('click', close);
  container.querySelector('#modalBackdrop')?.addEventListener('click', (e) => {
    if (e.target.id === 'modalBackdrop') close();
  });
}

function renderStatBar(label, value, maxVal, color, unit) {
  const val = Number(value || 0);
  const pct = Math.max(3, Math.min(100, (val / maxVal) * 100));

  return `
    <div class="stat-bar-row">
      <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:3px" class="mono">
        <span class="faint">${label}</span>
        <strong style="color:${color}">${val.toLocaleString()} ${unit}</strong>
      </div>
      <div style="height:8px; background:rgba(var(--text-rgb,0,0,0),0.06); border-radius:4px; overflow:hidden">
        <div style="width:${pct}%; height:100%; background:${color}; border-radius:4px"></div>
      </div>
    </div>
  `;
}
