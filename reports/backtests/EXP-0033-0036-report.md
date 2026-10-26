# Crypto intraday, EXP-0033..0036: report (research only, 2026-10-25)

Spec `docs/strategy-specifications/crypto-intraday.md` v0.1 (committed in 42003de before any run). Runner
`python -m trading_research.backtesting.run_intraday`; outputs `EXP-00xx-<strategy>.json`, `EXP-00xx-trades.csv`
(1× costs) and `intraday-buy-and-hold.json` in this folder. Data: Binance spot 5m BTCUSDT and ETHUSDT,
2018-01-01..2024-12-31 (verified fact: official archive, SHA-256 checked, retrieved 2026-10-25). 2025 onward
was not downloaded.

**Result: all four REJECTED.** None is a holdout candidate.

## Headline numbers (calculated; dev 2018–2022, BTC and ETH pooled)

| | Trades | Mean R 1× | 98.75% interval 1× | After tax 1× | Mean R 2× | 2018–20 2× | 2021–22 2× | 2023–24 2× |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXP-0033 opening-range breakout (5m) | 2,116 | +0.05 | −0.10..+0.19 | −0.20 | −0.17 | −0.11 | −0.25 | −0.45 |
| EXP-0034 9/21 EMA cross (15m) | 3,664 | −0.17 | −0.24..−0.10 | −0.29 | −0.40 | −0.40 | −0.39 | −0.43 |
| EXP-0035 Bollinger + RSI dip (1h) | 65 (< 200) | −0.29 | −0.61..−0.00 | −0.39 | −0.42 | −0.42 | −0.42 | −0.51 |
| EXP-0036 Supertrend flip (1h) | 847 | +0.16 | −0.02..+0.38 | −0.03 | +0.07 | +0.21 | −0.10 | +0.05 |

Illustrative equity (0.5% risk per trade, positions ≤ 50% of equity; not a forecast), dev, 1× costs:

| | Before tax, per year | After 31.2% tax on each winning trade, per year | Max drawdown |
| --- | --- | --- | --- |
| Opening-range breakout | +5.6% | −34.7% | −45% |
| EMA cross | −43.9% | −62.8% | −95% |
| Bollinger + RSI | −2.0% | −2.6% | −10% |
| Supertrend | +13.1% | −3.1% | −19% |
| BTC buy and hold (2018–2022) | +4.0% | | −81% |
| BTC buy and hold (2023–2024) | +138% | | −26% |

## Model interpretation
* **Costs decide intraday.** One round trip costs about 0.30% (fee + GST + slippage). The EMA cross trades
  about 60 times a month, so costs eat about 0.25R per trade; it loses in every period.
* **Indian crypto tax kills frequent trading.** 31.2% of every winning trade is taxed and losses can't be set
  off (assumption from secondary sources). The opening-range breakout is roughly break-even before tax and
  loses about a third of the account per year after tax.
* **Supertrend is the nearest miss**, and it is not really intraday (it holds about two days on average). It
  made money in 2018–2020, lost in 2021–2022, and its interval includes zero. After tax it is negative. It
  looks like the daily trend rules from Phases 13–14 on a faster clock, with the same weakness in choppy years.
* **Win rates are low** (22–36% for three of the four), so the long losing streaks real day-traders describe are what these rules
  produce even when they break even.

## Limitations
5m bars hide the order of moves inside a bar (stops are checked first). Slippage is a flat 3 bps; 2018
liquidity was thinner. One exchange, long only, no funding or shorting. Indicators run across the 1,944
missing 5m bars (exchange outages). Indian INR exchanges charge more than Binance and deduct 1% TDS on sales
(assumption, unverified; a cash-flow cost, not modelled).
