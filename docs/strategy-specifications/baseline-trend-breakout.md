# Baseline: trend + 20-day breakout (long only) — spec v0.1

Status: **specified, not tested** (2026-10-23). No backtest has been run. Nothing here is evidence of an
edge. Code: `src/trading_research/strategies/baseline_trend_breakout.py`. Registry: EXP-0005.

## Purpose
The simple reference every later idea (price action, SMC) must beat on the same data, costs and splits.
If this baseline cannot cover realistic Indian delivery costs, that is a useful finding too.

## Hypothesis (label: hypothesis)
Liquid NSE stocks that close at a 20-session high with above-normal volume, while in a long-term uptrend,
outperforming NIFTY 50, and while NIFTY 50 itself is in an uptrend, continue upward often and far enough
over the following weeks for expectancy per trade to stay positive after costs, slippage and gaps.

## Data
- NSE CM bhavcopy, series EQ, 2021-10-25..2026-10-22, split/bonus-adjusted for signals, raw prices for
  fills (`data/adjust.py`). Renamed tickers joined when confirmed (`data/symbols.py`).
- Benchmark: NIFTY 50 closes from NSE's daily index file (`data/indices.py`).
- Universe: every EQ symbol traded on the signal date (point-in-time from the bhavcopy itself, so stocks
  that later delisted are included). No index-membership filter. A symbol must pass gate 1
  (`data/quality.py`, window 260 sessions) on the signal date.

## Rules (all evaluated at the close of day t)
| Gate | Rule | Parameter (v0.1) |
| --- | --- | --- |
| 1 Data | gate-1 checks pass; all inputs below non-missing | window 260 |
| 2 Regime | NIFTY 50 trend label = `up` (close > SMA200 and SMA50 rising over 20 sessions) | — |
| 3 Higher timeframe | stock close > SMA200 and SMA50 > SMA200 | 50 / 200 |
| 4 Setup | close > highest high of the previous 20 sessions; 63-session RS vs NIFTY 50 > 0; close ≥ ₹50; 20-day median traded value ≥ ₹5 crore | 20, 63, 50, 5e7 |
| 5 Confirmation | volume ≥ 1.5 × median volume of the previous 20 sessions (else WATCHLIST) | 1.5 |
| 6 Risk | stop = close − 2 × ATR(14); stop distance ≤ 10% of close; sizer accepts within 0.5% / 2% caps | 2.0, 10% |
| 7 Event/liquidity | liquidity as in gate 4. **Event screen not implemented yet** → disclosed limitation | — |
| 8 Challenge | risk-manager and auditor review (this file, below) | — |
| 9 Final | at most 2 new candidates per day, highest 63-day RS first; the rest WATCHLIST | 2 |

## Trade management
- **Entry:** next session open (t+1), raw price + slippage. If that open is at or below the stop, skip.
- **Stop:** fixed at entry. Never widened. If a day's low touches it, fill at the stop; if the day opens
  below it, fill at the open (gap loss can exceed planned risk).
- **Exit:** close below the lowest low of the previous 10 sessions → exit next open. Time stop: exit at
  the open after 40 sessions in the trade.
- **Size:** `risk/sizing.py`, 0.5% planned risk per position, 2% aggregate; no averaging down, no
  pyramiding, one position per symbol.
- **Costs:** `config/settings.yaml` cost model (rates still unverified) and 10 bps slippage per side;
  every result is also run at 2× costs.

## Splits (fixed now, before any run)
| Split | Signal dates | Use |
| --- | --- | --- |
| Warm-up | 2021-10-25 .. 2022-08-12 | indicators only (SMA200 + 63-day RS need ~263 sessions) |
| Train | 2022-08-15 .. 2024-12-31 | development; any parameter change is made here only |
| Validation | 2025-01-01 .. 2025-12-31 | one check of the train-chosen version |
| Holdout | 2026-01-01 .. 2026-10-22 | **sealed**; run once, after the spec is frozen |

v0.1 has **no parameter grid**: all values above are fixed a priori from common practice, so the number of
variants tried is 1. Neighbouring values (breakout 15/30, stop 1.5/2.5 ATR, volume 1.25/2.0) are run on
train only as a robustness check, never to pick a winner.

## Acceptance / rejection (decided now)
- Fewer than 30 trades in a split → inconclusive for that split.
- Reject if, on validation at 2× costs, expectancy per trade ≤ 0 or profit factor < 1.1.
- Reject if the 95% bootstrap interval of train expectancy (1× costs) includes 0 **and** validation is
  not clearly positive.
- Also compare against: buying NIFTY 50 and holding over the same dates; the same entries without the
  volume and RS filters.
- Passing all of this makes the strategy eligible for paper trading only. It is not a probability claim.

## Known limitations (disclosed in every report)
Five years of history is short and covers few market regimes; the holdout is under 10 months. No event
screen (results dates, etc.) yet. Cost rates unverified. Circuit-locked days are not yet detected, so fills
on those days may be optimistic. The universe excludes BE-series days (trade-to-trade), so stocks that move
in and out of EQ have gaps and are skipped by gate 1.

## Review (gate 8, 2026-10-23)
**Risk manager:** sizing and caps reuse the tested sizer; the stop is fixed and never widened; gap risk is
modelled at the open. Concern: breakouts cluster on strong market days, so two same-day entries can be
highly correlated. Accepted for v0.1 because of the 2-per-day cap and the 2% aggregate cap; correlation is
to be reported in Phase 7.
**Independent auditor:** look-ahead covered by tests (`tests/test_strategy_baseline.py`); the breakout and
exit levels use the previous sessions only. Objections recorded: (1) RS uses NIFTY 50 while the universe
includes small caps, so RS > 0 partly selects small-cap beta; keep and report by size bucket. (2) Five
years and a short holdout make any result fragile; a pass must not be described as validated. (3) The
event screen gap means results-day gaps are included in returns. None is a veto for running the backtest;
all three must appear in the Phase 7 report.

## Changelog
- **v0.1 (2026-10-23):** initial spec. Tests: feature and candidate no-lookahead tests. No results exist,
  so no earlier results are affected. A holdout evaluation is needed once Phase 7 runs.
