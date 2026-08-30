# DESIGN.md — Local Fantasy Football Hub

> Built with [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) — **Data-Dense Dashboard Architecture** (192 reasoning rules, Fira Sans / Fira Code typography, bullet charts, compact table rows, Linear-style spotlight row hovers).

Isolated product: `hub/` is a read-only consumer of `data/fantasy.db` + `127.0.0.1:8000` GET endpoints. No writes, no model imports. Warm-boot connected: `hub/start.sh` gates on model warm (staleness + auto `POST /refresh`) before opening browser — see `hub/start.sh:3` flags `--auto/--no-refresh/--force`.

---

## 1. Visual Theme & Atmosphere

**Theme: Data-Dense Scoreboard Command Center (ui-ux-pro-max)**
The hub feels like a stadium press box at night — dark, dense, precise, where every pixel earns its place. Not playful, not editorial, not corporate. It is a *decision instrument* for a 2-FLEX PPR league where 0.5 pts matters. Combines RedZone ticker speed + Bloomberg terminal data density + linear.app micro-interactions.

**Atmosphere keywords:** tactical, luminous data, zero-fluff, confident, night-game.

**One-line pitch:** *A dark scoreboard that turns your local projections into instant answers — no tokens, no loading spinners, no storytelling.*

**Interaction Level: L2 (Smooth Data-Dense Interactivity)** — reveal on scroll, sticky header state, filter chips with micro-motion, Linear-style spotlight row hover, skeleton loading shimmers, instant client-side search.

---

## 2. Color Palette & Roles (ui-ux-pro-max Spec)

All colors are mapped to CSS variables in `hub/src/styles/tokens.css`.

```css
:root {
  /* Base — near-black scoreboard */
  --bg: #0A0E14;
  --bg-rgb: 10, 14, 20;
  --surface: #111720;
  --surface-rgb: 17, 23, 32;
  --surface-raised: #1A2332;
  --surface-hover: #1E2B3E;
  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.16);
  --border-active: rgba(245, 158, 11, 0.40);

  /* High Contrast Text (WCAG 2.1 AA Compliant) */
  --text: #F8FAFC;
  --text-rgb: 248, 250, 252;
  --text-muted: #94A3B8;
  --text-faint: #64748B;
  --text-inverse: #0A0E14;

  /* Accent — Luminous Amber (points, projections, active filters) */
  --amber: #F59E0B;
  --amber-rgb: 245, 158, 11;
  --amber-dim: rgba(245, 158, 11, 0.14);
  --amber-glow: rgba(245, 158, 11, 0.25);
  --amber-strong: #D97706;

  /* Semantic Data Indicators */
  --emerald: #10B981;
  --emerald-rgb: 16, 185, 129;
  --emerald-dim: rgba(16, 185, 129, 0.14);
  --crimson: #EF4444;
  --crimson-rgb: 239, 68, 68;
  --crimson-dim: rgba(239, 68, 68, 0.14);
  --sky: #38BDF8;
  --sky-rgb: 56, 189, 248;
  --sky-dim: rgba(56, 189, 248, 0.14);
  --violet: #A855F7;
  --violet-dim: rgba(168, 85, 247, 0.14);

  /* Position Badges */
  --pos-qb: #38BDF8;
  --pos-rb: #10B981;
  --pos-wr: #F59E0B;
  --pos-te: #A855F7;
  --pos-k: #EC4899;
  --pos-def: #94A3B8;

  /* Confidence & Weather */
  --conf-high: #10B981;
  --conf-medium: #F59E0B;
  --conf-low: #94A3B8;
  --weather-ok: #10B981;
  --weather-warn: #F59E0B;
  --weather-bad: #EF4444;

  /* Elevation Shadows */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
  --shadow-md: 0 4px 16px rgba(0,0,0,0.5);
  --shadow-lg: 0 12px 32px rgba(0,0,0,0.6);
  --shadow-glow: 0 0 20px rgba(245,158,11,0.20);

  /* ui-ux-pro-max Data Density Standards */
  --grid-gap: 8px;
  --card-padding: 12px;
  --table-row-height: 36px;
  --font-size-small: 12px;
}
```

---

## 3. Typography Rules (ui-ux-pro-max Specification)

```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Instrument+Sans:wght@400;500;600;700&display=swap');
```

| Role | Family | Weight | Size | Tracking | Use |
|------|--------|--------|------|----------|-----|
| Display | Fira Sans / Instrument Sans | 700 | 24–30px | -0.02em | Page titles |
| Section | Fira Sans | 600 | 16–20px | -0.015em | Card headers, tab labels |
| Body | Fira Sans | 400/500 | 13–14px | 0 | Descriptions, text content |
| Mono (Data) | Fira Code / JetBrains Mono | 600/700 | 12–13px | 0 | **All numerical data**, points, intervals, VBD |
| Label / Eyebrow | Fira Sans | 600 | 11px | 0.06em uppercase | Badges, table header categories |

---

## 4. Component & Micro-Interaction Stylings

### Linear-Style Spotlight Row Hover
Table rows and interactive cards receive subtle cursor-tracked radial glow:
```css
tbody tr:hover td {
  background: radial-gradient(400px circle at var(--mx, 50%) var(--my, 50%), rgba(245,158,11,0.06), var(--surface-hover));
}
```

### Table Density (36px Row Height)
```css
table { width: 100%; border-collapse: collapse; min-width: 760px; }
thead th { font: 600 11px 'Fira Sans', sans-serif; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); padding: 8px 12px; height: 36px; position: sticky; top: 0; background: var(--surface); }
tbody td { padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.04); font: 400 12px 'Fira Sans', sans-serif; color: var(--text); height: 36px; }
td.mono { font-family: 'Fira Code', 'JetBrains Mono', monospace; font-weight: 600; }
```

### KPI Bullet Chart Metrics
Bullet charts for model calibration targets (MAE, Pearson correlation):
```css
.bullet-track { height: 18px; background: rgba(255,255,255,0.08); border-radius: 4px; position: relative; }
.bullet-fill { height: 10px; top: 4px; background: var(--amber); border-radius: 999px; position: absolute; }
.bullet-target { width: 3px; background: var(--text); position: absolute; top: 0; bottom: 0; }
```

---

## 5. Skeleton Shimmer & Loading States

When changing routes or requesting live projections, `shimmer.js` supplies structured CSS skeleton pulses instead of blank screens:
```css
@keyframes shimmerPulse {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
.shimmer-box {
  background: linear-gradient(90deg, var(--surface) 25%, var(--surface-raised) 50%, var(--surface) 75%);
  background-size: 200% 100%;
  animation: shimmerPulse 1.5s infinite;
}
```

---

## 6. Accessibility & Responsive Requirements

- **WCAG 2.1 AA Compliance:** Minimum 4.5:1 text contrast on `--text-faint` (`#64748B`) and `--text-muted` (`#94A3B8`).
- **Touch Sizing:** Touch targets $\ge 44 \times 44\text{px}$ on mobile viewports.
- **Keyboard Navigation:** Tab navigation rings (`outline: 2px solid var(--amber)`), `aria-sort` headers on data tables.
