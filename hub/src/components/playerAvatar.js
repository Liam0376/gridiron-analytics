// Player headshot via Sleeper CDN with position-colored initial fallback
function escapeAttr(s) { return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#39;"); }

const POS_COLORS = { QB: '#38BDF8', RB: '#10B981', WR: '#F59E0B', TE: '#8B5CF6', K: '#EC4899', DEF: '#6B7280' };

function posColor(pos) { return POS_COLORS[(pos || '').toUpperCase()] || '#6B7280'; }

export function playerAvatar(player, size = 40) {
  const id = player.player_id || '';
  const name = player.player_name || player.name || '?';
  const pos = (player.position || player.position_group || '').toUpperCase();
  const initial = escapeAttr(name.charAt(0).toUpperCase());
  const color = posColor(pos);
  const src = `https://sleepercdn.com/content/nfl/players/thumb/${id}.jpg`;
  const fs = Math.round(size * 0.4);
  const fallbackHtml = '<div class=&quot;player-avatar-fallback&quot; style=&quot;width:' + size + 'px;height:' + size + 'px;border-radius:50%;background:var(--surface-raised);border:2px solid ' + escapeAttr(color) + ';display:flex;align-items:center;justify-content:center;font:700 ' + fs + 'px JetBrains Mono,monospace;color:' + escapeAttr(color) + ';flex-shrink:0&quot;>' + initial + '</div>';
  return `<div class="player-avatar" style="width:${size}px;height:${size}px;flex-shrink:0"><img src="${src}" alt="${escapeAttr(name)}" width="${size}" height="${size}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;border:2px solid ${color};display:block" onerror="this.outerHTML='${fallbackHtml}'"></div>`;
}
