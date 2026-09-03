# ADR 0001 — Vanilla JS, no framework, for the hub UI

- Status: Accepted
- Date: 2024 (inception)
- Deciders: repo owner
- Scope: `hub/` (Vite-built UI), not the model (`src/ffanalytics/`)

## Context

The hub UI is a read-only dashboard over `data/fantasy.db` (exposed via
`hub/server.py` in `mode=ro`). It needs to render rosters, projections,
matchups, waiver targets, news, and refresh-log state — and let the user
trigger `POST /refresh` on the model API. Single-user, local-only; no
auth, routing complexity, shared state, SSR, or SEO.

## Decision

The hub uses **vanilla JavaScript modules served by Vite**, no UI framework
(no React/Vue/Svelte/Solid). Vite is used purely as a dev server + ES-module
bundler; runtime code stays framework-free. Templates are plain HTML
(`hub/index.html` + `hub/src/` modules) and `fetch()` calls the proxy.

## Consequences

Positive:
- Zero JS-framework dep churn. `hub/package.json` only carries Vite itself
  (verified by `hub/verify-isolation.sh` step 6).
- Faster cold boot (`npm run dev` is just Vite serving files). No virtual
  DOM, no hydration, no compiler step on top of Vite.
- Mental model: "read DOM, write DOM, call `fetch`." Readable for someone
  who only opens the file occasionally.
- Single repo size stays small; no `node_modules` framework bloat (Vite's
  tree is enough).

Negative:
- Anything more than a dashboard (drag-and-drop, complex forms, optimistic
  UI) is hand-rolled. If the hub ever grows past ~10 views, this will hurt.
- No component model means CSS is hand-managed; risk of drift if styles
  aren't disciplined.

## Alternatives considered

- **React + Vite:** Considered for component reuse, but the surface area
  is too small for a framework — adds more ceremony than it removes.
- **HTMX + server-rendered HTML:** Rejected — proxy stays a thin
  JSON-over-HTTP layer; the UI wants a SPA-ish feel for the live refresh
  flow.
- **Svelte:** Would have been the natural middle ground, but adds a build
  tool on top of Vite. Vanilla JS keeps the toolchain one-deep.

## When to revisit

If the hub needs: (a) client-side routing across >5 pages, (b) shared
client state that needs to stay in sync across views, or (c) a non-trivial
form with validation — revisit this ADR and pick React or Svelte. Until
then, vanilla JS is the cheapest option.