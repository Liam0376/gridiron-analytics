// hub/src/components/playerModal.js — Draftea Player Detail Modal
import { playerAvatar } from './playerAvatar.js';
import { posBadge, injuryBadge } from './badges.js';
import { teamLogo } from './teamLogo.js';
import { intervalBar } from './intervalBar.js';

export function openPlayerModal(p, root = document.getElementById('app') || document.body) {
  let container = root.querySelector('#playerModalContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'playerModalContainer';
    root.appendChild(container);
  }

  const isPasser = p.position === 'QB';
  const isRunner = p.position === 'RB' || p.position === 'QB';
  const isReceiver = p.position === 'WR' || p.position === 'TE' || p.position === 'RB';

  const weekly = Number(p.weekly ?? p.projected_points ?? 0);
  const seasonPts = Number(p.season ?? (weekly * 17));
  const lower = Number(p.lower ?? p.projection_lower ?? Math.max(0, weekly - 2.5));
  const upper = Number(p.upper ?? p.projection_upper ?? (weekly + 2.5));
  const width = Number(p.width ?? (upper - lower));

  const gridironAuction = Number(p.gridironAuction ?? p.auction ?? Math.max(1, Math.round(weekly * 2.2)));
  const marketAuction = Number(p.marketAuction ?? p.market_auction ?? Math.max(1, Math.round(gridironAuction * 0.9)));
  const deltaAuction = Number(p.deltaAuction ?? (gridironAuction - marketAuction));
  const edge = (p.edge || 'NEUTRAL').toUpperCase();

  // 17-game stat projections
  const passYds = Math.round(p.season_pass_yd ?? (isPasser ? weekly * 16.5 * 17 : 0));
  const rushYds = Math.round(p.season_rush_yd ?? (p.position === 'RB' ? weekly * 5.2 * 17 : isPasser ? weekly * 1.4 * 17 : 0));
  const recYds = Math.round(p.season_rec_yd ?? ((p.position === 'WR' || p.position === 'TE') ? weekly * 5.6 * 17 : p.position === 'RB' ? weekly * 2.1 * 17 : 0));
  const recs = Math.round(p.season_rec ?? ((p.position === 'WR' || p.position === 'TE') ? weekly * 0.46 * 17 : p.position === 'RB' ? weekly * 0.28 * 17 : 0));
  const tds = Number((p.season_tds ?? (weekly * 0.52 * 17 / 10)).toFixed(1));

  // Recommendation logic
  let adviceTitle = 'START';
  let adviceCls = 'alert-ok';
  let adviceText = '';

  const slot = String(p.slot || 'BENCH').toUpperCase();

  if (slot === 'IR') {
    adviceTitle = 'INJURED RESERVE';
    adviceCls = 'alert-bad';
    adviceText = `${p.player_name} is on Injured Reserve. Monitor medical reports prior to activating.`;
  } else if (slot.startsWith('BN') || slot === 'BENCH') {
    if (weekly >= 12.0) {
      adviceTitle = 'HIGH-UPSIDE BENCH (CONSIDER STARTING)';
      adviceCls = 'alert-warn';
      adviceText = `Strong bench projection (${weekly.toFixed(1)} pts/wk, ceiling ${upper.toFixed(1)} pts). Compare floor/ceiling with your starting FLEX slots before kickoff.`;
    } else {
      adviceTitle = 'BENCH DEPTH';
      adviceCls = 'alert-info';
      adviceText = `Solid depth piece (${weekly.toFixed(1)} pts/wk). Hold on bench for bye week coverage and favorable matchup switches.`;
    }
  } else {
    if (width > 7.0) {
      adviceTitle = 'VOLATILE STARTER (WIDE INTERVAL)';
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
      <div class="player-modal-card card reveal in" role="dialog" aria-modal="true" aria-labelledby="modalPlayerName">
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
            <span class="badge ${edge === 'BUY' ? 'badge-emerald' : edge === 'SELL' ? 'badge-crimson' : 'badge-faint'}">${edge} EDGE</span>
            <span class="mono faint micro">ECR #${p.ecr ?? '—'} · ADP #${p.adp ?? '—'}</span>
          </div>
        </div>

        <!-- Market vs Model Comparison Cards -->
        <div class="modal-values-grid" style="margin-top:16px">
          <div class="modal-val-card">
            <span class="kicker">Gridiron Model $</span>
            <span class="mono val-large" style="color:var(--amber)">$${gridironAuction}</span>
            <span class="micro faint">${weekly.toFixed(1)} projected pts/wk</span>
          </div>
          <div class="modal-val-card">
            <span class="kicker">Market Consensus $</span>
            <span class="mono val-large" style="color:var(--sky)">$${marketAuction}</span>
            <span class="micro faint">FP ECR &amp; ADP Consensus</span>
          </div>
          <div class="modal-val-card">
            <span class="kicker">Value Delta (Δ $)</span>
            <span class="mono val-large ${deltaAuction > 0 ? 'text-good' : deltaAuction < 0 ? 'text-bad' : 'faint'}">
              ${deltaAuction > 0 ? '+' : ''}$${deltaAuction}
            </span>
            <span class="micro faint">${deltaAuction > 0 ? 'Model Overweight (BUY)' : deltaAuction < 0 ? 'Model Underweight (SELL)' : 'Fair Market Price'}</span>
          </div>
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

  const close = () => {
    container.innerHTML = '';
    document.removeEventListener('keydown', handleKey);
  };

  const handleKey = (e) => {
    if (e.key === 'Escape') close();
  };

  root.querySelector('#modalCloseBtn')?.addEventListener('click', close);
  root.querySelector('#modalDismissBtn')?.addEventListener('click', close);
  root.querySelector('#modalBackdrop')?.addEventListener('click', (e) => {
    if (e.target.id === 'modalBackdrop') close();
  });
  document.addEventListener('keydown', handleKey);
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
      <div style="height:8px; background:rgba(0,0,0,0.06); border-radius:4px; overflow:hidden">
        <div style="width:${pct}%; height:100%; background:${color}; border-radius:4px; transition:width 300ms ease"></div>
      </div>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}
