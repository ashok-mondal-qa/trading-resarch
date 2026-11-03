# Trailing-stop exits vs fixed targets on the morning scan entries (research only) — spec v0.1

Status: **EXP-0082 REJECTED** (run 2026-11-03, report `reports/backtests/EXP-0082-report.md`; pre-registered in
commit 86624896 before the run). Registry: EXP-0082. Code: `src/trading_research/strategies/trailing_exits.py`, runner
`src/trading_research/backtesting/run_trailing.py`, tests `tests/test_trailing_exits.py`. Nothing here places orders.

## Why (label: owner hypothesis)
On 2026-11-03 Ashok took the 09:35 scan pick BHARTIARTL (plan: entry 2010.55, stop 1994.45, 2R target 2042.75). He
sold at 2038.01 and the stock later traded around 2048-2050 (his report, not verified here). His idea: once a trade
moves in our favour, trail the stop and let the winner run for a bigger target instead of a fixed 1:2. This tests
that idea on the same entries the scan uses, with only the exit changed.

Source tier (research-source-library rule): owner idea plus common practitioner advice ("cut losers, let winners
run", breakeven stop, chandelier/ATR trail, partial profit). Tier 3-4, no peer-reviewed claim relied on. Known
counter-evidence (label: hypothesis from general literature, not verified here): trailing exits on intraday entries
help only when the entry has fat right tails; they turn many +2R winners into small or breakeven exits.

## Entries (not changed by this experiment)
Exactly the EXP-0081 historical replay of the v0.2 scan (`intraday-orb-scan.md`, replay section; code
`backtesting/run_orb_scan_replay.replay_day`, which reuses the live scan's `quote_screen`, `plan` and `money_plan`):
126 NSE stocks, 1-minute bars 2017-01..2020-12 from the unofficial `ShabbirHasan1/NSE-Data` vendor, each day scaled to
the official NSE CM bhavcopy (high and low factors agree within 0.10%, >= 360 bars); scan at 09:35 from bars
09:15-09:34; Rs 15,000 cash, Rs 300 risk cap, charges check at 2R with the Rs 40 estimate; one pick a day (most
traded passing idea whose check passes); buy-stop from 09:35, cancelled if the stop trades first; fill = max(entry,
bar open). The same 411 triggered trades as EXP-0081 are expected; the F2 row must reproduce EXP-0081's 2R numbers
under its cost schedule (a cross-check of both harnesses).

Robustness set (reported, not used for the choice): every triggered passing idea, not only the daily pick
(more trades, several a day; not tradable under the one-trade rule).

## Exits compared (all decided now; every exit also leaves at the 15:10 bar's open at the latest)
Fixed: **F1** 1R target · **F2** 2R target (the live v0.2 rule, the baseline) · **F3** 3R target · **F0** no
target (original stop, 15:10).
Trailing (no target; the stop only moves in the trade's favour; "+1R reached" = a bar's high (long) reached
entry + 1R; every update uses completed bars only and applies from the next 1-minute bar):
- **T1 breakeven**: after +1R, stop = entry.
- **T2 ladder**: after +1R stop = entry; after +kR (k >= 2) stop = entry + (k-1)R.
- **T3 ATR trail**: after +1R, stop = max(entry, highest high since entry - 2 x ATR14 of 5-minute bars), updated
  at each completed 5-minute bar (ATR runs across sessions, simple mean of 14 true ranges).
- **T4 swing trail**: after +1R, stop = max(entry, lowest low of the last 3 completed 5-minute bars).
- **T5 EMA trail**: after +1R, stop = entry, and exit at the next 1-minute bar's open once a completed 5-minute
  bar closes below EMA9 of 5-minute closes (EMA runs across sessions).
5-minute bars are anchored at 09:15 and built from the vendor's split-adjusted minutes of gate-passing days, so
EMA9 and ATR14 run across sessions without split jumps; on each day they are scaled by that day's factor.
Partial (half = floor(qty/2) sold at the 2R target; when qty < 2 the whole position follows the trail rule):
- **P1** half at 2R, rest T1 (breakeven after +1R), 15:10.
- **P2** half at 2R, rest T3 (ATR trail).
- **P3** half at 2R, rest T4 (swing trail).

Fill rules (as EXP-0081 `exit_walk`, extended): stop before target inside a bar; a bar opening through the stop fills at its open (gap loss beyond
plan kept); a bar opening through the target fills at the target (no gap gain); on the entry bar a fill inside
the bar can stop out but not reach the target or move the stop. The 2R partial sale and stop moves on the same bar:
stop checked first.

## Costs
Primary (decisions): Groww intraday schedule as used for EXP-0061..0077 (brokerage 0.1% capped at Rs 20 per order,
min Rs 5; STT 0.025% on the sell; exchange 0.00297%; SEBI 0.0001%; stamp 0.003% on the buy; GST 18% on brokerage and
fees) — **unverified placeholders** (groww.in is blocked by the proxy; Ashok's own app showed about Rs 40 a round
trip). Cross-check: the EXP-0081 schedule (`intraday_scan.round_trip_charges`, brokerage 0.03% capped Rs 20). A
partial exit pays a third order. Slippage 0.05% of price per fill, adverse. Stress: 2x charges and 2x slippage.
Sensitivity: slippage 0, 0.05%, 0.10% per fill.

## Splits and what is out of sample
dev 2017-2018 · validation 2019 · 2020 reported. **Not out of sample:** these 126 stocks and years were already used
by EXP-0061..0066, 0069/0070, 0073..0077 and EXP-0081 (2020 was the holdout of 0061-0066). The splits still let one choice be made on 2017-18
and checked on later years the choice never saw. Walk-forward: anchored yearly; for each test year 2018, 2019,
2020 the exit with the best mean net Rs/trade at 1x on all earlier years is applied to that year.

## Metrics (per exit and split)
Trades, win rate, average win and loss (Rs), profit factor, expectancy (Rs and net R = net Rs / planned Rs risk),
max drawdown of cumulative Rs P&L, longest losing streak, charges, slippage sensitivity, 2x stress, and the
favourable-excursion profile (share of trades whose high reached +1R, +2R, +3R, +5R before the exit time).

## Decision rules (decided now)
1. **Does trailing beat the 2R target?** S = the trailing or partial exit (T1-T5, P1-P3) with the best mean net
   Rs/trade at 1x in dev. S beats F2 only if its paired mean difference vs F2 on the same trades is > 0 in dev, 2019
   and 2020, and the pooled 95% bootstrap interval of that difference (resampled by month) is above 0. Otherwise
   **F2 stays** (no change to the live scan from this test; a change would need a new registered version and
   forward data). The same test is also reported for the overall dev-best exit if that is a fixed one.
2. **Is the rule with S positive?** Net Rs at 2x costs > 0 in all three splits, pooled 95% bootstrap CI of net Rs/
   trade at 1x above 0, and the walk-forward exit net > 0 in each test year. Otherwise **REJECTED**.
3. The robustness set is reported with the same numbers; a result that holds on only one of the two sets is not
   evidence.
A pass would be a reason for forward paper tracking, not a probability claim or live approval.

## Known limitations
Unofficial minute bars; 126 large/mid caps chosen in 2021 (survivorship) vs ~2,000 names live; no order book or
queue position; 1-minute bars hide the order inside a bar (resolved against the trade); live quotes are 1-3 minutes
delayed, so real fills are worse than modelled; trailing stops placed by hand in an app lag the rule. Gaps and fast
markets can lose more than planned risk.

## Changelog
- v0.1 (2026-11-03): first version, pre-registered before any run. Tests: `tests/test_trailing_exits.py`.
  No earlier results affected. No holdout used (none left for this universe).
- Result (2026-11-03, no rule change): **REJECTED.** 410 trades (EXP-0081 entries; F2 exits match EXP-0081 on 100%
  of trades). Mean net Rs/trade at Groww costs: F2 2R -59.7, best trailing/partial -60.1 (P1), all 12 exits -59 to
  -64 with 95% intervals below zero; gross already -6 to -11. No trailing exit beats 2R (paired -4.2..+0.5 Rs, all
  intervals span zero). Only 31% of trades reach +1R, 10% +2R, 3% +3R, 0% +5R. Walk-forward -63.8 Rs/trade.
  Impact: none on the live rule (EXP-0080 continues with 2R). Tests: `tests/test_trailing_exits.py`, full suite.
