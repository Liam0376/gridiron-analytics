// Floor/ceiling (P20/P80) mirror of src/ffanalytics/stat_projector.py
// INTERVAL_TABLE + interval_bounds, and decision.beat_prob. Pinned by
// tests/test_interval_parity.py; refit with scripts/fit_intervals.py.
export const INTERVAL_TABLE = {
  QB: [[4.2, 0.0, 14.0], [11.0, 3.2, 22.2], [14.7, 8.8, 24.7], [17.1, 10.1, 24.1], [19.5, 11.0, 28.9], [23.4, 14.2, 29.8]],
  RB: [[0.7, 0.0, 1.4], [1.9, 0.0, 4.2], [3.4, 0.4, 7.0], [5.1, 1.1, 9.4], [7.2, 2.3, 12.5], [10.1, 4.3, 15.9], [13.5, 7.4, 20.2], [18.8, 9.9, 25.0]],
  WR: [[0.6, 0.0, 2.0], [2.0, 0.0, 4.2], [3.5, 0.0, 7.4], [5.1, 1.0, 8.6], [7.0, 1.7, 10.8], [9.3, 3.1, 15.6], [12.1, 5.1, 18.9], [17.0, 7.8, 21.8]],
  TE: [[0.8, 0.0, 2.4], [2.0, 0.0, 4.1], [3.2, 0.0, 6.1], [4.5, 1.3, 7.1], [6.3, 2.4, 10.8], [8.6, 3.7, 14.4], [12.6, 4.8, 18.7]],
  K: [[5.8, 4.0, 12.0], [7.6, 4.0, 12.0], [8.7, 4.0, 12.0], [10.7, 4.0, 13.0]],
};

export function intervalBounds(point, pos) {
  const pts = INTERVAL_TABLE[(pos || '').toUpperCase()] || INTERVAL_TABLE.WR;
  let c, lo, hi;
  if (point <= pts[0][0]) [c, lo, hi] = pts[0];
  else if (point >= pts[pts.length - 1][0]) [c, lo, hi] = pts[pts.length - 1];
  else {
    for (let i = 1; i < pts.length; i++) {
      const [c0, lo0, hi0] = pts[i - 1];
      const [c1, lo1, hi1] = pts[i];
      if (point <= c1) {
        const f = (point - c0) / (c1 - c0);
        [c, lo, hi] = [point, lo0 + f * (lo1 - lo0), hi0 + f * (hi1 - hi0)];
        break;
      }
    }
  }
  return [Math.max(0, Math.min(point, point - (c - lo))), Math.max(point, point + (hi - c))];
}

const Z80 = 0.8416;
export const TOSS_UP_PROB = 0.40;

// Abramowitz-Stegun 7.1.26, |error| < 1.5e-7
function erf(x) {
  const s = Math.sign(x), a = Math.abs(x), t = 1 / (1 + 0.3275911 * a);
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a);
  return s * y;
}

// P(a outscores b) using both players' ranges ({weekly, lower, upper}).
export function beatProb(a, b) {
  const s = Math.hypot((a.upper - a.lower) / (2 * Z80), (b.upper - b.lower) / (2 * Z80));
  if (s === 0) return a.weekly === b.weekly ? 0.5 : Number(a.weekly > b.weekly);
  return 0.5 * (1 + erf((a.weekly - b.weekly) / (s * Math.SQRT2)));
}
