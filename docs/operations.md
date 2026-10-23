# Operations runbook (paper trading only)

Nothing in this repository sends an order to a broker or exchange. `get_broker()` returns only the paper
simulator, which writes journal records. Live trading needs a separate written authorization from the
project owner (CLAUDE.md rule 1).

## Daily report
```
.venv/bin/python -m trading_research.reporting.daily            # latest completed session
.venv/bin/python -m trading_research.reporting.daily --date 2026-10-22
```
- Run after NSE publishes the day's files: the bhavcopy and `ind_close_all` index file. Before they exist
  the freshness check says the data may be stale, and the report's status is DATA INSUFFICIENT.
- A fresh container works: the command fetches the ~330 stock sessions and ~840 index sessions it needs
  (about 6 minutes from an empty `data/` folder, measured 2026-10-23).
- Output: `reports/YYYY-MM-DD.md` (12 sections, validated before it is written) and records in
  `journal/YYYY-MM.jsonl` (append-only, hash-chained; `Journal().verify()` must return `[]`).

## What the final status means
| Status | Meaning |
| --- | --- |
| TRADE CANDIDATE | a setup passed gates 1–9; the paper broker places a simulated order for the next open |
| WATCHLIST | the setup lacks only its confirmation, or a third candidate beyond the 2-a-day ceiling |
| REJECTED | a rule failed (regime, setup, risk, or the strategy is not ACCEPTED in the registry) |
| NO TRADE | data fine, nothing passed every gate (an acceptable outcome) |
| DATA INSUFFICIENT | stale or missing data, or a required check (such as the event screen) is unavailable |

As of 2026-10-23 no strategy is ACCEPTED and gate 7 has no event screen, so the report can only say
NO TRADE or DATA INSUFFICIENT. Both must change, through the registry and a reviewed spec, before a
TRADE CANDIDATE is possible.

## Checks
- `.venv/bin/python -m pytest -q`: unit, no-lookahead, safety and end-to-end tests
  (`tests/test_end_to_end.py` runs a synthetic market through signal → order → fill → exit).
- Alerts (project post plus email) are switched off until a strategy passes validation (owner's choice,
  2026-10-23).
