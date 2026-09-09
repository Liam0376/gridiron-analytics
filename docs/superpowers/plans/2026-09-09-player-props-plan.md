# Plan: Player Props Section — Fair Lines + Manual-Entry Edge (separate from fantasy)

> For agentic workers: execute task-by-task, checkbox discipline. **Stop for user
> confirmation after Task 1** (width-semantics pin + spec re-confirm) before writing
> `props.py`, per `AGENTS.md: Process`. Commit at each checkpoint task.

**Goal:** Ship a props section (model `props.py` + calibration backtest + `prop_lines`
table/API + hub "Props" tab) that turns existing stat projections into fair lines
and EV-vs-manual-book-line edges, without touching fantasy code, $0, outbound, or
isolation constraints.

**Spec:** `docs/superpowers/specs/2026-09-09-player-props-spec.md`

**Constraints:** $0 forever (no odds feed — Business $99/mo rejected in spec); local-only
`127.0.0.1`; outbound only Sleeper/nflverse/Open-Meteo (manual book-line entry, no new
host); NFL only; `stat_projector.py`/`scoring.py`/`decision.py`/`comparison/` untouched;
hub `mode=ro`, `bash hub/verify-isolation.sh` green after any `hub/` change; RG copy
mandatory on every props surface.

---

### Task 1: Pin width semantics + research lock (read-only, then confirm)

**Files:** none (read-only) + this plan's Task-1 note

- [ ] **Step 1:** Resolve the audit-found divergence: `projection.py:216-217`
  (`lower=point−width`, span 2×width) vs `hub/server.py:1636-1639`
  (`low=pts−width/2`, span 1×width). Decide ONE canonical definition for props
  sigma (recommend src semantics: half-width = `width`), record decision here.
- [ ] **Step 2:** Confirm prop-market stat keys exist in `project_player_stats`
  outputs for QB/RB/WR/TE (pass yds/TDs, rush yds, recv yds, receptions, TD means).
- [ ] **Step 3:** Confirm week-1 handling for props (exclude week 1 from backtest +
  edge until `stat_projector.py:512-513` leakage hole is fixed).
- [ ] **Step 4:** STOP — report Task-1 findings + ask user to confirm spec/plan
  before Task 2.

**Task-1 findings (2026-09-09, verified read-only):**
- Width semantics divergence CONFIRMED: src (`projection.py:216-217`,
  `decision.py:342-343`) treats `width` as half-width (`lower=point−width`,
  span 2×width); hub (`server.py:917-918`, `:1638-1639`) treats it as full span
  (`low=pts−width/2`). DECISION: props pins **src semantics** —
  sigma = width / 1.2816. Hub display divergence is a pre-existing bug for the
  separate fix batch, not props scope.
- Stat keys CONFIRMED: QB 6 (`passing_yards/tds/interceptions, rushing_yards/tds`),
  SKILL 6 (`rushing/rec yards/tds, receptions`), KICKER 7 distance buckets
  (K excluded v1 — buckets don't map to standard K props + thinnest coverage).
- Week-1 leak CONFIRMED (`stat_projector.py:512-513` fallback to full `reg`
  when `week < 1` filter empties). DECISION: week 1 excluded from props backtest
  + edge until the hole is fixed.

**Task-1 correction (2026-09-09, width fix):** the divergence writeup above was
incompletely researched. `compute_conformal_bounds` ALSO returns `width`, but
as FULL span (`high - low`), while `projection.py`/`decision.py` use HALF-width —
the inconsistency lived in src, not just the hub. For `interval_width` rows
flowing through `comparison` (full-span), the hub's `/2` rendered the CORRECT
band; only fallbacks and the JS rebuild were wrong. Fixed at the root instead:
`compute_conformal_bounds` now returns half-width (qhat scale, matching
`projection.py`, its own `<4/<7` confidence bands, and the Task-4 sigma
convention), `comparison` fallback `width 20.0→5.0`, hub renders `±width`
with `max(0,…)` floor everywhere. Pinned by
`test_conformal_bounds_width_is_half_width`.

**Commit:** none (research only).

---

### Task 2: `props.py` odds math (pure functions first)

**Files:** `src/ffanalytics/props.py` (new), `tests/test_props.py` (new)

- [ ] **Step 1:** Write failing tests: `prob_to_american`/`american_to_prob`
  round-trip (0.5→±100, 0.6→−150, 0.4→+150), `ev_per_unit` sign (−110 both sides
  ⇒ EV<0 at p=0.5; +EV case), edge-rule thresholds (5pp + 4% EV + empty-flag veto),
  Poisson anytime-TD (`1−e^−λ`, λ=0⇒0, λ=1⇒0.632).
- [ ] **Step 2:** Implement pure functions only (no DB, no projector import yet):
  `prob_to_american`, `american_to_prob`, `ev_per_unit`, `poisson_anytime_td`,
  `normal_over_prob(mean, sigma, line)`, `apply_prop_edge_rule(...)`.
- [ ] **Step 3:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/test_props.py -v` PASS.
- [ ] **Step 4:** Commit: `feat: props odds-math primitives (fair odds, EV, edge rule)`

**Verification:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/test_props.py -q` green.

---

### Task 3: Fair-line builder on stat projections (import, never edit)

**Files:** `src/ffanalytics/props.py` (extend), `tests/test_props.py` (extend)

- [ ] **Step 1:** Add `build_prop_fair_lines(player_history, position, game_ctx)`
  → per-market `{fair_line, sigma, p_over_at(line)}` using `project_player_stats`
  + canonical width semantics from Task 1. Grep-guard: no edits to
  `stat_projector.py`, `scoring.py`, `decision.py`, `comparison/`.
- [ ] **Step 2:** `is_empty_projection=True` ⇒ fair line present but edge forced
  `NO EDGE (unknown)` — test this veto explicitly.
- [ ] **Step 3:** Week-1 exclusion enforced (per Task-1 decision) — test.
- [ ] **Step 4:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/test_props.py -q` PASS.
- [ ] **Step 5:** Commit: `feat: props fair-line builder on stat projections (read-only)`

---

### Task 4: Calibration backtest (gates edge labels)

**Files:** `scripts/backtest_props.py` (new), `data/props/backtest_props_results.json`

- [ ] **Step 1:** Write `scripts/backtest_props.py`: 2025-holdout (weeks 4-18,
  same discipline as `backtest_ml.py`), per-market Brier + reliability deciles +
  fair-line MAE vs book-line-absent baseline (fair line vs actual, no book needed).
- [ ] **Step 2:** Run; record per-market reliability. Non-monotonic groups ⇒
  `status:"tracking"` (no edge labels); monotonic ⇒ `status:"edges_on"`.
- [ ] **Step 3:** K props: expect exclusion (thin sample) — record, do not force.
- [ ] **Step 4:** Commit: `chore: props calibration backtest 2025 holdout (results json)`

**Verification:** results JSON exists with per-market Brier + decile tables; Gate 2
decision (which markets get edge labels) recorded in the JSON + Task-5 picks it up.

---

### Task 5: `prop_lines` table + API (manual entry in, props out)

**Files:** `src/ffanalytics/schema.sql` (additive table only), `src/ffanalytics/db.py`
(migration `user_version`+1, additive), `src/ffanalytics/api.py` (2 endpoints),
`tests/test_props_api.py` (new)

- [ ] **Step 1:** Schema: `prop_lines(player_id, week, season, market, line,
  over_price, under_price, book, created_at)` + UNIQUE(player,week,market,book).
  Additive migration only — no ALTER of existing tables.
- [ ] **Step 2:** `POST /props/lines` (manual entry: validate market allowlist,
  numeric prices, week 1-18) + `GET /props/edges?week=` (fair line + EV vs stored
  book lines + shadow status per market group).
- [ ] **Step 3:** Shadow logging: every surfaced edge logged `kind="prop:<market>"`;
  resolve path reuses `shadow.record_outcome` on `(player_id, week)` vs actual stat.
- [ ] **Step 4:** Tests: entry validation, edges math vs fixture, shadow log/resolve,
  `is_trusted` False before 20 resolved ("tracking" state in response).
- [ ] **Step 5:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` full green.
- [ ] **Step 6:** Commit: `feat: prop_lines table + props API (manual entry, shadow-logged)`

---

### Task 6: Hub "Props" tab (sidebar, read-only)

**Files:** `hub/src/views/props.js` (new), `hub/src/router.js` (route), sidebar nav,
`hub/server.py` (GET passthrough only — no writes, no odds fetch)

- [ ] **Step 1:** Sidebar "Props" tab + route (DESIGN.md: sidebar-only nav, tokens,
  mono numbers, `intervalBar` reuse, text+color edge chips
  `VALUE / TRACKING / NO EDGE` — never "LOCK").
- [ ] **Step 2:** Table columns per spec; manual-entry form POSTs to **model `:8000`**
  directly (never hub proxy — hub stays `mode=ro`).
- [ ] **Step 3:** RG disclaimer bar + "model-implied, uncalibrated" chip while any
  market group is below shadow 20; K markets show exclusion reason.
- [ ] **Step 4:** `bash hub/verify-isolation.sh` green + `npm run build` clean.
- [ ] **Step 5:** Commit: `feat(hub): Props sidebar tab (read-only, RG copy)`

**Verification:** isolation script green; no new outbound host in `hub/` or `src/`
(grep `fetch\(|https://` review in task).

---

### Task 7: Docs + closeout

**Files:** `docs/superpowers/specs/2026-09-09-player-props-spec.md` (status line),
`hub/README.md` (Props tab row), `docs/research/2026-data-sources.md` (odds-feed
rejection row)

- [ ] **Step 1:** Append odds-feed rejection to data-sources doc (The Odds API
  Business $99/mo props — evidence dated 2026-09-09).
- [ ] **Step 2:** Hub README tabs list + RG note.
- [ ] **Step 3:** Full `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` + isolation green,
  `git status` review (no `data/*.db*`, no `.env`), commit: `docs: props closeout`

---

### Deferred / Not in this plan

- Odds-feed adapter (`adapters/odds.py` seam) — only if $0 lifted + allowlist exception.
- CLV tracking (needs closing feed) — noted, not faked.
- Parlay optimizer, live/in-play, K/DEF props, combo markets (need covariance).
- Fractional-Kelly staking — behind shadow gate, later.

### Sign-off fix batches (post-Task-7, agent-driven)

- **Batch 1 — 22-agent sign-off REDs:** missed width renderers (`playerCard.js`,
  projections table), NaN per-row quarantine, week-1 + position serving gates,
  upsert `RETURNING id`, whitespace `player_id` 422, vig/import docstrings.
- **Batch 2 — council vote (idempotency wins 8–3–2):** `log_prop_edge_once`
  dedupe (v6 partial index), logging at POST + idempotent GET catch-up,
  POST/GET history parity, per-row calibration detail, credential-shaped
  `book` rejection, `_CACHE`/`update_cache` model_projections seed.
- **Deferred with reasons:** tracking-VALUE veto (needs experiment design, not a
  patch), VALUE-only logging expansion (would rewrite experiment semantics
  mid-flight — revisit after first 20 resolved), retention job + restore drill
  (operational, needs a designed TTL), n=20 power upgrade (don't move gates
  mid-experiment), UI polish batch, multi-season replication (needs 2024
  holdout rerun — data work, separate task).
