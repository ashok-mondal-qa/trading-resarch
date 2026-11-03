# EXP-0054/0055 — NIFTY expiry-day failed breakout of the 12:00 range: REJECTED

Run 2026-11-02 (spec `docs/strategy-specifications/nifty-expiry-reversal.md` v0.1, committed before any run in
df90702d). Raw numbers: `EXP-0054-0055-step1.json` (grid, dev + validation), `EXP-0054-0055-step2.json`
(adds the one holdout read), trades `EXP-0054-base-trades-step2.csv`. All figures are **calculated** from the
data below; none is a probability forecast.

## Verdict
* **EXP-0054 (owner's rule, literal): REJECTED.** Net of futures costs it lost money in dev, validation and the
  holdout. Over all 277 expiry days with a signal (Feb 2019 – Oct 2026) the **net win rate is 26%**, not 80%.
  Price reached the other side of the 12:00 range in only **9%** of trades.
* **EXP-0055 (32 variants): REJECTED.** No variant had a positive dev mean even at 1× costs; none passed, so
  no variant was carried to the holdout. Best dev variant (5-min bars, fixed 0.25% stop, 1R target) won
  54% of trades but still lost −0.07R per trade at 1× and −0.26R at 2× costs, and −0.33R in validation.
* The **8/10 claim is not supported** by this data. The highest win rate in any variant was 54%.

## Data (verified / labelled)
* Intraday: NIFTY 50 spot 1-min bars, **unofficial** (`technovusin/nifty50-historical-data`, commit 7f94ced,
  retrieved 2026-11-02 19:20 UTC, manifest `data/manifests/nifty_1min_unofficial/manifest.json`).
* Expiry days: 404 NIFTY option expiries from the NSE F&O bhavcopy (contract traded on its expiry date and
  never after). Weekdays found: Thursday 2019 – 28 Aug 2025 (Wednesday when Thursday was a holiday),
  Tuesday from 2 Sep 2025 (Monday on holidays). 403 expiries in the test window: dev 203, validation 104,
  holdout 96.
* Gate 1: 5 days excluded (1-min high/low more than 0.05% from NSE's official high/low): 2020-10-15,
  2021-10-21, 2021-12-02, 2022-01-20, 2022-12-29. Nothing repaired.
* Second source (`sandeepkapri/Nifty50-Minute-Data`), 258 common expiry days to Mar 2024: base rule −0.51R
  net, 25% wins there vs −0.46R, 24% on the primary source. Same answer on both vendors.

## Base rule (15-min bars, first close back inside, stop beyond the extreme + 0.02%, target other side, exit 15:15)
Costs: NIFTY futures, ₹20/order, STT 0.02% sell, exchange, stamp, GST, 1 point slippage per side (2× = stress).

| Split | Trades | Win rate net 1× | Mean R 1× (95% CI) | Mean R 2× | ₹ per lot 1× (mean) | Max DD ₹/lot 1× | Reached other side |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev 2019-02..2022 | 150 | 26% | −0.39 (−0.74..+0.04) | −0.76 | −602 | −98,473 | 11% |
| validation 2023-24 | 64 | 17% | −0.75 (−1.00..−0.47) | −1.18 | −818 | −55,498 | 3% |
| holdout 2025-26 | 63 | 33% | −0.13 (−0.50..+0.24) | −0.48 | −304 | −40,213 | 11% |
| **all** | 277 | 26% | −0.42 | −0.79 | −584 | −170,899 | 9% |

By year (1×, mean R / win rate): 2019 −1.04 / 19% · 2020 −0.14 / 21% · 2021 −0.18 / 33% · 2022 −0.22 / 31% ·
2023 −0.78 / 18% · 2024 −0.73 / 16% · 2025 +0.04 / 33% · 2026 −0.36 / 33%. Only 2025 was (barely) positive.
By expiry weekday (all splits): Thursday 227 trades −0.48R · Tuesday 40 trades −0.07R · Wednesday 8 −0.44R ·
Monday 2. Tuesday expiries are too few to call different.

**Control (non-expiry days, dev):** 465 trades, −0.51R net, 27% wins. Expiry day gives no special edge to
this pattern; it behaves the same as any other day.

## Why it fails (model interpretation)
The stop sits just above the failed high (median 23 points), while the target is the other side of a morning
range that price rarely reaches the same afternoon. A failed breakout often turns into a second breakout. Costs
of about 8 points per round trip on a futures lot are a third of a typical stop.

## Sizing against Ashok's ₹15,000 / ₹150-risk rule
* One NIFTY futures lot risks a median **₹1,397** per trade (23 points × lot) — about 9× the ₹150 limit — and
  needs margin far above ₹15,000. Not tradable within his rules.
* Option buying could not be tested (no intraday option prices); on expiry afternoons decay works against buyers.
* A ₹15,000 NIFTYBEES-style intraday position (no leverage): mean **−₹62 per trade**, only 8% of trades profit
  after ₹40 brokerage and charges; −₹17,182 in total over 277 trades. Charges are bigger than the typical move.
* Gaps cannot hurt an intraday exit, but a fast move can fill a stop worse than planned.

## Process notes
* The holdout was read twice: the first read used an expiry calendar that included three stale long-dated
  contract dates (e.g. Thursday 2025-09-25 after the switch to Tuesday). The calendar was fixed (contract must
  trade on its expiry date and never after; dev and validation unchanged) and the holdout re-read; the first
  read is kept in `EXP-0054-0055-step2-firstread-calendar-bug.json` (63→66 trades, −0.15R). No rule was changed.
* 32 variants were compared on dev; none passed, so there was no selection to overfit.
