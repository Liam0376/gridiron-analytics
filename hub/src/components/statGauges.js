// Shared projected-stat speedometers (weekly proj_* API fields).
// Compact semicircular SVG dials, one per stat in the position's set.
// Value beside each dial carries the meaning (color supplementary);
// role="img" labels + titles for assistive tech. Static SVG keeps card
// grids cheap. Scale caps are fixed per stat so fills stay comparable
// week to week. Pure string building — no DOM — so it renders inside
// cards, modals, or anywhere else. Returns '' when data is absent.
const GAUGE_MAX = { PaYd: 350, PaTD: 5, RuYd: 150, RuTD: 3, Rec: 12,
                    RecYd: 150, RecTD: 3, FGm: 5, XP: 6 };

export function statGauge(label, v) {
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
}

export function statGaugesForPosition(pos, p) {
  const dials = [];
  const push = (label, v) => { const g = statGauge(label, v); if (g) dials.push(g); };
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
  return `<div class="pc-gauges" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start">${wk}${dials.join('')}</div>`;
}
