# Three intraday strategy families on liquid NSE stocks and indices (research only) — spec v0.1

Status: **REJECTED, all six** (run 2026-11-02, report `reports/backtests/EXP-0061-0066-report.md`). Pre-registered
before any run (5121953c). Registry: EXP-0061..0066.

**Why:** Ashok rewrote the project brief as "AI Trading Desk India" (2026-11-02). Section 4 asks for three strategy
families to be backtested with out-of-sample validation before any of them is used: Opening Range Breakout,
Breakout and Retest, and EMA 9/15 Trend Pullback, under section 5 risk rules (₹300 maximum planned risk per trade,
one trade per day, at least 1:2 risk/reward, costs and slippage included). Each family has exactly one base rule and
one filtered rule, fixed here before any data is read, so every split is out of sample for rules nobody tuned.
Research and paper only; nothing here places orders.

## Data (all unofficial vendor 1-minute bars, each day checked against official NSE daily files)
| Universe | Source | Window used | Gate 1 (per day) |
| --- | --- | --- | --- |
| 126 liquid NSE stocks (NIFTY 50 + midcap names, alphabetical to TATACHEM, chosen by the vendor in 2021) | `ShabbirHasan1/NSE-Data` (GitHub, GPL-3.0) 1-min with volume, split/bonus adjusted | 2017-01-02..2020-12-31 | ≥ 360 bars 09:15–15:29; the vendor's day high and low, each scaled to the official NSE CM bhavcopy (EQ) high/low, must give the same factor within 0.10%; prices used = vendor × that factor (real traded prices) |
| NIFTY 50 index | `technovusin/nifty50-historical-data` (MIT), as PR #22 | 2017-04-03..2026-10-30 | `nifty_intraday.day_check` vs NSE `ind_close_all` (0.05%) |
| NIFTY BANK index | `sandeepkapri/BankNifty-Data` (MIT) 1-min | 2017-04-03..2026-04-22 | same check vs NSE `ind_close_all` |

Vendor symbols are mapped to the NSE symbol in force on each date via NSE `symbolchange.csv` (e.g. COFORGE was
NIITTECH until 2020); the factor check confirms the match. A day that fails gate 1 is dropped, never repaired.
**Known bias:** the stock list is the vendor's 2021 choice of large and mid caps (survivorship: firms that did well
enough to be in those indices in 2021), and stops at "T" (no TCS, TATAMOTORS, TITAN, WIPRO...). This flatters
long trades. Indices have no volume.

### Daily liquidity filter (stocks, point in time)
A stock is eligible on day t only if its median official traded value over the 20 sessions before t is ≥ ₹50 crore
and its previous official close is ≥ ₹50.

## Splits (each read once, all reported)
| Universe | Dev (halves) | Validation | Holdout |
| --- | --- | --- | --- |
| Stocks | 2017-01..2018-12 (2017, 2018) | 2019 | 2020 |
| Indices | 2017-04..2021-12 (2017-04..2019-06, 2019-07..2021-12) | 2022-2023 | 2024-01..2026-10 |

Disclosure: NIFTY expiry days 2019–2026 were already read by EXP-0054..0060 (incl. an expiry-day ORB); about one
day in five of the index sample is therefore not fresh. Nothing from those runs is used to set rules here.

## Shared mechanics
* Signals use 5-minute bars built from the 1-minute bars (09:15 anchor). A signal known at a 5-min bar's close
  enters at the open of the next 1-minute bar. Exits are checked on 1-minute bars: stop before target in the same
  bar (conservative); a bar opening beyond the stop fills at its open. Time exit at the 15:15 open (MIS square-off).
* R = |entry − stop|. Target = entry ± 2R (1:2), never changed. Stop never moved. One position per instrument.
* Skip a signal if the stop is closer than 0.20% or farther than 2.0% of entry (cost-dominated or too wide).
* **One trade per day per universe** (stocks; indices): among all eligible signals that day, the one with the
  earliest entry time; ties by higher trigger-bar relative volume (stocks), then higher 20-day traded value
  (stocks) or NIFTY before BANK NIFTY (indices). "All signals" (first signal per instrument per day) are also
  reported as a diagnostic of the raw edge, but the verdict uses the one-trade-a-day series.
* No entries after 14:30.
* Indicators: EMA 9 and EMA 15 on 5-min closes, continuous across sessions (each value uses only earlier bars).
  Session VWAP = cumulative Σ(typical price × volume)/Σ volume from 09:15 (stocks); indices use the time-weighted
  average of typical price (no volume; a proxy, not true VWAP). Relative volume (RVOL) = trigger 5-min bar volume /
  mean volume of the same 5-min slot over the previous 20 sessions (stocks only).

## Rules
| EXP | Family | Rule |
| --- | --- | --- |
| 0061 | Opening Range Breakout (base) | OR = 09:15–09:30 high/low. First 5-min close above OR high → long, below OR low → short; signal bars ending 09:35–11:00; only the first breakout of the day per instrument. Stop = other side of the OR. |
| 0062 | Breakout and Retest (base) | Level = previous session official high (long) / low (short); the day must open on the near side of it. Breakout = first 5-min close beyond the level (bars ending 09:35–13:30). Retest = within the next 12 bars, a bar whose low ≤ level × 1.001 and close > level (mirror for shorts). Invalidated if, before a retest, a bar closes below level × 0.999. Entry next 1-min open after the retest bar. Stop = min(retest bar low, level) × (1 − 0.05%) (mirror). |
| 0063 | EMA 9/15 Trend Pullback (base) | Trend up at a 5-min close: EMA9 > EMA15, EMA15 > EMA15 three bars earlier, close > session VWAP. Pullback bar: trend up, low ≤ EMA9, close > EMA15 (bars ending 09:45–14:25). Entry: buy-stop at the pullback bar's high during the next 5 minutes only (fill = max(high, 1-min open)); else the setup lapses and a new pullback is awaited. Stop = pullback bar low × (1 − 0.05%). Mirror for shorts. |
| 0064 | ORB + filter | EXP-0061 plus the filter below |
| 0065 | Breakout and Retest + filter | EXP-0062 plus the filter below |
| 0066 | EMA Pullback + filter | EXP-0063 plus the filter below |

**Filter (same for all three, fixed):** (a) higher timeframe: longs only if the previous official close is above its
20-session average close, shorts only if below; (b) market: longs only if NIFTY 50 at the signal bar's close is above
its 09:15 open, shorts only if below; (c) participation (stocks only): trigger bar RVOL ≥ 1.5.

## Sizing and costs
* **Scenario A (₹300 rule, the brief):** qty = largest integer with qty × (R + slippage on both legs) + round-trip
  charges ≤ ₹300. Notional is reported (it can need intraday margin or more capital).
* **Scenario B (₹15,000 capital, no leverage):** as A but also qty × entry ≤ ₹15,000.
* Indices are traded as an index ETF in cash (NIFTYBEES / BANKBEES style): index % moves on a notional, same equity
  intraday charges. Futures are rejected outright when one lot's stop risk exceeds ₹300; this is reported per trade.
* Charges (Groww help page "What are intraday charges", read via web search 2026-11-02; unverified on the live
  pricing page): brokerage min(₹20, 0.1% of order value) per order, minimum min(₹5, 2.5%); STT 0.025% on the sell
  leg; NSE transaction 0.00297% both legs; SEBI 0.0001% both legs; stamp duty 0.003% on the buy leg; GST 18% on
  brokerage + transaction + SEBI.
* Slippage per side: base 0.02% (stocks, ≥ ₹50 crore/day) and 0.03% (index ETF); sensitivity 0%, base, 0.05%, 0.10%.
  Stress = 2× slippage and 2× charges.

## Metrics (per rule, per split, scenario A and B)
Trades, win rate (net), average winning and losing trade (₹), profit factor, expectancy (₹ and R), max drawdown (₹,
daily equity), longest losing streak, total charges, slippage sensitivity, 95% month-clustered bootstrap interval of
mean net R.

## Acceptance (per rule, scenario A, one-trade-a-day series)
Paper candidate (forward tracking only, never a live signal) only if all hold: dev ≥ 100 trades; dev mean net R > 0
with the bootstrap interval above 0; dev profit factor ≥ 1.15; both dev halves > 0; dev stress > 0; validation mean
net R > 0 and stress > 0; holdout mean net R > 0. For stocks and indices separately. Six rules × two universes = 12
tries, so one pass by luck is plausible; that is why validation and holdout must both agree. Otherwise **REJECTED**.
After this run every split above is used; any changed rule needs new forward data.

## Known limitations
Unofficial 1-minute data; survivorship in the stock list; no order book (fills at bar prices plus a fixed
slippage); index results stand in for an ETF whose own spread and tracking error are not modelled; cost rates
not verified on the broker's live page; no intraday news or circuit-limit handling; gaps and halts can lose more
than the planned ₹300.

## Changelog
* v0.1 (2026-11-02): first version, pre-registered before any run.
* v0.1 result (2026-11-02): one run, no parameter changed. Every rule loses after charges in every split, for stocks
  and indices, at 0–0.10% slippage; all six REJECTED. Tests: `tests/test_intraday_families.py` (rules, no look-ahead,
  charges, sizing), full suite passing. Impact on earlier results: none. All splits listed above are now used, so a new
  holdout does not exist for these data; any revised rule needs forward paper data.
