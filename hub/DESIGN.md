# DESIGN.md — Local Fantasy Football Hub

> Enhanced via [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) — **Data-Dense Dashboard** (192 reasoning rules, Fira Sans/Code, bullet charts). See `tokens.css: --grid-gap 8px --card-padding 12px --table-row-height 36px` and `app.css: Fira Sans/Code` for implementation.

Isolated product: `hub/` is a read-only consumer of `data/fantasy.db` + `127.0.0.1:8000` GET endpoints. No writes, no model imports. Warm-boot connected: `hub/start.sh` now gates on model warm (staleness + auto `POST /refresh`) before opening browser — see `hub/start.sh:3` flags `--auto/--no-refresh/--force`.

## 1. Visual Theme & Atmosphere

**Theme: Scoreboard Command Center**
The hub should feel like a stadium press box at night — dark, dense, precise, where every pixel earns its place. Not playful, not editorial, not corporate. It is a *decision instrument* for a 2-FLEX PPR league where 0.5 pts matters. Think NFL RedZone ticker + Bloomberg terminal + linear.app density.

**Atmosphere keywords:** tactical, luminous data, zero-fluff, confident, night-game.

**One-line pitch:** *A dark scoreboard that turns your local projections into instant answers — no tokens, no loading spinners, no storytelling.*

**Why this theme for fantasy?** Fantasy is anxious (who to start?). A dark, high-contrast, monospace-accented UI signals "calculation, not opinion". Amber = points/confidence, emerald = healthy/positive Δ, crimson = risk/injury/wind. User is experienced at fantasy generally, new to NFL — so football context (matchup ratings, weather penalties) gets explicit callouts, not buried.

**Interaction档位: L2 (流畅交互)** — reveal on scroll, sticky header state, filter chips with micro-motion, but no WebGL, no scroll-jacking. Data must stay readable at 60fps with 500 rows filtered live.

## 2. Color Palette & Roles

All colors as CSS variables. Source of truth: `hub/src/styles/tokens.css`.

```css
:root {
  /* Base — near-black scoreboard */
  --bg: #0A0E14;
  --bg-rgb: 10, 14, 20;
  --surface: #111720;
  --surface-rgb: 17, 23, 32;
  --surface-raised: #1A2332;
  --surface-hover: #1E2B3E;
  --border: rgba(255,255,255,0.07);
  --border-strong: rgba(255,255,255,0.12);
  --border-active: rgba(245,158,11,0.35);

  /* Text */
  --text: #E6EDF3;
  --text-rgb: 230, 237, 243;
  --text-muted: #8B9BB4;
  --text-faint: #5C6B84;
  --text-inverse: #0A0E14;

  /* Accent — amber is PRIMARY (points, projection, active filter) */
  --amber: #F59E0B;
  --amber-rgb: 245, 158, 11;
  --amber-dim: rgba(245,158,11,0.12);
  --amber-glow: rgba(245,158,11,0.25);
  --amber-strong: #D97706;

  /* Semantic */
  --emerald: #10B981;
  --emerald-rgb: 16, 185, 129;
  --emerald-dim: rgba(16,185,129,0.12);
  --crimson: #EF4444;
  --crimson-rgb: 239, 68, 68;
  --crimson-dim: rgba(239,68,68,0.12);
  --sky: #38BDF8;
  --sky-rgb: 56, 189, 248;
  --sky-dim: rgba(56,189,248,0.10);
  --violet: #8B5CF6;
  --violet-dim: rgba(139,92,246,0.12);

  /* Position chips */
  --pos-qb: #38BDF8;
  --pos-rb: #10B981;
  --pos-wr: #F59E0B;
  --pos-te: #8B5CF6;
  --pos-k: #EC4899;
  --pos-def: #6B7280;

  /* Confidence */
  --conf-high: #10B981;
  --conf-medium: #F59E0B;
  --conf-low: #6B7280;

  /* Weather */
  --weather-ok: #10B981;
  --weather-warn: #F59E0B;
  --weather-bad: #EF4444;

  /* Shadow */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
  --shadow-md: 0 4px 16px rgba(0,0,0,0.5);
  --shadow-glow: 0 0 20px rgba(245,158,11,0.15);
}
```

**Roles:**
- Background `#0A0E14` everywhere; cards are `#111720` with 1px `border` — no white cards.
- Primary CTA (e.g., "run search", active tab) = `amber` on `bg`, text = `text-inverse`.
- Data numbers (projections) = `text` (white), `amber` only for the *point estimate* to draw eye.
- Healthy = emerald dot, Questionable/Doubtful = amber, Out/IR = crimson.

## 3. Typography Rules

```css
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Instrument+Sans:wght@400;500;600;700&family=Fragment+Mono&display=swap');
```

| Role | Family | Weight | Size | Tracking | Use |
|------|--------|--------|------|----------|-----|
| Display | Instrument Sans | 700 | 28–36px | -0.02em | Page titles (Dashboard, Projections) |
| Section | Instrument Sans | 600 | 18–22px | -0.015em | Card headers, tab labels |
| Body | Instrument Sans | 400/500 | 14px | 0 | Table body, descriptions |
| Mono (data) | JetBrains Mono | 500/700 | 13px | 0 | **All numbers**: projections, intervals, Δ, ratings |
| Label | Instrument Sans | 600 | 11px | 0.06em uppercase | Eyebrows (POS, CONF, WIND), badges |
| Micro | Fragment Mono | 400 | 11px | 0.02em | Timestamps, `last_updated`, stale badge |

**Rules:**
- Numbers are always mono, aligned tabular. Never use Instrument Sans for points.
- Page titles use Instrument Sans 700, no gradient — scoreboard is flat, not glossy.
- Body line-height 1.5, mono line-height 1.4.
- No other fonts. Fallback stack: `Instrument Sans` → `Inter, system-ui`; `JetBrains Mono` → `ui-monospace`.

**Chinese note:** N/A — product is English only.

## 4. Component Stylings

### Nav (top, sticky)
```css
.nav {
  height: 56px; background: rgba(10,14,20,0.85); backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 50;
}
.nav-tab { padding: 8px 14px; border-radius: 8px; font: 500 13px Instrument Sans; color: var(--text-muted); }
.nav-tab:hover { background: var(--surface-raised); color: var(--text); }
.nav-tab.active { background: var(--amber); color: var(--text-inverse); box-shadow: var(--shadow-glow); }
.nav-tab:focus-visible { outline: 2px solid var(--amber); outline-offset: 2px; }
```
Staleness dot in nav-right: `● fresh` emerald, `● stale` amber, `○ cold` faint.

### Search bar (global)
```css
.search-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
.search-wrap:focus-within { border-color: var(--border-active); box-shadow: 0 0 0 3px var(--amber-dim); }
.search-input { font: 400 14px Instrument Sans; color: var(--text); background: transparent; }
.chip { background: var(--surface-raised); border: 1px solid var(--border); border-radius: 999px; padding: 4px 10px; font: 600 11px Instrument Sans; letter-spacing: 0.04em; }
.chip.active { background: var(--amber-dim); border-color: var(--border-active); color: var(--amber); }
```

### Card
```css
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
.card:hover { border-color: var(--border-strong); }
.card-header { padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
.card-header h3 { font: 600 13px Instrument Sans; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-muted); }
```

### Table
```css
table { width: 100%; border-collapse: collapse; }
thead th { font: 600 11px Instrument Sans; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); position: sticky; top: 56px; background: var(--bg); }
tbody td { padding: 11px 14px; border-bottom: 1px solid rgba(255,255,255,0.04); font: 400 13px Instrument Sans; color: var(--text); }
tbody tr:hover { background: var(--surface-hover); }
td.mono { font-family: JetBrains Mono; font-weight: 700; }
```

### Buttons
```css
.btn-primary { background: var(--amber); color: var(--text-inverse); border-radius: 10px; padding: 9px 16px; font: 600 13px Instrument Sans; }
.btn-primary:hover { background: var(--amber-strong); transform: translateY(-1px); }
.btn-primary:active { transform: translateY(0); }
.btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text-muted); border-radius: 10px; }
.btn-ghost:hover { border-color: var(--border-strong); color: var(--text); background: var(--surface-raised); }
.btn:disabled { opacity: 0.4; pointer-events: none; }
.btn:focus-visible { outline: 2px solid var(--amber); outline-offset: 2px; }
```

### Badges / Pills
```css
.badge-pos { padding: 3px 7px; border-radius: 6px; font: 700 11px JetBrains Mono; letter-spacing: 0.04em; }
.badge-pos[data-pos="QB"] { background: rgba(56,189,248,0.14); color: var(--pos-qb); }
.badge-pos[data-pos="RB"] { background: rgba(16,185,129,0.14); color: var(--pos-rb); }
.badge-pos[data-pos="WR"] { background: rgba(245,158,11,0.14); color: var(--pos-wr); }
.badge-pos[data-pos="TE"] { background: rgba(139,92,246,0.14); color: var(--pos-te); }
.badge-wind[data-level="ok"] { color: var(--weather-ok); }
.badge-wind[data-level="warn"] { background: var(--amber-dim); color: var(--weather-warn); }
.badge-wind[data-level="bad"] { background: var(--crimson-dim); color: var(--weather-bad); }
.badge-stale { font: 500 11px Fragment Mono; padding: 4px 8px; border-radius: 999px; }
```

### Interval bar (signature component)
```css
.interval-track { height: 4px; background: rgba(255,255,255,0.08); border-radius: 999px; position: relative; }
.interval-fill { position: absolute; height: 100%; background: var(--amber); border-radius: 999px; opacity: 0.9; }
.interval-dot { width: 8px; height: 8px; background: var(--amber); border: 2px solid var(--surface); border-radius: 50%; position: absolute; top: 50%; transform: translate(-50%, -50%); box-shadow: 0 0 8px var(--amber-glow); }
```
Used in Projections and Roster to show `low — point — high`. Overlapping intervals visually = toss-up.

### Links
```css
a { color: var(--sky); text-decoration: none; }
a:hover { color: var(--amber); text-decoration: underline; text-underline-offset: 3px; }
```

## 5. Layout Principles

- **Grid:** 12-col, max-width `1280px`, centered. Gutter `24px` desktop, `16px` mobile. Cards use `gap: 16px`.
- **Density:** Data tables are compact (11px row padding), dashboards are airy (20px card padding). No wasted hero — Dashboard's hero is 160px tall, not full viewport.
- **Nav stays sticky**; table headers sticky under nav (top 56px). Side filters are sticky on desktop.
- **Spacing scale:** `4, 8, 12, 16, 20, 24, 32, 48`.
- **Containers:** Page `max-width: 1280px`, projection table `100%` with horizontal scroll on <900px (no column hiding — scroll).

## 6. Depth & Elevation

No neumorphism. Depth comes from border + subtle surface lift.

```css
--shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
--shadow-md: 0 4px 16px rgba(0,0,0,0.5);
--shadow-lg: 0 12px 32px rgba(0,0,0,0.6);
--shadow-glow: 0 0 20px rgba(245,158,11,0.15);
```
- Cards: `border` only, no shadow by default. Hover adds `border-strong`.
- Active tab / primary button: `shadow-glow`.
- Drawer/modal: `shadow-lg` + `border-strong`.
- No `backdrop-blur` over large scroll areas (only nav, 12px).

## 7. Animation & Interaction — L2

**Dependencies:** none (CSS + IntersectionObserver). No GSAP/Lenis.

- **Entrance (L1):** Cards `fadeInUp` 180ms ease-out, stagger 40ms, once on load. `prefers-reduced-motion: reduce` → no motion.
- **Scroll reveal:** `IntersectionObserver` adds `.in` class to sections; `opacity 0→1` + `translateY 8px→0` 220ms.
- **Hover:** card border transition 150ms, row bg 120ms, btn `translateY(-1px)` 120ms.
- **Interval bar:** width animates 400ms ease-out on data change.
- **Search:** debounced 150ms, results cross-fade 120ms.
- **Staleness badge:** pulse `emerald` dot `2s infinite` when fresh.
- **Spotlight (signature, low-cost):** table rows get `--mx` radial `rgba(245,158,11,0.06)` on hover (rAF throttled) — same as Linear.app row hover.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```

## 8. Do's and Don'ts

**Do:**
1. Use mono for every number; keep tabular alignment.
2. Keep dark surface hierarchy: bg < surface < raised < hover.
3. Use amber only for point estimates / active states, not for decoration.
4. Show interval whenever you show a point — point without uncertainty is a lie (per conformal spec).
5. Keep table headers sticky and searchable — data hub must be scannable without scrolling to top.
6. Surface `stale` / `placeholder weather` warnings inline, not in a toast that disappears.
7. Use uppercase 11px labels for metadata (POS, CONF, WIND) — scan faster.
8. Keep search instant (<5ms) via client-side filter; never add a loading spinner for search.

**Don't:**
1. Don't use light cards or white backgrounds — breaks scoreboard.
2. Don't use emoji for position/weather — use color-coded pills/dots.
3. Don't hardcode hex anywhere — always `var(--*)`.
4. Don't add `filter: blur()` on moving rows or large scroll containers.
5. Don't use `backdrop-blur` >12px or over tables.
6. Don't hide columns on mobile — horizontal scroll instead (analysts need all columns).
7. Don't add WebGL/Three.js — L2 only.
8. Don't add Lenis/scroll-jacking or pin — would fight sticky headers.

## 9. Responsive Behavior

- **Breakpoints:** `640px` (sm), `900px` (md), `1280px` (lg). No `xl`.
- **Nav:** <900px collapses tabs into `overflow-x: scroll` with snap, no hamburger — tabs must stay one tap away.
- **Tables:** <900px wrap in `.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }` with sticky first col (player name).
- **Cards:** Dashboard grid `1 col` <640, `2 col` <900, `3 col` ≥900. Tierlist lanes stack vertically <640.
- **Touch targets:** filter chips, tabs, buttons ≥44×44px (`min-height: 44px` on mobile).
- **No horizontal overflow:** `body { overflow-x: hidden; }`, `max-width: 100vw` guard.

