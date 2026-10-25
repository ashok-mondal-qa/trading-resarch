# Crypto intraday: four popular day-trading rules on BTC and ETH (research only) — spec v0.1

Status: **REJECTED, all four** (2026-10-25; `reports/backtests/EXP-0033-0036-report.md`). Rules were committed
before any intraday backtest (42003de).
Code: `src/trading_research/strategies/intraday.py`, runner `src/trading_research/backtesting/run_intraday.py`,
data `src/trading_research/data/binance_intraday.py`. Registry: EXP-0033..0036.

**Scope (owner, 2026-10-25):** after the swing and options results Ashok asked to explore intraday. Indian
intraday needs a paid minute-data feed, so intraday is tested first on crypto, where the official Binance
archive has free 5-minute data. Paper/research only; long only, spot, no leverage.

## Data
Binance spot 5-minute klines for **BTCUSDT and ETHUSDT**, 2018-01-01..2024-12-31 (official archive, SHA-256
checked, gaps listed, never filled). 15-minute and 1-hour bars are built from complete groups of 5m bars.
Universe chosen before testing as the two most liquid pairs; picking them with hindsight is a (small)
survivorship bias. The **holdout 2025-01-01..2026-09-30 is not even downloaded** by this phase.

## Execution model (shared)
* A signal is known at the close of its bar; entry at the open of the next 5m bar (= the next bar of the
  strategy's timeframe). If that 5m bar is missing, no trade.
* Planned stop known at the signal. Skip the signal if the stop is not below the signal close or the stop
  distance is < 0.6% of the signal close (2× the round-trip cost; tighter stops make costs ≥ 0.5R).
* Stops are checked on every 5m bar from the entry bar on: if low ≤ stop, exit at min(open, stop) (a gap
  through the stop fills at the open). Exit signals fill at the next bar's open.
* One position per pair per strategy; a new entry needs a signal bar starting at or after the last exit.
* R = entry fill − stop. Net P&L = exit fill − entry fill − fees.
* **Costs per side:** Binance fee 0.10% + 18% GST on the fee, slippage 3 bps (BTC/ETH); round trip ≈ 0.30%.
  **2× stress** doubles fees and slippage. (Unverified for any Indian venue; INR exchanges charge more.)
* **Indian tax (assumption from secondary sources, as Phase 14):** 31.2% of each profitable trade's gain,
  losses not set off. Reported as after-tax R per trade.

## Strategies
| | Strategy | Timeframe | Entry | Stop | Exit |
| --- | --- | --- | --- | --- | --- |
| EXP-0033 | `orb` opening-range breakout | 5m | range = high/low of 00:00–00:59 UTC (all 12 bars present); first 5m close above the range high between 01:00 and 11:55 UTC | range low | next 00:00 UTC open (end of day) |
| EXP-0034 | `ema_cross` 9/21 EMA with 200 EMA filter | 15m | EMA9 crosses above EMA21 and close > EMA200 | lowest low of the last 10 bars (incl. signal bar) | EMA9 crosses below EMA21 (next open) |
| EXP-0035 | `bb_rsi` Bollinger + RSI mean reversion | 1h | close < SMA20 − 2σ20 and RSI14 < 30 and close > EMA200 | close − 2 × ATR14 | close ≥ SMA20 (next open), or 48 bars after entry |
| EXP-0036 | `supertrend` Supertrend(10, 3) flip | 1h | direction turns up | Supertrend line at the signal | direction turns down (next open) |

(UTC 00:00 = 05:30 IST; crypto trades 24/7, so the "open" is a clock time, not an auction.)

## Splits
dev 2018-01-01..2022-12-31 (decides) · sub-periods 2018–2020 and 2021–2022 · validation 2023-01-01..2024-12-31
· holdout 2025-01-01..2026-09-30 sealed (not downloaded). A trade belongs to the split of its entry.
Daily BTC/ETH prices for these years were already seen in Phase 14 (different rules, daily bars).

## Acceptance (decided now; per strategy, BTC and ETH pooled)
1. Dev ≥ 200 trades; at 2× costs expectancy > 0 and profit factor ≥ 1.1.
2. Dev at 1× costs: 98.75% bootstrap interval of mean R (Bonferroni over four; whole entry months resampled)
   above 0.
3. 2× costs expectancy > 0 in 2018–2020, in 2021–2022 and in validation 2023–2024.
4. Dev at 1× costs: mean **after-tax** R > 0.
Otherwise **REJECTED**. Passing makes a strategy a holdout candidate only.

## Reported but not decided on
Win rate, average holding time, trades per month, worst trade, share of profit from the best 5 trades, BTC
and ETH separately, an illustrative equity curve risking 0.5% per trade (position ≤ 50% of equity, so two
positions never exceed 100%; no leverage), and BTC buy and hold over the same splits.

## Known limitations
5m bars hide the order of moves within a bar (a stop and an exit can't both occur in one 5m bar here; stops
are checked first). Slippage is flat; liquidity in 2018 was thinner. One exchange. No funding, no shorting.
Binance outages leave gaps; indicators run across gaps on the bars that exist.

## Review (gate 8, 2026-10-25)
**Risk manager:** long only, spot, no leverage, illustrative sizing within the 0.5% / 2% limits. Accepted as
research. **Independent auditor:** four common rule sets taken as usually described, one parameter set each,
no tuning; the 0.6% minimum stop is a cost rule fixed before any run. Objection: the same years were seen at
daily resolution in Phase 14. Not a veto.

## Changelog
- **v0.1 (2026-10-25):** initial spec, before any intraday run.
- **v0.1 result (2026-10-25):** run once, no changes; all four REJECTED.
