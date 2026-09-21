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

// Semicircle dial geometry. Center (36,40), radius 30; pct 0 = left,
// 100 = right, 50 = top.
function _dialPoint(pct, r) {
  const a = (180 - Math.max(0, Math.min(100, pct)) * 1.8) * Math.PI / 180;
  return [36 + r * Math.cos(a), 40 - r * Math.sin(a)];
}

function _fmt(n) {
  return (Math.round(n * 10) / 10).toString();
}

function _ticks() {
  let s = '';
  for (let i = 0; i <= 10; i++) {
    const [x1, y1] = _dialPoint(i * 10, 30);
    const [x2, y2] = _dialPoint(i * 10, 25.5);
    const major = i % 5 === 0;
    s += `<line x1="${_fmt(x1)}" y1="${_fmt(y1)}" x2="${_fmt(x2)}" y2="${_fmt(y2)}" stroke="var(--text-faint)" stroke-width="${major ? 1.6 : 1}" opacity="${major ? 0.9 : 0.5}" stroke-linecap="round"/>`;
  }
  return s;
}

export function statGauge(label, v, delayMs = 0) {
  const st = GAUGE_STYLE[label];
  if (v == null || !st) return '';
  const pct = Math.max(0, Math.min(100, (Number(v) / st.max) * 100));
  const gid = `gg${__gid++}`;
  const sr = `${label} ${v} of ${st.max} scale`;
  const [nx, ny] = _dialPoint(pct, 21);
  return `<div class="modal-val-card pc-gauge-card" role="img" aria-label="${sr}" title="${sr}" style="min-width:104px;padding:10px 8px">`
    + `<span class="kicker">${label}</span>`
    + `<svg viewBox="0 0 72 46" width="76" height="48" aria-hidden="true" focusable="false" style="margin:4px auto;overflow:visible">`
    + `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="1" y2="0">`
    + `<stop offset="0" stop-color="${st.from}"/><stop offset="1" stop-color="${st.to}"/>`
    + `</linearGradient>`
    + `<filter id="${gid}-glow" x="-60%" y="-60%" width="220%" height="220%">`
    + `<feGaussianBlur stdDeviation="2.2" result="b"/>`
    + `<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>`
    + `</filter></defs>`
    + _ticks()
    + `<path d="M6 40 A30 30 0 0 1 66 40" fill="none" stroke="var(--border)" stroke-width="7" stroke-linecap="round"/>`
    + `<path class="gauge-arc" style="--p:${pct.toFixed(1)} 100;animation-delay:${delayMs}ms" d="M6 40 A30 30 0 0 1 66 40" fill="none" stroke="url(#${gid})" stroke-width="7" stroke-linecap="round" filter="url(#${gid}-glow)" pathLength="100" stroke-dasharray="${pct.toFixed(1)} 100"/>`
    + `<line x1="36" y1="40" x2="${_fmt(nx)}" y2="${_fmt(ny)}" stroke="var(--text)" stroke-width="2" stroke-linecap="round"/>`
    + `<circle cx="36" cy="40" r="3" fill="var(--text-faint)"/>`
    + `</svg><span class="mono val-large" style="color:${st.from};font-size:20px">${v}</span></div>`;
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
  return `<div class="pc-gauges" style="display:flex;gap:8px;flex-wrap:wrap;align-items:stretch">${wk}${dials.join('')}</div>`;
}
