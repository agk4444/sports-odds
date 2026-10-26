# Sports Odds — how `data.json` is generated

Daily Jev sports picks for https://odds.socialnews.xyz/ (GitHub Pages).
The live page is `index.html` + `app.js`; it only fetches `data.json`.

## Pipeline (runs every morning, ~7:08 AM ET)

```
make_sports_data.py
  │  1. Fetch upcoming games from ESPN's core API (keyless, date-dynamic:
  │     no hardcoded dates). NFL uses a 7-day window, MLB/NBA/NHL today,
  │     soccer today..+4 days. Lines/totals come from ESPN's odds feed
  │     (DraftKings preferred for 3-way soccer).
  │  2. Jev picks, lightly threaded (3 workers, 1s stagger, 3 retries):
  │     2-way leagues -> jev-sports-pick, 3-way soccer -> jev-soccer-pick.
  │     Cricket -> jev-sports-pick, from cricket_fixtures.json.
  │  3. Assemble data.json (tabs, cards, "Latest changes" notes).
  ▼
refresh.sh — commits + pushes data.json; Pages redeploys automatically.
```

`refresh.sh` starts with `git reset --hard origin/main`, so the working
tree must be clean before it runs. Exit code 2 from `make_sports_data.py`
means ESPN returned zero upcoming games: the old `data.json` is kept
untouched and the run aborts — never an empty board.

## Safeguards (borrowed from the elections pipeline)

- An ESPN failure never becomes a fake pick: that league gets an honest
  empty state, and if *nothing* fetches, the old `data.json` is kept.
- A game with no successful Jev call after 3 retries is skipped, never
  invented.
- Past games (started >1h ago) are filtered out; cricket fixtures in the
  past are filtered the same way.

## Files

| File | What it is |
|---|---|
| `make_sports_data.py` | The generator. Usage: `./make_sports_data.py [--out DIR] [--dry-run] [--max-games N]`. |
| `refresh.sh` | Daily driver: reset to `origin/main`, run the generator, commit + push `data.json` only if it changed. Appends to `refresh.log` (untracked). |
| `jev-soccer-pick` | The 3-way soccer Jev caller (vendored reference copy). Calls `https://api.typesafe.ai/v1/systemone` for home/draw/away + probabilities + confidence. Auth is via the agent runtime's surrogate credential exchange (`custom.typesafe`) — no key is stored in this file. |
| `cricket_fixtures.json` | Manual input: upcoming cricket fixtures (event, teams, venue, date, note). Edit by hand when new fixtures are announced; past ones are ignored automatically. |
| `index.html`, `app.js`, `data.json`, `CNAME` | The static site itself. |

## Dependency note

`make_sports_data.py` shells out to two Jev CLIs by absolute VM path:

- 2-way: `/home/hatch/workspace/skills/typesafe/bin/jev-sports-pick`
  (TypeSafe skill CLI — not vendored here, same as the elections pipeline)
- 3-way: `/home/hatch/workspace/sports-calls/jev-soccer-pick`
  (the `jev-soccer-pick` file in this repo is a verbatim reference copy;
  the daily run still uses the `sports-calls/` path — switching it to the
  repo copy is a one-line `JEV_3WAY` change)

ESPN's core API needs no key. The only credential in the whole pipeline
is the TypeSafe one, held by the agent runtime, never in the repo.

## Never commit

- `refresh.log` (per-run log), `__pycache__/` (see `.gitignore`)
- API keys or any credential

---
© 2026 AGK FIRE INC. All rights reserved. See LICENSE.
