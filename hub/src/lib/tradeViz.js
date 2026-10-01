// Pure builders for the trade verdict visuals: strings in, strings out,
// no DOM access. Kept dependency-free (inline SVG + CSS classes) so the
// bundle cost stays flat. Self-check: `node src/lib/tradeViz.js`.

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Shared y-maximum across both team panels — one scale, honest comparison. */
export function sharedMax(...seriesLists) {
  const vals = seriesLists.flat().map(Number).filter(Number.isFinite);
  return Math.max(1, ...vals);
}

/**
 * Before-vs-after weekly lineup chart. viewBox 0 0 100 30 stretched to the
 * container (preserveAspectRatio="none"); non-scaling-stroke keeps line
 * weights honest at any width. Playoff weeks get a shaded rect starting at
 * the first remaining week >= playoffWeekStart. Length mismatch or empty
 * input returns '' so callers can hide the whole block.
 */
export function impactSvg(before, after, yMax, weeks, playoffWeekStart) {
  if (!before || !after || !before.length || before.length !== after.length) return '';
  const n = before.length;
  const x = (i) => (n === 1 ? 50 : (i / (n - 1)) * 100);
  const y = (v) => 29 - (clamp(Number(v) || 0, 0, yMax) / yMax) * 27;
  const pts = (arr) => arr.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(' ');
  const poStart = Number(playoffWeekStart || 15);
  const poIdx = (weeks || []).findIndex((w) => Number(w) >= poStart);
  const shade = (poIdx > 0 && poIdx < n)
    ? `<rect x="${x(poIdx).toFixed(2)}" y="0" width="${(100 - x(poIdx)).toFixed(2)}"`
      + ` height="30" class="po-shade"></rect>`
    : '';
  return `<svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">${shade}`
    + `<polyline class="ln-before" vector-effect="non-scaling-stroke" points="${pts(before)}"></polyline>`
    + `<polyline class="ln-after" vector-effect="non-scaling-stroke" points="${pts(after)}"></polyline>`
    + `</svg>`;
}

/** Diverging green/red bars for per-position lineup deltas. */
export function groupBars(gd) {
  if (!gd) return '';
  const rank = ['QB', 'RB', 'WR', 'TE', 'DEF', 'K'];
  const pos = (g) => { const i = rank.indexOf(g); return i < 0 ? 99 : i; };
  const entries = Object.entries(gd)
    .map(([g, v]) => [g, Number(v) || 0])
    .filter(([, v]) => Math.abs(v) >= 0.05)
    .sort((a, b) => pos(a[0]) - pos(b[0]));
  if (!entries.length) return '';
  const max = Math.max(...entries.map(([, v]) => Math.abs(v)), 1);
  return `<div class="gd-block">${entries.map(([g, v]) => `
    <div class="gd-row"><span class="gd-lab">${g}</span>
      <div class="gd-track"><div class="gd-fill ${v >= 0 ? 'pos' : 'neg'}"`
    + ` style="width:${((Math.abs(v) / max) * 50).toFixed(1)}%"></div></div>
      <span class="gd-val ${v >= 0 ? 'pos' : 'neg'}">${v > 0 ? '+' : ''}${v.toFixed(1)}</span>
    </div>`).join('')}</div>`;
}

// Runnable self-check for the chart math (node only, inert in the browser).
if (typeof process !== 'undefined' && process.argv[1]
    && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  const check = (cond, msg) => { if (!cond) throw new Error(`tradeViz: ${msg}`); };
  const yMax = sharedMax([100, 110, 120], [110, 120, 130]);
  check(yMax === 130, 'sharedMax takes the top of every series');
  const svg = impactSvg([100, 110, 120], [110, 120, 130], yMax, [4, 5, 6], 15);
  check(svg.includes('ln-before') && svg.includes('ln-after'), 'both lines render');
  check(!svg.includes('po-shade'), 'no playoff shade outside the playoff window');
  const po = impactSvg([100, 110, 120], [100, 110, 120], 130, [14, 15, 16], 15);
  check(po.includes('po-shade'), 'shade starts at the first playoff week');
  check(impactSvg([1], [2, 3], 10, [], 15) === '', 'length mismatch hides the chart');
  check(impactSvg([], [], 10, [], 15) === '', 'empty input hides the chart');
  const bars = groupBars({ RB: 15.3, WR: -7.8, QB: 0 });
  check(bars.includes('gd-fill pos') && bars.includes('gd-fill neg'), 'bars go both ways');
  check(!bars.includes('>QB<'), 'zero deltas drop out');
  check(groupBars({}) === '' && groupBars(null) === '', 'empty deltas render nothing');
  console.log('tradeViz self-check ok');
}
