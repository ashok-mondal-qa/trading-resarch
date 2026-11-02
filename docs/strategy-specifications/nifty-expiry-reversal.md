# NIFTY expiry-day failed breakout of the 12:00 range (research only) — spec v0.1

Status: **PRE-REGISTERED** (2026-11-02, written before any backtest of this rule). Registry: EXP-0054 (base rule,
owner's description) and EXP-0055 (variant grid, best dev variant). Results go to
`reports/backtests/EXP-0054-0055-report.md`.

**Owner idea (Ashok, 2026-11-02, from social media):** on NIFTY expiry day, mark the day's high and low at
12:00. If price breaks above that high and fails (closes back below it), go short; same logic for the low.
Claim: works "8 out of 10 times". We test the claim; we never place orders.

## Data
* **Intraday (unofficial, labelled as such):** NIFTY 50 spot index 1-minute bars, `technovusin/nifty50-historical-data`
  (GitHub, MIT licence), commit recorded in the manifest, 2017-04-03..2026-11-02. NSE publishes no free
  intraday history, so no official intraday source exists for this test.
* **Cross-check source (unofficial):** `sandeepkapri/Nifty50-Minute-Data` 1-minute bars 2015-01-09..2024-03-27.
  The base rule is re-run on it for the overlap as a second-source check.
* **Official checks:** NSE daily index file (`ind_close_all`, NIFTY 50 high/low) and the NSE F&O bhavcopy.
* **Expiry days:** every expiry date of a NIFTY index option contract that traded **on** that date, from the NSE
  F&O bhavcopy. This follows the real calendar: Thursday weekly expiries from Feb 2019, holiday moves to the
  previous session, and the move to **Tuesday from September 2025**. No weekday rule is assumed.
* **Gate 1 per expiry day (else the day is excluded, never repaired):** at least 370 of 375 one-minute bars
  09:15–15:29, no gap over 5 minutes between 12:00 and 15:15, and the 1-minute day high and low within 0.05% of
  the official NSE NIFTY 50 high and low. Excluded days are listed in the report.

## Rule (base = EXP-0054, the owner's description read literally)
* **Range:** high (RH) and low (RL) of 1-minute bars 09:15–11:59.
* **Bars:** 15-minute bars from 12:00 (12:00, 12:15, ...), built from 1-minute bars.
* **Short:** after a bar trades above RH (high > RH), the first bar that **closes below RH** is the signal
  (it may be the breakout bar itself). **Long:** mirror image at RL. A bar that triggers both sides is skipped.
* Signal bar must close by 15:00. One trade per expiry day, the first signal only; no re-entry.
* **Entry:** open of the first 1-minute bar at or after the signal bar's close.
* **Stop:** the most extreme price since 12:00 on the failed side (highest high for a short) + 0.02% buffer.
  Skip if entry is already at or beyond the stop.
* **Target:** the other side of the 12:00 range (RL for a short).
* **Exits, checked on every 1-minute bar from the entry bar:** stop first, then target (if both in one bar,
  the stop counts). A bar opening through the stop fills at its open. Otherwise exit at the 15:15 open.

## Variant grid (EXP-0055; 32 variants, selection on dev only)
timeframe 5 / 15 min × confirmation `wick` (base: the first close back inside) / `close` (needs a prior bar
close beyond the level, then a close back inside) × stop `extreme` (base) / `fixed` (0.25% from entry) ×
target `range` (base) / `1R` / `2R` / `time` (no target, 15:15 exit). Everything else as the base.

## Costs (per side; assumption, rates not verified against a broker; 2× stress doubles all)
NIFTY **futures** as the instrument proxy (spot points ≈ futures points intraday): brokerage ₹20 per order,
STT 0.02% of sell value, exchange 0.00173%, SEBI ₹10/crore, stamp 0.002% of buy value, GST 18% on
brokerage + exchange + SEBI, slippage 1 index point. Lot size from the F&O bhavcopy of that day.
**Options are not simulated:** there is no intraday option price history. Reported in ₹ for 1 futures lot
and for a ₹15,000 NIFTYBEES-equivalent intraday position (brokerage ₹20/order, STT 0.025% sell, exchange
0.00297%, stamp 0.003% buy, GST, slippage 0.02%/side; NIFTYBEES assumed to move like NIFTY).
R = |entry − stop| in index points; net R = (gross points − cost points) / R.

## Splits
dev 2019-02-01..2022-12-31 (halves 2019–2020, 2021–2022) · validation 2023-01-01..2024-12-31 ·
holdout 2025-01-01..2026-10-30 (contains the Tuesday expiries). The holdout is read **once**, for the base rule
(not tuned, it tests the owner's claim) and for the single variant selected on dev. All three are on data no
experiment in this project has used (no earlier test read NIFTY intraday bars).
**Control:** the base rule on every non-expiry session in dev, to see whether expiry day matters.

## Acceptance (decided now)
A rule is a **paper candidate** only if: dev ≥ 60 trades; dev 1× mean net R > 0 with the 95% bootstrap
interval (whole months resampled) above 0; dev 2× mean net R > 0; both dev halves 1× > 0; validation 2× > 0;
holdout 1× and 2× > 0. Otherwise **REJECTED**. Selection for EXP-0055: among variants passing the dev
checks, the highest dev 2× mean R. If none pass dev, EXP-0055 is REJECTED and the holdout is read only for
the base rule. With 32 variants, a dev pass can be luck; the holdout is the real check.
**The 8/10 claim** is checked as: share of base-rule trades closed with a net profit, and share that reached
the other side of the 12:00 range before the stop, per split.

## Reported, not decided on
Win rate, expectancy (R, points, ₹ per lot), profit factor, max drawdown (cumulative R and ₹ per lot), results
per year and per expiry weekday, exit reasons, median stop in points and ₹ per lot vs the owner's ₹150 risk
limit, and the second-source rerun.

## Known limitations
Unofficial intraday data (two vendors agree within 1 point on ~97% of minutes); spot index, not futures or
options prices; no intraday option data, so option buying (theta and IV crush on expiry afternoons) is not
tested; cost rates unverified; small samples per year.

## Changelog
* v0.1 (2026-11-02): first version, pre-registered before any run. Tests: unit tests for the signal and
  exits on synthetic days. Impact on earlier results: none (new data set). Holdout: one read, as above.
