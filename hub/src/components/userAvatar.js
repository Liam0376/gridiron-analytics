// User avatar component via Sleeper CDN with initials fallback
function escapeAttr(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

export function userAvatar(user, size = 32) {
  const name = user?.display_name || user?.team_name || user?.owner_name || user?.name || '?';
  const initial = escapeAttr(name.charAt(0).toUpperCase());
  const avatarId = user?.avatar || user?.avatar_id;
  const avatarUrl = user?.avatar_url || (avatarId ? `https://sleepercdn.com/avatars/thumbs/${avatarId}` : null);
  
  const fs = Math.round(size * 0.42);
  const fallbackHtml = `<div class="user-avatar-fallback" style="width:${size}px;height:${size}px;border-radius:50%;background:linear-gradient(135deg, var(--surface-raised), var(--surface));border:1px solid var(--border-active);display:flex;align-items:center;justify-content:center;font:700 ${fs}px ui-monospace, SFMono-Regular,monospace;color:var(--amber);flex-shrink:0">${initial}</div>`;
  
  if (!avatarUrl) {
    return fallbackHtml;
  }

  return `<div class="user-avatar" style="width:${size}px;height:${size}px;flex-shrink:0;position:relative"><img src="${escapeAttr(avatarUrl)}" alt="${escapeAttr(name)}" width="${size}" height="${size}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;border:1px solid var(--border-active);display:block;background:var(--surface)" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex'"><div class="user-avatar-fallback" style="display:none;width:${size}px;height:${size}px;border-radius:50%;background:linear-gradient(135deg, var(--surface-raised), var(--surface));border:1px solid var(--border-active);align-items:center;justify-content:center;font:700 ${fs}px ui-monospace, SFMono-Regular,monospace;color:var(--amber);flex-shrink:0">${initial}</div></div>`;
}
