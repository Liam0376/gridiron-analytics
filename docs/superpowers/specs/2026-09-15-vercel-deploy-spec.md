# Spec: Vercel Deployment — Gridiron Public

Date: 2026-09-15
Status: PROPOSED

## What

Deploy a clean, public-facing version of Gridiron Analytics to Vercel.
User pastes a Sleeper league link → sees projections + auction values.
No sign-up, no config, no maintenance.

## Why

Current system is local-only (SQLite, two local servers, manual refresh).
Vercel deployment makes it accessible from anywhere, shareable via link,
and professional enough for LinkedIn/portfolio.

## Architecture

```
┌──────────────────────────────────────────────┐
│  Vercel (free tier)                          │
│                                              │
│  /public/              ← static frontend     │
│    index.html            (HTML/CSS/JS)       │
│                                              │
│  /api/index.py        ← Python serverless    │
│    GET /api/league?id=   Sleeper league info │
│    GET /api/projections  precomputed JSON    │
│    GET /api/analytics    VBD + auction vals  │
│                                              │
│  /data/projections/   ← precomputed JSON     │
│    2026_week_01.json     (committed weekly)  │
│    2026_week_02.json                         │
│    ...                                       │
└──────────────────────────────────────────────┘

GitHub Action (weekly cron):
  Tue night → fetch nflverse → compute projections → commit JSON → Vercel auto-deploys
```

## Data flow

### First visit (cold)
1. User pastes league link or types league ID
2. Frontend calls `GET /api/league?id=LEAGUE_ID`
3. Serverless function fetches from Sleeper API:
   - `GET /v1/league/{id}` → settings (scoring, roster, budget)
   - `GET /v1/league/{id}/rosters` → team compositions
   - `GET /v1/league/{id}/users` → team names/owners
4. Frontend calls `GET /api/projections?week=CURRENT`
5. Serverless reads precomputed JSON (committed by cron)
6. Frontend calls `GET /api/analytics?league_id=LEAGUE_ID&week=CURRENT`
7. Serverless computes league-specific VBD + auction values in-memory
8. Frontend renders

### Weekly cron (Tuesday 6am UTC)
1. GitHub Action triggers on schedule
2. Fetches nflverse weekly stats for current season
3. Runs `compute_projections()` (stat_projector pipeline subset)
4. Writes `data/projections/{season}_week_{week:02d}.json`
5. Commits + pushes → Vercel auto-deploys

## What gets kept (MVP)

| Feature | Source | Notes |
|---|---|---|
| Player projections (weekly + ROS) | stat_projector | Precomputed weekly |
| Auction values (VBD, $/VOR) | decision.py | Computed per-league on-demand |
| League import from Sleeper link | Sleeper API | Instant, no config |
| Roster analysis | Sleeper API | Current starters/bench |
| Matchup projections | projections + schedule | Per-week view |
| Confidence intervals | projection.py | Width per player |
| Position scarcity (flex) | scoring.py | 2-flex adjustment |

## What gets cut (MVP)

| Feature | Reason |
|---|---|
| Weather integration | Adds latency, marginal value |
| News/trending | Requires FantasyPros API key |
| Trade analyzer | Power-user feature |
| Waiver wire | Power-user feature |
| Backtest engine | Not needed for public |
| Shadow testing | Internal quality gate |
| Player props | Not MVP |
| DEF/ST projections | Sleeper handles defense scoring |

## New repo structure

```
gridiron-public/
├── public/
│   ├── index.html          # SPA entry
│   ├── app.js              # Main app logic
│   ├── styles.css          # Styling
│   └── lib/
│       ├── api.js          # API client
│       ├── table.js        # Projection table component
│       └── auction.js      # Auction board component
├── api/
│   ├── index.py            # Vercel serverless entry (router)
│   ├── league.py           # Sleeper league fetch
│   ├── projections.py      # Read precomputed JSON
│   └── analytics.py        # VBD + auction computation
├── data/
│   └── projections/
│       └── .gitkeep        # Precomputed JSONs committed by cron
├── scripts/
│   └── compute_week.py     # Weekly projection computation (cron)
├── requirements.txt        # Python deps (minimal)
├── vercel.json             # Vercel config
├── package.json            # For Vercel build (static)
└── README.md               # Setup + deploy instructions
```

## Python deps (minimal)

```
requests>=2.31
```

That's it. No pandas, no numpy, no heavy deps. The projection math is
simple enough for pure Python. nflverse data is fetched as CSV/JSON and
parsed with stdlib.

## Vercel config

```json
{
  "builds": [
    { "src": "api/index.py", "use": "@vercel/python" },
    { "src": "public/**", "use": "@vercel/static" }
  ],
  "routes": [
    { "src": "/api/(.*)", "dest": "/api/index.py" },
    { "src": "/(.*)", "dest": "/public/$1" }
  ]
}
```

## API contracts

### GET /api/league?id=LEAGUE_ID
```json
{
  "league_id": "1397736035240173568",
  "name": "Fantasy Bahamas",
  "season": 2026,
  "settings": {
    "scoring": { "pass_yd": 0.04, "rec": 1.0, ... },
    "roster_positions": ["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF","BN","BN","BN","BN"],
    "budget": 200,
    "num_teams": 12
  },
  "teams": [
    { "roster_id": 1, "team_name": "Team 1", "owner_name": "User", "players": [...] }
  ]
}
```

### GET /api/projections?week=3&season=2026
```json
{
  "week": 3,
  "season": 2026,
  "updated_at": "2026-09-16T06:00:00Z",
  "players": [
    {
      "player_id": "4046",
      "player_name": "Josh Allen",
      "position": "QB",
      "team": "BUF",
      "projected_points": 24.5,
      "projection_lower": 16.2,
      "projection_upper": 32.8,
      "width": 8.3,
      "opponent_team": "MIA",
      "ros_points": 418.0,
      "remaining_games": 16
    }
  ]
}
```

### GET /api/analytics?league_id=LEAGUE_ID&week=3
```json
{
  "players": [
    {
      "player_id": "4046",
      "player_name": "Josh Allen",
      "position": "QB",
      "projected_points": 24.5,
      "vor": 14.2,
      "auction_value": 32,
      "auction_value_dollars": "$32",
      "tier": 1,
      "edge": "FAIR"
    }
  ],
  "meta": {
    "budget": 200,
    "num_teams": 12,
    "total_budget": 2400,
    "spent": 0,
    "available": 2400
  }
}
```

## Frontend UX

### Landing page
- Hero: "Gridiron — Fantasy Football Analytics"
- Subtitle: "Paste your Sleeper league link for instant projections"
- Input: league URL or ID
- Button: "Analyze League"
- Loading state: spinner + "Importing league from Sleeper..."

### Main view (after import)
- Tab bar: Projections | Auction | Matchups
- **Projections tab**: sortable table (name, pos, team, proj pts, confidence, tier)
- **Auction tab**: budget board, $/VOR column, roster slots remaining
- **Matchups tab**: weekly matchup projections with opponent
- Week picker: prev/next week buttons
- League name in header

### Responsive
- Mobile-first, works on phone (auction draft tool at the table)
- Desktop: full table view with sort/filter

## Validation

- [ ] `vercel dev` locally serves frontend + API
- [ ] Pasting a real Sleeper league ID loads league settings
- [ ] Projections table renders with real data
- [ ] Auction values compute correctly (match local hub)
- [ ] Mobile layout is usable
- [ ] Cold start < 5s (precomputed data)
- [ ] Deploy to Vercel succeeds
- [ ] Public URL works for anyone with the link
