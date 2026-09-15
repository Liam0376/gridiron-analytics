# League — Fantasy Bahamas

12-team full-PPR auction ($200 per Sleeper draft settings 2026, verified 2026-09-15 via `/v1/league/<id>/drafts`), Sleeper `1397736035240173568`. Roster `['QB','RB','RB','WR','WR','TE','FLEX','FLEX','K','DEF','BN','BN','BN','BN']` + `reserve_slots=2` IR (not in `roster_positions`). 2 extra FLEX → receiving volume premium at RB/WR/TE.

Scoring: `rec=1.0` + 40+ bonuses (`pass_cmp_40p/rush_40p/rec_40p=1.0`, `pass_td_40p/...=1.0`, `fgm_*/fgmiss`, `fum_lost=-2.0`, etc). **Never hardcode** — `sleeper.get_league_settings()` is truth (editable mid-season). Trades deadline week 11, 2-day review, majority 6 votes; waivers FAAB $100 2-day clear (per Sleeper league settings — re-verify via API each season). Entry $750 MXN prizes $5,500/$2,500/$1,000.

User: fantasy-savvy, NFL-new — explain football context concisely.

2 FLEX + bonuses context captured here; pull exact scoring via API each season.
