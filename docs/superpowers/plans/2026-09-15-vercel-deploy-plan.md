# Plan: Vercel Deployment — Gridiron Public

Date: 2026-09-15
Spec: `docs/superpowers/specs/2026-09-15-vercel-deploy-spec.md`

## Task 1: Scaffold new repo

- [ ] Create `gridiron-public/` directory
- [ ] Add `vercel.json` with build + route config
- [ ] Add `requirements.txt` (requests only)
- [ ] Add `package.json` (empty, for Vercel static build)
- [ ] Add `README.md` with setup + deploy instructions
- [ ] Add `.gitignore` (node_modules, .vercel, __pycache__)

**Verify**: `ls gridiron-public/` shows all files

## Task 2: API layer (Python serverless)

- [ ] `api/index.py` — router: `/api/league`, `/api/projections`, `/api/analytics`
- [ ] `api/league.py` — fetch from Sleeper API (league, rosters, users)
- [ ] `api/projections.py` — read precomputed JSON from `data/projections/`
- [ ] `api/analytics.py` — compute VBD + auction values per-league

**Verify**: `cd gridiron-public && python -c "from api.index import app"` imports clean

## Task 3: Frontend (static)

- [ ] `public/index.html` — SPA shell with input + loading + main view
- [ ] `public/styles.css` — clean dark theme, mobile-first
- [ ] `public/app.js` — orchestrator: league import → tab switching → rendering
- [ ] `public/lib/api.js` — API client (fetch wrappers)
- [ ] `public/lib/table.js` — sortable projection table component
- [ ] `public/lib/auction.js` — auction board component

**Verify**: `open public/index.html` renders landing page in browser

## Task 4: Weekly computation script

- [ ] `scripts/compute_week.py` — fetch nflverse, compute projections, write JSON
- [ ] Test: run manually, verify JSON output

**Verify**: `python scripts/compute_week.py --week 1 --season 2026` produces `data/projections/2026_week_01.json`

## Task 5: GitHub Action (weekly cron)

- [ ] `.github/workflows/weekly-projections.yml` — Tuesday 6am UTC
- [ ] Steps: checkout → setup python → run compute_week.py → commit + push
- [ ] Verify: action YAML is valid

**Verify**: `act -l` or manual trigger succeeds

## Task 6: Integration test

- [ ] `vercel dev` locally serves frontend + API
- [ ] Paste real Sleeper league ID → loads league
- [ ] Projections table renders
- [ ] Auction values compute
- [ ] Mobile layout works

**Verify**: end-to-end flow works on localhost:3000

## Task 7: Deploy

- [ ] `vercel --prod` deploys to production
- [ ] Public URL works
- [ ] Cold start < 5s

**Verify**: share URL with someone, they see projections

## Implementation order

Tasks 1-2 first (backend works before UI), then 3 (frontend), then 4-5 (cron), then 6-7 (test + deploy).

## Commit strategy

- Task 1: `chore: scaffold vercel deployment`
- Task 2: `feat: add API layer for league/projections/analytics`
- Task 3: `feat: add frontend with projection table and auction board`
- Task 4: `feat: add weekly projection computation script`
- Task 5: `ci: add GitHub Action for weekly projection refresh`
- Task 6-7: `docs: add deploy instructions and README`
