# ADR 0002 — Hub isolation is enforced, not aspirational

- Status: Accepted
- Date: 2024 (inception)
- Deciders: repo owner
- Scope: `hub/` ↔ `src/ffanalytics/` boundary

## Context

This repo hosts two products in one tree: the Python projection model
(`src/ffanalytics/`, root `pyproject.toml`) and the read-only Vite UI
(`hub/`, its own `package.json`). Tempting to let `hub/server.py` import
the model directly, share constants, and write to `data/fantasy.db` —
would simplify a lot of code. The user pushed back: **the hub must remain
a pure read-only consumer** so the model test suite stays independent and
the hub can be rebuilt without touching the model.

## Decision

The hub must not `import ffanalytics` from any runtime code, must not
write to `data/fantasy.db`, and must not bind `0.0.0.0`. **Real gates**
(grep-based, can't lie), checked by `hub/verify-isolation.sh`, not style
rules. The check is deliberately simple so it can't lie and exits non-zero
on failure:

1. No `from ffanalytics …` or `import ffanalytics` in `hub/**/*.py` or
   `hub/**/*.js`.
2. No `INSERT INTO`/`UPDATE SET` from `hub/**`.
3. No `0.0.0.0` host binding anywhere in `hub/**` source.
4. `hub/vite.config.js` and `hub/server.py` must bind `127.0.0.1`.
5. `hub/server.py` must open the DB with `mode=ro`.
6. Hub has its own `package.json`; `vite` is never added to the root
   `pyproject.toml`.

To honour (1) without losing cold-boot DB warm, `scripts/db_warm.py` was
created. `hub/start.sh` and `hub/FantasyHub.command`
shell out to `.venv/bin/python scripts/db_warm.py` instead of inlining a
`python -c "from ffanalytics import db …"` heredoc (which the isolation
grep would also flag, since `.command` files are treated as code by some
reviewers, and shell heredocs aren't a clean boundary either way).

## Consequences

Positive:
- `rm -rf hub/` leaves the model test suite green — the two products
  are mechanically independent, even though they share a working tree.
- The hub can be rewritten in any stack without touching `src/ffanalytics/`.
- A single grep is enough to audit the boundary; no AST tool required.

Negative:
- Some logic is duplicated (`hub/server.py` has a small amount of model
  knowledge — Sleeper player-name lookup, scoring constants). This is the
  intentional cost.
- Cold-boot DB warm requires shelling out from `hub/start.sh` to a Python
  script under `scripts/` instead of a one-liner inside the shell script.
- `scripts/` is now implicitly "model-owned helper scripts" — anything
  placed there will be considered safe to import `ffanalytics`.

## Alternatives considered

- **Soft lint rule:** Rejected — the user has been bitten before by
  lint rules that "warn" but don't fail. Grep-and-fail is louder and
  simpler.
- **Separate repos:** Would give stronger isolation but doubles the
  bootstrap cost (two clones, two venvs, two deploys) for a single-user
  tool. Not worth it.
- **Make `hub/server.py` part of `src/ffanalytics/`:** Would lose the
  "hub can be deleted without touching model" property and brings Vite
  into the Python dep graph (forbidden by check 6).

## When to revisit

If the user ever wants a feature that genuinely requires the hub to call
model logic directly (e.g. an in-hub "run projection" panel), revisit
this ADR — but the right answer is most likely to expose a new endpoint
on the model API and call it via HTTP, not to break the isolation.