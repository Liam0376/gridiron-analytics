# DESIGN.md — Gridiron Hub — Sidebar + Top Search

> System fonts: Helvetica / Apple SF · Sidebar navigation · L2 fluid · Data-dense but airy

---

## 1. Visual Theme & Atmosphere

**Theme: Apple / Helvetica Light — Airy Sidebar Dashboard**
The hub is a native-macOS-feeling sports console: left dark sidebar for wayfinding, top white search bar for command, airy content canvas. Helvetica renders crisp on Retina, SF Mono for numbers. Sidebar is deep navy `#192741` with subtle inner shadow, not flat. Content area breathes with 24px gutters and 16px card radius. Feels like Linear + Apple App Store, not a Bootstrap admin.

**Atmosphere keywords:** airy, precise, native, calm, confident — no neon, no glassmorphism, no storytelling hero.

**One-line pitch:** *A Helvetica-native sidebar console where search is command and every table feels like Finder.*

**Interaction Level: L2 — Fluid** — `fadeInUp 220ms` reveal, sticky topbar compress on scroll, `transform` hover lifts, `8px` interval bar growth, sidebar `120ms` indicator slide, search dropdown `140ms` scale.

---

## 2. Color Palette & Roles

```css
:root {
  --bg: #F3F4F6;
  --bg-rgb: 243, 244, 246;
  --surface: #FFFFFF;
  --surface-raised: #F8FAFC;
  --surface-hover: #EFF6FF;
  --border: #E2E8F0;
  --border-strong: #CBD5E1;
  --border-active: #1E40AF;

  --text: #0F172A;
  --text-muted: #475569;
  --text-faint: #94A3B8;
  --text-inverse: #FFFFFF;

  /* Sidebar — deep navy, distinct from topbar */
  --sidebar-bg: #192741;
  --sidebar-bg-hover: rgba(255,255,255,0.08);
  --sidebar-bg-active: #FFFFFF;
  --sidebar-text: rgba(255,255,255,0.72);
  --sidebar-text-active: #192741;
  --sidebar-icon: #93C5FD;
  --sidebar-border: rgba(255,255,255,0.08);

  /* Topbar — white, separates search */
  --topbar-bg: #FFFFFF;
  --topbar-border: #E2E8F0;
  --topbar-height: 56px;
  --sidebar-width: 240px;
  --sidebar-collapsed: 72px;

  --primary: #1E40AF;
  --primary-hover: #1E3A8A;
  --primary-dim: rgba(30,64,175,0.08);
  --amber: #D97706;
  --amber-dim: rgba(217,119,6,0.10);
  --emerald: #059669;
  --emerald-dim: rgba(5,150,105,0.08);
  --crimson: #DC2626;
  --crimson-dim: rgba(220,38,38,0.08);
  --sky: #0284C7;
  --sky-dim: rgba(2,132,199,0.08);
  --violet: #7C3AED;
  --violet-dim: rgba(124,58,237,0.08);

  --pos-qb: #0369A1; --pos-rb: #059669; --pos-wr: #D97706; --pos-te: #7C3AED; --pos-k: #DB2777; --pos-def: #64748B;

  --shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
  --shadow-lg: 0 10px 24px rgba(0,0,0,0.12);
}
```

---

## 3. Typography Rules

```css
/* System only — no Google Fonts */
--font-sans: "Helvetica Neue", Helvetica, -apple-system, BlinkMacSystemFont, Arial, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
```

| Role | Family | Weight | Size | Tracking | Use |
|------|--------|--------|------|----------|-----|
| Display | Helvetica | 600 | 26px | -0.02em | Page `h1` |
| Section | Helvetica | 700 | 12px | 0.05em uppercase | Card headers, `th` |
| Body | Helvetica | 400/500 | 13px | 0 | Descriptions |
| Mono Data | SF Mono | 600/700 | 12px | 0 | Points, `$`, intervals |
| Label | Helvetica | 600 | 11px | 0.06em | Kicker, badges |

---

## 4. Component Stylings

**Sidebar Nav (new):**
```css
.sidebar { width: var(--sidebar-width); background: var(--sidebar-bg); border-right: 1px solid var(--sidebar-border); display:flex; flex-direction:column; }
.sidebar-brand { padding:20px 18px; border-bottom:1px solid var(--sidebar-border); }
.sidebar-tab { display:flex; align-items:center; gap:12px; padding:10px 14px; border-radius:10px; margin:4px 10px; font:600 13px Helvetica; color:var(--sidebar-text); border:1px solid transparent; cursor:pointer; transition: all 120ms ease; }
.sidebar-tab:hover { background: var(--sidebar-bg-hover); color:#fff; }
.sidebar-tab.active { background: var(--sidebar-bg-active); color:var(--sidebar-text-active); font-weight:700; box-shadow:0 1px 6px rgba(0,0,0,0.12); }
.sidebar-tab svg { width:18px; height:18px; flex-shrink:0; }
```

**Topbar Search (new):**
```css
.topbar { height:var(--topbar-height); background:var(--topbar-bg); border-bottom:1px solid var(--topbar-border); display:flex; align-items:center; gap:16px; padding:0 24px; position:sticky; top:0; z-index:40; }
.search-top { flex:1; max-width:640px; display:flex; align-items:center; gap:10px; background:var(--surface-raised); border:1px solid var(--border); border-radius:12px; padding:8px 14px; }
.search-top:focus-within { border-color:var(--primary); box-shadow:0 0 0 3px var(--primary-dim); }
.search-top input { flex:1; border:0; outline:0; background:transparent; font:400 14px Helvetica; color:var(--text); }
```

**Cards/Tables:** `radius 16px`, `padding 16px`, `shadow-sm` default, `shadow-md` on hover, `row height 40px`.

---

## 5. Layout Principles

* **Shell:** `display:flex` — `sidebar 240px` fixed left, `main flex:1` column (`topbar 56px` sticky + `page` scroll). `page { max-width:1280px; padding:24px; gap:16px }`.
* **Grid:** `12-col` `gap 10px`, `kpi-card span 3` (12→6→12 responsive).
* **Whitespace:** Section `gap 16px` (was 10), card `padding 16px` (was 14), hero `padding 8 0 16`.
* **Container:** Sidebar collapses to `72px` icon-only at `1100px` hover-expand, to bottom sheet nav at `640px` (existing `.mobile-nav` reused, topbar stays).

---

## 6. Depth & Elevation

* Sidebar: `inset 1px 0 0 rgba(255,255,255,0.06)`, `shadow-lg` on active tab.
* Topbar: `shadow-sm` (`0 1px 3px rgba(0,0,0,0.06)`).
* Cards: `shadow-sm` resting, `shadow-md` + `border-strong` on hover.
* Search dropdown: `shadow-lg` + `1px border-strong`.

---

## 7. Animation & Interaction — L2

* **Reveal:** `.reveal { opacity:0; translateY(6px); transition: opacity 220ms, translate 220ms }` staggered `40ms`.
* **Topbar compress:** `scrollY >12` → `height 48px` + `shadow-sm`.
* **Sidebar indicator:** active tab `::before` `4px` rail with `120ms` slide.
* **Hover:** `card translateY(-1px)`, `tr td` `radial-gradient` spotlight (existing `--mx/--my`).
* **Search:** dropdown `scale 0.98→1` `140ms`.
* **Reduced motion:** all `transition:none`.

---

## 8. Do's and Don'ts

Do:
1. Use `Helvetica / -apple-system` everywhere — zero `Fira/JetBrains` imports.
2. Sidebar `240px` + topbar `56px` only — no second horizontal nav.
3. Search is sole topbar control; tabs live only in sidebar.
4. All colors via `var(--*)`, no hex.
5. Mono only for numbers (`pts`, `$`, intervals).
6. Active sidebar item is white pill, not underline.
7. Keep `page` max `1280` centered in `main`.
8. Maintain `44px` touch target on mobile.

Don't:
1. Don't reintroduce top tabs — breaks airy hierarchy.
2. Don't add glass `backdrop-filter:blur` >14px or full-page.
3. Don't use `filter:blur` on moving elements.
4. Don't add Google Fonts or custom `@font-face`.
5. Don't change sidebar bg from `#192741` without updating `--sidebar-*` tokens.
6. Don't put badges or stats in sidebar — nav only.
7. Don't exceed `16px` card radius.
8. Don't animate `height` — use `transform`.

---

## 9. Responsive Behavior

* `>1100px` : sidebar `240px` fixed, topbar `56px`.
* `900-1100px` : sidebar `72px` icon-only, hover expands to `240px` overlay.
* `≤640px` : sidebar `display:none`, `.mobile-nav` bottom bar `64px` (existing), topbar search `max-width:100%`, `page` `padding 12px`, `kpi-card span 6→12`, touch `44px`.
