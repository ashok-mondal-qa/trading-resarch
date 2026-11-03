# EXP-0073..0078 — Popular Indian influencer intraday setups: all REJECTED (NO TRADE)

Run 2026-11-03, spec `docs/strategy-specifications/influencer-intraday.md` v0.1 (pre-registered with code and tests in
878473cd before the run). Numbers: `EXP-0073-0077.json`; one-trade-a-day trades: `EXP-00xx-{stocks,indices}-trades.csv`.
Every value is **calculated** from unofficial 1-minute data whose every used day matched NSE's official daily files;
none is a forecast. Sources: `docs/research/source-register.csv` rows SR-0073..SR-0078 (all SEARCH-VERIFIED at best:
the network blocks YouTube, Instagram, TradingView and most broker sites, so no original video or page was opened).

## Verdict
| EXP | Setup (source) | Stocks 2017–2020 net R per trade dev / val / holdout | NIFTY + BANK NIFTY 2017–2026 dev / val / holdout | Status |
| --- | --- | --- | --- | --- |
| 0073 | 5 EMA (Power of Stocks) | −0.13 / −0.04 / −0.19 | −0.40 / −0.37 / −0.39 | REJECTED |
| 0074 | Supertrend(10,3) 5-min, flip exit | −0.25 / −0.14 / −0.15 | −0.27 / −0.26 / −0.30 | REJECTED |
| 0075 | Supertrend + 2R target | −0.27 / −0.15 / −0.16 | −0.27 / −0.29 / −0.30 | REJECTED |
| 0076 | Open = High / Open = Low | −0.34 / −0.23 / −0.19 | −0.32 / −0.49 / −0.37 | REJECTED |
| 0077 | Narrow CPR breakout | −0.24 / −0.32 / −0.25 | −0.34 / −0.32 / −0.31 | REJECTED |
| 0078 | 9:20 short straddle | not run | not run | DATA INSUFFICIENT |

R = the planned ₹300 risk. **Not one of the 10 rule × universe tests is positive after costs in any split.** Rolling
6-month windows (the walk-forward for fixed rules): 5 EMA on stocks 2 of 8 positive; every other test **0 of 8**
(stocks) or **0 of 20** (indices). Daily status from these setups: **NO TRADE**. Paper phase: not started (nothing
passed). Live use: not recommended.

## Detail (scenario A: ₹300 risk incl. charges, one trade a day; dev split unless stated)
| | Trades dev/val/hold | Win rate | Avg win ₹ | Avg loss ₹ | Profit factor | Expectancy ₹ | Max DD ₹ (dev) | Longest losing run | Charges ₹/trade | Gross R dev/val/hold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5 EMA stocks | 490/243/244 | 35% | 405 | −275 | 0.78 | −40 | −26,573 | 13 | 62 | **+0.20 / +0.32 / +0.05** |
| 5 EMA indices | 1116/460/630 | 28% | 310 | −286 | 0.42 | −119 | −132,535 | 14 | 78 | +0.07 / +0.14 / +0.13 |
| Supertrend stocks | 475/241/237 | 27% | 184 | −171 | 0.41 | −74 | −35,180 | 11 | 51 | −0.06 / +0.08 / +0.04 |
| Supertrend indices | 987/408/548 | 28% | 222 | −195 | 0.44 | −80 | −78,959 | 14 | 65 | +0.08 / +0.11 / +0.06 |
| OHOL stocks | 477/241/237 | 32% | 250 | −261 | 0.44 | −99 | −47,426 | 12 | 56 | −0.12 / −0.01 / +0.04 |
| OHOL indices | 507/155/183 | 36% | 198 | −263 | 0.43 | −97 | −49,467 | 10 | 70 | +0.09 / −0.17 / +0.04 |
| CPR stocks | 457/242/231 | 36% | 233 | −245 | 0.54 | −71 | −32,587 | 16 | 58 | +0.02 / −0.09 / −0.04 |
| CPR indices | 433/181/241 | 34% | 162 | −238 | 0.35 | −103 | −44,765 | 11 | 66 | −0.03 / +0.01 / +0.05 |

(Supertrend with a 2R target is within 0.02R of the flip-exit version everywhere; see the JSON.)

**Slippage sensitivity** (mean net R, dev / val / holdout): at **zero** slippage, only 5 EMA on stocks in validation is
above zero (+0.03); everything else stays negative (5 EMA indices −0.24/−0.20/−0.21, Supertrend indices −0.16/−0.15/
−0.19, OHOL stocks −0.30/−0.20/−0.15, CPR stocks −0.19/−0.27/−0.21). At 0.10% per side every test is −0.23R or worse.
**Stress** (2× charges and slippage): −0.30R to −0.87R everywhere.

**₹15,000 without leverage** (scenario B, notional capped at ₹15,000): every test loses more per R (−0.15R to −0.62R),
because the same ₹20 brokerage orders sit on a smaller position. Index setups need a median ₹50,000–95,000 NIFTYBEES
notional to risk ₹300, i.e. 3–6× MIS leverage on ₹15,000.

**Futures/options:** one smallest-ever index lot (NIFTY 25, BANK NIFTY 15) at these stops risks a median ₹850 (5 EMA),
₹1,283 (OHOL), ₹1,723 (Supertrend), ₹1,830 (CPR): **0–1.6% of trades fit ₹300.** Today's lots (65 / 30) are worse.

## Why they fail (calculated, then interpretation)
* **Costs are 0.2–0.45R per trade at ₹300 risk.** Groww intraday charges average ₹46–80 a round trip (two ₹20
  brokerage orders + STT, exchange, GST, stamp) plus 0.02–0.03% slippage each side. The 5 EMA's stops are tiny on the
  index (median 0.15–0.17% of price; raw signals without the width check also 0.14–0.17%), so ₹300 needs ~₹90,000
  notional and costs eat ~0.45R.
* **Gross edges are zero or small.** Before any cost, Supertrend, OHOL and CPR sit between −0.17R and +0.11R with no
  consistent sign. The 5 EMA is the only one positive before costs in every split (stocks +0.20/+0.32/+0.05R, indices
  +0.07/+0.14/+0.13R) — interpretation: a short-term mean-reversion effect may exist, but it is smaller than the cost of
  trading it at this size. Its dev-split net interval on stocks is −0.25..−0.004R (below zero).
* **Win rates are 27–36%.** The 3R/2R targets are hit on 8–23% of trades; most trades end at the stop or at 15:15.
  Losing runs of 10–23 trades in a row occur in every test (roughly ₹3,000–6,900 at ₹300 risk).
* **Answer to "how do people make money with simple strategies?"** (interpretation, with the evidence we have): on
  this data, these simple setups do not make money after costs; the published numbers we could find are claims without
  method (Pani's "60%", inside-bar "70%") or independent tests that also show ~36–45% win rates and PF < 1 (tradingqna
  Streak 5 EMA test PF 0.924; marketcalls Supertrend 41–45% wins). SEBI's FY23 cash-intraday study (search-verified via
  press coverage, see the source register) found ~71% of individual intraday traders lost money. Winners shown on social
  media are a selected sample: with ~30% win rates and 10+ loss streaks, many traders will have a good month by chance.

## What this does and does not show
* Evidence class: **historical statistical evidence** on seen data (all splits were read by EXP-0061..0072; no
  parameter was chosen here, so there was no tuning, but none of it is truly unseen).
* The rules are reconstructions of informal sources; a creator's own nuance (discretion, news, market context) cannot be
  tested. What is tested is the rule as publicly shared.
* Stocks cover only 2017–2020 and 126 names (survivorship). Index trades use NIFTYBEES/BANKBEES as index/100.
* Gaps and fast moves can lose more than the planned ₹300; the backtest keeps those losses.

## Not tested, recorded for later (sources in `docs/research/source-register.md` / scratch notes)
* Power of Stocks Bollinger Band (1.5 SD) + 5 EMA reversal and the 15-min inside-bar breakout — close relatives of
  EXP-0073 (mean reversion / range breakout); same cost problem expected, not yet run.
* marketcalls already tested the social-media VWAP setup on NIFTY/BANK NIFTY futures 2011–2019: unprofitable after
  costs (search-verified), so it was not repeated.
* EXP-0078 9:20 straddle: needs intraday option prices (none free) and breaks the ₹300 / no-derivatives rules.
