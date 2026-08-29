// hub/src/tierlist.js — deterministic tiering, no LLM.
// Groups sorted projections into tiers where gap > threshold.
// Vendored logic mirrors the plan's tier_gap/tier_cap — pure sort + gap walk.

export function buildTiers(players, { gap = 2.0, cap = 6, useFlex = false } = {}) {
  if (!players || players.length === 0) return [];
  // Optionally apply flex adjustment before tiering is done server-side; here we just tier by provided points.
  const sorted = [...players].sort((a,b) => (b.projected_points ?? b.point_estimate ?? 0) - (a.projected_points ?? a.point_estimate ?? 0));
  // Adaptive gap: if interval widths are known, increase gap to avoid splitting within uncertainty
  const medianWidth = median(sorted.map(p => p.width ?? p.projection_width ?? 5));
  const effGap = Math.max(gap, medianWidth * 0.7);

  const tiers = [];
  let cur = [];
  for (let i = 0; i < sorted.length; i++) {
    const p = sorted[i];
    const prev = sorted[i-1];
    const prevPts = prev ? (prev.projected_points ?? prev.point_estimate ?? 0) : null;
    const curPts = p.projected_points ?? p.point_estimate ?? 0;
    const gapToPrev = prevPts !== null ? (prevPts - curPts) : 0;
    const newTier = prev && (gapToPrev > effGap || cur.length >= cap);
    if (newTier) {
      tiers.push(cur);
      cur = [];
    }
    cur.push(p);
  }
  if (cur.length) tiers.push(cur);
  // assign tier numbers
  tiers.forEach((tier, idx) => tier.forEach(p => { p.tier = idx + 1; }));
  return tiers;
}

function median(arr) {
  if (!arr.length) return 5;
  const s = [...arr].sort((a,b)=>a-b);
  const mid = Math.floor(s.length/2);
  return s.length % 2 ? s[mid] : (s[mid-1]+s[mid])/2;
}
