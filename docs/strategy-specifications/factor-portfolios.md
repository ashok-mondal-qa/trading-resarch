# Monthly factor portfolios on NSE stocks (research and paper only) — spec v0.1

Status: **REJECTED, all three** (2026-10-25; `reports/backtests/EXP-0039-0041-report.md`). Low volatility and the
mix failed only the significance check and go to forward paper tracking. Rules were committed before any run
(2e6396e).
Code: `src/trading_research/strategies/factors.py`, runner `src/trading_research/backtesting/run_factors.py`.
Registry: EXP-0039..0041. Exploration notes: `docs/validation/exploration-2026-10-25.md`.

**Why (owner, 2026-10-25):** after 29 rejected rule sets Ashok asked for a strategy built from the data,
the way a professional desk would. Earlier swing rules risk 0.5% per trade with stops, so they sit mostly in
cash and cannot keep up with a rising market. This spec tests the opposite style: always invested, picking
which stocks to hold.

## How these were chosen (disclosed, model interpretation)
An exploration on **2013–2022 data only** (stocks built to 2022-12-31; nothing later was looked at) compared
four well-known stock-selection signals by quintile: low volatility, 12-1 momentum, nearness to the 52-week
high and 1-month reversal. Low volatility and momentum had the best risk-adjusted top quintiles and low
turnover. Both are among the most studied effects in finance (hypothesis that they persist in India). So
**dev results are in-sample by construction**; the decision rests on validation 2023–2025 and the sealed
2026 holdout.

## Rules (shared)
* Rebalance at each month's last session t (signal at the close), trade at the next session's open.
* Universe at t: the 200 stocks with the highest 63-session median traded value, at least 240 closes in the
  last 260 sessions and a bar on t (NSE EQ, ETFs excluded, point-in-time adjustment validity as in Phase 11+).
* Hold the top 30 by score, equal weight at entry; names that drop out are sold, names that enter are bought
  with min(cash / new names, equity / 30); no top-ups; idle cash earns nothing; a holding with no bar for
  5 sessions is sold at its last close.

| | Strategy | Score at t (adjusted closes up to t) |
| --- | --- | --- |
| EXP-0039 | `lowvol` | minus the standard deviation of the last 252 daily returns |
| EXP-0040 | `momentum` | close 21 sessions ago / close 252 sessions ago − 1 |
| EXP-0041 | `mom_lowvol` | mean of the two percentile ranks |

## Costs and tax (unverified assumptions)
Delivery costs from `config/settings.yaml` (STT 0.1% each side, stamp 0.015% on buys, exchange and SEBI fees,
GST, DP ₹15.34 per sell) plus 0.10% slippage per side; 2× stress doubles all of it. Start ₹10 lakh per split.
Tax as Phase 14: short term (< 1 year) 20.8%, long term 13% above ₹1.25 lakh a year, set-off and carry-forward;
open positions are sold at each split's end for tax. Benchmark: NIFTY 50 price index bought at the first open
with the same costs and held (no dividends on either side; adjusted stock prices exclude dividends).

## Splits
dev 2013-01-01..2022-12-31 · sub-periods 2013–2017 and 2018–2022 · validation 2023-01-01..2025-12-31 (never
used for portfolio rules; seen by earlier swing rules) · **holdout 2026-01-01..2026-10-22 sealed** (one use).
Each split starts fresh from cash.

## Acceptance (decided now; Bonferroni over three, α = 0.05/3)
1. Dev at 2× costs: Sharpe (monthly returns, rf 0) above NIFTY's, and after-tax CAGR above NIFTY's.
2. Dev at 1× costs: 98.33% moving-block bootstrap interval (12-month blocks) of Sharpe(strategy) − Sharpe(NIFTY)
   above 0.
3. At 2× costs, Sharpe not below NIFTY's in 2013–2017, in 2018–2022 and in validation 2023–2025.
4. Validation at 2× costs: maximum drawdown at most 10 points worse than NIFTY's.
Otherwise **REJECTED**. Passing makes a strategy a holdout candidate; passing the holdout makes it a paper-tracking
candidate only.

## Policy note (risk manager)
A fully invested 30-stock portfolio without stops does not fit the swing risk rules (0.5% planned risk per
position, 2% aggregate). This is research and paper tracking only. Any real-money use would need the owner to
approve a separate investing policy in writing after review; no limit is changed here.

## Known limitations
Price-only returns (no dividends) on both sides; the universe uses today's list of loaded stocks (delisted
names are in the archive data, but symbol history may miss some); slippage is flat; costs are current rates;
no market-impact model (fine for ₹10 lakh, not for large money).

## Review (gate 8, 2026-10-25)
**Risk manager:** long only, no leverage, no derivatives; policy note above. Accepted as research.
**Independent auditor:** signals were picked after seeing dev quintiles, which the spec states; validation and
the holdout are untouched; one parameter set, no tuning. Objection: 2023–2025 is a strong bull market for
mid-caps, which may flatter momentum. Not a veto.

## Changelog
- **v0.1 (2026-10-25):** initial spec, before any portfolio run.
- **v0.1 result (2026-10-25):** run once, no changes; all three REJECTED; EXP-0039 and EXP-0041 to forward tracking.
- **v0.1.1 (2026-10-26), benchmark fix, no rule change:** the NIFTY buy-and-hold curve in `run_factors.nifty_curve`
  kept its buy cost as idle cash (found while writing the Phase 19 tests): about 0.2% (1×) to 0.4% (2×) of the
  start equity sat in NIFTY's curve without growing. Now the whole start equity buys NIFTY. Strategy rules,
  `factors.py` defaults and EXP-0042/0043's frozen rules are unchanged. `factors.Params` also gains
  `min_median_value` and `value_on_t` for the crypto run (defaults 0 / off, no effect here). Tests: 308 pass.
  Rerun once on dev and validation (no holdout use): NIFTY CAGR +0.03 to +0.05 points, Sharpe within 0.001,
  intervals unchanged to three decimals, **all verdicts unchanged**. No new holdout evaluation is needed.
- **v0.1.2 (2026-10-26), data-handling fix (look-ahead), no rule change:** `run_factors.load` dropped every bar
  of a stock before its last adjustment error known by the data end (`usable_as_of`). An "error" is any move
  above 35% without a corporate action, which includes real crashes: YESBANK's −56% day on 2020-03-06 removed
  all its 2013–2020 bars, so the backtest could never hold a stock that later crashed. 660 of 2,205 adjusted
  stocks have at least one error. Now every bar is kept and each error starts a new stretch: at a rebalance
  only bars in the same stretch as that day count (history, liquidity, scores), so an error removes nothing
  before it, and a holding takes the full move on the error day (a real loss if it is a crash; a false loss if
  it is a missing split, which only biases against the strategies). Found while building the 2006–2011 test
  (factor-portfolios-pre2011.md). Impact on earlier results: unknown until rerun; dev and validation are rerun
  once (no holdout use) and the report is updated whatever the outcome. EXP-0042/0043 use the fixed loader;
  no forward data exists yet (first forward close 2026-10-30, first check 2026-11-02). The swing experiments
  EXP-0011..0028 used the same filter; they were all rejected, and the bias favoured them, so their verdicts
  stand. Tests: 315 pass.
