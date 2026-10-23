# Price-action pullback and SMC sweep (long only) — spec v0.1

Status: **specified, not tested** (2026-10-23). Nothing here is evidence of an edge. Code:
`src/trading_research/strategies/pa_smc.py`, runner `src/trading_research/backtesting/run_phase8.py`.
Registry: EXP-0007 (`pa_pullback`), EXP-0008 (`smc_sweep`).

## Purpose
Test whether one price-action idea and one Smart Money Concepts idea add anything, measured the way the
skills require: each against the same entry **without** its PA/SMC component (ablation), and against the
baseline (EXP-0006, rejected) on the same data, costs, engine and splits.

## Hypotheses (label: hypothesis)
- **H7 `pa_pullback`:** in a stock whose confirmed swing structure is up (higher high and higher low),
  a pullback that touches the 20-EMA, holds above the last higher low and then closes above the previous
  bar's high resumes the trend often and far enough for positive expectancy after costs.
- **H8 `smc_sweep`:** a bullish displacement bar shortly after sell-side liquidity below a swing low was
  swept (traded through, closed back above) marks demand stepping in, giving positive expectancy after
  costs, and better than the same displacement bar without a prior sweep.

## Definitions (price-action-structure and smc-concepts skills v0.1; `indicators/structure.py`)
Swings use k = 3 and are known only 3 bars after the swing bar. Displacement uses the previous bar's
ATR(14). A sweep uses the last confirmed swing low as known at the previous bar.

## Rules (all at the close of day t)
| Gate | `pa_pullback` | `smc_sweep` |
| --- | --- | --- |
| 1 Data | gate-1 checks (window 260) and all inputs present | same |
| 2 Regime | NIFTY 50 trend = `up` | same |
| 3 Higher timeframe | stock close > SMA200 | same |
| 4 Setup (event) | low ≤ EMA20, close > last confirmed swing low, close > previous high | bullish displacement: body ≥ 1.5 × ATR(14) of t−1, close in the top 25% of the range |
| 5 PA/SMC component (removed in the ablation) | swing structure = `up` | a sell-side sweep on any of the last 5 sessions incl. t |
| 6 Risk | stop = last confirmed swing low − 0.1 × ATR | stop = lowest low of the last 5 sessions − 0.1 × ATR |
|  | stop below close and at most 10% away; sizer within 0.5% / 2% caps | same |
| 7 Event/liquidity | ₹50 raw price floor, 20-day median traded value ≥ ₹5 crore; **no event screen** | same |
| 9 Final | at most 2 a day, highest 63-day RS vs NIFTY 50 first (ranking only, not a filter) | same |

**Trade management (both, same as baseline v0.2):** entry next open; skip if it opens at or below the
stop; stop fixed, gap fills at the open; exit at the next open after a close below the lowest low of the
previous 10 sessions, or after 40 sessions; a new position only if the 2% cap has room for a full 0.5%.
Costs from `config/settings.yaml` (unverified) plus 10 bps slippage per side, every run also at 2×.

## Splits
Same as the baseline: train 2022-08-15..2024-12-31, validation 2025-01-01..2025-12-31, holdout
2026-01-01..2026-10-22 (sealed). **Disclosure:** 2025 was already used once, to validate the baseline. These
two ideas were not fitted on it, but their author knows breakouts did badly in 2025. That is a mild form
of data snooping and is stated in every report.

## Variants and multiple testing
Two strategies, one fixed parameter set each (variants tried: 2, plus the 2 ablations). Neighbouring
values run on train only as a robustness check, never to pick: `pa_pullback` EMA 10/30 and swing k 2/5;
`smc_sweep` displacement 1.25/2.0 × ATR and sweep window 3/10.

## Acceptance / rejection (decided now, per strategy)
- Fewer than 30 trades in a split → inconclusive for that split.
- Reject if, on validation at 2× costs, expectancy per trade ≤ 0 or profit factor < 1.1.
- Reject if the 95% bootstrap interval of train expectancy (1× costs) includes 0 **and** validation is
  not clearly positive.
- The PA/SMC component is rejected as a concept if the strategy does not beat its own ablation on
  validation at 1× costs (expectancy per trade).
- Holdout: only a strategy that passes all of the above may use it, once. If both pass, the one with the
  higher train expectancy (1× costs) goes; the holdout is then used up for every later strategy.
- Passing makes a strategy eligible for paper trading only. It is not a probability claim.

## Known limitations
Those of the baseline (short history, unverified costs, no circuit-lock detection, no event screen,
ETFs in EQ series not excluded), plus: swing points with k = 3 on daily bars are a coarse reading of
"structure", and SMC labels are hypotheses about order flow inferred from OHLC only.

## Review (gate 8, 2026-10-23)
**Risk manager:** same engine, caps and exits as the baseline; stops sit at defined structural levels,
not fitted to size. Accepted.
**Independent auditor:** look-ahead covered by perturb-and-truncate tests for both strategies
(`tests/test_strategy_pa_smc.py`); swing levels respect the confirmation lag. Objections: (1) the 2025
snooping above; (2) two strategies tested means a pass is weaker evidence than one pre-chosen test;
(3) as before, no event screen. Not vetoes; all must appear in the report.

## Changelog
- **v0.1 (2026-10-23):** initial spec, written before any run. Also vectorised
  `structure.swing_state` (same output, checked against the old loop on random bars; tests unchanged).
  No earlier results affected.
