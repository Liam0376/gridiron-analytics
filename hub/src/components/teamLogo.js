// NFL team logo via Sleeper CDN with colored-pill fallback
import { getTeamColor } from './teamColors.js';

function escapeAttr(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

export function teamLogo(teamAbbr, size = 24) {
  const abbr = (teamAbbr || '').toUpperCase();
  if (!abbr || abbr === '—') return '';
  const color = getTeamColor(abbr);
  const src = `https://sleepercdn.com/images/team_logos/nfl/${abbr.toLowerCase()}.png`;
  const label = escapeAttr(abbr.slice(0, 3));
  const r = Math.round(size / 2);
  const fs = Math.round(size * 0.45);

  return `<span class="team-logo-wrap" style="display:inline-flex;align-items:center;justify-content:center"><img class="team-logo" src="${src}" alt="${label}" width="${size}" height="${size}" style="border-radius:${r}px;object-fit:contain;flex-shrink:0" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='inline-flex'"><span class="team-logo-fallback" style="display:none;align-items:center;justify-content:center;width:${size}px;height:${size}px;border-radius:${r}px;background:${escapeAttr(color)};color:#fff;font:700 ${fs}px ui-monospace, SFMono-Regular,monospace;flex-shrink:0">${label}</span></span>`;
}
