# EXP-0061..0066 — three intraday strategy families on NSE stocks and indices: all REJECTED

Run 2026-11-02 (spec `docs/strategy-specifications/intraday-three-families.md` v0.1, pre-registered in 5121953c and
code committed before the run). One fixed version of each rule, so dev, validation and holdout are all out-of-sample
tests of rules nobody tuned. Numbers: `EXP-0061-0066.json`; trades `EXP-006x-{stocks,indices}-trades.csv`.
All values are **calculated** from unofficial 1-minute data that matched official NSE daily files; none is a forecast.

## Verdict
**No rule passes.** All 12 rule × universe combinations lose money after charges in **every** split, at every
slippage level tested including zero. The 95% interval of mean net R is below zero in every split except the two
small index breakout-retest holdouts (72 trades, −0.41..+0.01; filtered, 33 trades, −0.53..+0.02), which are still
negative on average. Status for all six EXPs: **REJECTED**. Signal status for live use: **NO TRADE**.

## Why they fail (calculated, then interpretation)
* **Before costs there is almost no edge.** Mean gross R (before slippage and charges) ranges −0.22 to +0.32; across
  all ~50,000 stock EMA-pullback signals it is +0.04 to +0.09R, across ~37,000 stock ORB signals −0.04 to 0.00R.
* **Charges alone cost ~0.2R a trade at ₹300 risk.** Average charges are ₹45–73 per round trip (two brokerage orders
  up to ₹20 each, STT, GST), i.e. 15–25% of the ₹300 budget, before any slippage.
* **₹15,000 capital, no leverage (scenario B):** every rule loses ₹34–85 per trade; the stop has to be so small in
  rupees that charges dominate.
* **Index futures are not allowed by the ₹300 rule:** median stop risk on the smallest-ever lot is ₹1,200–1,900;
  0% of index trades fit within ₹300, so indices are only usable through an ETF, where they also lose.
* Model interpretation: on these liquid names, well-known breakout and pullback entries are close to coin flips at a
  1:2 target; a 33–38% win rate at 1:2 is roughly break-even before costs and clearly negative after them.

## Results

### 126 NSE stocks, 2017–2020 (scenario A: ₹300 risk, one trade a day)

| EXP | Rule | Split | Trades | Win rate | Avg win ₹ | Avg loss ₹ | PF | Expectancy ₹ | Mean net R (95% CI) | Gross R | Max DD ₹ | Losing streak | Charges/trade ₹ | Stress R | ₹15k cap: ₹/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EXP-0061 | Opening Range Breakout | dev | 469 | 32% | 217 | -216 | 0.48 | -76 | -0.26 (-0.33..-0.20) | -0.08 | -36,196 | 15 | 48 | -0.45 | -62 |
|  |  | validation | 239 | 37% | 178 | -219 | 0.48 | -71 | -0.25 (-0.37..-0.13) | -0.07 | -17,915 | 11 | 47 | -0.43 | -60 |
|  |  | holdout | 228 | 30% | 250 | -242 | 0.45 | -93 | -0.32 (-0.39..-0.24) | -0.16 | -22,045 | 8 | 45 | -0.49 | -83 |
| EXP-0062 | Breakout and Retest | dev | 483 | 32% | 303 | -288 | 0.50 | -97 | -0.33 (-0.40..-0.25) | -0.01 | -47,658 | 12 | 69 | -0.64 | -45 |
|  |  | validation | 244 | 33% | 306 | -292 | 0.51 | -96 | -0.32 (-0.39..-0.26) | -0.01 | -23,391 | 13 | 68 | -0.64 | -47 |
|  |  | holdout | 243 | 31% | 314 | -287 | 0.49 | -102 | -0.35 (-0.46..-0.24) | -0.07 | -25,578 | 10 | 66 | -0.65 | -49 |
| EXP-0063 | EMA 9/15 Pullback | dev | 488 | 35% | 298 | -278 | 0.57 | -78 | -0.26 (-0.33..-0.20) | +0.03 | -38,986 | 12 | 64 | -0.55 | -45 |
|  |  | validation | 244 | 38% | 315 | -284 | 0.67 | -58 | -0.20 (-0.28..-0.11) | +0.10 | -14,150 | 10 | 63 | -0.48 | -38 |
|  |  | holdout | 246 | 39% | 345 | -289 | 0.75 | -44 | -0.15 (-0.29..-0.00) | +0.14 | -11,686 | 9 | 59 | -0.40 | -34 |
| EXP-0064 | Opening Range Breakout + filter | dev | 394 | 34% | 201 | -209 | 0.49 | -71 | -0.24 (-0.29..-0.20) | -0.05 | -28,273 | 11 | 50 | -0.45 | -54 |
|  |  | validation | 216 | 38% | 170 | -210 | 0.49 | -67 | -0.23 (-0.33..-0.14) | -0.04 | -14,731 | 12 | 48 | -0.42 | -56 |
|  |  | holdout | 184 | 31% | 183 | -236 | 0.35 | -106 | -0.36 (-0.44..-0.23) | -0.22 | -19,926 | 11 | 45 | -0.54 | -85 |
| EXP-0065 | Breakout and Retest + filter | dev | 290 | 28% | 298 | -287 | 0.41 | -121 | -0.41 (-0.50..-0.32) | -0.13 | -35,194 | 11 | 69 | -0.73 | -55 |
|  |  | validation | 180 | 30% | 310 | -289 | 0.46 | -109 | -0.37 (-0.51..-0.23) | -0.10 | -20,744 | 11 | 68 | -0.69 | -48 |
|  |  | holdout | 176 | 33% | 308 | -292 | 0.52 | -95 | -0.33 (-0.43..-0.23) | -0.03 | -17,348 | 12 | 67 | -0.64 | -49 |
| EXP-0066 | EMA 9/15 Pullback + filter | dev | 451 | 35% | 292 | -277 | 0.56 | -80 | -0.27 (-0.37..-0.17) | +0.01 | -36,089 | 11 | 63 | -0.55 | -44 |
|  |  | validation | 241 | 39% | 297 | -279 | 0.68 | -54 | -0.18 (-0.24..-0.12) | +0.14 | -13,559 | 10 | 63 | -0.46 | -40 |
|  |  | holdout | 225 | 38% | 323 | -278 | 0.70 | -51 | -0.18 (-0.32..-0.05) | +0.10 | -12,529 | 10 | 59 | -0.44 | -35 |

**Slippage sensitivity (mean net R, dev / validation / holdout):**

| EXP | 0% | base | 0.05% | 0.10% |
|---|---|---|---|---|
| EXP-0061 | -0.24 / -0.23 / -0.30 | -0.26 / -0.25 / -0.32 | -0.29 / -0.28 / -0.34 | -0.34 / -0.33 / -0.38 |
| EXP-0062 | -0.25 / -0.25 / -0.28 | -0.33 / -0.32 / -0.35 | -0.41 / -0.41 / -0.42 | -0.51 / -0.51 / -0.51 |
| EXP-0063 | -0.20 / -0.14 / -0.09 | -0.26 / -0.20 / -0.15 | -0.34 / -0.28 / -0.22 | -0.43 / -0.38 / -0.30 |
| EXP-0064 | -0.22 / -0.21 / -0.34 | -0.24 / -0.23 / -0.36 | -0.28 / -0.27 / -0.38 | -0.33 / -0.31 / -0.41 |
| EXP-0065 | -0.34 / -0.31 / -0.25 | -0.41 / -0.37 / -0.33 | -0.49 / -0.45 / -0.41 | -0.58 / -0.54 / -0.51 |
| EXP-0066 | -0.21 / -0.12 / -0.13 | -0.27 / -0.18 / -0.18 | -0.34 / -0.27 / -0.25 | -0.43 / -0.37 / -0.34 |

### NIFTY + BANK NIFTY as index ETF, 2017–2026 (scenario A: ₹300 risk, one trade a day)

| EXP | Rule | Split | Trades | Win rate | Avg win ₹ | Avg loss ₹ | PF | Expectancy ₹ | Mean net R (95% CI) | Gross R | Max DD ₹ | Losing streak | Charges/trade ₹ | Stress R | ₹15k cap: ₹/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EXP-0061 | Opening Range Breakout | dev | 1084 | 34% | 182 | -230 | 0.41 | -90 | -0.30 (-0.34..-0.26) | +0.01 | -97,825 | 11 | 63 | -0.61 | -49 |
|  |  | validation | 460 | 32% | 178 | -230 | 0.36 | -102 | -0.34 (-0.40..-0.28) | -0.03 | -47,069 | 9 | 65 | -0.66 | -50 |
|  |  | holdout | 638 | 34% | 173 | -220 | 0.41 | -84 | -0.28 (-0.33..-0.24) | +0.06 | -54,216 | 12 | 65 | -0.60 | -47 |
| EXP-0062 | Breakout and Retest | dev | 136 | 34% | 245 | -290 | 0.43 | -109 | -0.36 (-0.52..-0.21) | +0.02 | -15,552 | 7 | 72 | -0.74 | -48 |
|  |  | validation | 53 | 28% | 212 | -293 | 0.29 | -150 | -0.50 (-0.71..-0.29) | -0.17 | -8,195 | 9 | 73 | -0.89 | -58 |
|  |  | holdout | 72 | 43% | 213 | -267 | 0.60 | -60 | -0.20 (-0.41..+0.01) | +0.32 | -4,844 | 8 | 73 | -0.59 | -40 |
| EXP-0063 | EMA 9/15 Pullback | dev | 932 | 31% | 226 | -280 | 0.36 | -124 | -0.41 (-0.46..-0.37) | -0.04 | -115,470 | 16 | 72 | -0.80 | -52 |
|  |  | validation | 383 | 31% | 217 | -272 | 0.36 | -120 | -0.40 (-0.47..-0.34) | -0.02 | -46,289 | 20 | 73 | -0.79 | -50 |
|  |  | holdout | 442 | 34% | 206 | -260 | 0.41 | -101 | -0.34 (-0.41..-0.27) | +0.08 | -44,726 | 12 | 73 | -0.72 | -45 |
| EXP-0064 | Opening Range Breakout + filter | dev | 601 | 33% | 174 | -236 | 0.36 | -101 | -0.34 (-0.39..-0.28) | -0.04 | -60,636 | 11 | 64 | -0.64 | -52 |
|  |  | validation | 259 | 36% | 164 | -226 | 0.40 | -88 | -0.29 (-0.36..-0.23) | +0.03 | -22,921 | 8 | 65 | -0.61 | -46 |
|  |  | holdout | 356 | 34% | 174 | -220 | 0.41 | -86 | -0.29 (-0.35..-0.23) | +0.04 | -30,740 | 6 | 65 | -0.60 | -46 |
| EXP-0065 | Breakout and Retest + filter | dev | 68 | 34% | 251 | -283 | 0.45 | -103 | -0.34 (-0.58..-0.10) | +0.05 | -7,701 | 10 | 72 | -0.72 | -47 |
|  |  | validation | 24 | 33% | 210 | -286 | 0.37 | -121 | -0.40 (-0.73..-0.09) | -0.01 | -3,759 | 7 | 74 | -0.80 | -49 |
|  |  | holdout | 33 | 39% | 220 | -274 | 0.52 | -79 | -0.26 (-0.53..+0.02) | +0.21 | -2,949 | 6 | 72 | -0.65 | -44 |
| EXP-0066 | EMA 9/15 Pullback + filter | dev | 492 | 29% | 220 | -280 | 0.32 | -134 | -0.45 (-0.51..-0.38) | -0.10 | -66,118 | 19 | 72 | -0.83 | -54 |
|  |  | validation | 208 | 34% | 215 | -268 | 0.41 | -105 | -0.35 (-0.45..-0.24) | +0.06 | -21,890 | 14 | 73 | -0.74 | -46 |
|  |  | holdout | 227 | 34% | 200 | -255 | 0.41 | -98 | -0.33 (-0.42..-0.23) | +0.10 | -23,030 | 10 | 73 | -0.72 | -45 |

**Slippage sensitivity (mean net R, dev / validation / holdout):**

| EXP | 0% | base | 0.05% | 0.10% |
|---|---|---|---|---|
| EXP-0061 | -0.21 / -0.25 / -0.18 | -0.30 / -0.34 / -0.28 | -0.35 / -0.39 / -0.34 | -0.44 / -0.48 / -0.44 |
| EXP-0062 | -0.24 / -0.39 / -0.03 | -0.36 / -0.50 / -0.20 | -0.43 / -0.55 / -0.29 | -0.54 / -0.65 / -0.43 |
| EXP-0063 | -0.29 / -0.28 / -0.20 | -0.41 / -0.40 / -0.34 | -0.47 / -0.46 / -0.40 | -0.58 / -0.57 / -0.52 |
| EXP-0064 | -0.26 / -0.20 / -0.19 | -0.34 / -0.29 / -0.29 | -0.38 / -0.34 / -0.34 | -0.47 / -0.44 / -0.44 |
| EXP-0065 | -0.22 / -0.28 / -0.11 | -0.34 / -0.40 / -0.26 | -0.41 / -0.47 / -0.34 | -0.52 / -0.58 / -0.48 |
| EXP-0066 | -0.33 / -0.22 / -0.19 | -0.45 / -0.35 / -0.33 | -0.50 / -0.42 / -0.40 | -0.60 / -0.54 / -0.52 |
R = planned risk of that trade (≤ ₹300 including charges). Stress = 2× slippage and 2× charges. Max DD is on the
one-trade-a-day equity in ₹ for that split. The interval is a 95% month-clustered bootstrap of mean net R.

## Data used (gate 1)
* Stocks: 126 vendor stocks, 121,087 stock-days, **98,308 (81%) passed** the high/low factor check against the NSE CM
  bhavcopy; failures were mostly low-priced stocks where one tick exceeds 0.10%. A stock-day was traded only with
  ≥ ₹50 crore median turnover and price ≥ ₹50 (point in time).
* NIFTY 50: 2,306 days passed; BANK NIFTY: 2,069 days passed (`day_check` vs NSE `ind_close_all`).
* Manifest: `data/manifests/intraday_minute_vendor/manifest.json`.

## Limitations
Survivorship in the vendor's 2021 stock list; unofficial minute data; fixed-percentage slippage with no order book;
target fills assumed exactly at the target; index ETF tracking error and spread not modelled; charges from Groww's
help page (₹20 or 0.1% per order), not verified on the live pricing page; a cheaper broker (₹20 or 0.03%) would
lower charges a little but gross edges are near zero anyway. Gaps and halts can lose more than ₹300. The 2020
stock holdout and the 2024–26 index holdout are now used; any new version of these rules needs forward paper data.
