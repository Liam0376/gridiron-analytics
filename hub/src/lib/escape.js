// hub/src/lib/escape.js — safe HTML/attribute escaping and URL sanitization.

export function escapeHtml(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function escapeAttr(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
    .replaceAll('`', '&#96;');
}

const FORBIDDEN_URL_SCHEMES = /^(?:javascript|data|vbscript):/i;

export function safeUrl(url) {
  const s = String(url ?? '').trim();
  if (!s) return '';
  if (FORBIDDEN_URL_SCHEMES.test(s)) return '';
  return s;
}

const AVATAR_URL_ALLOWLIST = [
  /^https:\/\/sleepercdn\.com\//i,
  /^https:\/\/a\.espncdn\.com\//i,
  /^https:\/\/static\.nfl\.com\/static\/content\/public\/static\/img\/players\//i,
  /^https:\/\/nflverse\.github\.io\/nflverse-player-ids\//i,
];

export function safeAvatarUrl(url) {
  const s = String(url ?? '').trim();
  if (!s) return '';
  if (FORBIDDEN_URL_SCHEMES.test(s)) return '';
  if (!AVATAR_URL_ALLOWLIST.some(re => re.test(s))) return '';
  return s;
}