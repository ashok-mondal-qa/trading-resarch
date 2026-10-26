# NIFTY options, EXP-0029..0032: report (research only, 2026-10-25)

Spec `docs/strategy-specifications/nifty-options.md` v0.1.1 (rules pre-registered and committed in fea7d35 before
any run). Runner `python -m trading_research.backtesting.run_options`; outputs `EXP-00xx-<strategy>.json` and
`EXP-00xx-trades.csv` (1× costs) in this folder. Data: NSE F&O bhavcopy and NIFTY 50 index files,
2012-02-21..2024-12-31 (verified fact: NSE archive, retrieved 2026-10-25, SHA-256 per file in manifests).
The 2025-01-01..2026-10-23 holdout was never loaded.

**Result: all four REJECTED.** None is a holdout candidate. Derivatives stay banned for paper and live trading.

## Headline numbers (calculated; dev 2012-02-21..2022-12-31 unless stated)

| | Trades | Mean R 1× | 98.75% interval 1× | Mean R 2× | PF 2× | 2012–16 2× | 2017–22 2× | 2023–24 2× |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXP-0029 iron condor | 107 | −0.06 | −0.17..+0.04 | −0.09 | 0.70 | −0.10 | −0.07 | +0.02 |
| EXP-0030 short strangle | 127 | −0.00 | −0.16..+0.15 | −0.03 | 1.16 | −0.09 | +0.01 | −0.01 |
| EXP-0032 long call (breakout) | 52 (< 60) | −0.01 | −0.31..+0.38 | −0.05 | 1.14 | −0.30 | +0.09 | +0.09 |

PF is computed on index points, mean R on each trade's own risk unit, so they can disagree (strangle: small
losses in quiet, low-credit months are large in R; the few high-credit months carry the points profit).

| EXP-0031 covered call (monthly) | Sharpe | CAGR | Max drawdown |
| --- | --- | --- | --- |
| NIFTY buy and hold, dev | 0.72 | 11.8% | −28.9% |
| Covered call 1×, dev | 0.65 | 8.2% | −26.7% |
| Covered call 2×, dev | 0.63 | 7.9% | −26.8% |
| 2012–16 2× (hold 0.60) | 0.70 | 8.2% | −14.3% |
| 2017–22 2× (hold 0.75) | 0.54 | 7.1% | −26.8% |
| 2023–24 2× (hold 1.20) | 1.47 | 15.6% | −7.6% |

The covered call gave up about 3.6 points of yearly return for almost no drawdown relief: capped upside in
strong months (2017–22), not much cushion in crashes (worst month −24.3% vs −25.7%, March 2020).

## Model interpretation
* Selling options here (iron condor, strangle) wins about 70% of months, but the losing months take it all
  back. That matches the SEBI study's picture (verified fact, SEBI press release 23 Sep 2024: 93% of individual
  F&O traders lost money FY22–FY24). A high win rate is not an edge.
* The short strangle's worst month lost 1.9× its risk unit (2014-12) and the 2020-03 crash 1.06×; losses are
  not capped and a gap open can be far worse than an end-of-day stop. Margin needs (not modelled) would make
  it unaffordable for a ₹10 lakh account at the project's 0.5% risk limit anyway.
* Breakout call buying only worked in 2017–22 and lost heavily in 2012–16; profits came from a handful of
  trades (top 5 > 100% of net profit).
* Illustrative equity, risking 5% per trade (not project policy), 1× costs, dev: iron condor ended at 0.70×
  start, strangle 0.90×, long call 0.91×. F&O tax (31.2% of each year's net profit, losses carried; assumption)
  barely changes these because there were few profitable years.

## What this does not test (limitations)
End-of-day data only: intraday stops, the popular 9:20 short straddle and weekly expiry-day trades are not
tested. Some months were skipped because a far leg did not trade at t+1's open (iron condor 107 of 129 dev
months, strangle 127, covered call 128); skipped months are not filled and may include bad ones (e.g. no
strangle in April 2020). Slippage is a flat estimate; margin, collateral interest and dividends are not modelled.

## Process note
The first run (same rules) used a monthly-expiry calendar that included five stale holiday dates (contracts
listed months ahead carried an expiry later moved for a holiday, e.g. 2014-02-27 → 2014-02-26), which skipped
the following month. Fixed in v0.1.1 (calendar only) and rerun; every verdict was the same in both runs.
