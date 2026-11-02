# EXP-0056..0060 — five NIFTY expiry-day intraday ideas: all REJECTED

Run 2026-11-02 (spec `docs/strategy-specifications/nifty-expiry-ideas.md` v0.1, committed before any run in
e7172e30). Same data, expiry calendar (398 expiry days passing gate 1, Feb 2019 – Oct 2026, Thursday then Tuesday),
futures costs and splits as EXP-0054. Each rule is one fixed version, so every split is out of sample. Numbers:
`EXP-0056-0060.json`, trades `EXP-005x-*-trades.csv`. All values are calculated, not forecasts.

| EXP | Idea | Trades | Net win rate | Mean R 1× dev / val / holdout | Mean R 2× all | ₹ per futures lot, mean 1× | Median risk per lot | ₹15k ETF per trade | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0056 | Opening-range breakout (09:15–09:30) | 383 | 46% | +0.07 / −0.17 / −0.05 | −0.13 | −175 | ₹4,046 | −₹52 | REJECTED |
| 0057 | VWAP trend (TWAP proxy) | 315 | 23% | −0.21 / −0.25 / −0.12 | −0.40 | −401 | ₹2,383 | −₹58 | REJECTED |
| 0058 | Gap fade (≥ 0.30%) | 178 | 35% | −0.25 / −0.37 / +0.24 | −0.60 | −33 | ₹1,528 | −₹54 | REJECTED |
| 0059 | Gap follow (≥ 0.30%) | 179 | 16% | −0.80 / +0.07 / −0.59 | −1.22 | −528 | ₹1,243 | −₹57 | REJECTED |
| 0060 | Late-day trend (13:30 → 15:15) | 217 | 41% | −0.06 / −0.10 / +0.24 | −0.18 | +63 | ₹2,223 | −₹52 | REJECTED |

* **None passes the dev checks.** Closest: ORB (dev +0.07R at 1× but −0.04R at 2×, interval −0.06..+0.20, then
  negative in validation and holdout) and late-day trend (negative in dev and validation, +0.24R in the 2025–26
  holdout with interval −0.03..+0.53; one good period after two bad ones is not evidence).
* **Max drawdown per futures lot (1×, all):** ORB −₹186,828 · VWAP −₹158,630 · gap fade −₹55,707 · gap follow
  −₹136,419 · late trend −₹56,131.
* **₹15k / ₹150 rule:** every idea needs a stop worth ₹1,200–4,000 on one futures lot, 8–27× the ₹150 limit. At
  ₹15,000 without leverage (NIFTYBEES-style) every idea loses about ₹50–60 per trade, because the ₹40 brokerage
  plus charges is larger than the average move on ₹15k. Options could not be tested (no intraday option prices).
* Model interpretation: on expiry days NIFTY spot moves are mostly noise at these horizons; any small gross edge
  (ORB +0.09R, late trend +0.17R gross) is smaller than costs of roughly 8–10 points a round trip.
