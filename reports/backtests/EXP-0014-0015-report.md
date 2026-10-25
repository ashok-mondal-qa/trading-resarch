# EXP-0014 / 0015: weekly 12-1 momentum and gap-up drift — backtest report

**Verdict: both REJECTED** by the rules in `docs/strategy-specifications/swing-ideas-2.md`, committed
(943972f, data note a9c6c6f) before any run. The sealed 2026 holdout was **not** run. No strategy is
eligible for paper trading.

Generated 2026-10-25. Raw outputs: the `EXP-0014-*` and `EXP-0015-*` files beside this report. Every
number is a **calculated value** from NSE CM bhavcopy (2011-07-01 on) and NSE daily index files (2012-02-21
on), retrieved 2026-10-23..25, manifests in `data/manifests/`. Same engine, costs and caps as before; cost
rates are **unverified placeholders**. Nothing here is a probability claim.

## Pass/fail (rules fixed before the run; `run_swing_ideas2 --verdict`)
| Rule | momentum_weekly (0014) | gap_drift (0015) |
| --- | --- | --- |
| Early (2013–2015) portfolio ≥ 30 trades; 2×: expectancy > 0, PF ≥ 1.1 | 49 trades, +0.24R, PF 1.32: pass | 39 trades, −0.03R, PF 0.95: **fail** |
| Early standalone ≥ 100 trades | 191: pass | 53: **fail** (inconclusive) |
| Early standalone 1×: Bonferroni (97.5%) interval above 0 | +0.24R (−0.21..+0.83): **fail** | +0.29R (−0.50..+0.89): **fail** |
| Early standalone 2× > 0 | +0.18R: pass | +0.20R: pass |
| Presample standalone 2× > 0 | +0.31R: pass | −0.18R: **fail** |
| Train standalone 2× > 0 | +0.54R: pass | +0.04R: pass |
| Validation (2025) standalone 2× > 0 | −0.22R: **fail** | −0.03R: **fail** |
| **Outcome** | **REJECTED** | **REJECTED** |

## Results (closed trades, 1× costs)
| Strategy, split | Portfolio trades | Portfolio expectancy (PF) | Portfolio net | Standalone trades | Standalone expectancy (95% CI, month-clustered) | NIFTY 50 |
| --- | --- | --- | --- | --- | --- | --- |
| momentum_weekly, early 2013–2015 | 48 | +0.33R (1.45) | +7.2% | 191 | +0.24R (−0.16..+0.75) | +33.5% |
| momentum_weekly, presample 2016..2022-08 | 92 | +0.72R (2.16) | +36.3% | 538 | +0.38R (+0.05..+0.73) | +122% |
| momentum_weekly, train 2022-08..2024 | 38 | +0.75R (1.95) | +19.6% | 487 | +0.62R (−0.03..+1.33) | +32.6% |
| momentum_weekly, validation 2025 | 11 | −0.35R (0.60) | −1.0% | 181 | −0.18R (−0.57..+0.23) | +10.1% |
| gap_drift, early | 39 | +0.04R (1.05) | +0.6% | 53 | +0.29R (−0.40..+0.83) | +33.5% |
| gap_drift, presample | 166 | −0.20R (0.74) | −15.9% | 249 | −0.11R (−0.41..+0.23) | +122% |
| gap_drift, train | 104 | +0.13R (1.15) | +5.8% | 317 | +0.13R (−0.19..+0.54) | +32.6% |
| gap_drift, validation | 31 | −0.11R (0.80) | −2.1% | 75 | +0.05R (−0.67..+0.80) | +10.1% |

By year, standalone 1×: momentum_weekly 2013 +0.19R, 2014 +0.74R, **2015 −0.47R**, 2016 +0.11R,
2017 +0.98R, **2018 −0.57R, 2019 −0.23R**, 2020 +0.96R, 2021 +0.83R, **2025 −0.18R**. gap_drift had only
8–107 signals a year and no consistent sign.

## What the numbers say (model interpretation)
- **Weekly momentum** is the most consistent idea tested so far: positive in the fresh 2013–2015 split, in
  2016–2022 and in 2022–2024, and still positive at 2× costs in each. It is also clearly
  **regime-dependent**: it lost in 2015, 2018–2019 and 2025, years when Indian mid and small caps
  corrected. Because good and bad years cluster, the month-clustered interval for the fresh split
  includes zero, and 2025 is negative. By the rules, that is a rejection. It is not shown to lose money
  over the whole record; it is shown not to be reliable enough.
- **Gap drift** produced too few signals in 2013–2015 (53) and lost in 2016–2022. Rejected.
- Weekly momentum's presample interval (+0.05..+0.73R) excludes zero, but that split was already used
  for monthly momentum (EXP-0013), which suggested this design. It is not independent evidence.

## Bias checklist
- **Look-ahead:** perturb-the-future and truncation tests for both feature sets; weekly momentum reuses
  the tested monthly feature definition; bars only to each split end; adjustment errors only if dated
  by then.
- **Survivorship:** point-in-time universe from each day's bhavcopy (delisted names included). Early
  split: 994 stocks loaded, 68 too short, 25 funds and 151 superseded old tickers excluded.
- **Data snooping:** 2 strategies, 1 parameter set each (Bonferroni). EXP-0014 was suggested by EXP-0013.
  Across Phases 6–12, 11 strategy definitions have now been tested; 2025 has been seen six times.
- **Missing data:** NSE's archive has no index file for 11 sessions in 2013-10..2016-01 (404); no entries
  on those days.
- **Costs:** placeholder rates applied back to 2013; no circuit-lock detection; no event screen
  (gap_drift trades are often results days; worst trades −2.6R, so gaps can lose more than planned).

## Holdout
Not run. Nothing passed. It stays sealed.

## Where this leaves the research (model interpretation)
The development data (2013–2025) has now been used for 11 strategy definitions. Another idea tested on
it would mostly measure luck. Two honest ways to get new evidence remain:
1. **Forward paper tracking:** record weekly momentum's signals each week from now on, as a shadow
   journal (no status change, no alerts as candidates), and judge it later on data nobody has seen.
2. **The 2026 holdout:** the rules reserve it for a strategy that passes; none has.
