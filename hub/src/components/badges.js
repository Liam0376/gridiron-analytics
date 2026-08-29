export function posBadge(pos) {
  const p = (pos || 'UNK').toUpperCase().slice(0,3);
  return `<span class="badge badge-pos" data-pos="${p}">${p}</span>`;
}
export function injuryBadge(status) {
  if (!status || status === 'Healthy' || status === 'Active') return `<span class="badge-injury healthy">● Healthy</span>`;
  const s = String(status);
  const cls = /out|ir|injured reserve/i.test(s) ? 'out' : /questionable|doubtful|limited/i.test(s) ? 'questionable' : 'questionable';
  return `<span class="badge-injury ${cls}">● ${s}</span>`;
}
export function windBadge(wind) {
  const w = Number(wind ?? 0);
  if (!w || w <= 0) return `<span class="badge-wind ok">—</span>`;
  const level = w > 20 ? 'bad' : w > 15 ? 'warn' : 'ok';
  const label = w > 15 ? `${w.toFixed(0)} mph` : `${w.toFixed(0)} mph`;
  return `<span class="badge-wind ${level}">${level === 'ok' ? '◍' : '⚑'} ${label}</span>`;
}
export function confBadge(width) {
  const w = Number(width ?? 5);
  const label = w < 3 ? 'HIGH' : w < 6 ? 'MED' : 'WIDE';
  const cls = w < 3 ? 'high' : w < 6 ? 'medium' : 'low';
  return `<span class="badge" style="background:${cls==='high'?'var(--emerald-dim)':cls==='medium'?'var(--amber-dim)':'rgba(255,255,255,0.06)'}; color:${cls==='high'?'var(--emerald)':cls==='medium'?'var(--amber)':'var(--text-muted)'}; border:1px solid ${cls==='high'?'rgba(16,185,129,0.2)':cls==='medium'?'rgba(245,158,11,0.2)':'var(--border)'}">${label} · ±${w.toFixed(1)}</span>`;
}
