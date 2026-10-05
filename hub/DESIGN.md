# DESIGN.md — Press Box v2

> Rebrand + retheme spec. Hybrid of Sleeper / FantasyPros / Yahoo Fantasy analysis
> (`~/fantasy-design-specs/*/design.md`). Replaces the Helvetica/mono "Press Box v1"
> look. Kills the AI-generic card-grid feel.

**Name:** Press Box
**One-line pitch:** A purple-accented sports editorial console: cool-gray canvas,
white hairline cards, condensed display type over clean geometric body text,
density borrowed from Sleeper score rows.

---

## 1. Brand

| Item | Value |
| ---- | ----- |
| Name | Press Box |
| Wordmark | `PRESS BOX` — Oswald 600, uppercase, letter-spacing 0.02em, white on sidebar |
| Badge (logo) | Rounded square, `--accent: #7D2EFF`, white `PB` in Oswald 600, radius 10px, 28×28px in sidebar / 16px in favicon |
| Page `<title>` | `Press Box — Fantasy Football Analytics` |
| Manifest short_name | `Press Box` |
| Favicon | `public/favicon.svg` — purple rounded square, white condensed `PB` |
| Voice | Sports desk, not SaaS. Labels read like a stats feed: short, uppercase sparingly, numbers lead. |

Replace every user-facing `FantasyHub` string with `Press Box` (sidebar header,
title, manifest, setup modal header, README, `AGENTS.md` mentions).
`package.json` name and internal route/API keys stay unchanged — branding only.

Sidebar header block, top to bottom:

```
[P]  PRESS BOX            ← badge + wordmark, one row
     12-TEAM · 2 FLEX     ← league line, Poppins 500, muted, uppercase, 0.06em
```

---

## 2. Typography

Fonts via Google Fonts `<link>` in `index.html` (only new network cost; both free):

- **Oswald** (600) — display only: page headlines (`DASHBOARD`, team name), badge,
  big numerals (`W4`, scores when shown large). Condensed = sports broadcast feel.
- **Poppins** (400/500/600) — everything else: nav, body, card headers, buttons,
  labels. Replaces current mono-uppercase label habit (Sleeper/FP both use
  geometric sans for labels, not mono).
- **Mono** (`ui-monospace, SFMono-Regular, Menlo`) — tabular data ONLY: projections,
  dollar values, percentages, timestamps. Never labels, never nav.

```css
--font-display: "Oswald", "Arial Narrow", sans-serif;
--font-sans: "Poppins", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
```

Scale (grounded in Yahoo + FP specs):

| Role | Font | Size | Weight | Line height | Tracking |
| ---- | ---- | ---- | ------ | ----------- | -------- |
| Display | Oswald | 40px | 600 | 1.05 | 0.01em |
| H2 / card title | Poppins | 14px | 600 | 1.3 | 0.06em, uppercase |
| Body | Poppins | 14px | 400 | 1.5 | 0 |
| Small | Poppins | 12px | 500 | 1.4 | 0.02em |
| Data | mono | 13px | 400–500 | 1.4 | 0 |

Rules: page headlines always Oswald uppercase. No mono labels anywhere. Uppercase
reserved for card titles and eyebrows (3–6 words max).

---

## 3. Color

Purple is the single accent. Green/red stay semantic-only (status, ±, buy/sell).

```css
:root {
  /* canvas + surfaces — Yahoo grounded */
  --bg: #EEF2FB;            /* cool-gray page canvas */
  --surface: #FFFFFF;       /* cards */
  --surface-raised: #F8FAFC;
  --surface-hover: #F5F3FF; /* purple 4% tint, from purple-rgb */

  /* borders — flat, hairline, no ambient shadow (FP + Yahoo both flat) */
  --border: #DEE4F3;
  --border-strong: #CBD5E1;

  /* text */
  --text: #0F172A;
  --text-muted: #475569;
  --text-faint: #94A3B8;
  --text-inverse: #FFFFFF;

  /* accent */
  --accent: #7D2EFF;            /* Yahoo brand purple — CTAs, active nav, links */
  --accent-hover: #6A20E6;
  --accent-dim: rgba(125, 46, 255, 0.08);
  --accent-rgb: 125, 46, 255;

  /* semantic — keep existing values */
  --green: /* current success green */;
  --red:   /* current danger red */;

  /* sidebar — keep near-black, it works */
  --sidebar-bg: #0B0B0F;
}
```

Rules:
- Purple fires on: primary buttons, active nav item, links, focus rings, badge,
  progress fills. Never on body copy, never as page background.
- Green/red: status dots, OUT/IN, ±proj, buy/sell only.
- Orange v1: removed entirely (badge, accents, headlines).
- Shadows: none at rest. Cards separate via 1px `--border`. Modal/dropdown only:
  `0 16px 48px rgba(15, 23, 42, 0.16)` (Yahoo elevation).

Fill `--green`/`--red` from existing `tokens.css` values during implementation —
they already pass contrast.

---

## 4. Layout & density

Sleeper's 4px grid, Yahoo's flat cards, tighter than v1:

- Spacing ramp: `4, 8, 12, 16, 24, 32, 48, 64` px. Card padding `16px` (v1 was 20–24).
- Radius: cards `12px`, inputs/buttons pill `9999px` (Yahoo split), badges `6px`.
- Max content width stays. Sidebar stays fixed dark.
- Dashboard: break the uniform 3-card grid. Yahoo-style hierarchy:
  1. **Hero strip** — Playoff Race gets full-width or double-width slot, top.
  2. **Two compact lists** — Status Report + Waiver Targets side by side, tighter rows.
  3. **Full-width strips** — Trade Signals + Sync below, one row each.
- Score/player rows: Sleeper pattern — name left, number right-aligned mono,
  status dot far right, 36px row height, hairline divider, no card-in-card.
- Buttons: pill, `--accent` primary / white with border secondary / ghost link.

---

## 5. Motion

Minimal, sports-app snappy. Keep existing durations where already tuned; drop any
bounce/glow. Focus ring: `2px solid var(--accent)` + `2px offset` everywhere.

---

## 6. Out of scope (v2)

- Dark mode restyle — existing toggle keeps working with current dark tokens;
  re-deriving dark palette from purple lands in v2.1.
- Data/logic changes of any kind — CSS + `index.html` + string swaps only.
- Landing/marketing pages.

---

## 7. Implementation map

| File | Change |
| ---- | ------ |
| `src/styles/tokens.css` | rewrite per §3, add font vars per §2 |
| `src/styles/pressbox.css` | rewrite per §2–4 (display type, density, hero grid) |
| `src/styles/app.css` | targeted: label font swaps, card padding/radius, remove shadows |
| `index.html` | Google Fonts link, title, favicon link |
| `public/favicon.svg` | new (purple PB square) |
| `public/manifest.json` | name/short_name → Press Box |
| views/components | dashboard grid per §4; `FantasyHub` → `Press Box` strings |
| `src/styles/pressbox.css` badge | `.badge PB` styles |

Verification (one check): `npm run build` passes, then headless screenshot
dashboard + matchups + trade at 1440×900 — compare against
`~/fantasy-design-specs/current-ui.png`. No mono labels, no orange, purple fires
on active nav.
