# Multibagger hunt: what 22 years of data say, and a research watchlist (2026-11-01)

Research only. No orders, no signals. Nothing here is a TRADE CANDIDATE; the watchlist is a set of
**hypotheses** to track. Experiments EXP-0052 (NSE) and EXP-0053 (crypto) in `experiments/registry.csv`.

## The short answer (model interpretation)

1. **10x stocks are rare and mostly found with hindsight.** Of every NSE stock alive at the start of a year, 2–3%
   were worth 10x five years later. About 1 in 4 lost half or more and 1 in 8 stopped trading.
2. **No screen we could test reliably raises the odds.** The screens that raise the 10x rate (penny price, least
   traded, most beaten-down, most volatile) raise the chance of a wipe-out by as much or more. That is a lottery,
   not an edge.
3. **When you buy matters more than what you buy.** The 5-year 10x rate was 0.1% for stocks bought in Jan 2008
   and 9.2% for stocks bought in Jan 2020. Nobody knew in advance which kind of year it was.
4. **Crypto is worse for coin-picking.** Only 14% of Binance altcoins beat simply holding Bitcoin over 3 or 5
   years; the median altcoin lost half its value over 3 years, and 1 in 5 was delisted.
5. **Fundamental "hidden signals"** (promoter buying, earnings acceleration, institutional coverage) could not be
   tested: **DATA INSUFFICIENT** in this session (see Limitations). No claim is made about them.

## Evidence: NSE stocks (calculated, EXP-0052)

Source: NSE CM bhavcopy, 5,641 sessions 2004-01-01..2026-10-30, split/bonus adjusted with NSE's own adjusted
previous close; renames joined with NSE's symbol-change list. Cohorts start each January; "dev" = starts 2006–14,
"check" = starts 2015–21 (5y) / 2015–23 (3y). 47,431 stock-windows; 4,165 (9%) dropped for a one-day move above
3x or below 1/3 (unadjusted corporate actions or relistings). Raw output:
`reports/backtests/EXP-0052-multibagger-base-rates.json`.

5-year results (dev / check):

| Screen at purchase | 10x | 5x | Ever 10x at peak | Lost ≥ half | Stopped trading |
| --- | --- | --- | --- | --- | --- |
| All stocks | 2.1% / 3.0% | 7.9% / 9.6% | 4.0% / 5.8% | 27% / 21% | 12% / 13% |
| Penny (< ₹10) | 3.2% / 6.1% | 10.0% / 13.7% | 7.5% / 13.3% | 35% / 31% | **32% / 43%** |
| Least traded 20% | 3.7% / 5.2% | 10.3% / 11.9% | 7.1% / 10.0% | 24% / 23% | 21% / 28% |
| > 60% below 52-week high | 2.0% / 7.3% | 6.9% / 16.3% | 3.6% / 12.7% | 32% / 28% | 16% / 35% |
| Top 20% momentum | 2.2% / 2.2% | 8.9% / 8.3% | 4.0% / 4.8% | 25% / 19% | 9% / 9% |
| Small + uptrend + calm (watchlist rule) | 2.5% / **0.9%** | 13.0% / **8.4%** | 4.7% / 2.8% | 16% / 15% | 9% / 5% |
| Lowest volatility 20% | 1.2% / 0.6% | 6.8% / 5.7% | 2.4% / 1.7% | 15% / 12% | 7% / 5% |

- Median outcome for a penny stock over 5 years, counting stocks that stopped trading as zero: **0.4x**.
- The real 2020–25 multibaggers (e.g. TARIL 176x, Lloyds Engineering 155x, CG Power 66x, Suzlon 32x) were
  mostly cheap, ignored and **falling** in Jan 2020. The same profile in Jan 2008–2011 mostly lost money.
- 3-year horizon: base 10x rate 0.6% / 1.2%.

## Evidence: crypto (calculated, EXP-0053)

Source: Binance spot USDT pairs, data.binance.vision (delisted pairs included), cohorts Jan 2018–2023, prices to
2026-09-30. Five token swaps corrected (COCOS, DREP, QUICK, SUN, BNX); LUNA counted as a total loss. Raw output:
`reports/backtests/EXP-0053-crypto-multibagger-base-rates.json`.

| Horizon | Coin-windows | 10x | Beat BTC | Lost ≥ 80% | Delisted | Median |
| --- | --- | --- | --- | --- | --- | --- |
| 3 years | 897 | 3.1% | 14% | 21% | 21% | 0.50x |
| 5 years (2018–21 starts) | 286 | 11.5% | 14% | 20% | 29% | 0.90x |
| 3 years, bought Jan 2022 | 299 | 0.3% | 2% | 37% | 23% | 0.27x |
| 3 years, bought Jan 2023 | 314 | 1.0% | 2% (BTC did 5.4x) | 22% | 28% | 0.43x |

The highest-volume 20% of coins did best over 5 years (10x 22%, median 1.6x, n=58), but that is mostly the 2020
cohort before one bull run. New listings and 6-month trend gave no consistent edge.

## Research watchlist: Indian small caps (hypotheses, not trade candidates)

**Rule, fixed before looking at names:** NSE EQ series, market cap ₹300–5,000 cr, liquidity in the 2nd–3rd
fifth of all stocks and ≥ ₹1 cr/day median traded value, 12-1 momentum in the top 40%, within 25% of the
52-week high, volatility below the median, no suspicious one-day jump in the last year. 47 stocks passed; ranked
by momentum rank + low-volatility rank (a ranking, **not a probability**).

**What history says about this rule:** in the check era it found 10x stocks no more often than chance (0.9% vs
3.0%), but it halved less often (15% vs 21%) and stopped trading less often (5% vs 13%). Treat it as "small
caps that are already working and not collapsing", not as a multibagger finder.

Prices: NSE close 30 Oct 2026; market cap: NSE PR archive `mcap30102026.csv`; other columns calculated.

| # | Symbol | Company | Close ₹ | Mcap ₹ cr | Traded ₹ cr/day | 12-1 mom | From 52w high | Volatility | Invalid below ₹ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | TEXINFRA | Texmaco Infra & Holdings | 112.94 | 1,439 | 1.8 | +28% | −12% | 30% | 84.70 |
| 2 | SANGAMIND | Sangam (India) | 608.75 | 3,059 | 1.1 | +52% | −6% | 34% | 456.56 |
| 3 | ASHIANA | Ashiana Housing | 336.95 | 3,387 | 1.2 | +38% | −17% | 34% | 252.71 |
| 4 | PIXTRANS | Pix Transmissions | 1,635.40 | 2,228 | 2.2 | +19% | −18% | 33% | 1,226.55 |
| 5 | MONARCH | Monarch Networth Capital | 351.80 | 2,601 | 2.9 | +17% | −12% | 34% | 263.85 |
| 6 | MUKANDLTD | Mukand | 141.45 | 2,044 | 1.8 | +40% | −24% | 37% | 106.09 |
| 7 | THEJO | Thejo Engineering | 2,008.90 | 2,179 | 1.2 | +14% | −10% | 33% | 1,506.68 |
| 8 | GLOBAL | Global Education | 143.74 | 732 | 1.3 | +103% | −1% | 43% | 107.81 |
| 9 | AURUM | Aurum Proptech | 201.19 | 1,538 | 2.7 | +22% | −20% | 35% | 150.89 |
| 10 | GUFICBIO | Gufic Biosciences | 413.55 | 4,147 | 3.1 | +27% | −8% | 36% | 310.16 |

**Thesis (hypothesis, same for all):** small companies whose price has already risen for a year with calm
swings; if the business behind it keeps growing, small size leaves room to compound. The business part is
**unverified**.

**Key risks:** no fundamentals checked (earnings, debt, promoter pledges, governance); thin trading (₹1–3 cr/day)
means exits can gap; small caps fell 40–60% in 2008 and 2018-type years; gaps can lose more than any stop.

**Invalidation triggers (any one):** close below the "invalid below" level (−25% from 30 Oct close); stock moved
to BE/BZ (trade-to-trade) series or a surveillance list; falls out of the rule at the next quarterly re-run.

**Not listed on purpose:** penny and beaten-down "lottery" stocks. The data show a median 0.4x outcome and up to
43% disappearing. Penny stocks are also the usual target of pump-and-dump schemes (general knowledge, not
measured here).

## Crypto watchlist

- **BTC** (83,624 USDT on 2026-09-30) and **ETH** (2,686) as the reference holdings: over 5 years, 86% of
  altcoins did worse than BTC.
- **No altcoin is listed.** None of the tested screens (volume, age, trend) beat BTC consistently. Indian tax
  (assumed 31.2% on every gain, no loss set-off, 1% TDS; unverified, from earlier project research) makes coin-hopping worse.

## Limitations

- Fundamental and ownership data were not reachable from this session: screener/BSE/Yahoo hosts are blocked, and
  NSE's website APIs were not used. A fundamentals pass needs the NSE MCP connection or another approved source.
- Dividends excluded (understates large, steady companies). Stocks that stopped trading keep their last price
  (delisting buy-outs and collapses look alike). The 9% dropped stock-windows may hide both blow-ups and winners.
- All these years were already used by earlier experiments; this is descriptive, not an out-of-sample test.
  The crypto outcome prices reach into the sealed crypto holdout (2025-01..2026-09); no rule was tuned on it, but
  any future crypto strategy test should treat that holdout as seen at the price-level.
- Market cap is today's only (no history), so the historical tests use traded value as the size proxy.
- No probability claims: the percentages are historical frequencies, not calibrated forecasts.

## If you put real money in anyway (model interpretation)

Only money you can lose completely; split equally across many names (on these base rates only about 1 stock in
30–50 became a 10x in 5 years); cash delivery only, no margin or F&O; write the invalidation level down before buying and act on it.

Reproduce: `python -m trading_research.backtesting.multibagger_base_rates` and `... .multibagger_crypto`
after `python -m trading_research.data.mb_download nse` and `... crypto` (raw data under `data/mb/`,
git-ignored; NSE ~7 min, Binance ~4 min).
