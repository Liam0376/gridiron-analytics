export function intervalBar({ point, low, high, width, min = 0, max = 30 }) {
  const range = max - min;
  const pt = Number.isFinite(Number(point)) ? Number(point) : 0;
  const w = Number.isFinite(Number(width)) ? Number(width) : (Number.isFinite(Number(high)) && Number.isFinite(Number(low)) ? (Number(high) - Number(low)) : 10);
  const lo = Number.isFinite(Number(low)) ? Number(low) : (pt - w / 2);
  const hi = Number.isFinite(Number(high)) ? Number(high) : (pt + w / 2);
  const leftPct = Math.max(0, Math.min(100, ((lo - min) / range) * 100));
  const widthPct = Math.max(4, Math.min(100 - leftPct, ((hi - lo) / range) * 100));
  const dotPct = Math.max(0, Math.min(100, ((pt - min) / range) * 100));
  const srLabel = `Target ${pt.toFixed(1)}, floor ${lo.toFixed(1)}, ceiling ${hi.toFixed(1)}`;
  return `
    <div class="interval" role="img" aria-label="${srLabel}" title="${lo.toFixed(1)} — ${pt.toFixed(1)} — ${hi.toFixed(1)}">
      <div class="interval-track"><div class="interval-fill" style="left:${leftPct}%; width:${widthPct}%"></div><div class="interval-dot" style="left:${dotPct}%"></div></div>
      <span class="interval-label mono">${pt.toFixed(1)}</span>
    </div>
  `;
}
