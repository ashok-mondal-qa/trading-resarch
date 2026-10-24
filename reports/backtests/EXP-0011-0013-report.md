# EXP-0011 / 0012 / 0013: displacement, short-term reversal, 12-1 momentum — backtest report

**Verdict: all three REJECTED** by the rules in `docs/strategy-specifications/swing-ideas.md`, which was
committed (adfc773, clarification 6302413) before any run. The sealed 2026 holdout was **not** run and is
still unused. No strategy is eligible for paper trading.

Generated 2026-10-24. Raw outputs: the `EXP-0011-*`, `EXP-0012-*`, `EXP-0013-*` files beside this report.
Every number is a **calculated value** from NSE CM bhavcopy and NSE daily index files, 2015-01-01..
2025-12-31 used (retrieved 2026-10-23/24; manifests in `data/manifests/`). Same engine, cost model and caps
as EXP-0006..0008. Cost rates are **unverified placeholders**. Nothing here is a probability claim.

## Pass/fail (rules fixed before the run; `run_swing_ideas --verdict`)
| Rule | displacement (0011) | st_reversal (0012) | momentum_12_1 (0013) |
| --- | --- | --- | --- |
| Presample portfolio ≥ 30 trades; 2×: expectancy > 0, PF ≥ 1.1 | 164 trades, +0.07R, PF 1.12: pass | 1,095 trades, −0.05R, PF 0.68: **fail** | 48 trades, +1.10R, PF 2.80: pass |
| Presample standalone: ≥ 100 trades; 1× Bonferroni (98.3%) interval above 0 | 1,529 trades, +0.03R (−0.11..+0.18): **fail** | 7,095, −0.02R (−0.07..+0.02): **fail** | 343, +0.36R (−0.15..+0.95): **fail** |
| Presample standalone 2× expectancy > 0 | −0.02R: **fail** | −0.07R: **fail** | +0.29R: pass |
| Train standalone 2× > 0 | +0.09R: pass | −0.06R: **fail** | +0.74R: pass |
| Validation (2025) standalone 2× > 0 | −0.31R: **fail** | −0.07R: **fail** | −0.46R: **fail** |
| **Outcome** | **REJECTED** | **REJECTED** | **REJECTED** |

"Standalone" = every signal that passed the gates and the up-market filter, each traded alone by the same
engine (one open trade per stock at a time). Intervals resample whole entry months, because trades
entered in the same month share market moves.

## Results (closed trades, 1× costs unless marked)
| Strategy, split | Portfolio trades | Portfolio expectancy (PF) | Portfolio net | Standalone trades | Standalone expectancy (95% CI, month-clustered) | NIFTY 50 |
| --- | --- | --- | --- | --- | --- | --- |
| displacement, presample 2016-01..2022-08 | 160 | +0.15R (1.30) | +12.0% | 1,529 | +0.03R (−0.09..+0.16) | +122% |
| displacement, train 2022-08..2024 | 92 | +0.19R (1.38) | +8.2% | 1,662 | +0.16R (−0.05..+0.36) | +32.6% |
| displacement, validation 2025 | 23 | +0.17R (1.47) | +2.1% | 362 | −0.27R (−0.50..−0.02) | +10.1% |
| st_reversal, presample | 1,096 | +0.00R (1.00) | −0.5% | 7,095 | −0.02R (−0.06..+0.01) | +122% |
| st_reversal, train | 499 | −0.01R (0.92) | −3.1% | 6,850 | −0.01R (−0.06..+0.04) | +32.6% |
| st_reversal, validation | 131 | +0.01R (1.03) | +0.2% | 1,784 | −0.01R (−0.07..+0.06) | +10.1% |
| momentum_12_1, presample | 48 | +1.21R (2.98) | +31.2% | 343 | +0.36R (−0.06..+0.83) | +122% |
| momentum_12_1, train | 26 | +1.10R (2.66) | +14.0% | 291 | +0.83R (−0.15..+1.79) | +32.6% |
| momentum_12_1, validation | 8 | −0.43R (0.64) | −0.2% | 91 | −0.44R (−0.86..+0.13) | +10.1% |

At 2× costs (portfolio / standalone, presample): displacement +0.07R / −0.02R; st_reversal −0.05R / −0.07R
(net −25.3%); momentum +1.10R / +0.29R.

## What the numbers say (model interpretation)
- **Displacement (the Phase 8 lead):** on 1,529 never-before-tested presample signals it earned +0.03R
  before stress and −0.02R at 2× costs. Three of six years were negative (2016 −0.09R, 2018 −0.34R,
  2019 −0.27R). The +0.15R portfolio figure came from which few signals the cap let
  through, not from the signal. The earlier train result does not hold up on fresh data. **No edge shown.**
- **Short-term reversal:** about +0.03R before costs, wiped out by costs (4–5 session holds, ~0.05R of
  costs per trade at 1×). Consistent across all three periods. **Clearly rejected.**
- **12-1 momentum:** the strongest of everything tested so far. Positive in presample and train at 2×
  costs, but the result depends on a few months (2017, 2020, 2021 strong; 2018, 2019 negative), so the
  month-clustered interval includes zero, and 2025 was negative (91 signals, −0.44R). Only about 50
  entry months exist in 6.6 years. **Not enough evidence; rejected by the rules.** It is the only idea
  here that could deserve a different, pre-registered follow-up (see below), not a re-tune.
- The 2% cap and 2-a-day ceiling keep every strategy far below NIFTY 50's return (exposure is small by
  design). Per-trade numbers, not capital growth, are the evidence here.

## Bias checklist
- **Look-ahead:** perturb-the-future and truncation tests for all three feature sets and for the momentum
  rank (`tests/test_strategy_swing_ideas.py`). Each run loads bars only to its split end. The adjuster's
  "usable" flag looked at errors in the whole file, so a stock with a 2025 error lost its 2016–2022 bars;
  fixed before the run (spec clarification) so only errors known by the split end count.
- **Survivorship:** point-in-time universe from each day's bhavcopy; delisted stocks included. Presample
  universe: 1,257 stocks loaded, 169 with < 200 usable bars, 44 ETFs/funds excluded, 129 old tickers
  already joined into a renamed successor excluded (earlier runs counted some companies twice).
- **Data snooping:** 3 strategies, 1 parameter set each, no variants (handled by the Bonferroni interval).
  Displacement came from earlier results, so only its presample counts. 2025 has now been seen 5 times.
- **Corporate actions:** split/bonus-adjusted prices for signals; raw rupees for sizing and costs.
  537 of 2,125 stocks have at least one unexplained jump or unadjusted event (demerger, rights), handled
  by cutting history at the error.
- **Costs:** placeholders applied unchanged back to 2016 (stamp duty was state-wise before July 2020).
  No circuit-lock detection; no event screen (results-day gaps are inside these returns; worst trades
  −1.5R to −2.5R, so gaps can lose more than planned).

## Holdout
Not run. Nothing passed, so nothing qualifies for it. It stays sealed for one future strategy.

## Possible next step (hypothesis, not a finding)
Momentum's weakness here is statistical power: one entry day a month gives ~50 independent months in
6.6 years. A fair follow-up would be a separately pre-registered momentum design (for example a weekly
rebalance, or a longer history from 2010) judged by the same rules, without changing the 12-1 rules
above after seeing these results.
