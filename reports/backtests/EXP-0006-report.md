# EXP-0006: baseline trend-breakout v0.2 — backtest report

**Verdict: REJECTED** by the rules fixed in the spec before any run. The sealed holdout (2026-01-01..
2026-10-22) was **not** run and stays unused. Paper trading of this strategy is not justified.

Generated 2026-10-23. Spec: `docs/strategy-specifications/baseline-trend-breakout.md` (v0.2). Raw outputs:
`EXP-0006-train.json`, `EXP-0006-validation.json`, `EXP-0006-train-robustness.json` and the `-trades.csv`
files beside this report. Every number below is a **calculated value** from those files (source: NSE CM
bhavcopy and NSE daily index files, 2021-10-25..2026-10-22, retrieved 2026-10-23; manifests under
`data/manifests/`). None of it is a probability claim.

## Acceptance rules and outcome
| Rule (spec, decided before any run) | Result | Outcome |
| --- | --- | --- |
| Validation at 2× costs: expectancy per trade > 0 and profit factor ≥ 1.1 | −0.31R, PF 0.52 (30 trades) | **fails** |
| Train 95% bootstrap CI of expectancy (1× costs) excludes 0, or validation clearly positive | CI −0.34R..+0.26R; validation negative | **fails** |
| At least 30 trades per split | train 103, validation 30 | met (validation only just) |

## Results (closed trades; positions still open at the end are marked separately)
| Split, run | Trades | Net return | Max DD | Win rate | Expectancy | 95% CI | PF |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Train 2022-08-15..2024-12-31, 1× | 103 | −3.5% | −8.8% | 30% | −0.06R | −0.34..+0.26R | 0.86 |
| Train, 2× costs | 86 | −0.03% | −5.8% | 31% | +0.00R | −0.28..+0.30R | 0.98 |
| Train, no volume/RS filters | 101 | −4.4% | −10.9% | 31% | −0.10R | −0.37..+0.20R | 0.81 |
| Validation 2025, 1× | 30 | +3.9% | −3.9% | 30% | −0.28R | −0.67..+0.17R | 0.56 |
| Validation, 2× costs | 30 | +2.8% | −4.2% | 30% | −0.31R | −0.68..+0.11R | 0.52 |
| Validation, no volume/RS filters | 33 | −0.3% | −7.2% | 24% | −0.29R | −0.68..+0.17R | 0.57 |

- **Benchmark:** NIFTY 50 price return was +32.6% over the train dates and +10.1% over 2025.
- **Validation net return is positive only because of 4 open positions marked at the 2025-12-31 close**
  (+₹80,093 unrealised, two of them silver ETFs). Closed trades lost ₹41,898. The verdict uses closed trades.
- The 2× cost run on train scores slightly better than 1×. That is path dependence, not a cost benefit:
  higher costs change which later signals find room under the 2% cap, so the two runs hold different trades.
- Exits, train 1×: 49 stop, 39 exit signal, 15 time stop. Validation 1×: 11 stop, 4 gap through the stop
  (worst −1.51R, so **gaps lost more than the planned risk**), 12 exit signal, 3 time stop.
- The cap was the binding constraint: 719 train and 188 validation entries were skipped for lack of room
  under the 2% aggregate risk cap. Which signals got taken therefore depends on order and timing.
- The volume and RS filters do slightly better than no filters on train (−0.06R vs −0.10R), but the
  difference is well inside the confidence intervals.

## Robustness (train only, pre-registered neighbouring values; not used to choose anything)
Each line changes one value from v0.2 and keeps the rest. Base v0.2 on train: 103 trades, −0.06R, PF 0.86.

| Variant | Trades | Expectancy 1× (95% CI) | PF 1× | Net 1× | Expectancy 2× | PF 2× |
| --- | --- | --- | --- | --- | --- | --- |
| breakout 15 | 103 | −0.02R (−0.33..+0.35) | 0.94 | +2.3% | −0.17R | 0.69 |
| breakout 30 | 104 | −0.10R (−0.38..+0.21) | 0.81 | −5.1% | −0.15R | 0.72 |
| stop 1.5 × ATR | 114 | −0.07R (−0.37..+0.29) | 0.87 | −0.7% | −0.14R | 0.76 |
| stop 2.5 × ATR | 77 | +0.21R (−0.10..+0.55) | 1.45 | +10.2% | +0.21R | 1.49 |
| volume 1.25× | 96 | +0.18R (−0.16..+0.57) | 1.32 | +7.9% | +0.05R | 1.08 |
| volume 2.0× | 101 | +0.18R (−0.14..+0.54) | 1.33 | +8.9% | +0.30R | 1.60 |

Read this as **fragility, not as a better setting**. Small changes swing train expectancy from −0.10R
to +0.21R, every confidence interval includes zero, and volume 1.25× and 2.0× (on opposite sides of the
1.5× base) both beat it, which points to noise in which signals found room under the cap. Picking the best
line here would be fitting noise. Any new version built from these numbers would also lack a clean
validation set, because 2025 has now been seen; it would need the one-time holdout or data after
2026-10-22.

## Auditor objections from the gate-8 review
1. **RS vs NIFTY 50 favours small caps.** Market caps are not in our data, so trades are bucketed by 20-day
   median traded value at the signal (a size proxy). Train 1×: 5–20 crore/day 34 trades −0.05R; 20–100
   crore/day 43 trades −0.04R; >100 crore/day 26 trades −0.12R. Validation: 9 trades +0.41R; 14 trades
   −0.81R; 7 trades −0.10R. Buckets are small and their CIs are wide. No bucket shows a reliable edge.
2. **Five years and a short holdout.** Confirmed as a limit: the regime gate allowed entries on 457 of 586
   train sessions and 132 of 248 validation sessions; there were few down-trend periods to learn from.
3. **No event screen.** Results-day gaps are inside these returns. Not fixed in this version.

**Same-day entries (risk manager's concern):** train had 17 days with two entries; on 9 of them both lost
and on 1 both won (correlation of their R multiples −0.01, a weak estimate from 17 pairs). Validation had
7 such days (2 both lost, 1 both won), too few to estimate a correlation.

## Bias checklist
- Look-ahead: signals use bars up to the signal close (no-lookahead tests); entries at the next open;
  each split loads no bars after its end date.
- Survivorship: the universe is every EQ symbol in each day's bhavcopy, so later-delisted stocks are in.
- Pre-filter: only the 1,892 symbols that met the ₹5 crore / ₹50 rule on at least one day were adjusted.
  Signals need that same rule on the signal date, so the filter changes no trade.
- Adjustment selection: `valid_from` is set using errors found anywhere in the 5 years, so a few
  symbols' early bars were dropped using later knowledge (mild; disclosed in Phase 4).
- Data gaps: 2 symbols lacked corporate-action data and were excluded; 309 (train) symbols had too few
  usable bars or no bars before the split end.
- Tuning: v0.1 → v0.2 fixed position sizing after the first train run. No strategy parameter was changed,
  validation was run once, and the holdout was never touched.

## Limitations (as in the spec)
Cost rates are unverified. Circuit-locked days are not detected, so some fills may be optimistic. The
volatility-regime split is "unknown" for all of train because its 756-session window needs more history
than train has. **ETFs are not excluded:** EQ series includes ETFs (ISIN prefix INF, 89 in the universe);
validation took 3 ETF trades (GOLDIETF, SILVERAG, SBISILVER). Excluding them is a candidate change for a
next version and must be decided on train only.

## What this means
The simplest trend-breakout rule, with realistic costs and a strict risk cap, did not show positive
expectancy on 2022–2025 NSE data and did not beat holding NIFTY 50. This is the reference any price-action
or SMC strategy in Phase 8 must beat on the same data, costs and splits.
