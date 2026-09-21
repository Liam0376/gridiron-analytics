// Mobile-friendly player card component
import { playerAvatar } from './playerAvatar.js';
import { teamLogo } from './teamLogo.js';
import { getTeamColor } from './teamColors.js';
import { posBadge, injuryBadge, windBadge } from './badges.js';
import { intervalBar } from './intervalBar.js';
import { escapeHtml } from '../lib/escape.js';

export function playerCard(player, options = {}) {
  const { showDraftBtn = false, showInterval = true, showTeamLogo = true, draftValue = null, statWeek = null } = options;
  const p = player;
  const pos = (p.position || p.position_group || 'UNK').toUpperCase();
  const proj = Number(p.projected_points ?? p.point_estimate ?? 0);
  // why no /2: width is HALF-width (unified 2026-09-09); the (high-low)
  // fallback derives from a full span, so it halves. Floor matches src.
  const low = Number(p.projection_lower ?? p.lower_bound ?? Math.max(0, proj - (p.width ?? 5)));
  const high = Number(p.projection_upper ?? p.upper_bound ?? proj + (p.width ?? 5));
  const width = Number(p.width ?? p.projection_width ?? (high - low) / 2);
  const team = p.team || '';
  const opp = p.opponent_team || '';

  const teamSection = showTeamLogo && team ? `${teamLogo(team, 16)} ` : '';
  const oppSection = opp ? `<span class="faint">vs</span> ${showTeamLogo ? teamLogo(opp, 16) + ' ' : ''}${escapeHtml(opp)}` : '';

  const intervalSection = showInterval ? `<div class="pc-interval">${intervalBar({ point: proj, low, high, width, min: 0, max: 35 })}</div>` : '';

  const badgeRow = [];
  if (p.wind_mph > 0) badgeRow.push(windBadge(p.wind_mph));
  if (p.injury_status) badgeRow.push(injuryBadge(p.injury_status));
  if (p.trending) badgeRow.push('<span class="badge" style="background:var(--sky-dim);color:var(--sky)">&#8599; trending</span>');

  const draftSection = showDraftBtn
    ? `<button class="btn btn-primary btn-sm draftBtn pc-draft-btn" data-pid="${escapeHtml(p.player_id)}" data-name="${escapeHtml(p.player_name)}" data-val="${draftValue ?? p.auction ?? 1}">Draft $${draftValue ?? p.auction ?? 1}</button>`
    : '';

  // Projected-stat speedometers from the weekly proj_* API fields.
  // Compact semicircular SVG gauges (one per stat in the position's set),
  // value beside the dial per accessible-chart practice: color is
  // supplementary, the number carries the meaning. Nothing renders when
  // the data is absent (e.g. auction views), so shared callers are
  // unaffected. Static SVG (no animation) keeps card grids cheap.
  // Scale caps are fixed per stat so fills stay comparable week to week.
  const GAUGE_MAX = { PaYd: 350, PaTD: 5, RuYd: 150, RuTD: 3, Rec: 12,
                      RecYd: 150, RecTD: 3, FGm: 5, XP: 6 };
  const gauge = (label, v) => {
    if (v == null) return '';
    const max = GAUGE_MAX[label] || 100;
    const pct = Math.max(0, Math.min(100, (Number(v) / max) * 100));
    const sr = `${label} ${v} of ${max} scale`;
    return `<span class="pc-gauge" role="img" aria-label="${sr}" title="${sr}" style="display:inline-flex;flex-direction:column;align-items:center;width:52px">`
      + `<svg viewBox="0 0 44 26" width="44" height="26" aria-hidden="true" focusable="false">`
      + `<path d="M4 22 A18 18 0 0 1 40 22" fill="none" stroke="var(--border)" stroke-width="5" stroke-linecap="round"/>`
      + `<path d="M4 22 A18 18 0 0 1 40 22" fill="none" stroke="var(--amber)" stroke-width="5" stroke-linecap="round" pathLength="100" stroke-dasharray="${pct.toFixed(1)} 100"/>`
      + `</svg><span class="pc-gauge-val mono" style="font-size:11px;font-weight:700">${v}</span>`
      + `<span class="pc-gauge-label" style="font-size:9px;color:var(--text-faint)">${label}</span></span>`;
  };
  const dials = [];
  const pushGauge = (label, v) => { const g = gauge(label, v); if (g) dials.push(g); };
  if (pos === 'QB') {
    pushGauge('PaYd', p.proj_pass_yd); pushGauge('PaTD', p.proj_pass_td);
    pushGauge('RuYd', p.proj_rush_yd); pushGauge('RuTD', p.proj_rush_td);
  } else if (pos === 'RB') {
    pushGauge('RuYd', p.proj_rush_yd); pushGauge('RuTD', p.proj_rush_td);
    pushGauge('Rec', p.proj_rec); pushGauge('RecYd', p.proj_rec_yd);
  } else if (pos === 'WR' || pos === 'TE') {
    pushGauge('Rec', p.proj_rec); pushGauge('RecYd', p.proj_rec_yd);
    pushGauge('RecTD', p.proj_rec_td);
  } else if (pos === 'K') {
    pushGauge('FGm', p.proj_fgm); pushGauge('XP', p.proj_xpm);
  }
  const statSection = dials.length
    ? `<div class="pc-gauges" style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;align-items:flex-start">${statWeek != null ? `<span class="mono" style="font-size:11px;color:var(--text-faint);align-self:center">Wk${escapeHtml(String(statWeek))}</span>` : ''}${dials.join('')}</div>`
    : '';

  return `
    <div class="player-card-v2" data-pid="${escapeHtml(p.player_id || '')}" style="--team-accent:${getTeamColor(team)}">
      <div class="pc-header">
        ${playerAvatar(p, 44)}
        <div class="pc-info">
          <div class="pc-name">${escapeHtml(p.player_name || p.player_id)}</div>
          <div class="pc-meta">${posBadge(pos)} ${teamSection}${escapeHtml(team)} ${oppSection}</div>
        </div>
        <div class="pc-proj mono">${proj.toFixed(1)}</div>
      </div>
      ${intervalSection || badgeRow.length || draftSection || statSection ? `
        <div class="pc-details">
          ${intervalSection}
          ${statSection}
          ${badgeRow.length ? `<div class="pc-badges">${badgeRow.join(' ')}</div>` : ''}
          ${draftSection}
        </div>
      ` : ''}
    </div>
  `;
}
