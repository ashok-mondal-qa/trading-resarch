# EXP-0082 — trailing stops vs fixed targets on the morning-scan entries (2026-11-03)

**Verdict: REJECTED.** No trailing or partial exit beats the fixed 2R target, and every exit loses money after
costs. Spec: `docs/strategy-specifications/trailing-exits.md` (pre-registered in commit 86624896 before the run).
Data: `reports/backtests/EXP-0082-trailing-exits.json`, trades `EXP-0082-trailing-exits-trades.csv`.

Labels: all numbers are **calculated** from unofficial 1-minute vendor bars (ShabbirHasan1/NSE-Data, 126 stocks,
2017-2020) checked day by day against the official NSE bhavcopy. Costs are the Groww intraday schedule as a
**placeholder** (about Rs 39 a round trip on these trades) plus 0.05% slippage per fill. Not out of sample: these
years and stocks were used by earlier experiments.

## Entries
Exactly the EXP-0081 replay of the live v0.2 scan: 594 picked days, **410 triggered trades** (EXP-0081: 411; the F2
exit price matches EXP-0081 on 100% of shared trades and its mean net at EXP-0081's cost schedule is -36.1 vs
-36.2, so both harnesses agree). Average planned risk about Rs 174 (cash cap of Rs 15,000 limits quantity).

## Why trailing cannot help here: the winners never run
Best price reached before the original stop or 15:10 (pooled): **31% of trades reach +1R, 10% reach +2R, 3% reach
+3R, none reach +5R; median best move 0.61R.** Trailing pays off only when some trades run far; these do not.

## Results (pooled 2017-2020, mean per trade, Rs)
| Exit | Win % | Avg win | Avg loss | PF | Gross | Net 1x | Net 2x | Net R | Max DD | Losing streak | vs 2R |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 1R | 41.0 | 101 | -178 | 0.39 | -10.9 | -63.9 | -145.5 | -0.40 | 26,206 | 10 | -4.2 |
| **F2 2R (live)** | 36.1 | 141 | -173 | 0.46 | -6.7 | **-59.7** | -141.3 | -0.37 | 24,479 | 11 | — |
| F3 3R | 35.6 | 147 | -173 | 0.47 | -6.2 | -59.2 | -140.7 | -0.37 | 24,264 | 11 | +0.5 |
| F0 no target | 35.6 | 141 | -173 | 0.45 | -8.2 | -61.2 | -142.8 | -0.38 | 25,104 | 11 | -1.5 |
| T1 breakeven at +1R | 33.7 | 142 | -164 | 0.44 | -8.1 | -61.1 | -142.6 | -0.38 | 25,039 | 13 | -1.4 |
| T2 ladder | 34.4 | 133 | -166 | 0.42 | -9.8 | -62.8 | -144.4 | -0.39 | 25,762 | 13 | -3.1 |
| T3 2xATR trail | 39.8 | 109 | -175 | 0.41 | -8.9 | -61.9 | -143.5 | -0.39 | 25,391 | 10 | -2.2 |
| T4 3-bar swing trail | 39.8 | 106 | -175 | 0.40 | -10.5 | -63.5 | -145.0 | -0.40 | 26,022 | 10 | -3.8 |
| T5 EMA9 trail | 38.8 | 111 | -173 | 0.41 | -9.9 | -62.9 | -144.5 | -0.39 | 25,796 | 10 | -3.2 |
| P1 half 2R + breakeven | 34.4 | 141 | -166 | 0.45 | -7.1 | -60.1 | -141.7 | -0.37 | 24,640 | 13 | -0.4 |
| P2 half 2R + ATR | 39.8 | 111 | -175 | 0.42 | -8.1 | -61.1 | -142.7 | -0.38 | 25,062 | 10 | -1.4 |
| P3 half 2R + swing | 40.0 | 107 | -176 | 0.41 | -9.7 | -62.7 | -144.2 | -0.39 | 25,703 | 10 | -3.0 |

Every pooled 95% interval of net Rs/trade (resampled by month) is below zero (F2: -73.6 to -45.8). Every paired
"vs 2R" interval spans zero: the exit choice moves results by at most a few rupees a trade.
Slippage sensitivity (F2): 0% -45.4, 0.05% -59.7, 0.10% -74.0 Rs/trade. Charges average Rs 38.7 a trade.

## Decision rules (as pre-registered)
1. Selected trailing exit on dev 2017-18: P3 (-63.1). Paired vs 2R: dev -0.5, 2019 -5.4, 2020 -5.2 → **does not
   beat 2R.** The overall dev-best exit was F1 1R; it does not beat 2R either.
2. Rule positive? Net at 2x is negative in every split, every CI is below zero, walk-forward (exit chosen on earlier
   years: 2018 F1, 2019 F1, 2020 F3) loses -63.8 Rs/trade over 317 trades → **REJECTED**.
3. Robustness (all 1,144 triggered ideas, not only the daily pick): same picture; best T1 breakeven -60.7 vs 2R -63.7,
   difference +3.0 with interval -2.4 to +9.9 (spans zero); all exits net negative, gross -8 to -14.

## What this means for the owner
The entry, not the exit, is the problem: before any charges the average trade already loses a few rupees, and only
1 in 10 trades ever reaches 2R. Trailing turns a few +2R wins into breakeven exits and rarely catches a bigger move.
The live scan rule (EXP-0080, 2R) is unchanged; its forward test continues. One good day (BHARTIARTL, 3 Nov) is not
evidence either way. Gaps and fast markets can lose more than planned risk.

## Limitations
Unofficial minute bars; 126 large/mid caps chosen by the vendor in 2021 (survivorship); no order book; live quotes
are 1-3 minutes delayed; trailing a stop by hand in an app lags the rule; cost schedule unverified.
