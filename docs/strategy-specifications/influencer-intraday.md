# Popular Indian influencer intraday setups (research only) — spec v0.1

Status: **EXP-0073..0077 REJECTED, EXP-0078 DATA INSUFFICIENT** (run 2026-11-03, report
`reports/backtests/EXP-0073-0078-report.md`; pre-registered with code and tests in 878473cd before the run). Registry: EXP-0073..0078. Source register rows SR-0073..SR-0078.
Code: `src/trading_research/strategies/influencer.py`, runner `src/trading_research/backtesting/run_influencer.py`,
tests `tests/test_influencer.py`. Nothing here places orders.

**Why:** after every textbook intraday rule failed (EXP-0061..0072), Ashok asked (2026-11-03) "how are people making
money with simple strategies? check the ideas influencers share — who knows, they might work". This tests the most
widely shared Indian retail setups that the project had **not** tested yet, each in its most common public form,
under the owner brief's risk rules (₹300 maximum planned risk, one trade a day, Groww intraday charges).

## What is tested
| EXP | Rule | Popular source (register row) | Tier |
| --- | --- | --- | --- |
| 0073 | `ema5` — "5 EMA strategy" | Subhashish Pani, Power of Stocks (SR-0073) | 3–4 |
| 0074 | `st_flip` — Supertrend(10, 3) on 5-min, exit on opposite flip | Indian YouTube/blogs; marketcalls (SR-0074) | 4 |
| 0075 | `st_2r` — as 0074 with a 2R target (brief's minimum 1:2) | as 0074 | 4 |
| 0076 | `ohol` — Open = High / Open = Low, first 15 minutes | broker-education blogs, tradingqna (SR-0076) | 2 (broker edu) / 4 |
| 0077 | `cpr` — narrow Central Pivot Range breakout | Frank Ochoa, *Secrets of a Pivot Boss* (2010); Indian YouTube (SR-0077) | 3 / 4 |
| 0078 | 9:20 ATM short straddle, 25% per-leg stop | forums, AlgoTest/Streak users, marketcalls (SR-0078) | 4 |

**EXP-0078 is not run: DATA INSUFFICIENT.** It needs intraday NIFTY option prices (no free source; we have only
daily F&O bhavcopy), and it fails the risk rules before any data: one NIFTY lot (65) short straddle with a 25% stop on
a ~₹100–150 leg risks ~₹1,600–2,400 per leg, far above ₹300, and options selling is a derivative position the risk
policy forbids. Recorded so it is not re-proposed without new data.

Not repeated here (already REJECTED): ORB 5/15/30-min, breakout-retest, EMA 9/15 pullback and scalp, daily
Supertrend, 44 MA, Minervini, Turtle, golden cross, RSI(2), SMC, expiry-day ideas, gap fade/follow, intraday momentum.

## Rules (all on 1-minute bars; 5- and 15-minute bars are anchored at 09:15; indicators run continuously across
sessions and use closed bars only)
Shared: entries 09:15–14:30; exit at the 15:15 bar open (MIS square-off) if nothing else; stop checked before target
within a bar; a bar opening through the stop fills at its open (gap loss beyond plan kept); a stop-order entry fills at
the trigger or at the bar open if it opens beyond it, and that entry bar can stop out but not reach the target.
Stop-width check: 0.10%–2.0% of entry (below 0.10% a 0.03% slippage each side eats over half of R and ₹300 risk needs
over ₹3 lakh notional). Stop never moved.

**`ema5` (EXP-0073)** — reconstruction of the public descriptions (TradingView scripts citing Power of Stocks; the
original videos could not be opened):
* Sell on 5-min bars: an **alert candle** is a bar entirely above EMA 5 (low > EMA 5 of the 5-min closes). If the
  **next** bar trades below the alert low → short at the alert low (stop order). If the next bar does not break it and
  is itself entirely above EMA 5, it becomes the new alert; otherwise the alert lapses.
* Buy on 15-min bars: mirror (alert = bar entirely below EMA 5 of 15-min closes; long on a break of its high).
* Stop: the other end of the alert candle (high for sells, low for buys). Target: **1:3** (the published minimum).
* One trade a day: the earliest trigger of either side that passes the width check.
* Ambiguities resolved here: the alert lasts one bar; alerts start from today's first bar; target fixed at 3R (no
  trailing); both instruments the sources name (index and stocks) are tested.

**`st_flip` / `st_2r` (EXP-0074 / 0075)** — Supertrend(10, 3) (Wilder ATR over 10 5-min bars, band multiplier 3):
* Signal: the first 5-min close that flips direction on a bar ending 09:45–14:25 (earlier flips mostly reflect the
  overnight gap); entry at the next 1-min open in the flip direction.
* Stop: the Supertrend line at the signal bar, fixed. Exit: the next opposite flip (at the next 1-min open), the stop,
  or 15:15. `st_2r` adds a 2R target.

**`ohol` (EXP-0076)** — broker-education consensus (Kotak, Bajaj, Angel One, Swastika, StockGro):
* Window: first 15 minutes (09:15–09:29). Day open = the 09:15 bar's open. **Open = Low** if the window low is within
  0.02% of the open (tolerance instead of exact equality, since vendor prices are split-adjusted; sources do not
  agree on a tolerance) → long; **Open = High** mirror → short; both or neither → no trade.
* Entry: the 09:30 bar open. Stop: the 15-min low (long) / high (short). Target 2R ("at least 1:2"). Exit 15:15.
* Stocks: when several qualify, the highest first-15-minute relative volume (vs the previous 20 sessions) wins, ties
  by liquidity. Indices: NIFTY before BANK NIFTY.

**`cpr` (EXP-0077)** — Ochoa's CPR as reported by secondary sources (book not read):
* From the previous session: P = (H+L+C)/3, BC = (H+L)/2, TC = 2P − BC; top = max(TC, BC), bottom = min.
  Width = (top − bottom)/P. **Narrow** if the width is at or below the 25th percentile of the previous 20 sessions'
  widths (LuxAlgo-style relative definition; fixed thresholds of 0.25%/0.5% are also published).
* Signal (narrow days only): the first 15-min bar close from the 09:30–09:44 bar onward (bar ending 09:45..13:00) above
  the top (long) or below the bottom (short); a day that opens beyond the CPR and stays signals at 09:45. Entry at the
  next 1-min open. Stop: the other side of the CPR. Target 2R. First signal only.

## Data, universe, splits (same as EXP-0061..0066)
* Stocks: `ShabbirHasan1/NSE-Data` 1-min, 126 large/mid caps 2017–2020, each day checked against NSE bhavcopy
  (98,308 stock-days pass); eligible if 20-day median traded value ≥ ₹50 crore and previous close ≥ ₹50.
  Survivorship: the vendor's 2021 list. CPR uses vendor-scale daily bars and needs the previous session to pass.
* Indices: NIFTY 50 (technovusin 1-min, 2017-04..2026-10) and BANK NIFTY (sandeepkapri 1-min ..2026-04-22), each day
  checked against NSE `ind_close_all`; CPR from the official daily bars. Traded as NIFTYBEES/BANKBEES (index/100).
* Splits: stocks dev 2017–2018 (halves by year), validation 2019, holdout 2020; indices dev 2017-04..2021 (halves at
  2019-07), validation 2022–2023, holdout 2024..2026-10.
* **Disclosure: none of these periods is unseen.** All were read by EXP-0061..0066 (and indices by 0054..0060,
  0068..0072). "Holdout" here only means it plays no role in any choice made for these rules — and no choice is made:
  each rule is fixed above, with no parameter search. The only truly unseen data is forward paper data.

## Costs, sizing, scenarios (as EXP-0061)
Groww intraday charges (brokerage min(₹20, 0.1%) per order, STT 0.025% sell, exchange 0.00297%, SEBI 0.0001%, stamp
0.003% buy, GST 18%; rates via web search, not the live page). Slippage per side 0.02% stocks, 0.03% index ETF;
sensitivity 0 / base / 0.05% / 0.10%; stress = 2× charges and 2× slippage. Scenario A: quantity so that stop loss +
slippage + charges ≤ ₹300. Scenario B: also notional ≤ ₹15,000 (no leverage). Index futures: one smallest-ever lot's
risk reported (NIFTY 25, BANK NIFTY 15).

## Walk-forward
No parameter is fitted, so walk-forward reduces to rolling out-of-sample windows: consecutive 6-month windows over the
whole period (stocks 8, indices 20), each needing ≥ 10 trades to count.

## Acceptance (per rule and universe, scenario A) — PAPER CANDIDATE only if every item holds
1. dev ≥ 100 trades; dev mean net R > 0 with the month-clustered 95% interval above 0; dev PF ≥ 1.15; both dev halves
   > 0; dev stress > 0.
2. validation > 0 and validation stress > 0.
3. holdout > 0.
4. ≥ 60% of counted 6-month windows positive.
Otherwise **REJECTED**. Ten rule × universe tests are run at once: one pass would still need forward paper testing
(≥ 50 sessions, pre-registered separately) before anything else; no live use is ever recommended from a backtest
(CLAUDE.md rule 1).

Diagnostics (never used for the verdict): raw signals without the width check (gross R, median stop %), exit reasons,
by year, by instrument, all-instrument signals, scenario B.

## Known limitations
Rules are reconstructions of informal sources (no creator publishes a full rule book we could read); unofficial 1-min
data; stocks only to 2020 and survivorship-biased; ETF modelled as index/100 (spread and iNAV not modelled); target
fills assumed at the price; charges not checked on Groww's live page; gaps can lose more than ₹300.

## Changelog
* v0.1 (2026-11-03): first version, pre-registered before any run of these rules. Tests run: `tests/test_influencer.py`.
* v0.1 result (2026-11-03): one run, no rule or parameter changed. All 10 rule × universe tests negative after costs in
  every split (net −0.04R to −0.49R per trade); rolling 6-month windows 2/8 positive (5 EMA stocks) and 0 elsewhere.
  Only the 5 EMA is positive before costs in every split (stocks +0.05..+0.32R, indices +0.07..+0.14R); costs at ₹300
  risk are 0.2–0.45R. No paper phase. Impact on earlier results: none. A new test of a 5 EMA variant (e.g. wider stops)
  would be a new hypothesis and needs unseen (forward) data.
