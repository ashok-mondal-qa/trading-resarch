# Popular strategies from books, YouTube and Instagram (long only, daily) — spec v0.1

Status: **REJECTED, all five** (2026-10-25; `reports/backtests/EXP-0016-0020-report.md`). Written and committed
before any backtest of these rules (2891330).
Code: `src/trading_research/strategies/social.py`, runner `src/trading_research/backtesting/run_social.py`.
Registry: EXP-0016..0020. Nothing here is evidence of an edge.

## Why these five (label: hypothesis)
The owner asked (2026-10-25) to test strategies that traders share on YouTube, Instagram and in books,
without trusting their claims. These five are among the most widely shared for Indian cash-market swing
trading **and can be tested honestly on end-of-day data** (intraday ideas such as opening-range breakouts,
VWAP or CPR need intraday bars we do not have; option-selling ideas need derivatives, which the risk policy
forbids). Each rule follows its common public description; where a rule needs an intraday order, the daily
approximation is stated.

| Strategy | Source of the idea | Our daily version |
| --- | --- | --- |
| `minervini` (EXP-0016) | Mark Minervini, *Trade Like a Stock Market Wizard* (Trend Template, SEPA) | template + close above the 20-session high on ≥ 1.5× volume |
| `supertrend` (EXP-0017) | Supertrend(10, 3), one of the most shared indicators on Indian trading YouTube | buy the flip up, exit the flip down |
| `ma44` (EXP-0018) | the "44 moving average" setup popular on Indian YouTube/Instagram | buy-stop above the candle's high approximated by a close above it, then next open |
| `turtle55` (EXP-0019) | Richard Dennis's Turtle traders, System 2 (Curtis Faith, *Way of the Turtle*) | close above the 55-session high |
| `golden_cross` (EXP-0020) | 50/200-day moving-average cross, a staple of social-media "investing" content | buy the cross up, exit the cross down |

## Rules (all at the close of day t; shared gates as in earlier specs)
NIFTY 50 trend `up` at t (runner); raw close ≥ ₹50; 20-day median traded value ≥ ₹5 crore; gate-1 data
checks; stop below the close and at most 10% away; 0.5% / 2% caps (a new position only if a full 0.5%
fits); at most 2 new a day; entry next open, skipped at or below the stop; fixed stop, gaps fill at the
open; ETFs and superseded renamed tickers excluded; adjustment errors count only if dated by the split end.
Unlike earlier specs there is **no** stock-above-SMA200 filter unless the strategy itself has one.

| | Setup | Stop | Target | Exit (next open) | Time stop | Rank |
| --- | --- | --- | --- | --- | --- | --- |
| `minervini` | close > SMA150 and SMA200; SMA150 > SMA200; SMA200 > its value 21 sessions ago; SMA50 > SMA150; close > SMA50; close ≥ 1.30 × 252-session low and ≥ 0.75 × 252-session high; RS rank ≥ 70 (percentile of 2×ROC63 + ROC126 + ROC189 + ROC252 among liquid, gate-1 stocks that day); close > previous 20-session high; volume ≥ 1.5 × median of 20 previous sessions | close × 0.92 | none | close < SMA50 | 126 | RS score |
| `supertrend` | Supertrend(10, 3) direction turns up at t | Supertrend line at t | none | direction down | 126 | 63d RS |
| `ma44` | day t−1: SMA44 > SMA44 five sessions earlier, low ≤ SMA44 < close, close > open; day t: close > high of t−1 | low of t−1 | high(t−1) + 2 × range(t−1) | none (stop/target/time) | 40 | 63d RS |
| `turtle55` | close > highest high of the previous 55 sessions | close − 2 × ATR(20) | none | close < lowest low of the previous 20 sessions | 252 | 63d RS |
| `golden_cross` | SMA50 crosses above SMA200 | close × 0.90 | none | SMA50 < SMA200 | 252 | 63d RS |

Engine change: an optional profit target (fixed at the signal, like the stop). A day that opens at or
above it fills at the open; else a high at or above it fills at the target; the stop is checked first,
so a day that touches both counts as a stop. Tested in `tests/test_engine.py`.

## Data and splits
NSE CM bhavcopy 2011-07-01.. and NSE index files 2012-02-21.., as in Phase 12. **All of 2013–2025 has
been used before** (16 strategy definitions including these five). There is no fresh development data,
so the decision uses the whole period **dev = 2013-01-01..2025-12-31** with a strict multiple-testing
correction, plus sign checks on each sub-period (early 2013–2015, presample 2016..2022-08, train
2022-08..2024, validation 2025). **The 2026 holdout stays sealed**; the runner has no path to it.

## Acceptance / rejection (decided now, per strategy)
A strategy **passes** only if every rule holds:
1. Dev portfolio: ≥ 30 closed trades; at 2× costs expectancy > 0 and profit factor ≥ 1.1.
2. Dev standalone: ≥ 300 closed trades; at 1× costs the lower end of the month-clustered interval at
   1 − 0.05/16 (99.7%, Bonferroni over every definition tested on these dates) is above 0; at 2× costs
   expectancy > 0.
3. Standalone at 2× costs: expectancy > 0 in each of early, presample, train and validation.

Otherwise **REJECTED** (`run_social --verdict`). A pass makes a strategy a candidate for the one-time
2026 holdout; if several pass, the one with the highest dev standalone expectancy at 1× costs goes. The
report also gives each portfolio's CAGR, volatility and Sharpe ratio (risk-free 0) against NIFTY 50, for
the later comparison with crypto. No status is a probability claim.

## Known limitations
As before (unverified cost rates applied back to 2013, no event screen, no circuit-lock detection,
weekend special sessions missing, 11 sessions without an index file). Plus: daily approximations of
rules that are often traded intraday (`ma44` buy-stop, Minervini's intraday pivot buys); Minervini's
full method also uses earnings and base patterns, not tested here; Turtle sizing and pyramiding are
replaced by this project's fixed 0.5% risk; the 10% stop cap rejects Turtle and Supertrend setups in
very volatile stocks.

## Review (gate 8, 2026-10-25)
**Risk manager:** same caps; every stop is fixed at entry and never widened; the target only closes
trades. Accepted.
**Independent auditor:** perturb-the-future and truncation tests for all five feature sets; the RS rank
is cross-sectional at t only; engine target tests. Objections: (1) the data has been used for 11 earlier
definitions, handled by the 16-way correction, but a pass would still need the holdout; (2) `minervini`
overlaps the rejected baseline breakout (EXP-0006); (3) no event screen. Not vetoes; all must appear in
the report.

## Changelog
- **v0.1 (2026-10-25):** initial spec, committed before any run. Adds `core.supertrend` and engine profit
  targets (no change for strategies without a `target` column). No earlier results affected.
- **Result (2026-10-25, no rule change):** all five REJECTED by the rules above; holdout not run. Review
  found that expectancy counts closed trades only (biased against long holds in short splits); re-checked
  with open trades marked to market, no verdict changes. Later specs should report both.
