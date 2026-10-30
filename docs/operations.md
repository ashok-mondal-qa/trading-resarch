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
  Observed on 2026-10-23 (polling every 5 minutes): bhavcopy available by 16:36 IST, index file by
  18:01 IST. So start a scheduled run after about 18:15 IST.
- Real-day run 2026-10-23 (18:06 IST): NO TRADE, 4 setups all rejected (NIFTY 50 trend down), about 4 min.
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

## Monthly forward check (EXP-0027 / EXP-0028 / EXP-0042 / EXP-0043, shadow only)
Fresh container, after the last completed session (NSE after ~18:15 IST; crypto any time after 00:00 UTC):
```
uv venv .venv && uv pip install -e '.[dev]'
.venv/bin/python -m trading_research.data.binance --load --end <last full month YYYY-MM> --daily-through <YYYY-MM-DD>
.venv/bin/python -m trading_research.backtesting.run_forward --market crypto --as-of <YYYY-MM-DD>
# NSE: reload bhavcopy and index files from 2011-07-01, list symbols and adjust (as in Phase 12), then
.venv/bin/python -m trading_research.backtesting.run_forward --market nse --as-of <last session>
.venv/bin/python -m trading_research.backtesting.run_factors --forward --as-of <last session>   # EXP-0042/0043
```
Commit `reports/forward/` and the Binance manifests. Results are interim until the decision rule in the spec
says otherwise; never change a signal status or send an alert from them.

## Weekday morning opening-range scan (EXP-0052, paper only)
A scheduled task fires weekdays at 09:35 IST into the project thread that owns it. Each run, in a fresh or
resumed container:
```
uv venv .venv && uv pip install -e '.[dev]'
# 1. grade the previous session's ideas, if any (its EOD bar must exist)
.venv/bin/python -m trading_research.live.intraday_scan score --day <previous session> --out-dir /mnt/project-files/trading-reports/intraday
# 2. today's scan (about 3 minutes; stale quotes -> DATA INSUFFICIENT, e.g. on holidays)
.venv/bin/python -m trading_research.live.intraday_scan scan --out-dir /mnt/project-files/trading-reports/intraday --capital <owner's capital>
```
Ideas and grades live in the project's shared folder (`trading-reports/intraday/<date>.json|.md|.score.json`),
not in git. The run posts a short message to the owner. It never places orders.
