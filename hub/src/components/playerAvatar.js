// Player headshot via Sleeper CDN with position-colored initial fallback
import { safeAvatarUrl, escapeAttr } from '../lib/escape.js';

const POS_COLORS = {
  QB: '#38BDF8',
  RB: '#10B981',
  WR: '#F59E0B',
  TE: '#8B5CF6',
  K: '#EC4899',
  DEF: '#6B7280'
};

function posColor(pos) {
  return POS_COLORS[(pos || '').toUpperCase()] || '#6B7280';
}

export function playerAvatar(player, size = 36) {
  const rawId = String(player?.sleeper_id || player?.player_id || player?.id || '');
  const isSleeper = /^\d+$/.test(rawId);
  const nflHead = safeAvatarUrl(player?.headshot_url || player?.headshot || player?.headshotUrl || '');
  const name = player?.player_name || player?.full_name || player?.name || '?';
  const pos = (player?.position || player?.position_group || '').toUpperCase();
  const team = (player?.team || '').toUpperCase();
  const initial = escapeAttr(name.charAt(0).toUpperCase());
  const color = posColor(pos);
  const fs = Math.round(size * 0.4);

  // DEF: show team logo instead of player headshot
  if (pos === 'DEF' && team) {
    const logoSrc = `https://sleepercdn.com/images/team_logos/nfl/${team.toLowerCase()}.png`;
    const label = escapeAttr(team.slice(0, 3));
    return `<div class="player-avatar" style="width:${size}px;height:${size}px;flex-shrink:0;position:relative"><img src="${logoSrc}" alt="${label}" width="${size}" height="${size}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:contain;border:1.5px solid ${color};display:block;background:var(--surface)" loading="lazy" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex'"><div class="player-avatar-fallback" style="display:none;width:${size}px;height:${size}px;border-radius:50%;background:var(--surface-raised);border:1.5px solid ${color};align-items:center;justify-content:center;font:700 ${fs}px ui-monospace, SFMono-Regular,monospace;color:${color};flex-shrink:0">${label}</div></div>`;
  }

  // Prefer numeric Sleeper CDN (constructed from validated numeric id), fallback to nflverse headshot_url (validated against allowlist), else initial
  let src = '';
  if (isSleeper) src = `https://sleepercdn.com/content/nfl/players/thumb/${rawId}.jpg`;
  else if (nflHead) src = nflHead;

  const fallbackHtml = `<div class="player-avatar-fallback" style="width:${size}px;height:${size}px;border-radius:50%;background:var(--surface-raised);border:1.5px solid ${color};display:flex;align-items:center;justify-content:center;font:700 ${fs}px ui-monospace, SFMono-Regular,monospace;color:${color};flex-shrink:0">${initial}</div>`;

  if (!src) return fallbackHtml;

  return `<div class="player-avatar" style="width:${size}px;height:${size}px;flex-shrink:0;position:relative"><img src="${src}" alt="${escapeAttr(name)}" width="${size}" height="${size}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;border:1.5px solid ${color};display:block;background:var(--surface)" loading="lazy" decoding="async" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex'"><div class="player-avatar-fallback" style="display:none;width:${size}px;height:${size}px;border-radius:50%;background:var(--surface-raised);border:1.5px solid ${color};align-items:center;justify-content:center;font:700 ${fs}px ui-monospace, SFMono-Regular,monospace;color:${color};flex-shrink:0">${initial}</div></div>`;
}
