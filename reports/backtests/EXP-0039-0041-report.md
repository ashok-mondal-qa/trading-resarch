# Factor portfolios, EXP-0039..0041: report (research and paper only, 2026-10-25)

Spec `docs/strategy-specifications/factor-portfolios.md` v0.1 (committed in 2e6396e before any run). Runner
`python -m trading_research.backtesting.run_factors`; outputs `EXP-00xx-<strategy>.json` and dev equity curves
here. Data: NSE EQ adjusted bars and NIFTY 50 index files to 2025-12-31 (verified fact: NSE archive, manifests
in data/manifests). The 2026 holdout was not read.

**Verdict under the pre-registered rules: all three REJECTED** (unchanged after the 2026-10-26 rerun). Low
volatility and the momentum + low-volatility mix passed every check except the strictest one (statistical proof
that their Sharpe beats NIFTY's); momentum alone also failed sub-period and validation checks.

**Correction, 2026-10-26 (spec v0.1.2).** The first run dropped every bar of a stock before its last data error
(any move above 35% without a corporate action, real crashes included), so stocks that later crashed, such as
YESBANK in 2020, were missing from earlier years. That flattered all three portfolios. The figures below are the
rerun with point-in-time handling; the first-run figures are kept at the end of this section for the record.

## Results at 2× costs (calculated; ₹10 lakh start per split; NIFTY = price index, same costs)
| | Dev 2013–22 CAGR | after tax | Sharpe | Max DD | Validation 2023–25 CAGR | after tax | Sharpe | Max DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NIFTY 50 buy and hold | 12.1% | 11.1% | 0.75 | −38% | 13.1% | 12.1% | 1.25 | −16% |
| EXP-0039 low volatility 30 | 13.4% | 12.3% | 0.98 | −29% | 14.6% | 13.2% | 1.25 | −18% |
| EXP-0040 momentum 30 | 16.7% | 15.0% | 0.77 | −56% | 26.5% | 23.0% | 1.07 | −39% |
| EXP-0041 momentum + low vol 30 | 15.1% | 13.8% | 0.95 | −33% | 26.4% | 22.7% | 1.50 | −25% |

Checks that failed: the 98.33% block-bootstrap interval of the dev Sharpe difference vs NIFTY includes zero for
all three (low vol −0.14..+0.53, momentum −0.48..+0.58, mix −0.14..+0.68); momentum also failed 2018–2022
(Sharpe 0.54 vs 0.62) and validation (Sharpe 1.07 vs 1.25, drawdown −39% vs −16%). Low volatility's validation
Sharpe equals NIFTY's (1.25), which passes "not below". Low volatility and the mix had a higher or equal Sharpe
than NIFTY in both sub-periods and in validation, but in 2018–2022 both returned slightly less than NIFTY
(11.2% and 10.7% vs 11.9% a year), with smaller drawdowns.

Calendar years, mix at 1× costs: 2013 +11%, 2014 +50%, 2015 +8%, 2016 +4%, 2017 +37%, 2018 0%, 2019 +10%,
2020 +11%, 2021 +38%, 2022 0%, 2023 +47%, 2024 +25%, 2025 +13% (NIFTY +10%).

First-run figures (v0.1.1, superseded): dev 2× CAGR low vol 14.8%, momentum 24.9%, mix 18.7%; Sharpe 1.09,
0.99, 1.13; validation mix 20.9%, 2025 −0.3%.

## Cross-check with real funds (verified prices, calculated returns)
NSE lists ETFs on these themes (bhavcopy 2025-12-31): e.g. ALPL30IETF (alpha low-volatility 30), LOWVOLIETF,
MOM30IETF. Their closes (unit-split days removed) returned in 2024 / 2025: ALPL30IETF +18.0% / −3.9%,
LOWVOLIETF +11.1% / +10.6%, MOM30IETF +18.8% / −5.3%, NIFTYBEES +10.2% / +12.0%. The ETFs were ahead
of NIFTY in 2024 and mostly behind in 2025. The corrected simulation agrees on 2024 but not on 2025 (mix +13% vs
NIFTY +10%); the first run had matched the ETFs in 2025. Their index rules differ from ours (not verified).

## Model interpretation
* Holding the right stocks all the time beat every timing rule tested since Phase 7. The gain comes from
  owning calmer or stronger companies, not from predicting the next move.
* Ten years of monthly data cannot prove a Sharpe advantage of this size beyond doubt; the interval is wide.
  That is why the verdict is REJECTED under the rules, even though the direction held out of sample.
* Momentum alone is too bumpy (−56% drawdown in dev); mixing it with low volatility kept much of the return
  with a drawdown smaller than NIFTY's in dev.
* An ETF does the rebalancing inside the fund, so the investor pays tax only when selling the ETF; a DIY
  30-stock portfolio pays short-term tax on every rebalance (included above).

## Next step (decided, not a rule change)
Low volatility (EXP-0039) and the mix (EXP-0041) go to forward paper tracking with frozen rules, like the
Phase 15 near misses (`docs/strategy-specifications/forward-tracking.md` v0.2). The 2026 holdout stays sealed.

## Limitations
Price returns without dividends on both sides (NIFTY dividends ≈ 1–1.5% a year, unverified); costs are current
rates (unverified); flat 0.10% slippage; no market impact; universe built from the loaded symbols; validation
2023–2025 was a strong mid-cap market, which may flatter momentum.
