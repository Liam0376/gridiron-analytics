// Shared projected-stat speedometers (weekly proj_* API fields).
// Each stat renders as a Model-$-style mini card: kicker label, gradient
// dial, big value. Colors mirror the modal's stat bars (passing sky,
// rushing emerald, receiving amber, TDs/kicking violet, XP slate) so the
// two views read as one system. Scale caps are fixed per stat so fills
// stay comparable week to week. Static final state in the attribute;
// CSS animates the fill on mount (disabled under reduced-motion).
// Pure string building — no DOM. Returns '' when data is absent.
const GAUGE_STYLE = {
  PaYd:  { max: 350, from: '#0EA5E9', to: '#38BDF8' },
  PaTD:  { max: 5,   from: '#0284C7', to: '#38BDF8' },
  RuYd:  { max: 150, from: '#059669', to: '#10B981' },
  RuTD:  { max: 3,   from: '#059669', to: '#6EE7B7' },
  Rec:   { max: 12,  from: '#D97706', to: '#F59E0B' },
  RecYd: { max: 150, from: '#D97706', to: '#FBBF24' },
  RecTD: { max: 3,   from: '#B45309', to: '#F59E0B' },
  FGm:   { max: 5,   from: '#7C3AED', to: '#A855F7' },
  XP:    { max: 6,   from: '#64748B', to: '#94A3B8' },
};

let __gid = 0;

export function statGauge(label, v, delayMs = 0) {
  const st = GAUGE_STYLE[label];
  if (v == null || !st) return '';
  const pct = Math.max(0, Math.min(100, (Number(v) / st.max) * 100));
  const gid = `gg${__gid++}`;
  const sr = `${label} ${v} of ${st.max} scale`;
  return `<div class="modal-val-card pc-gauge-card" role="img" aria-label="${sr}" title="${sr}" style="min-width:76px;padding:8px 6px;text-align:center">`
    + `<span class="kicker">${label}</span>`
    + `<svg viewBox="0 0 44 30" width="52" height="35" aria-hidden="true" focusable="false" style="margin:2px auto;display:block">`
    + `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="1" y2="0">`
    + `<stop offset="0" stop-color="${st.from}"/><stop offset="1" stop-color="${st.to}"/>`
    + `</linearGradient></defs>`
    + `<path d="M4 24 A18 18 0 0 1 40 24" fill="none" stroke="var(--border)" stroke-width="5" stroke-linecap="round"/>`
    + `<path class="gauge-arc" style="--p:${pct.toFixed(1)} 100;animation-delay:${delayMs}ms" d="M4 24 A18 18 0 0 1 40 24" fill="none" stroke="url(#${gid})" stroke-width="5" stroke-linecap="round" pathLength="100" stroke-dasharray="${pct.toFixed(1)} 100"/>`
    + `</svg><span class="mono val-large" style="color:${st.from}">${v}</span></div>`;
}

export function statGaugesForPosition(pos, p) {
  const dials = [];
  const push = (label, v) => { const g = statGauge(label, v, dials.length * 90); if (g) dials.push(g); };
  if (pos === 'QB') {
    push('PaYd', p.proj_pass_yd); push('PaTD', p.proj_pass_td);
    push('RuYd', p.proj_rush_yd); push('RuTD', p.proj_rush_td);
  } else if (pos === 'RB') {
    push('RuYd', p.proj_rush_yd); push('RuTD', p.proj_rush_td);
    push('Rec', p.proj_rec); push('RecYd', p.proj_rec_yd);
  } else if (pos === 'WR' || pos === 'TE') {
    push('Rec', p.proj_rec); push('RecYd', p.proj_rec_yd);
    push('RecTD', p.proj_rec_td);
  } else if (pos === 'K') {
    push('FGm', p.proj_fgm); push('XP', p.proj_xpm);
  }
  return dials;
}

export function statGaugesRow(pos, p, weekLabel = null) {
  const dials = statGaugesForPosition(pos, p);
  if (!dials.length) return '';
  const wk = weekLabel != null ? `<span class="mono" style="font-size:11px;color:var(--text-faint);align-self:center">Wk${weekLabel}</span>` : '';
  return `<div class="pc-gauges" style="display:flex;gap:8px;flex-wrap:wrap;align-items:stretch;justify-content:center">${wk}${dials.join('')}</div>`;
}
