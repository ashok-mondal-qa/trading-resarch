# Weekly 12-1 momentum and gap-up drift (long only) — spec v0.1

Status: **pre-registered, not run** (written and committed before any backtest of these rules).
Code: `src/trading_research/strategies/swing_ideas2.py`, runner `src/trading_research/backtesting/run_swing_ideas2.py`.
Registry: EXP-0014 (`momentum_weekly`), EXP-0015 (`gap_drift`). Nothing here is evidence of an edge.

## Why these two (label: hypothesis)
- **H14 `momentum_weekly`:** the 12-1 momentum effect (Jegadeesh & Titman 1993) tested in EXP-0013, with
  the rank checked every week instead of every month. EXP-0013 was positive in 2016–2024 but rested on
  about 50 entry months, so its interval included zero. Weekly checks give about four times as many entry
  dates. **Disclosure:** this design was suggested by EXP-0013's results (its report named it as a
  possible follow-up), so the presample, train and 2025 results of monthly momentum are known. Only the
  new early split below can test it fairly.
- **H15 `gap_drift`:** prices keep drifting after news (post-earnings drift, Bernard & Thomas 1989; news
  momentum, Chan 2003). Without an announcement calendar, a large opening gap up that holds through the
  day on heavy volume stands in for "news the market liked". No earlier experiment used gaps.

## Data and splits
- New data: NSE CM bhavcopy from 2011-07-01 (the first legacy files with an ISIN column; files before that
  lack ISIN and trade counts) and NSE daily index files from their first archive date (about 2012-03;
  earlier dates return 404). All with the same loader, checks and manifests.
- **early: 2013-01-01..2015-12-31.** Never evaluated by any experiment (2015 was only warm-up for
  Phase 11). It is the decisive test. 2011-07..2012 is warm-up (SMA200, NIFTY 50 regime, 12-1 momentum,
  260-session gate-1 window).
- presample 2016-01-01..2022-08-12 (used once, by EXP-0011..0013), train 2022-08-15..2024-12-31 and
  validation 2025 (both used several times): sign checks only.
- **holdout 2026-01-01..2026-10-22 stays sealed.** The runner has no path to it.
- Each run loads bars only up to its split end; adjustment errors count only if dated by then.

## Shared rules (as in `swing-ideas.md`)
NIFTY 50 trend `up`; stock close > SMA200; raw close ≥ ₹50; 20-day median traded value ≥ ₹5 crore;
stop below the close and at most 10% away; 0.5% / 2% caps, a new position only if a full 0.5% fits; at
most 2 new a day; no event screen. Entry next open, skipped at or below the stop; fixed stop, gaps fill
at the open. Costs from `config/settings.yaml` (unverified) plus 10 bps slippage per side, all also at 2×.
ETFs (ISIN `INF…`) and old tickers already joined into a renamed successor are excluded.

## Strategy rules
| | `momentum_weekly` (H14) | `gap_drift` (H15) |
| --- | --- | --- |
| Setup at close t | t is the week's first session; stock in the top 10% of 12-1 momentum among liquid, gate-1 stocks that day | open ≥ 1.04 × previous close, close ≥ open, volume ≥ 3 × median volume of the 20 previous sessions |
| Stop | close − 2.5 × ATR(14) | low of t − 0.1 × ATR(14) |
| Exit (next open) | on a later week start: rank below the top 20%, not rankable, or close < SMA200 | close below the lowest low of the previous 10 sessions |
| Time stop | 126 sessions | 40 sessions |
| Rank when > 2 a day | highest 12-1 momentum | highest 63-day RS vs NIFTY 50 |

One parameter set each; no other values are run. 12-1 momentum as in EXP-0013.

## Measurements
Portfolio (as traded) and standalone (every signal alone, one open trade per stock), as in
`swing-ideas.md`; intervals resample whole entry months.

## Acceptance / rejection (decided now, per strategy)
A strategy **passes** only if every rule holds:
1. Early portfolio: ≥ 30 closed trades; at 2× costs expectancy > 0 and profit factor ≥ 1.1.
2. Early standalone: ≥ 100 closed trades; at 1× costs the lower end of the month-clustered interval at
   1 − 0.05/2 (97.5%, Bonferroni for two strategies) is above 0; at 2× costs expectancy > 0.
3. Presample, train and validation standalone at 2× costs: expectancy > 0 in each.

Otherwise **REJECTED**. Applied mechanically by `run_swing_ideas2 --verdict`. A pass makes a strategy a
candidate for the one-time holdout, which also needs the project owner's go-ahead; if both pass, the one
with the higher early standalone expectancy at 1× costs is proposed. No status is a probability claim.

## Known limitations
As in `swing-ideas.md` (unverified costs applied back in time, no event screen, no circuit-lock
detection, weekend special sessions missing), plus: the early split is short (3 years, mostly one
2014–2015 rally after a 2013 range); gap days include results days, so gap stops can lose more than
planned; the 2013–2015 universe is smaller (fewer liquid stocks).

## Review (gate 8, 2026-10-25)
**Risk manager:** same engine and caps; `gap_drift` stops sit under the gap day's low, a defined level;
momentum stops are volatility-based. Accepted.
**Independent auditor:** perturb-the-future and truncation tests for both feature sets; weekly momentum
uses the exact monthly feature definition (tested). Objections: (1) H14 was suggested by EXP-0013, so its
later splits are not independent evidence; (2) the 2025 split has now been seen six times; (3) momentum
and gap signals both favour stocks already moving up, so their results may be correlated; (4) no event
screen. Not vetoes; all must appear in the report.

## Changelog
- **v0.1 (2026-10-25):** initial spec, committed before any run. Also: `standalone_summary` takes the
  interval level as an argument (Phase 11 output unchanged). No earlier results are affected. A holdout
  evaluation is needed only if a strategy passes.
- **v0.1 data note (2026-10-25, before any run):** the index loader now reads NIFTY 50 under its 2012 name
  "S&P CNX Nifty" too, and excludes an index name listed twice in one file (ind_close_all_08022013.csv lists
  "CNX Alpha Index" twice) instead of rejecting the whole file. NIFTY 50 closes now start 2012-02-21. NSE's
  archive has no index file (HTTP 404, re-checked) for 11 sessions between 2013-10 and 2016-01; on those
  days the regime is unknown, so no entries. No rule changes.

