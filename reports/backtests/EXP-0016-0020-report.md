# EXP-0016..0020: popular social-media strategies (Minervini, Supertrend, 44-MA, Turtle 55, golden cross)

**Verdict: all five REJECTED** by the rules in `docs/strategy-specifications/social-strategies.md`, committed
(2891330) before any run. The sealed 2026 holdout was **not** run. No strategy is eligible for paper trading.

Generated 2026-10-25. Raw outputs: the `EXP-0016-*` .. `EXP-0020-*` files beside this report. Every number
is a **calculated value** from NSE CM bhavcopy (2011-07-01 on) and NSE daily index files (2012-02-21 on),
retrieved 2026-10-23..25, manifests in `data/manifests/`. Same engine, costs and caps as Phases 11–12, plus
profit targets for `ma44`; cost rates are **unverified placeholders**. Nothing here is a probability claim.
Reproduce: `python -m trading_research.backtesting.run_social --split dev` (and early, presample, train,
validation), then `--verdict`.

## Pass/fail (rules fixed before the run)
| Rule | minervini | supertrend | ma44 | turtle55 | golden_cross |
| --- | --- | --- | --- | --- | --- |
| Dev portfolio ≥ 30 trades; 2×: expectancy > 0, PF ≥ 1.1 | pass | pass | **fail** | pass | pass |
| Dev standalone ≥ 300 trades | pass | pass | pass | pass | pass |
| Dev standalone 1×: 99.7% interval (Bonferroni 16) above 0 | **fail** (−0.03..+0.51) | **fail** | **fail** | **fail** (−0.02..+0.60) | pass (+0.07..+1.93) |
| Dev standalone 2× > 0 | pass | pass | **fail** | pass | pass |
| Early / presample / train standalone 2× > 0 | pass | **fail** early | **fail** | pass | pass |
| Validation (2025) standalone 2× > 0 | **fail** | **fail** | **fail** | **fail** | **fail** (−0.89R) |
| **Outcome** | **REJECTED** | **REJECTED** | **REJECTED** | **REJECTED** | **REJECTED** |

## Results, whole development period 2013-01-01..2025-12-31 (1× costs unless marked)
| Strategy | Portfolio trades | Portfolio expectancy (PF) | Portfolio CAGR | Max drawdown | Sharpe (rf 0) | Standalone trades | Standalone expectancy (99.7% CI) | Standalone 2× |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| minervini (0016) | 291 | +0.44R (1.53) | +4.8% | −18.9% | 0.73 | 4,432 | +0.23R (−0.03..+0.51) | +0.17R |
| supertrend (0017) | 219 | +0.12R (1.25) | +1.2% | −8.3% | 0.36 | 2,631 | +0.11R (−0.09..+0.35) | +0.06R |
| ma44 (0018) | 1,189 | −0.03R (0.91) | −1.6% | −27.5% | −0.26 | 5,465 | −0.03R (−0.11..+0.06) | −0.11R |
| turtle55 (0019) | 231 | +0.31R (1.35) | +2.8% | −15.7% | 0.48 | 9,410 | +0.27R (−0.02..+0.60) | +0.19R |
| golden_cross (0020) | 98 | +0.88R (2.23) | +3.3% | −7.2% | 0.74 | 2,311 | +0.89R (+0.07..+1.93) | +0.80R |
| **NIFTY 50 buy and hold** | | | **+12.4%** | | **0.80** | | | |

Standalone expectancy by entry year (1×, closed trades):

| Year | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| minervini | −0.06 | +0.69 | −0.41 | −0.11 | +0.76 | −0.37 | −0.21 | +0.81 | +0.29 | −0.28 | +0.98 | −0.12 | −0.20 |
| supertrend | −0.22 | +0.49 | −0.38 | +0.21 | −0.01 | −0.27 | −0.23 | +0.40 | +0.37 | −0.22 | +0.65 | +0.02 | −0.33 |
| turtle55 | −0.09 | +1.15 | −0.59 | +0.21 | +0.40 | −0.69 | −0.43 | +0.75 | +0.27 | −0.22 | +1.16 | +0.09 | −0.27 |
| golden_cross | +0.59 | +2.09 | −0.24 | +0.86 | +0.41 | −0.67 | −0.69 | +2.68 | −0.10 | +0.88 | +3.25 | −0.20 | −0.89 |

Sub-periods, standalone 1× (2× in brackets): minervini early +0.23R (+0.17), presample +0.31R (+0.25), train
+0.17R (+0.12), validation −0.21R (−0.24); supertrend −0.00R (−0.05), +0.11R, +0.23R, −0.33R; ma44 negative in
all four; turtle55 +0.27R, +0.23R, +0.38R, −0.27R (−0.31); golden_cross +1.01R, +0.84R, +1.48R, −0.89R.

## Censoring check (found during review, does not change any verdict)
The pre-registered metrics count **closed** trades only. Trades still open at a split's end are marked to
market in the equity curve but left out of expectancy. For long holds (golden cross up to 252 sessions)
in a one-year split this favours losers (stops close fast, winners stay open): 2025 golden cross closed
trades −0.89R (334), but all 512 including the 178 still open: −0.04R. Including open trades, 2025 is
still negative for every strategy except minervini (+0.06R at 1×, which still fails the Bonferroni rule),
so **every verdict stands**. Later specs should count marked-open trades, or report both.

## What the numbers say (model interpretation)
- **None of the five beat simply holding the NIFTY 50.** Over 2013–2025 the index returned 12.4% a year
  with a Sharpe of 0.80; the best portfolio (minervini) made 4.8% a year with a Sharpe of 0.73. Part of
  the gap is by design: 0.5% risk per trade and a 2% cap keep only about a fifth of the capital invested.
  But even per unit of risk, none was better than the index.
- **The trend-following ideas (minervini, turtle55, golden_cross, supertrend) behave alike**: strong in
  2014, 2017, 2020 and 2023, losing in 2015, 2018–2019, 2022 (some), 2024 (some) and 2025, when mid and
  small caps corrected. Gains come from a few big bull years. This is the same pattern as weekly momentum
  (EXP-0014): a real tendency in rising markets, not a reliable edge.
- **Golden cross** is the only one whose dev interval excludes zero after the 16-way correction, but it is
  slow (≈ 100 portfolio trades in 13 years), lost in 6 of 13 entry years, and is negative in 2025 under
  both measurements.
- **The 44-MA setup**, very popular on Indian YouTube and Instagram, loses after costs in every period.
  About half of its trades win, but costs eat the small average gain.
- **Supertrend(10, 3)** is roughly break-even after costs over 13 years.

## Bias checklist
- **Look-ahead:** perturb-the-future and truncation tests for all five feature sets; the RS rank is
  cross-sectional at t only; engine target tests; bars only to each split end.
- **Survivorship:** point-in-time universe (delisted names included); funds and superseded tickers out.
- **Data snooping:** 16 definitions have now used 2013–2025; the Bonferroni correction covers them. 2025
  has now been seen 11 times.
- **Overlap:** minervini overlaps the rejected baseline breakout (EXP-0006).
- **Costs:** placeholder rates back to 2013; no circuit-lock detection; no event screen; gaps can lose
  more than planned (worst stop-gap trades below −2R).
- **Path dependence:** turtle55's portfolio at 2× costs did better than at 1× (+0.72R vs +0.31R) because
  a different set of trades fit under the caps; the standalone figures, which do not depend on that, are
  the evidence.

## Holdout
Not run. Nothing passed. It stays sealed.

## Next (decided, model interpretation)
The Indian equity research now has a clear, data-backed baseline answer: for this account size and risk
policy, **no tested trading rule beat buying and holding the index**. The next step is the crypto
comparison (Binance daily data, India tax and fees), judged by the same rules, with its own sealed period.
