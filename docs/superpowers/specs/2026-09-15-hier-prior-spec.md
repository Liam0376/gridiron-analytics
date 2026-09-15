# Spec: hierarchical TD prior (partial pooling)

> Status (2026-09-15): DRAFT — blanket-approved with points list 2026-09-15,
> implementing with pre-registration below. Production wiring needs a
> separate confirm on a pass verdict.

## Problem

POP (full pooling to the position xFP mean) beat X2 (no pooling) both
samples. Neither extreme is the right model: the correct shape is partial
pooling — shrink noisy individual estimates toward the population mean in
proportion to how much data backs them. A veteran with 15 games of xFP
history deserves near-individual treatment; a player with 2 games does not.

## Design (pre-registered, single variant)

HIER arm in `scripts/backtest_opportunity.py`: prior = w·individual +
(1-w)·POP with w = n/(n+m), m=5, n = games in the trailing window.
m=5 is the principle pick (one RECENT_N window of prior strength), fixed
before running, no grid. Same 30% regression weight, same windows as
X2/POP. Skill positions only (RB/WR/TE receiving+rushing TDs).

## Gates (frozen)

HIER promotes iff it beats POP with paired p<0.05 in BOTH samples with
corr neutral; else POP stands and HIER is REJECTED inline. If HIER fails
to beat BASE in both samples, reject outright. Full suite green.

## Non-goals

X1 revival, weight changes, QB scope, new data, production wiring on any
verdict short of the gate (separate spec + confirm).
