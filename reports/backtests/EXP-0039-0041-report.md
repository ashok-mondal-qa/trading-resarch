# Factor portfolios, EXP-0039..0041: report (research and paper only, 2026-10-25)

Spec `docs/strategy-specifications/factor-portfolios.md` v0.1 (committed in 2e6396e before any run). Runner
`python -m trading_research.backtesting.run_factors`; outputs `EXP-00xx-<strategy>.json` and dev equity curves
here. Data: NSE EQ adjusted bars and NIFTY 50 index files to 2025-12-31 (verified fact: NSE archive, manifests
in data/manifests). The 2026 holdout was not read.

**Verdict under the pre-registered rules: all three REJECTED.** Low volatility and the momentum + low-volatility
mix passed every check except the strictest one (statistical proof that their Sharpe beats NIFTY's); momentum
alone also failed validation on risk. These two are the best results in this project so far.

## Results at 2× costs (calculated; ₹10 lakh start per split; NIFTY = price index, same costs)
NIFTY row as rerun on 2026-10-26 after the v0.1.1 benchmark fix (validation after tax 12.0% → 12.1%; every other
figure, interval and verdict unchanged at this rounding).

| | Dev 2013–22 CAGR | after tax | Sharpe | Max DD | Validation 2023–25 CAGR | after tax | Sharpe | Max DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NIFTY 50 buy and hold | 12.1% | 11.1% | 0.75 | −38% | 13.1% | 12.1% | 1.25 | −16% |
| EXP-0039 low volatility 30 | 14.8% | 13.4% | 1.09 | −27% | 15.6% | 14.1% | 1.31 | −18% |
| EXP-0040 momentum 30 | 24.9% | 22.4% | 0.99 | −50% | 27.7% | 24.5% | 1.09 | −39% |
| EXP-0041 momentum + low vol 30 | 18.7% | 16.8% | 1.13 | −32% | 20.9% | 18.3% | 1.34 | −24% |

Checks that failed: the 98.33% block-bootstrap interval of the dev Sharpe difference vs NIFTY includes zero
for all three (low vol −0.14..+0.77, momentum −0.27..+0.85, mix −0.06..+0.99); momentum's validation Sharpe
(1.09 < 1.25) and drawdown (−39% vs −16%) also failed. Every other check passed for low vol and the mix,
including both sub-periods at 2× costs and validation, which no portfolio rule had seen.

Calendar years, mix at 1× costs: 2013 +17%, 2014 +65%, 2015 +13%, 2016 +9%, 2017 +29%, 2018 0%, 2019 +13%,
2020 +18%, 2021 +45%, 2022 −1%, 2023 +46%, 2024 +24%, **2025 −0.3% (NIFTY +10%)**.

## Cross-check with real funds (verified prices, calculated returns)
NSE lists ETFs on these themes (bhavcopy 2025-12-31): e.g. ALPL30IETF (alpha low-volatility 30), LOWVOLIETF,
MOM30IETF. Their closes (unit-split days removed) returned in 2024 / 2025: ALPL30IETF +18.0% / −3.9%,
LOWVOLIETF +11.1% / +10.6%, MOM30IETF +18.8% / −5.3%, NIFTYBEES +10.2% / +12.0%. Same direction as the
simulation (factor tilts ahead in 2024, behind NIFTY in 2025). Their index rules differ from ours (not verified).

## Model interpretation
* Holding the right stocks all the time beat every timing rule tested since Phase 7. The gain comes from
  owning calmer or stronger companies, not from predicting the next move.
* Ten years of monthly data cannot prove a Sharpe advantage of this size beyond doubt; the interval is wide.
  That is why the verdict is REJECTED under the rules, even though the direction held out of sample.
* Momentum alone is too bumpy (−50% drawdown in dev); mixing it with low volatility kept most of the return
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
