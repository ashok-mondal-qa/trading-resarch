---
name: quant-backtesting
description: Design and run reproducible, bias-checked backtests with Indian delivery costs, chronological splits and an untouched holdout. Use for any experiment, parameter study or performance claim.
---

# Quantitative research and backtesting

## Responsibility
Turn a written strategy spec into a reproducible experiment whose result can be trusted or rejected.

## Workflow
1. **Pre-register.** Add a row to `experiments/registry.csv` with hypothesis, data range, split,
   parameter grid and cost model BEFORE running anything.
2. **Data check.** Run the data-validation step; abort with DATA INSUFFICIENT on any failure.
3. **Splits.** Chronological train / validation / holdout. The holdout range is fixed in the spec and
   its date range hash recorded. Never look at holdout results while choosing parameters.
4. **Execution model.** Signal at close t, entry at open t+1; gap through stop fills at the open;
   slippage per side from config; full cost model from `backtesting/costs.py`; cash and overlapping
   positions respected; no fills on circuit-locked days.
5. **Metrics.** Net return, CAGR (only if >= 3 years), max drawdown, expectancy per trade, profit
   factor, win rate, average win / loss, trade count with a bootstrap confidence interval on
   expectancy, exposure, turnover, benchmark-relative return, results by regime.
6. **Robustness.** 2x costs; neighbouring parameter values; sub-period stability; a simple baseline
   (e.g. buy-and-hold benchmark, plain trend filter) on identical data.
7. **Record.** Update the registry row with results and status (accepted / rejected / inconclusive).
   Failed experiments stay in the registry.

## Bias checklist (all must be answered in the report)
- Look-ahead: does any input at t use data after t? (indicator tests must prove not)
- Survivorship: is the universe point-in-time? If not, disclosed?
- Data snooping: how many variants were tried? Report the count.
- Corporate actions: adjusted for signals, unadjusted for fills?

## Verification
- Re-running the experiment from the registry row reproduces the numbers.
- Fewer than 30 trades in a split = inconclusive, regardless of the metrics.
