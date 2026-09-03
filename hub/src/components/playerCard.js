// Mobile-friendly player card component
import { playerAvatar } from './playerAvatar.js';
import { teamLogo } from './teamLogo.js';
import { getTeamColor } from './teamColors.js';
import { posBadge, injuryBadge, windBadge } from './badges.js';
import { intervalBar } from './intervalBar.js';
import { escapeHtml } from '../lib/escape.js';

export function playerCard(player, options = {}) {
  const { showDraftBtn = false, showInterval = true, showTeamLogo = true, draftValue = null } = options;
  const p = player;
  const pos = (p.position || p.position_group || 'UNK').toUpperCase();
  const proj = Number(p.projected_points ?? p.point_estimate ?? 0);
  const low = Number(p.projection_lower ?? p.lower_bound ?? proj - (p.width ?? 5) / 2);
  const high = Number(p.projection_upper ?? p.upper_bound ?? proj + (p.width ?? 5) / 2);
  const width = Number(p.width ?? p.projection_width ?? (high - low));
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
      ${intervalSection || badgeRow.length || draftSection ? `
        <div class="pc-details">
          ${intervalSection}
          ${badgeRow.length ? `<div class="pc-badges">${badgeRow.join(' ')}</div>` : ''}
          ${draftSection}
        </div>
      ` : ''}
    </div>
  `;
}
