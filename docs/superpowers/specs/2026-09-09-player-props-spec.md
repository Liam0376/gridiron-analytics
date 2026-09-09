# Spec: Player Props Section — Model Fair Lines + Manual Book-Line Edge (separate from fantasy)

> Status (2026-09-09): implemented Tasks 1–7, width unification (f35dc9f),
> and the 22-agent sign-off RED batch (missed renderers, API veto gates, NaN
> quarantine, upsert id, whitespace validation, docstring corrections).
> Calibration verdict: only `passing_yards` earned edge labels; all other
> markets ship as tracking.

## Context

`src/ffanalytics/stat_projector.py:project_player_stats()` already predicts per-stat
lines, not just fantasy points. Per-position keys (`stat_projector.py:QB_STATS/SKILL_STATS`):

- QB: `passing_yards, passing_tds, passing_interceptions, rushing_yards, rushing_tds`
- RB/WR/TE: `rushing_yards, rushing_tds, receiving_yards, receiving_tds, receptions`
- (+ `fumbles_lost_total`, K keys)

These map 1:1 onto standard NFL player-prop markets (pass yds, pass TDs, rush yds,
recv yds, receptions, anytime-TD via TD means). The fantasy path scores these into
points (`scoring.py`); the props path must use the **raw stat distributions** instead.
`build_weekly_projections()` already returns neutral + interval data per player-week.

Separate section because the question differs: fantasy asks "who scores more PPR?"
Props asks "is the book's line mispriced vs my distribution?" — needs odds math,
book-line inputs, and edge/bankroll discipline the fantasy layer must never absorb.

## Goals

- New `src/ffanalytics/props.py`: fair line (= projected stat median) + over/under
  probability + no-vig fair American odds + EV vs a user-supplied book line/price,
  per player-week per market, from existing `stat_projector` outputs + intervals.
- Book lines enter **manually** (CLI/API payload, stored in new `prop_lines` table).
  No automated odds feed (see Non-Goals — $0/outbound).
- Shadow-log every surfaced edge; resolve vs actuals; gate "trusted" on
  `MIN_SHADOW_SAMPLES=20` resolved per market group (reuse `shadow.py` pattern).
- Hub: new **sidebar** tab "Props" (DESIGN.md §8: nav lives only in sidebar),
  read-only GETs, same tokens/a11y (mono numbers, interval bar, text+color badges).
- Calibration backtest on 2025 holdout: predicted P(over) vs empirical hit rate
  per market group before any "edge" label ships.

## Non-Goals

- No automated odds feed. Evidence (live check 2026-09-09): The Odds API player
  props — incl. NFL in season — requires **Business $99/mo**; Free ($0) covers only
  NBA/MLB moneylines (25 req/day); Pro ($29/mo) has no props at all.
  `# REJECTED — evidence: theoddsapi.com pricing/FAQ, props endpoint Business-only.
  Revisit only if $0-forever is explicitly lifted.`
- No new outbound host. `AGENTS.md` allows only Sleeper/nflverse/Open-Meteo.
  A future odds adapter needs an explicit allowlist exception — spec reserves the
  seam (`adapters/odds.py` interface shape) but ships nothing behind it.
- No auto-betting, no bet placement, no parlay optimizer v1, no live/in-play.
- No scoring-layer changes; no fantasy decision-layer changes (props is additive).
- No Kelly staking by default — flat-unit EV display v1 (Kelly optional later,
  fractional only, behind shadow gate; full-Kelly is a known bankroll killer).

## Data & Interfaces

### Fair-line mapping (stat_key → prop markets v1)

| Prop market | Source stat | Probability model |
|---|---|---|
| Pass yds O/U | `passing_yards` | Normal(mean=proj, sigma from §Model) |
| Pass TDs O/U (incl. 0.5/1.5) | `passing_tds` | Normal approx v1; Poisson candidate phase 2 |
| Rush yds O/U | `rushing_yards` | Normal |
| Rec yds O/U | `receiving_yards` | Normal |
| Receptions O/U | `receptions` | Normal (round line to .5 client-side) |
| Anytime TD scorer | `rushing_tds + receiving_tds` (+QB `passing_tds` excluded) | Poisson P(X≥1)=1−e^−λ, λ=proj TD mean |

Out of scope v1: interceptions, fumbles, K props (sample too thin — audit found K
coverage weakest), DEF props, combo markets (rush+rec yds needs covariance we
don't estimate — `# REJECTED v1 — evidence: no joint-residual artifact`).

### Sigma (honest approximation, flagged) — SHIPPED AS HISTORY-STD (see note)

> 2026-09-09 correction: the width/1.2816 design below was SUPERSEDED during
> Task 3. Fantasy-points widths don't transfer to stat units, so shipped sigma
> is the player's own-history sample std per stat, floored per market
> (`props.py: SIGMA_FLOORS`, starting values judged by Task-4 calibration).
> Uncalibrated by construction — same labeling mitigations apply.

Original design (rejected — evidence: stat-unit mismatch): sigma = displayed
half-width / 1.2816 (80% normal quantile), where displayed
half-width is the `projection.py` heuristic width for that row. Known limitation:
audit proved these widths are heuristic, not calibrated (QB 1.45× overcovers raw,
K 0.55× undercovers to 58.6% displayed) — so P(over) inherits that distortion.
Mitigations: (a) label probabilities "model-implied, uncalibrated until shadow≥20";
(b) calibration backtest must report per-market reliability before edge labels;
(c) K props excluded v1. Dependency: src-vs-hub width-semantics divergence
(half- vs full-width, found in 22-agent audit) must be pinned to ONE definition
before props ships — Task 1 does this (RESOLVED at the root 2026-09-09, f35dc9f).

### Odds math (pure functions, fully tested)

- `prob_to_american(p)`: no-vig fair odds, round-trip tested (`american_to_prob`
  inverse, p=0.5→±100, boundaries p→0/1 guarded).
- `ev_per_unit(p_model, book_price)`: EV = p·payout − (1−p)·1 for $1 stake.
- Edge rule v1 (mirrors `_edge.py` discipline): surface only if
  `|model_prob − novig_prob(book_line)| ≥ 5pp` AND `EV ≥ +4%` per unit AND
  `is_empty_projection == False` AND shadow gate status shown (baseline vs trusted).
- Book line payload: `{player_id, week, market, line, over_price, under_price,
  book}` — manual entry via CLI/API; stored `prop_lines` table (model writes —
  hub stays `mode=ro` and only GETs, preserving isolation contract).

### Shadow & calibration

- Extend `shadow.py` pattern: `kind="prop:<market>"`, log
  `{fair_line, p_over, book, book_line, edge_pp, ev}`; resolve vs actual stat.
- Calibration gate: 2025-holdout backtest (`scripts/backtest_props.py`) reports
  per-market Brier score + reliability bins (predicted decile vs hit rate).
  SHIPPED (2026-09-09): normal markets gate on 80%-band coverage + PIT
  uniformity (Brier needs book lines, which don't exist under manual entry —
  P(over=fair) is 0.5 by construction); Brier + reliability bins retained for
  anytime_td only. Documented in `props.py` calibration section.
  Edge labels ship only for market groups with monotonic reliability; others stay
  "tracking only".
- CLV: skipped v1 (no closing feed without paid API) — noted, not faked.

## Hub section

- Sidebar tab "Props" (`hub/src/views/props.js` + route), same card/table language
  as Projections tab; columns: player, market, fair line, model P(over), book
  line+price (manual), edge pp, EV/u, interval, shadow status chip.
- Manual-entry form POSTs to **model `:8000`** (not hub proxy — hub never writes,
  `verify-isolation.sh` must stay green; the known `triggerRefresh` regex blind
  spot must not gain a sibling — form targets model base URL explicitly).
- Copy honesty (audit-driven): no "±1 SD" language; K excluded with reason shown;
  "model-implied, uncalibrated" disclaimer until per-market shadow≥20.

## Verification Gates

- **Gate 1 (odds math):** `prob_to_american`/`american_to_prob` round-trip +
  EV sign tests (`tests/test_props.py`), incl. -110 both-sides ⇒ EV<0 at p=0.5.
- **Gate 2 (calibration):** `scripts/backtest_props.py` on 2025 holdout; per-market
  Brier + reliability monotonicity reported; non-monotonic groups stay untracked.
- **Gate 3 (no fantasy regression):** full `SLEEPER_LEAGUE_ID=test pytest -q`
  green; `stat_projector.py`/`scoring.py` untouched (props imports, never edits).
- **Gate 4 (isolation):** `bash hub/verify-isolation.sh` green; hub does zero
  odds-fetch, zero writes; no new outbound host in `src/` or `hub/`.
- **Gate 5 (shadow):** `is_trusted("prop:<market>")` False before 20 resolved;
  edge UI shows "tracking" state, never "trusted".

## Risks

- **Gambling harm (single private user, entertainment-only):** no auto-bet surface,
  flat units, persistent RG copy ("props are priced with vig; model edge estimates
  are uncertain; never bet more than you can afford to lose"), no dark patterns
  (no "LOCK" language — edge chips read `VALUE / TRACKING / NO EDGE`).
- **Legality:** personal-analysis tool, no bookmaking; user checks local laws.
- **Uncalibrated probabilities:** heuristic widths in ⇒ honest labels + gates above.
- **Week-1 leakage hole** (`stat_projector.py:512-513`, audit finding) propagates
  to props — fix or exclude week 1 from props backtest/edge.
- **Scope creep into fantasy:** props module must not import or alter
  `decision.py`/`comparison/` — review gate greps for it.
