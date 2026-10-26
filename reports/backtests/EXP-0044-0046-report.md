# Crypto factor portfolios, EXP-0044..0046: report (research and paper only, 2026-10-26)

Spec `docs/strategy-specifications/crypto-factor-portfolios.md` v0.1 (committed in b66ac0e before any run).
Runner `python -m trading_research.backtesting.run_crypto_factors`; outputs `EXP-00xx-crypto-<strategy>.json`,
dev equity curves and dev lots here. Data: Binance archive daily USDT pairs to 2024-12-31 (verified fact:
data.binance.vision, SHA-256 checked at load, Phase 14), 436 instruments after splitting at missing days. The
crypto holdout (2025-01..2026-09) was not read.

**Verdict under the pre-registered rules: all three REJECTED.** The NSE stock-picking signals do not carry over
to coins well enough to beat simply holding BTC. Low volatility came closest in dev but lost to BTC in 2024;
momentum lost 92% in 2022.

## Results at 2× costs (calculated; percentages; BTC bought at the first open with the same costs and held)
| | Dev 2020-07..2023 CAGR | after tax | Sharpe | Max DD | Validation 2024 return | after tax | Sharpe | Max DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTC buy and hold | 54% | 43% | 0.89 | −77% | 111% | 76% | 1.65 | −26% |
| EXP-0044 low volatility 10 | 75% | 45% | 0.98 | −77% | 117% | 72% | 1.29 | −38% |
| EXP-0045 momentum 10 | 30% | 4% | 0.64 | −94% | −2% | −21% | 0.58 | −60% |
| EXP-0046 momentum + low vol 10 | 59% | 33% | 0.82 | −79% | 40% | 14% | 0.96 | −48% |

Checks that failed:
* **Low volatility (EXP-0044):** passed the dev Sharpe and after-tax CAGR checks and both dev sub-periods,
  but the dev interval of the Sharpe difference is −0.59..+0.76 (includes zero), and in 2024 its Sharpe (1.29
  vs 1.65) and drawdown (−38% vs −26%) lost to BTC.
* **Momentum (EXP-0045):** failed everything except 2020-07..2021 (+479% in 2021, then −92% in 2022).
* **Mix (EXP-0046):** below BTC in dev Sharpe and after-tax CAGR, in 2022–2023 and in 2024.

Calendar returns at 1× costs (2020 is July–December only):
| | 2020 H2 | 2021 | 2022 | 2023 | 2024 |
| --- | --- | --- | --- | --- | --- |
| BTC | +213% | +58% | −65% | +154% | +112% |
| Low volatility | +158% | +224% | −48% | +66% | +119% |
| Momentum | +87% | +479% | −92% | +173% | 0% |
| Mix | +159% | +250% | −67% | +69% | +41% |

## What this says (model interpretation)
* **Crypto factor returns are dominated by the market itself.** In 2022 everything fell 50–90%; owning
  "calmer" coins lost a bit less than BTC but still lost half. There is no low-risk corner of this market.
* **Tax hurts rotation hard.** Each profitable sale pays 31.2% with no loss set-off. Low volatility's 75% dev
  CAGR fell to 45% after tax, while BTC held fell only from 54% to 43% because it paid tax once at the end.
  Momentum paid tax on its 2021 winners and then lost 92% with no relief.
* **The NSE result did not replicate.** On NSE the same rules beat NIFTY in every period, including the unseen
  2023–2025. On coins they beat BTC only in some periods and lost the unseen 2024. This weakens the idea that
  these are universal effects, but says nothing new about NSE: the two NSE paper portfolios (EXP-0042/0043)
  keep running as planned.
* **Crypto vs Indian equities, best approach found in each (2× costs, after tax, dev):** NSE momentum + low
  volatility 16.8% a year with a −32% worst fall; BTC held 43% a year with a −77% worst fall. Neither has
  passed. BTC's higher return came with drops most people cannot sit through.

## Limitations
42 months of dev and one year of validation cover a single crypto cycle; prices in USDT, so rupee moves are
ignored; one exchange; flat slippage; quote volumes include some wash trading; a delisted coin is sold at its
last close five days after its last bar.
