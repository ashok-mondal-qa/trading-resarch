# Displacement, short-term reversal and 12-1 momentum (long only) — spec v0.1

Status: **pre-registered, not run** (written and committed before any backtest of these rules).
Code: `src/trading_research/strategies/swing_ideas.py`, runner `src/trading_research/backtesting/run_swing_ideas.py`.
Registry: EXP-0011 (`displacement`), EXP-0012 (`st_reversal`), EXP-0013 (`momentum_12_1`).
Nothing here is evidence of an edge.

## Why these three (label: hypothesis)
- **H11 `displacement`:** a bullish displacement bar (a wide-bodied up day closing near its high) in a
  stock above its 200-day SMA, in an up market, is followed by enough continuation for positive
  expectancy after costs. This is the EXP-0008 ablation, kept exactly as run. On train it scored +0.31R
  (95% CI +0.01..+0.65) and on 2025 validation +0.11R (22 trades), but it was never pre-registered, so
  those numbers are where the idea came from, not a test of it.
- **H12 `st_reversal`:** short-term reversal (Jegadeesh 1990; Lehmann 1990): in a stock that is in a
  long-term uptrend, a sharp 2–3 day sell-off (RSI(2) < 10) tends to recover within days.
- **H13 `momentum_12_1`:** intermediate-horizon momentum (Jegadeesh & Titman 1993): stocks with the
  highest 12-month return excluding the last month keep outperforming over the next months. A momentum
  factor is reported for Indian equities in published factor data (e.g. IIM Ahmedabad's India factor
  library); that is background, not evidence for these exact rules.

The three ideas work on different mechanisms (one-day impulse, multi-day reversal, months-long trend),
so they are not variations of one rule.

## Data and splits
- NSE CM bhavcopy (EQ series) and NSE daily index files from 2015-01-01 to 2026-10-22. The 2015..2021
  files are newly loaded with the same loader, checks and manifests as before.
- **presample: 2016-01-01..2022-08-12.** No experiment has evaluated any strategy on these dates (the old
  data started 2021-10-25 and the old train split started 2022-08-15; the gap was warm-up). It is the
  decisive test here. 2015 is warm-up (SMA200, NIFTY 50 regime, 260-session gate-1 window).
- train 2022-08-15..2024-12-31 and validation 2025 as before. Both were seen by earlier experiments
  (2025 four times), and H11's numbers on them are already known. Here they only serve as a sign check.
- **holdout 2026-01-01..2026-10-22 stays sealed.** The runner has no path to it. It can be used once,
  for at most one strategy that passes every rule below, and only after the project owner agrees.
- Each run loads bars only up to the end of its split.

## Shared rules (gates as in the earlier specs)
| Gate | Rule |
| --- | --- |
| 1 Data | gate-1 checks over 260 sessions; all inputs present; adjusted series usable |
| 2 Regime | NIFTY 50 trend = `up` (close > SMA200 and SMA50 rising over 20 sessions) |
| 3 Context | stock close > SMA200 |
| 6 Risk | stop below the close and at most 10% away; sizer within 0.5% / 2% caps; a new position only if a full 0.5% fits |
| 7 Liquidity | raw close ≥ ₹50, 20-day median traded value ≥ ₹5 crore; **no event screen** |
| 9 Final | at most 2 new a day |

Entry at the next open; skipped if it opens at or below the stop; fixed stop, gap fills at the open; signal
exits fill at the next open. Costs from `config/settings.yaml` (unverified rates) plus 10 bps slippage per
side; everything also at 2× costs.

**Universe changes, decided now:** (a) ETFs and other funds (ISIN starting `INF`) are excluded, as the
EXP-0007/0008 report required. (b) A ticker whose history is already joined into a newer ticker through a
confirmed rename is not loaded on its own. Earlier runs loaded both (for example ZOMATO and ETERNAL for
2021-10..2025-04), so one company could count twice.

## Strategy rules
| | `displacement` (H11) | `st_reversal` (H12) | `momentum_12_1` (H13) |
| --- | --- | --- | --- |
| Setup at close t | body ≥ 1.5 × ATR(14) of t−1, close in the top 25% of the range, up bar | RSI(2) (Wilder) < 10 | t is the month's first session and the stock is in the top 10% of 12-1 momentum among liquid, gate-1 stocks that day |
| Stop | lowest low of the last 5 sessions − 0.1 × ATR(14) | close − 2.5 × ATR(14) | close − 2.5 × ATR(14) |
| Exit (next open) | close below the lowest low of the previous 10 sessions | close above SMA(5) | on a later month start: rank below the top 20%, not rankable, or close < SMA200 |
| Time stop | 40 sessions | 10 sessions | 126 sessions |
| Rank when > 2 a day | highest 63-day RS vs NIFTY 50 | highest 63-day RS vs NIFTY 50 | highest 12-1 momentum |

12-1 momentum = adjusted close 21 sessions ago ÷ adjusted close 252 sessions ago − 1. One parameter set
each; no other values are run.

## Two measurements per split
- **Portfolio:** the strategy as it would be traded (caps, 2 a day, cash).
- **Standalone:** every signal that passes the gates and the regime filter, each simulated alone by the same
  engine (fresh ₹10 lakh portfolio, same costs), skipping a signal in a symbol while that symbol's
  previous standalone trade is still open. This measures the signal itself; in the portfolio run the 2%
  cap decides which signals become trades, and the sample stays small (the earlier reports' main problem).
  Trades on the same days share market moves, so intervals resample **whole entry months**.

## Acceptance / rejection (decided now, per strategy)
A strategy **passes** only if every rule holds:
1. Presample portfolio: ≥ 30 closed trades; at 2× costs expectancy > 0 and profit factor ≥ 1.1.
2. Presample standalone: ≥ 100 closed trades; at 1× costs the lower end of the month-clustered bootstrap
   interval at 1 − 0.05/3 (98.3%, Bonferroni for three strategies) is above 0; at 2× costs expectancy > 0.
3. Train and validation standalone at 2× costs: expectancy > 0 in each.

Otherwise it is **REJECTED** (or inconclusive where a trade count is short, which also means not passed).
The runner applies these rules mechanically (`--verdict`).
A pass makes a strategy a candidate for the one-time holdout, nothing more. If more than one passes, the
one with the highest presample standalone expectancy at 1× costs is proposed. No status here is a
probability claim.

## Known limitations
- Short-run costs: `st_reversal` holds a few days, so costs are a large share of each trade; the 2× run
  matters most for it.
- Cost rates are unverified placeholders, applied unchanged to 2016–2022 (stamp duty was state-wise
  before July 2020, exchange fees differed). The 2× run covers moderate errors.
- No event screen (results days, etc.), no circuit-lock detection.
- Corporate actions from the NSE MCP for 2015–2021 are checked against raw prices exactly as before; a
  symbol with an unexplained jump is usable only after it.
- Universe is every EQ symbol traded each day (delisted names included) that met the liquidity rule on at
  least one day in 2015..2026; that pre-filter cannot change which trades are taken.
- Weekend special sessions (e.g. Budget-day Saturdays) are not in the session calendar.
- The author knows the broad market history of 2016–2022 (demonetisation, the 2018 small-cap fall, the
  2020 crash). The rules were fixed before any run on it.

## Review (gate 8, 2026-10-24)
**Risk manager:** same engine, caps and next-open fills as before; stops are fixed at entry and never
widened; `st_reversal` and `momentum_12_1` stops are volatility-based, not structural. Accepted.
**Independent auditor:** perturb-the-future and truncation tests for all three feature sets, and for the
cross-sectional momentum rank (`tests/test_strategy_swing_ideas.py`); `displacement` is tested to equal
the EXP-0008 ablation exactly. Objections: (1) H11 was suggested by train and validation results, so only
the presample counts as a test of it; (2) three strategies tested, handled by the Bonferroni interval;
(3) no event screen; (4) the standalone view ignores capital limits, so a pass there must also show in
the portfolio rule. Not vetoes; all must appear in the report.

## Changelog
- **v0.1 (2026-10-24):** initial spec, committed before any run. Also: `core.rsi` (Wilder), month-clustered
  bootstrap in `metrics`, index loader reads 2015 files with DD/MM/YYYY dates and the pre-November-2015
  name "CNX Nifty" for NIFTY 50. No earlier results are affected (earlier runs use data from 2021-10-25,
  where neither applies). A holdout evaluation is needed only if a strategy passes.
- **v0.1 clarification (2026-10-24, after the price adjustment and before any backtest run):** the adjuster
  marks a stock's bars usable only after its last adjustment error anywhere in 2015..2026. 160 of 2,125
  stocks have their last error in 2025 or 2026, so their 2016–2022 history would have been dropped
  because of something that happened later (look-ahead in the universe). The runner now cuts history
  only at errors on or before the split's end (`run_swing_ideas.usable_as_of`, tested). Backward
  adjustment scales all earlier bars by the same factor, so a later event does not change returns or
  indicators before it. No rule or parameter changes, so the version stays 0.1. Earlier experiments
  (EXP-0006..0008) used the adjuster's flag directly; with their 2021..2026 data, stocks whose last error
  fell in 2025–2026 lost their train-period history. Their verdicts are not re-run here; this is noted as a
  limitation of those results.

