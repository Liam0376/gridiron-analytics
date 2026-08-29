export function intervalBar({ point, low, high, width, min = 0, max = 30 }) {
  const range = max - min;
  const w = width ?? (high != null && low != null ? (high - low) : 10);
  const lo = low ?? (point - w/2);
  const hi = high ?? (point + w/2);
  const leftPct = Math.max(0, Math.min(100, ((lo - min) / range) * 100));
  const widthPct = Math.max(4, Math.min(100 - leftPct, ((hi - lo) / range) * 100));
  const dotPct = Math.max(0, Math.min(100, ((point - min) / range) * 100));
  return `
    <div class="interval" title="${lo.toFixed(1)} — ${point.toFixed(1)} — ${hi.toFixed(1)}">
      <div class="interval-track"><div class="interval-fill" style="left:${leftPct}%; width:${widthPct}%"></div><div class="interval-dot" style="left:${dotPct}%"></div></div>
      <span class="interval-label mono">${point.toFixed(1)}</span>
    </div>
  `;
}
