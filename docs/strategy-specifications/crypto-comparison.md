# Crypto vs Indian equities: the same rules on Binance spot (long only, daily) — spec v0.1

Status: **REJECTED, all six** (2026-10-25; `reports/backtests/EXP-0021-0026-report.md`, comparison
`reports/market-comparison-2026-10-25.md`). Written and committed before any crypto backtest (8374c91).
Code: `src/trading_research/backtesting/run_crypto.py`; data loader `src/trading_research/data/binance.py`.
Registry: EXP-0021..0026. Nothing here is evidence of an edge.

## Why (label: hypothesis)
The owner asked (2026-10-25) to compare Indian equities with crypto on profitability, risk, fees, liquidity
and consistency, and to pick the best risk-adjusted, data-backed approach. To make the comparison fair and
avoid new tuning, crypto gets **the same six rule sets already tested on Indian stocks**, with the same
parameter values (in bars), the same engine, the same risk caps and the same kind of pass/fail rule:

| Experiment | Rules (as on NSE) |
| --- | --- |
| EXP-0021 `minervini` | EXP-0016 (social-strategies.md) |
| EXP-0022 `supertrend` | EXP-0017 |
| EXP-0023 `ma44` | EXP-0018 |
| EXP-0024 `turtle55` | EXP-0019 |
| EXP-0025 `golden_cross` | EXP-0020 |
| EXP-0026 `momentum_weekly` | EXP-0014 (swing-ideas-2.md): 12-1 momentum top 10%, checked weekly |

## Data (verified source, see docs/data-sources.md)
Binance's official archive data.binance.vision, monthly 1d klines, every USDT pair in the bucket listing
(677, delisted pairs included), SHA-256 checked, loaded 2026-10-25 up to 2026-09. Bars are UTC days.
Excluded bases: stablecoins, fiat, gold tokens, wrapped/staked copies, leveraged tokens (`binance.py`).

**Point-in-time handling:** a pair's series is split at any missing day; each piece is its own instrument
(a reused ticker such as LUNAUSDT after May 2022 never joins the old one); pieces shorter than 200 bars are
dropped. A piece that ends before the split's last day is treated as delisted: no new signals in its last
7 bars (Binance announces delistings in advance), and an exit signal on its second-to-last bar, so a held
position sells at the open of its last bar. Invalid or duplicate candles are dropped, never repaired.

## Shared rules (changed from NSE only where the market differs)
- Market regime: **BTCUSDT** trend `up` (close > SMA200 and SMA50 slope over 20 bars > 0), the same function
  as the NIFTY gate. Relative strength is measured against BTCUSDT.
- Liquidity: 20-day median quote volume ≥ **5,000,000 USDT** (about ₹40 crore at 80 ₹/USDT, eight times the
  NSE floor, because crypto volumes include some wash trading). **No price floor** (crypto has no ₹50
  equivalent). Gate-1 bar checks over the last 260 bars with every UTC day as a session.
- Costs per side: Binance spot base fee 0.10% (secondary sources, unverified) + 18% GST on the fee
  (= 0.118%) + 10 bps slippage; 2× stress. No STT or stamp duty. The 1% TDS on sales is a tax credit, not a
  cost (cash drag noted, not modelled).
- Risk: unchanged (0.5% per position, 2% aggregate, ≤ 2 new a day, no leverage, fixed stops, stop ≤ 10%
  away). Starting equity 10^9 USDT units so that whole-unit rounding never blocks BTC; results are in R and
  in percent, so the scale does not matter (no liquidity cap is applied; size is a fraction of equity).
- Holding limits stay in bars (126 bars = about 4 months in crypto vs 6 in equities).

## Splits
| Split | Dates | Use |
| --- | --- | --- |
| dev | 2018-04-01..2023-12-31 | decides (first date with a BTC regime value) |
| dev_a | 2018-04-01..2020-12-31 | sign check |
| dev_b | 2021-01-01..2023-12-31 | sign check |
| validation | 2024-01-01..2024-12-31 | sign check |
| **holdout** | 2025-01-01..2026-09-30 | **sealed**; one-time use for a strategy that passes; no runner path |

Each split loads bars only up to its own last day.

## Acceptance / rejection (decided now, per strategy)
Passes only if every rule holds:
1. Dev portfolio: ≥ 30 closed trades; at 2× costs expectancy > 0 and profit factor ≥ 1.1.
2. Dev standalone: ≥ 300 closed trades; at 1× costs the month-clustered interval at 1 − 0.05/6 (99.2%,
   Bonferroni over the six) is above 0; at 2× costs expectancy > 0.
3. dev_a, dev_b and validation standalone at 2× costs: expectancy > 0 **counting trades still open at the
   split end marked to market** (fixes the closed-only censoring found in EXP-0016..0020) and also over
   closed trades only.
Otherwise **REJECTED**. If several pass, the one with the highest dev standalone expectancy at 1× costs
goes to the holdout.

## Market comparison (descriptive, no pass/fail)
Over each market's common window (2018-04-01..2024-12-31, both markets) the report gives CAGR, volatility,
Sharpe (risk-free 0), maximum drawdown and worst calendar year, before and after Indian tax, for:
- each strategy's capped portfolio on each market;
- **buy and hold**: NIFTY 50 (price index, dividends excluded) and BTCUSDT; and an equal-weight basket of
  the 10 most liquid eligible coins, rebalanced weekly (a crypto "market" that is not just BTC);
- **200-day trend timing** of each index (hold from the next open while close > SMA200, else cash), with
  each market's costs on every switch.
Tax model (secondary sources, unverified, label: assumption): crypto 30% + 4% cess = 31.2% on every
profitable sale, losses never offset (Income-tax Act s.115BBH); Indian listed equity short-term 20% + cess
= 20.8% on each year's net gains with losses carried forward, long-term (> 12 months) 12.5% + cess = 13% above
₹1.25 lakh a year (rates from 23 Jul 2024, applied to the whole period). Surcharge ignored. Fully invested
benchmarks have no stop and do not meet the paper risk policy; they are a yardstick, not a candidate.

## Known limitations
One exchange (Binance) in USDT; INR exchanges trade at a premium with wider spreads; USDT/INR currency risk
and Indian KYC/withdrawal frictions not modelled. Volumes include wash trading. Pairs delisted before the
archive began are missing. 24/7 market: "next open" is the next UTC day's first trade. Cost rates
unverified. Same daily approximations as the NSE specs.

## Review (gate 8, 2026-10-25)
**Risk manager:** same caps and stop rules as equities; no leverage, no derivatives; benchmarks are not
tradeable under the policy. Accepted.
**Independent auditor:** same feature code as the NSE runs (already tested for look-ahead); new code is the
loader (tests), segmenting and delisting handling (tests). Objections: (1) these six rules were chosen after
seeing NSE results, but never on crypto data, so the crypto dev is fresh for them; (2) 2018–2023 crypto
contains one full boom and two busts, so the sign checks matter more than the averages. Not vetoes.

## Changelog
- **v0.1 (2026-10-25):** initial spec, committed before any crypto run.
- **v0.1 addendum (2026-10-25, before any run, 657fed3):** `compare_markets.py` and a portfolio-only `common`
  split (2018-04..2024-12) in `run_crypto` for the descriptive comparison; no verdict uses them.
- **Result (2026-10-25, no rule change):** all six REJECTED; holdout not run. The 10% stop cap refuses most
  Supertrend and momentum setups on crypto.
