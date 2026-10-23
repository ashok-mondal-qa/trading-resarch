# EXP-0007 / EXP-0008: price-action pullback and SMC sweep — backtest report

**Verdict: both REJECTED** by the rules in `docs/strategy-specifications/pa-smc.md`. That spec was committed
(11b1a57) before any run. The sealed holdout (2026-01-01..2026-10-22) was **not** run and is still unused.
Neither strategy is eligible for paper trading.

Generated 2026-10-23. Raw outputs are the `EXP-0007-*` and `EXP-0008-*` files beside this report. Every
number is a **calculated value** from NSE CM bhavcopy and NSE daily index files, 2021-10-25..2026-10-22,
retrieved 2026-10-23. Same engine, costs, caps, exits and universe as the baseline (EXP-0006). None of it
is a probability claim.

## Acceptance rules and outcome
| Rule (fixed before any run) | `pa_pullback` (EXP-0007) | `smc_sweep` (EXP-0008) |
| --- | --- | --- |
| ≥ 30 trades per split | train 116; **validation 25 → inconclusive** | train 79; **validation 22 → inconclusive** |
| Validation at 2× costs: expectancy > 0 and PF ≥ 1.1 | +0.12R, PF 1.17 (meets it, on 25 trades) | **−0.00R, PF 0.99 → fails** |
| Train 95% CI excludes 0, or validation clearly positive | CI −0.15..+0.55R; validation CI −0.35..+0.64R → **fails** | CI −0.15..+0.41R; validation flat → **fails** |
| PA/SMC component beats its ablation on validation (1×) | +0.20R vs −0.04R (passes) | **+0.05R vs +0.11R → SMC sweep concept rejected** |
| **Outcome** | **REJECTED: not enough evidence**, not shown to lose | **REJECTED** |

## Results (closed trades; positions open at the split end are marked separately)
| Split, run | Trades | Net return | Max DD | Win rate | Expectancy | 95% CI | PF |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **PA pullback**, train 1× | 116 | +10.2% | −9.1% | 29% | +0.18R | −0.15..+0.55 | 1.30 |
| train 2× costs | 115 | +7.8% | −9.8% | 30% | +0.14R | −0.17..+0.49 | 1.24 |
| train ablation (no structure filter) 1× | 125 | +17.4% | −9.5% | 29% | +0.29R | −0.16..+0.89 | 1.46 |
| validation 1× | 25 | +3.4% | −2.6% | 44% | +0.20R | −0.31..+0.78 | 1.42 |
| validation 2× costs | 25 | +1.8% | −2.6% | 40% | +0.12R | −0.35..+0.64 | 1.17 |
| validation ablation 1× | 25 | +9.2% | −2.6% | 36% | −0.04R | −0.52..+0.54 | 0.86 |
| **SMC sweep**, train 1× | 79 | +6.2% | −6.5% | 35% | +0.13R | −0.15..+0.41 | 1.33 |
| train 2× costs | 79 | +2.6% | −7.4% | 35% | +0.05R | −0.20..+0.32 | 1.12 |
| train ablation (displacement only) 1× | 86 | +13.3% | −5.1% | 41% | +0.31R | +0.01..+0.65 | 1.81 |
| validation 1× | 22 | +0.4% | −3.9% | 23% | +0.05R | −0.58..+0.86 | 1.08 |
| validation 2× costs | 22 | +0.1% | −3.9% | 23% | −0.00R | −0.60..+0.72 | 0.99 |
| validation ablation 1× | 22 | +1.1% | −2.7% | 41% | +0.11R | −0.29..+0.60 | 1.30 |
| Baseline v0.2 (EXP-0006), train / validation 1× | 103 / 30 | −3.5% / +3.9% | | | −0.06R / −0.28R | | 0.86 / 0.56 |

- **Benchmark:** NIFTY 50 price return was +32.6% over the train dates and +10.1% over 2025, far above
  every run here. Note that these strategies are invested only part of the time (at most 4 positions of
  0.5% risk each), so this comparison is about the capital as a whole, not per trade.
- **Both beat the baseline per trade** on train and on validation. The differences are inside wide
  confidence intervals.
- **The PA and SMC filters did not help on train.** Both ablations scored higher than the full
  strategies on train. On validation, the PA structure filter helped and the SMC sweep filter did not. With
  about 25 trades per run, this ordering is not reliable either way.
- Validation sizes are small because the regime gate allowed entries on only 132 of 248 sessions in 2025,
  and the 2% cap was often full (198 / 73 skipped entries).
- Validation net return includes open positions marked at 2025-12-31: +₹9,718 (PA) and −₹1,185 (SMC).

## Robustness (train only, pre-registered; not used to choose anything)
Each line changes one value and keeps the rest. Base on train: PA +0.18R (PF 1.30), SMC +0.13R (PF 1.33).

| Variant | Trades | Expectancy 1× (95% CI) | PF 1× | Net 1× | Expectancy 2× | PF 2× |
| --- | --- | --- | --- | --- | --- | --- |
| PA: EMA 10 | 123 | −0.05R (−0.32..+0.26) | 0.90 | −3.6% | −0.10R | 0.82 |
| PA: EMA 30 | 120 | +0.17R (−0.21..+0.60) | 1.24 | +9.3% | +0.24R | 1.39 |
| PA: swing k 2 | 101 | +0.25R (−0.30..+0.94) | 1.36 | +13.4% | +0.09R | 1.12 |
| PA: swing k 5 | 127 | −0.06R (−0.30..+0.20) | 0.88 | −4.3% | −0.11R | 0.80 |
| SMC: displacement 1.25 × ATR | 88 | +0.23R (−0.07..+0.56) | 1.49 | +11.2% | +0.16R | 1.31 |
| SMC: displacement 2.0 × ATR | 62 | +0.08R (−0.19..+0.38) | 1.20 | +3.3% | +0.00R | 1.01 |
| SMC: sweep window 3 | 76 | +0.12R (−0.17..+0.44) | 1.27 | +4.5% | −0.02R | 0.95 |
| SMC: sweep window 10 | 77 | +0.27R (−0.02..+0.57) | 1.82 | +11.4% | +0.07R | 1.18 |

PA swings from −0.06R to +0.25R on one-step changes, so it is fragile. SMC stays positive at 1× in every
variant, but each one drops sharply at 2× costs. Part of that drop is path dependence: higher costs change
which later signals fit under the cap. Every interval includes zero. Nothing here is used to pick a
setting.

## Auditor objections from the gate-8 review
1. **2025 was already seen** (it validated the baseline). Stated in the spec, and still true.
2. **Two strategies tested** (plus their ablations), so a pass would have been weaker evidence than a
   single pre-chosen test. Moot, since neither passed.
3. **No event screen.** Results-day gaps are inside these returns. Gap stops: PA 2 train / 1 validation,
   SMC 1 train / 2 validation; worst trade −1.15R (gaps can lose more than planned).

**Size buckets** (20-day median traded value as a size proxy, train 1×): PA 45 trades +0.25R (₹5–20
crore/day), 40 trades −0.20R (₹20–100 crore), 31 trades +0.58R (>₹100 crore). SMC 30 trades +0.44R,
34 trades −0.15R, 15 trades +0.15R. No consistent small-cap pattern; all buckets are small.
**Same-day entries:** PA had 25 train days with two entries (13 both lost, 3 both won). SMC had 14
(5 both lost, 3 both won). Paired entries lose together more often than they win together.

## Bias checklist
- Look-ahead: perturb-the-future and truncation tests for both strategies; swing levels lag 3 bars.
- Survivorship: point-in-time universe from each day's bhavcopy (delisted stocks included).
- Data snooping: 2 strategies + 2 ablations + 8 robustness variants on train; 2025 seen before (above).
- Corporate actions: adjusted prices for signals; sizing and costs in raw rupees.
- **ETFs are not excluded** (ISIN prefix INF). PA took 1 ETF trade on train and 2 on validation. SMC took
  6 on train, 4 of them liquid or gold funds whose tiny daily ranges make "displacement" meaningless, and
  1 on validation. Leaving them out after the fact (not a re-run) gives PA +0.17R train / +0.31R validation
  and SMC +0.14R / +0.06R. The verdicts do not change. Excluding ETFs must be a pre-registered change in the
  next version.

## What this means
- No strategy so far has shown an edge strong enough to paper trade. Under CLAUDE.md, zero candidates is
  an acceptable answer.
- **PA pullback** is the least bad: it is positive in both periods at 2× costs. However, its validation
  has 25 trades and a wide interval, and its structure filter did not help on train.
- **Plain displacement** (the SMC ablation) did best on train, and its train interval just excludes zero.
  It was not a pre-registered strategy, so this is a **new hypothesis, not a finding**. Testing it fairly
  needs data neither split has touched: the one-time 2026 holdout, or paper trading forward from now.
- The bottleneck is sample size. About 25 trades a year under a 2% cap cannot separate a small edge from
  noise in a few years of history.
