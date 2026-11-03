# EXP-0071/0072 — 30-minute NIFTY Opening Range Breakout: REJECTED (NO TRADE)

Run 2026-11-03, spec `docs/strategy-specifications/nifty-orb30.md` v0.1 (pre-registered in 2c426f8f, code and tests
committed in 603e64b0 before the run). Numbers: `EXP-0071-0072.json`; every configuration: `EXP-0071-grid.csv`;
trades: `EXP-0071-selected-trades.csv`, `EXP-0071-walkforward-trades.csv`. All values are **calculated** from
unofficial NIFTY 1-minute data whose every used day matched NSE's official daily high/low; none is a forecast.

## Verdict
* **EXP-0071: REJECTED.** Not one of the 72 configurations (3 variants × 2 stops × 4 targets × 3 directions) has a
  positive mean net R in dev, validation or test. The configuration selected on dev (`V2|atr|2R|short`) loses
  −0.20R / −0.22R / −0.22R per trade (dev / validation / test). Walk-forward (10 windows, re-selected each time):
  **0 of 10 windows positive**, 518 trades, −0.26R per trade (95% interval −0.31..−0.22), −₹40,407, max drawdown
  −136R. Only 1 of 14 acceptance checks passes (an instrument exists where ₹300 fits).
* **EXP-0072 (volume confirmation): DATA INSUFFICIENT.** Intraday NIFTY volume exists only in the vendor's 2026 files
  (meaning undocumented). From 2 Feb 2026 (184 sessions) the volume filter leaves 15–16 trades, all variants
  −0.46..−0.52R net and negative even before costs.
* **Paper phase: not started.** The brief and the spec allow paper trading only for a candidate that passes
  out-of-sample and walk-forward; none does. Daily status for this strategy: **NO TRADE**.
* **Live deployment: not recommended** (no positive net expectancy, drawdown far beyond limits, no robust OOS result).

## Can ₹300 risk be traded at all? (calculated, per trade, standard ORB)
| Instrument | One-unit risk at the ORB stop | Fits ₹300? |
| --- | --- | --- |
| NIFTY futures, 1 lot = 65 (since Jan 2026) | median stop 90 points → **₹5,826** (selected config 108 pts → ₹7,028) | **0% of trades** (also 0% at the smallest-ever lot of 25) |
| NIFTY ATM option, 1 lot (delta ≈ 0.5) | ≈ **₹2,913** | **0% of trades** |
| NIFTYBEES ETF (NSE cash, MIS) | any quantity | yes: median 234 units, notional **₹44,133** (needs ~3× intraday leverage on ₹15,000) |
| NIFTYBEES with ₹15,000 and no leverage | max ~53 units → risk ~₹60–120 | yes, but charges are a bigger share: −₹47 per trade |

So the only instrument where the ₹300 rule works is the ETF, and that is where the costs hurt most.

## Why it fails (calculated, then interpretation)
* **Gross edge is small:** mean gross R (before charges and slippage) −0.06..+0.18 across all configs and splits;
  standard ORB +0.06R. Short breakouts are slightly better before costs (+0.10..+0.13R in all three splits).
* **Costs at ₹300 risk are ~0.3R:** Groww intraday charges average ₹57–65 per round trip (two ₹20 brokerage orders
  plus STT, exchange, GST, stamp on a ~₹40,000 notional) ≈ 0.21R, plus 0.03% spread/slippage per side ≈ 0.08R.
* **Even at zero slippage** every config stays negative (selected −0.13R, standard −0.17..−0.19R).
* Post-hoc check (not pre-registered, not used for the verdict): on one 65-unit futures lot, ignoring the ₹300 rule,
  costs fall to ~0.1R and the short side is **≈ 0R net** (−0.07..+0.04R across splits), i.e. still no edge, while risking
  ~₹6,000–7,000 per trade.
* Interpretation: NIFTY's 30-minute range breaks are close to coin flips; a 2R target is reached on only 7–10% of
  trades and most exit at 15:15 (average win ₹140–190 against average loss ₹175–205).

## Selected configuration and the standard ORB (scenario A: ₹300 risk via NIFTYBEES, one trade a day)
| Config | Split | Trades | Win rate | Avg win ₹ | Avg loss ₹ | PF | Expectancy ₹ | Mean net R (95% CI) | Gross R | Max DD ₹ | Losing streak | Stress R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Selected `V2\|atr\|2R\|short` | dev 2020–22 | 322 | 33% | 190 | −184 | 0.51 | −60 | −0.20 (−0.28..−0.12) | +0.08 | −20,273 | 11 | −0.46 |
|  | validation 2023–24 | 220 | 32% | 170 | −176 | 0.46 | −65 | −0.22 (−0.30..−0.14) | +0.11 | −14,969 | 10 | −0.51 |
|  | test 2025–26 | 199 | 35% | 148 | −181 | 0.44 | −67 | −0.22 (−0.28..−0.15) | +0.11 | −14,606 | 7 | −0.52 |
| Standard `V0\|range\|2R\|both` | dev | 659 | 34% | 176 | −205 | 0.44 | −75 | −0.25 (−0.30..−0.20) | +0.06 | −50,161 | 13 | −0.54 |
|  | validation | 440 | 32% | 155 | −200 | 0.37 | −86 | −0.29 (−0.34..−0.24) | +0.05 | −38,567 | 10 | −0.61 |
|  | test | 397 | 33% | 139 | −185 | 0.36 | −79 | −0.27 (−0.32..−0.21) | +0.06 | −32,468 | 11 | −0.57 |

Stress = 2× charges and 2× slippage. Every calendar year 2020–2026 is negative for both (−0.15..−0.31R).

**Slippage sensitivity (mean net R, dev / validation / test):**
| Config | 0% | 0.03% (base) | 0.05% | 0.10% |
|---|---|---|---|---|
| Selected | −0.13 / −0.13 / −0.13 | −0.20 / −0.22 / −0.22 | −0.24 / −0.27 / −0.27 | −0.32 / −0.37 / −0.37 |
| Standard | −0.17 / −0.19 / −0.17 | −0.25 / −0.29 / −0.27 | −0.30 / −0.34 / −0.32 | −0.39 / −0.44 / −0.41 |

## Comparisons Ashok asked for (mean net R, dev / validation / test; full table in `EXP-0071-grid.csv`)
* **Targets** (standard ORB, range stop, both sides): 1R −0.29/−0.29/−0.28 · 1.5R −0.27/−0.29/−0.28 ·
  2R −0.25/−0.29/−0.27 · 3R −0.24/−0.28/−0.27. Larger targets lose slightly less; none is close to positive.
* **Stop:** opposite-range vs 0.5×ATR14: 2R both −0.25/−0.29/−0.27 vs −0.24/−0.24/−0.26. Similar.
* **VWAP confirmation (V2):** identical to V0 on every trade. With no index volume before 2026, VWAP is a
  time-weighted proxy, and a close beyond the 30-minute range is always on the right side of it, so the filter
  never removes a trade. True VWAP exists only for 2026 (EXP-0072, too few trades).
* **ATR opening-range filter (V4, 0.25 ≤ OR/ATR14 ≤ 0.60):** no better (2R both −0.29/−0.29/−0.25).
* **Opening-range width** (standard ORB, quartiles of OR/ATR14 fixed on dev: 0.27 / 0.35 / 0.44): narrowest quartile
  −0.21R (gross +0.20R), others −0.25..−0.32R. Narrow ranges move more relative to the stop, but the smaller stop
  means a bigger ETF notional, so charges grow too.
* **Long vs short** (standard ORB, all years): long −0.29R (gross +0.02R), short −0.24R (gross +0.10R).
* **Trending vs sideways (known before the open, previous-day ADX14):** ADX ≥ 25 −0.25R, ADX < 20 −0.26R, neutral
  −0.29R. No usable difference.
* **Trend day vs non-trend day (known only after the close, LOOK-AHEAD, cannot be traded):** trend days +0.20R,
  other days −0.55R. ORB only works on days you cannot identify in advance with this data.

## Walk-forward (24-month train, 6-month test, re-selected each window)
| Test window | Selected on training | Trades | Mean net R |
|---|---|---|---|
| 2022 H1 | V0\|atr\|2R\|short | 61 | −0.26 |
| 2022 H2 | V0\|atr\|2R\|short | 57 | −0.16 |
| 2023 H1 | V0\|range\|3R\|short | 54 | −0.24 |
| 2023 H2 | V0\|range\|3R\|short | 49 | −0.37 |
| 2024 H1 | V0\|range\|3R\|short | 56 | −0.19 |
| 2024 H2 | V4\|atr\|2R\|long | 49 | −0.31 |
| 2025 H1 | V0\|atr\|3R\|short | 56 | −0.34 |
| 2025 H2 | V4\|atr\|2R\|long | 54 | −0.31 |
| 2026 H1 | V0\|atr\|3R\|short | 54 | −0.20 |
| 2026 Jul–Oct | V4\|atr\|3R\|short | 28 | −0.22 |

Every training window's best configuration was already negative (−0.18..−0.25R), so the walk-forward could only
pick the least-bad loser.

## Data used
* NIFTY 50 1-min, technovusin commit 7f94ced (UNOFFICIAL): 1,695 sessions 2020-01-01..2026-10-30, **1,650 passed**
  the check against NSE `ind_close_all` (failures: 35 high/low mismatch > 0.05%, 7 no official file, 3 too few bars).
  1,523 days had a breakout by 13:00.
* NSE official daily NIFTY 50 (nsearchives `ind_close_all`, 2019-06..2026-10) for ATR14/ADX14 (previous sessions only).
* Bias controls: signals use only bars closed before entry; entry at the next 1-minute open; stop checked before
  target inside a bar; gap through the stop fills at the open; daily indicators shifted one session; single index,
  so no survivorship in the universe. Tests: `tests/test_orb30.py`.

## Limitations
Unofficial minute data; the index stands in for NIFTYBEES (ETF spread, iNAV deviation not modelled; 0.03%/side
covers a 1–2 tick spread plus delay); target fills at the target price; Groww charges from help pages via web search,
not the live pricing page; no news/event filter; gaps and halts can lose more than the planned ₹300. NIFTY 2017–2026
was already read by EXP-0061/0064 (15-minute ORB), so no split here is virgin data; the result agrees with them.
After this run every 2020–2026 split is used for 30-minute ORB ideas; any changed rule needs forward data.
