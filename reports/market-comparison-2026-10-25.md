# Indian equities vs crypto, 2018-04-01..2024-12-31 (paper research, 2026-10-25)

**Answer (model interpretation):** no trading strategy tested in either market has earned paper-trading
status (19 experiments rejected, EXP-0006..0026). Over this window the best results came from **holding**,
not trading: NIFTY 50 for steadiness, BTC for raw return with very deep falls. Both of those are investment
choices, not strategies this project can paper trade under its risk policy (no stop). The research found
**no data-backed edge** to recommend.

Every number is a **calculated value** (`python -m trading_research.backtesting.compare_markets`, raw output
`reports/backtests/market-comparison.json`) from NSE CM bhavcopy / NSE index files and Binance's official
archive (manifests in `data/manifests/`). Past results, one 6.75-year window; not a forecast, no probability
claim. Taxes and fee rates are **assumptions from secondary sources, unverified**.

## Results (1× costs; after tax = Indian tax rules below)
| Market | Approach | CAGR | After tax | Volatility | Sharpe (after tax) | Max drawdown | Worst year | Up years |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| India | NIFTY 50 buy and hold (price index) | +13.5% | +12.4% | 18% | 0.80 (0.74) | −38% | +2.7% | 7/7 |
| India | NIFTY 50 200-day timing | +7.2% | +6.6% | 12% | 0.63 (0.58) | −26% | −5.7% | 4/7 |
| India | weekly momentum, capped (EXP-0014 rules) | +5.0% | +4.0% | 5% | 0.99 (0.77) | −9% | −5.2% | 5/7 |
| India | golden cross, capped (EXP-0020) | +4.1% | +4.0% | 5% | 0.91 (0.89) | −7% | −3.0% | 5/7 |
| India | Minervini / Turtle / Supertrend / 44-MA, capped | +1.1..+2.6% | +0.8..+2.3% | 4–7% | 0.21–0.60 | −6..−16% | | |
| Crypto | BTC buy and hold | +47.3% | +40.1% | 66% | 0.92 (0.85) | **−77%** | **−65%** | 5/7 |
| Crypto | BTC 200-day timing | +43.4% | +27.8% | 46% | 1.01 (0.76) | −56% | 0.0% | 5/7 |
| Crypto | top-10 liquid coins, equal weight, weekly | +10.9% | ≥ −53%† | 86% | 0.56 | −87% | −84% | 4/7 |
| Crypto | Minervini, capped (EXP-0021) | +22.1% | +12.7% | 22% | 1.02 (0.64) | −23% | −0.8% | 4/7 |
| Crypto | Turtle 55, capped (EXP-0024) | +11.4% | +7.4% | 14% | 0.85 (0.57) | −24% | 0.0% | 5/7 |
| Crypto | golden cross, capped (EXP-0025) | +7.5% | +3.0% | 25% | 0.41 (0.25) | −49% | −7.9% | 3/7 |
| Crypto | Supertrend / weekly momentum / 44-MA, capped | −1.1..+0.4% | | | | | | |

† Upper bound on tax (every positive coin-week taxed, as if realised); the true figure lies between this and
the pre-tax return. "Capped" = this project's paper rules: 0.5% risk per trade, 2% total, stop ≤ 10%.

## Comparison on the owner's five questions
| | Indian equities | Crypto (Binance spot) |
| --- | --- | --- |
| Profitability | index +13.5%/yr; no active rule beat it | BTC +47%/yr in this window; altcoin basket only +11% |
| Risk | worst fall −38% (2020) | worst fall −77% (BTC), −87% (altcoins); 2018 and 2022 lost 46–84% |
| Fees per side | ≈ 0.22% (STT, stamp, exchange, GST + 10 bps slippage) | ≈ 0.22% (0.10% fee + 18% GST + 10 bps); INR exchanges charge more |
| Tax (assumed) | short term 20.8% on net yearly gains, losses offset and carried; long term 13% above ₹1.25 lakh | 31.2% on every profitable sale, **losses never offset**, 1% TDS; active trading is taxed hardest (BTC timing 43% → 28%) |
| Liquidity | ≈ ₹5 crore/day floor; hundreds of liquid stocks | BTC ≈ 1.3–2.9 billion USDT/day (2021–24); 70–170 pairs above 5M USDT/day, only 8–23 in 2018–20 |
| Consistency | index up in 7 of 7 years; trend rules lose in 2015, 2018–19, 2025 | profits concentrated in 2020–21; top 5 trades = 81–157% of strategy profit |

## Why the trading rules fall short (model interpretation)
1. **The risk caps keep most money in cash.** 0.5% risk per trade with stops 8–10% away means ≈ 5% of capital
   per position and ≈ 20% invested at most. That protects capital but cannot match a fully invested index.
2. **Trend rules work only in strong bull years**, in both markets, and lose the rest. The averages look
   good; the year-by-year record does not.
3. **Crypto's volatility breaks the 10% stop rule** for most setups (Supertrend, momentum), and Indian crypto
   tax (no loss offset) punishes frequent trading.
4. **BTC buy and hold's +47%** is one asset in one window that began after the 2017 bubble and ended near a
   high; picking BTC now is easy with hindsight. A −77% fall and a −65% year are the cost.

## Recommendation (model interpretation; owner's decision)
- **No live or paper trading of any rule tested so far.** Zero candidates is the correct output.
- The only strategies worth more evidence are the near misses: **crypto Minervini (EXP-0021)** and **NSE weekly
  momentum (EXP-0014)**. Neither passed; the next honest test is forward tracking on new data (a shadow log,
  no alerts), not more backtests on used data. The sealed holdouts (NSE 2026, crypto 2025–26) stay unused.
- If the goal is long-term wealth rather than trading, the data favour low-cost index holding; how much (if
  any) to put in crypto is an investment and risk-tolerance decision this research cannot make.

## Limitations
One window (2018-04..2024-12); NIFTY as a price index (dividends of ≈ 1–1.5%/yr excluded, so equities are
understated); one crypto exchange in USDT (INR rate risk, INR exchange premiums, KYC/withdrawal limits not
modelled); unverified fee and tax rates applied to the whole window (current rates, not historical);
surcharge ignored; benchmarks have no stop and are not tradeable under the paper risk policy.
