# Forward tracking of the two near misses (paper only) — spec v0.1

Status: **pre-registered, tracking from 2026-10-26** (written and committed before any forward data exists).
Code: `src/trading_research/backtesting/run_forward.py`. Registry: EXP-0027, EXP-0028.

## Why (label: hypothesis)
Every rule tested so far was rejected (EXP-0006..0026). The two closest were **crypto Minervini** (EXP-0021:
+1.91R standalone on 2018–2023, interval just below zero, too few trades, 2024 flat) and **NSE weekly 12-1
momentum** (EXP-0014: positive 2013–2024 at 2× costs, 2025 negative). All past data has now been used, so
more backtests mostly measure luck. The honest next test is data nobody has seen: from the next session on.

## What is tracked
| Experiment | Market | Rules (frozen, unchanged) |
| --- | --- | --- |
| EXP-0027 | Binance spot USDT pairs | EXP-0021 exactly (`run_crypto`, crypto-comparison.md v0.1) |
| EXP-0028 | NSE EQ | EXP-0014 exactly (`run_swing_ideas2`, swing-ideas-2.md v0.1) |

Same engine, costs (unverified), caps and fills as the backtests. Features use all bars up to the check date;
earlier bars (including the sealed holdout periods) serve only as indicator warm-up, and **no trade before
2026-10-26 is ever simulated or reported**. The sealed holdouts stay unused as evaluations. These are shadow
records: no signal status changes, no alerts, no orders; zero candidates remains the daily output.

## Checks
At most monthly (`run_forward --market crypto|nse --as-of <last completed day>`), after refreshing data
(Binance: `data.binance --load --end <last full month> --daily-through <day>`; NSE: bhavcopy, index files,
symbol changes and adjustment as in `docs/operations.md`). Data not loaded to the check date (crypto) or
within 4 days of it (NSE) → `DATA INSUFFICIENT` for that check. Each check writes
`reports/forward/<EXP>-<date>.json`; interim numbers are progress, not evidence.

## Decision rule (decided now, per experiment)
- **tracking** while fewer than 12 months have passed, or fewer than 30 portfolio trades (closed plus open,
  2× costs) and fewer than 24 months.
- Then **PASSED** only if all hold: ≥ 30 portfolio trades; portfolio at 2× costs expectancy > 0 (open trades
  marked to market) and profit factor ≥ 1.1; ≥ 50 standalone trades; standalone 1× month-clustered interval
  at 97.5% (Bonferroni over the two) above 0; standalone 2× expectancy > 0 (incl. open). Otherwise
  **REJECTED**, including when 24 months pass with fewer than 30 trades.
- A PASSED forward result makes the strategy a candidate for paper-trading review (risk manager, auditor,
  event screen, registry status). It is not a probability claim and not live-trading approval.

## Known limitations
Same as the source specs. The forward window will be short and regime-dependent (both strategies trade only
when their index is in an up trend). A functional check of the runner on already-used data (2020–2025) is
not evidence and is not reported.

## Changelog
- **v0.1 (2026-10-25):** initial spec, before any forward data. Adds daily-file loading to `data/binance.py`
  (current month) for the forward checks. No earlier results affected.
