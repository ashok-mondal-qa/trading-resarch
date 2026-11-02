# NIFTY expiry-day intraday ideas (research only) — spec v0.1

Status: **PRE-REGISTERED** (2026-11-02, written before any backtest of these rules). Registry: EXP-0056..0060.
Report: `reports/backtests/EXP-0056-0060-report.md`.

**Why:** after EXP-0054/0055 (failed-breakout fade, rejected) Ashok asked whether any expiry-day strategy works.
Five well-known intraday ideas, one fixed version each (no parameter search), so dev, validation and holdout are
all out-of-sample tests of a rule nobody tuned here.

## Shared (same as `nifty-expiry-reversal.md`)
Data, expiry calendar, gate 1 (1-min bars vs NSE official high/low), splits (dev 2019-02..2022, halves, validation
2023–2024, holdout 2025-01..2026-10-30, each read once), futures costs at 1× and 2×, the ₹15,000 NIFTYBEES-style
cost model, one trade per expiry day, stop checked before target on each 1-minute bar, a bar opening through the
stop fills at its open, exit at the 15:15 open at the latest. R = |entry − stop|. Stop buffer 0.02% where stated.

## Rules
| EXP | Idea | Entry | Stop | Exit |
| --- | --- | --- | --- | --- |
| 0056 | Opening-range breakout | OR = 09:15–09:29 high/low. First 5-min close above OR high → long (below OR low → short), signal bar closing 09:35–12:00; entry next 1-min open | other side of the OR ± 0.02% | 2R target, else 15:15 |
| 0057 | VWAP trend (TWAP proxy) | Session average price A(t) = mean of 1-min (H+L+C)/3 from 09:15. **Index volume is absent before 2026, so this is a time-weighted proxy, not true VWAP.** First 15-min close (bars closing 10:15–13:30) on the other side of A from the previous 15-min close → trade in the cross direction | extreme of the last two 15-min bars ± 0.02% | a 15-min close back across A (next open), else 15:15 |
| 0058 | Gap fade | gap = 09:15 open / previous official NSE close − 1, needs \|gap\| ≥ 0.30%. Entry 09:20 open against the gap | extreme of 09:15–09:19 ± 0.02% | target = previous close, else 15:15 |
| 0059 | Gap follow | same gap filter; entry 09:20 open with the gap | other extreme of 09:15–09:19 ∓ 0.02% | 15:15 |
| 0060 | Late-day trend | at 13:30, move = price / day open − 1, needs \|move\| ≥ 0.30%; entry 13:30 open in the move's direction | 0.25% from entry | 15:15 |

## Acceptance (same as EXP-0054, per rule)
Paper candidate only if: dev ≥ 60 trades; dev 1× mean net R > 0 with 95% month-clustered bootstrap interval above
0; dev 2× > 0; both dev halves 1× > 0; validation 2× > 0; holdout 1× and 2× > 0. Five rules, so one passing by
luck is possible; the holdout is the check. Otherwise **REJECTED**. Also reported: win rate, ₹ per lot, max drawdown,
by year, by expiry weekday, median risk per lot vs the ₹150 limit, ₹15k ETF result.

## Known limitations
As EXP-0054 (unofficial spot data, futures proxy, no intraday option prices, unverified cost rates), plus the TWAP
proxy for VWAP.

## Changelog
* v0.1 (2026-11-02): first version, pre-registered before any run.
