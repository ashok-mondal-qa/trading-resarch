# EXP-0068..0070: intraday ideas from the research source library — all REJECTED

Run 2026-11-03, one run, rules as pre-registered in `docs/strategy-specifications/sourced-intraday-ideas.md` v0.1
(commit e466eada, before any run). Sources: `docs/research/source-register.md` (SR-0068, SR-0070). Output
`EXP-0068-0070.json` and the trade files next to this report. Research and paper only.

Labels: numbers below are **calculated** from unofficial 1-minute vendor bars that passed checks against official
NSE daily files (data identical to EXP-0061..0066: same vendor commits, 2,306 NIFTY days, 2,069 BANK NIFTY days,
98,308 stock-days). Charges use the Groww intraday schedule (UNVERIFIED on the live pricing page). Source claims are
**search-verified** at most (publisher sites blocked by the network).

## Verdict
| EXP | Rule | Source (tier) | Dev net R (CI 95%) | Val | Holdout | Years > 0 | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0068 | NIFTY intraday momentum, 14:45–15:15 | Gao et al. 2018 JFE (1) | −0.231 (−0.241..−0.222), 1,129 trades | −0.231 | −0.231 | 0 of 10 | **REJECTED** |
| 0069 | same, big first-half-hour moves only | Gao et al. 2018 (1) | −0.221 (−0.248..−0.192), 215 | −0.253 | −0.231 | 0 of 10 | **REJECTED** |
| 0070 | 5-min ORB, top stock in play | Zarattini & Aziz 2023 (2), rules reconstructed | −0.305 (−0.414..−0.188), 474 | −0.361 | −0.299 | 0 of 4 | **REJECTED** |

No rule passes a single acceptance check except "dev ≥ 100 trades". Nothing goes to paper tracking.

## What we learned
1. **No intraday momentum in NIFTY, even before costs.** The paper's core claim (first half-hour return predicts the
   last half-hour) does not show up in NIFTY 2017-04..2026-10: the correlation between r1 and the 15:00–15:29 return
   is 0.0006 over 2,306 days; the signed gross return in that window is −0.32 bps (dev), −0.09 (val), −0.36
   (holdout), hit rate 50%. In the tradable 14:45–15:15 window: −0.04 / −0.04 / +0.05 bps. BANK NIFTY is the same
   (correlation −0.005). Higher-tier evidence (a JFE paper on US data) is therefore **not** supported on Indian data;
   our NSE result is the relevant evidence for NSE trading.
2. **Costs alone make it −0.23R a trade.** With a 1% protective stop and ₹300 risk, notional is about ₹23,000,
   charges about ₹55 and slippage about ₹14 per round trip: −₹69 per trade, win rate 4–9% net. Under the ₹15,000 cap:
   −₹49 per trade. Even at zero slippage −0.19R.
3. **The stocks-in-play ORB loses gross in 3 of 4 years.** Gross −0.10R (dev), −0.18R (2019), −0.09R (2020); net
   −0.30R, win rate 24–27%, 66–71% of trades stopped. The paper's top-20 form (15,820 setups) is also negative net in
   every split (−0.34 / −0.26 / −0.23R) and about zero gross (−0.12 / −0.02 / +0.01R). The US "stocks in play"
   result does not carry over to these 126 large NSE stocks (no small caps, no news filter, rules reconstructed).

## Required metrics (scenario A, ₹300 risk, one trade a day)
| | EXP-0068 dev / val / hold | EXP-0069 dev / val / hold | EXP-0070 dev / val / hold |
| --- | --- | --- | --- |
| Trades | 1,129 / 480 / 696 | 215 / 97 / 164 | 474 / 240 / 245 |
| Win rate (net) | 8.7% / 9.4% / 4.3% | 12.1% / 8.2% / 5.5% | 26.8% / 26.3% / 24.1% |
| Avg win / avg loss (₹) | 51 / −81, 30 / −79, 33 / −74 | 78 / −86, 30 / −85, 31 / −75 | 425 / −279, 356 / −271, 522 / −280 |
| Profit factor | 0.06 / 0.04 / 0.02 | 0.13 / 0.03 / 0.02 | 0.56 / 0.47 / 0.59 |
| Expectancy (₹/trade) | −69 / −69 / −69 | −66 / −76 / −69 | −90 / −106 / −87 |
| Mean gross R | 0.00 / 0.00 / 0.00 | +0.01 / −0.03 / 0.00 | −0.10 / −0.18 / −0.09 |
| Max drawdown (₹) | −78,155 / −33,210 / −48,016 | −14,200 / −7,348 / −11,295 | −43,912 / −26,110 / −21,647 |
| Longest losing streak | 66 / 35 / 88 | 26 / 38 / 54 | 16 / 19 / 15 |
| Avg charges (₹) | 55 | 55 | 56 / 53 / 52 |
| Stress (2× costs) net R | −0.46 all splits | −0.45 / −0.48 / −0.46 | −0.54 / −0.58 / −0.52 |
| ₹15k cap (₹/trade) | −50 / −49 / −49 | −48 / −54 / −49 | −60 / −76 / −71 |

Slippage sensitivity (dev net R at 0 / 0.02–0.03 base / 0.05% / 0.10% per side): EXP-0068 −0.19 / −0.23 / −0.26 /
−0.32; EXP-0069 −0.18 / −0.22 / −0.25 / −0.31; EXP-0070 −0.27 / −0.31 / −0.37 / −0.43.

Walk-forward (each calendar year, rules fixed before it): EXP-0068 net R between −0.224 and −0.238 every year
2017–2026, gross between −0.010 and +0.009; EXP-0070 2017 −0.23 (gross +0.01), 2018 −0.37, 2019 −0.36, 2020 −0.30.

Drawdowns are large because these are cumulative losses over hundreds of trades at ₹300 risk each, not because of
one bad day. Gaps or halts can lose more than the planned ₹300.

## Disclosures
* Splits were already read by EXP-0061..0066 (other rules); no sealed holdout existed (disclosed before the run).
* EXP-0068's 1% stop and 14:45–15:15 window are adaptations; the paper's own window is reported gross.
* EXP-0070's entry/stop/target are a reconstruction (search did not show the paper's rules); US screen thresholds
  were dropped or replaced by the house liquidity filter.
* Stock data is 2017–2020 only and survivorship-biased (vendor's 2021 list), which flatters longs; it still lost.
* Tests: `tests/test_sourced_intraday.py` (signal timing, no look-ahead in r1 and the big-move threshold, RVOL
  excludes today, stop-before-target, gap fills, stop-width bounds); full suite passing.
