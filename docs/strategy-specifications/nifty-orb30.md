# 30-minute NIFTY Opening Range Breakout: variant grid, out-of-sample and walk-forward (research only) — spec v0.1

Status: **PRE-REGISTERED** (written and committed before any 30-minute ORB number was computed). Registry: EXP-0071
(main grid, selection, out-of-sample and walk-forward), EXP-0072 (volume-confirmed variants, 2026 data only).

**Why:** Ashok asked (2026-11-03) for a serious validation of the 30-minute NIFTY Opening Range Breakout: standard,
volume-confirmed, VWAP-confirmed, both, and ATR opening-range filters; 1R/1.5R/2R/3R targets; opposite-range vs
volatility stop; opening-range widths; long vs short; trending vs sideways days; realistic Groww costs, spread and
slippage; no look-ahead or survivorship bias; out-of-sample and walk-forward validation; then 50 paper sessions for
the best candidate only if it shows positive net expectancy, acceptable drawdown and robust out-of-sample results.
Rules: ₹300 maximum planned risk per trade, one trade per day. Research and paper only; nothing here places orders.

## Sources (register row SR-0071)
* No peer-reviewed study of a 30-minute ORB on NIFTY was found (web search 2026-11-03; library hosts are blocked by
  the network, see `docs/research/source-register.md`). The rule is the generic practitioner ORB (Toby Crabel, *Day
  Trading with Short Term Price Patterns and Opening Range Breakout*, 1990, book, not read; tier 3 description) as
  Ashok specified it. Earlier project tests of the 15-minute ORB on NIFTY (EXP-0061/0064) and the 5-minute ORB on
  stocks (EXP-0070) were all REJECTED; nothing from them is used to set the parameters below.

## Data
| Item | Source | Window | Check |
| --- | --- | --- | --- |
| NIFTY 50 spot 1-min OHLC | `technovusin/nifty50-historical-data` (MIT, UNOFFICIAL), commit 7f94ced | 2020-01-01..2026-10-30 | each day ≥ 360 bars 09:15–15:29 and `nifty_intraday.day_check` vs NSE `ind_close_all` high/low within 0.05%; failing days dropped, never repaired |
| NIFTY 50 daily OHLC (official) | NSE `nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` | 2019-06..2026-10 | ATR14 and ADX14 (Wilder) from official daily bars, using only sessions before the trade date |
| Index "Volume" | same vendor, **2026 1-min files only**; meaning undocumented (likely summed constituent volume) | 2026-01..2026-10 | used only by EXP-0072 |

Survivorship: the instrument is the NIFTY 50 index itself (tradable through an index ETF), so there is no stock
selection and no survivorship in the universe. The vendor is unofficial; every used day must match NSE's own file.

**Disclosure:** NIFTY 2017–2026 was already read by EXP-0061/0064 (15-minute ORB, same data) and expiry days by
EXP-0054..0060. No split here is virgin data. "Out-of-sample" below means out of sample for the selection made in
this experiment, not unseen by the project. The only truly unseen data is forward paper data.

## Base rule (all variants share it)
* Opening range (OR) = high and low of the 1-minute bars 09:15–09:44 (30 bars, ≥ 28 required).
* Signal: first 5-minute close (09:15-anchored bars) above OR high (long) or below OR low (short), on bars ending
  09:50–13:00. **Only the first breakout of the day is considered** (either side); if it is rejected by a filter or
  the stop-width check, there is no trade that day. Entry at the open of the next 1-minute bar.
* Exit on 1-minute bars: stop checked before target within a bar (conservative); a bar opening beyond the stop fills
  at its open (gap loss beyond plan is kept); time exit at the 15:15 bar open (MIS square-off). Stop never moved.
* Skip if the stop is closer than 0.20% or farther than 2.0% from entry.
* One trade per day (it is the only instrument).

## Grid (selection space)
| Dimension | Values |
| --- | --- |
| Variant | **V0** standard; **V2** VWAP confirmation: long only if the signal bar closes above session VWAP, short only if below (2020–2025 have no volume, so VWAP = time-weighted average of typical price since 09:15, a proxy); **V4** ATR OR filter: trade only if 0.25 ≤ OR width / ATR14 ≤ 0.60 |
| Stop | **range**: other side of the OR; **atr**: entry ∓ 0.5 × ATR14 (daily, previous sessions) |
| Target | 1R, 1.5R, 2R, 3R (R = entry − stop distance) |
| Direction | both, long only, short only |

72 configurations. Only targets ≥ 2R are **eligible** to be selected (brief: minimum 1:2); 1R and 1.5R are reported
for comparison. 36 eligible configurations → multiple-testing risk is large; that is why the selected configuration
must also pass validation, test and walk-forward.

V1 (volume confirmation: signal 5-min bar volume ≥ 1.5 × mean volume of the same 5-min slot over the previous 20
sessions) and V3 (V1 + true volume-weighted VWAP) cannot be tested on 2020–2025 (no intraday volume for NIFTY, its
futures or NIFTYBEES in any free source found). They run as **EXP-0072 on 2026 only** (from the 21st session, so the
20-session baseline exists), side by side with V0 on the same days, as a diagnostic: too few trades for a verdict, so
EXP-0072 can only end as **DATA INSUFFICIENT** or REJECTED.

## Splits
| Split | Window | Use |
| --- | --- | --- |
| dev | 2020-01-01..2022-12-31 (halves: ..2021-06-30, 2021-07-01..) | selection: highest mean net R among eligible configs with ≥ 100 dev trades |
| validation | 2023-01-01..2024-12-31 | read once for the selected config (all configs reported) |
| test | 2025-01-01..2026-10-30 | read once for the selected config (all configs reported) |

**Walk-forward:** rolling 24-month training window, 6-month test window, step 6 months; test windows 2022-01..2022-06
through 2026-07..2026-10 (10 windows). In each window the eligible config with the highest training mean net R
(≥ 60 training trades) is chosen and traded in the next 6 months. The concatenated test-window trades are the
walk-forward out-of-sample record.

## Execution instrument, sizing and costs
* **NIFTY futures:** one lot's stop risk = stop points × lot size (65 from Jan 2026; 25 is the smallest lot NIFTY has
  had). Reported per trade; a trade is futures-feasible only if one lot risks ≤ ₹300 (4.6 points at lot 65).
* **NIFTY options:** an ATM option moves ≈ 0.5 × the index (delta approximation; no historical intraday option data);
  feasible only if 0.5 × stop points × lot ≤ ₹300. Buying far out-of-the-money options whose whole premium is ≤ ₹300 is
  a different, untested strategy (no OR stop) and is not evaluated.
* **NIFTYBEES (index ETF, NSE cash, MIS intraday):** modelled as index % moves on a ₹ notional (price = index × 0.01).
  Scenario A (₹300 rule): qty = largest integer with qty × (R + slippage both legs) + round-trip charges ≤ ₹300;
  notional is reported (it can need intraday leverage). Scenario B (₹15,000 capital, no leverage): also qty × entry ≤
  ₹15,000. ETF intraday deviation from the index (iNAV) is not modelled.
* Charges: Groww intraday as EXP-0061 (brokerage min(₹20, 0.1%) per order; STT 0.025% sell; NSE 0.00297%; SEBI 0.0001%;
  stamp 0.003% buy; GST 18%), rates from Groww help pages via web search (unverified on the live pricing page).
* Spread + slippage per side: base 0.03% (≈ 8 ticks of ₹0.01 on a ₹280 ETF; covers the 1–2 tick spread plus delay);
  sensitivity 0%, 0.03%, 0.05%, 0.10%. Stress = 2× slippage and 2× charges.

## Diagnostics (reported, never used for selection)
* OR width: trades by quartile of OR width / ATR14 (quartile edges fixed on dev).
* Long vs short (also part of the grid).
* Regime known before the open: previous-day ADX14 ≥ 25 "trending", < 20 "sideways", else neutral.
* Day type known only after the close (look-ahead, labelled as such): trend day if |close − open| ≥ 0.6 × day range.

## Metrics
Trades, win rate (net), average win and loss (₹), profit factor, expectancy (₹ and R), max drawdown (₹, daily
equity), longest losing streak, charges, slippage sensitivity, 95% month-clustered bootstrap interval of mean net R,
target/stop/time exit shares, futures/option feasibility share.

## Acceptance (selected config, scenario A) — PAPER CANDIDATE only if every item holds
1. dev ≥ 100 trades; dev mean net R > 0 with bootstrap interval above 0; dev PF ≥ 1.15; both dev halves > 0; dev stress > 0.
2. validation mean net R > 0 and validation stress > 0.
3. test mean net R > 0.
4. walk-forward out-of-sample mean net R > 0 with interval above 0, and ≥ 6 of 10 windows positive.
5. walk-forward max drawdown ≤ 15R (₹4,500, 30% of ₹15,000).
6. a real instrument exists where ₹300 risk fits (otherwise the strategy is not tradable at this risk size).
Otherwise **REJECTED** and the daily status is **NO TRADE**. A PAPER CANDIDATE is paper traded for ≥ 50 sessions
(EXP-0073, pre-registered separately) with predicted vs actual price logging. No live deployment is ever recommended
from a backtest alone; live trading also needs the owner's separate written authorization (CLAUDE.md rule 1).

## Known limitations
Unofficial 1-minute data; index stands in for the ETF (spread, iNAV deviation and auction effects not modelled); no
order book; target fills assumed at the target price; charges not verified on Groww's live page; no historical
intraday volume before 2026; no news/event filter; gaps and halts can lose more than the planned ₹300.

## Changelog
* v0.1 (2026-11-03): first version, pre-registered before any run.
