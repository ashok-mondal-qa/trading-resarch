# Data sources and data-quality contract

Ingested (2026-10-23): NSE CM bhavcopy, 2026-10-01..22 plus three test dates, via
`src/trading_research/data/bhavcopy.py`. Manifests: `data/manifests/nse_cm_bhavcopy/`. Provider status:
`docs/mcp-inventory.md`.

## Loader behaviour
- Raw files kept byte-for-byte with SHA-256 in the manifest; prices stored **unadjusted**.
- A date with no published file gets a `not_found` manifest and no bars (never filled).
- Rows with duplicate symbol/series, missing or non-positive prices, or high/low not bounding open/close are
  excluded and listed in the manifest's `excluded`; nothing is repaired.
- A file whose trade date differs from the requested date fails closed (no manifest written).
- `read_bars()` returns series EQ by default; other series need an explicit choice.

## Every dataset must carry a provenance manifest with
provider and source URL · instrument and exchange · timeframe · first/last bar timestamp (IST) ·
retrieval time (UTC) · price adjustment method · corporate actions applied · count of missing and
duplicated observations · known limitations · licence/terms note.

## Rules
- Primary EOD source: NSE CM bhavcopy (MCP or archive files). Unofficial sources may only cross-check.
- Signals use adjusted prices for indicator continuity; simulated fills use the unadjusted price of the
  fill day, consistent with the modelled execution.
- Universe: point-in-time index membership where obtainable. Until then, every result carries a
  survivorship-bias disclosure.
- Never fill missing candles. A missing bar for a symbol excludes that symbol for that date.
- Web-search snippets are never a substitute for market data.
- Stale data (last bar older than the most recent completed NSE session) → `DATA INSUFFICIENT`.

## Split/bonus adjustment (`src/trading_research/data/adjust.py`)
- Corporate actions come from the NSE bhavcopy MCP `get_corporate_actions` (ex-date + `adjustmentFactor`),
  cached with retrieval time in `data/raw/corporate_actions/`.
- Backward, price-only: bars before an ex-date × factor, volume ÷ factor; same-day events multiply.
  Dividends are not adjusted. Raw prices stay in the same file for simulated fills.
- NSE's bhavcopy `PrvsClsgPric` is **not** adjusted on ex-dates (RELIANCE 2024-10-28 bonus: prev close
  2655.7 = raw close of 2024-10-25), so it cannot be used as the check. Instead, each factor must agree
  within 25% with the raw ex-date open ÷ previous close.
- Any adjusted close-to-close move above 35% without a corporate action, or a price-changing event the
  source reports with factor 1.0 (demerger, rights, scheme, capital reduction), is an error. Errors are
  never patched: the series is usable only from `valid_from` (first bar after the last error); nothing usable
  → `DATA INSUFFICIENT`. Per-symbol manifests: `data/manifests/adjusted/`.
- A source with missing actions is caught by the jump check (KOTAKBANK 2026-01-14).
- First run (2026-10-23, 20 most-traded EQ stocks of 2026-10-22 + RELIANCE/HDFCBANK/BAJFINANCE, 2021-10-25
  ..2026-10-22): 17 ok, 3 partial (RELIANCE from 2023-07-21, INDHOTEL from 2021-11-12, KOTAKBANK from
  2026-01-16).

## Symbol changes (`src/trading_research/data/symbols.py`)
- Source: NSE's official `nsearchives.nseindia.com/content/equities/symbolchange.csv` (1,070 rows, retrieved
  2026-10-23; manifest `data/manifests/reference/symbolchange.json`).
- A rename is joined only when our bhavcopy confirms it: old ticker's last bar before the effective date,
  new ticker's first bar on/after it, same ISIN on both sides. Otherwise it is reported `unconfirmed` and
  history before it is not used. Renames before the loaded window are `before loaded range`.
- The adjuster joins confirmed predecessors (bars keep `raw_symbol`) and merges their corporate actions.
- Check over 2021-10-26..2026-10-22 (EQ): 229 renames confirmed, 15 unconfirmed (3 ISIN changed at the
  rename, 12 with one side missing from EQ data, e.g. listed in another series). ZOMATO → ETERNAL
  (2025-04-09) is confirmed; ETERNAL now has 1,233 bars, no issues.

## Gate 1 data checks (`src/trading_research/data/quality.py`)
- **Freshness:** the newest loaded session must be the most recent completed one (after 15:30 IST). A
  weekday counts as a holiday only if its bhavcopy was confirmed absent by a fetch after 20:00 IST that day.
- **Per symbol, over the last N sessions (default 260):** no missing session between first and last bar
  (sessions = dates with an `ok` bhavcopy manifest), no zero/missing volume, no duplicate dates, no
  non-positive prices, adjusted series usable for the whole window. Any failure → `DATA INSUFFICIENT`.
- First run (2026-10-23 09:54 IST): fresh (latest session 2026-10-22). Over the last 260 sessions, 2,491
  EQ symbols pass and 503 fail (mostly sessions missing from the EQ series, e.g. moves to BE or
  suspensions). Of the 20 adjusted symbols, 19 pass; KOTAKBANK fails because its usable series starts
  2026-01-16.

## Benchmark indices (`src/trading_research/data/indices.py`)
NSE's daily index file, one per session, same provenance rules (raw + SHA-256, manifest per date, missing
never filled, date mismatch fails closed). NIFTY 50 is the benchmark for regime (gate 2) and relative
strength. Index values are as published (indices need no corporate-action adjustment).

## History extended to 2015 (2026-10-24)
- Bhavcopy and index files 2015-01-01..2021-10-24 loaded with the same loader (2,905 sessions in total,
  2015-01-01..2026-10-22). Legacy files with a two-digit year (e.g. 2020-07-13, "13-Jul-20") and index
  files with DD/MM/YYYY dates (some 2015 files) are read only if the date still matches the file's date.
  NIFTY 50 was called "CNX Nifty" before 2015-11-09; `read_index("Nifty 50")` reads both names.
- Adjusted 2,125 EQ symbols (liquid on at least one day in 2015..2026; list from
  `run_swing_ideas --list-symbols`): 1,587 ok, 537 partial, 1 DATA INSUFFICIENT. NSE MCP corporate actions
  cover 2015 onward (checked RELIANCE 2017 bonus, INFY 2015 and 2018, HDFCBANK 2019 split).
- The adjuster's `usable` flag cuts history at the last error anywhere in the file. Backtests must use
  only errors known by their data end (`run_swing_ideas.usable_as_of`); otherwise a 2025 demerger would
  remove a stock's 2016 bars.

## History extended to 2011 (2026-10-25)
- Bhavcopy from 2011-07-01 (earlier legacy files have no ISIN or trade-count columns, so the loader fails
  closed on them). NSE index files exist in the archive from about 2012-02 (earlier dates return 404).
- NIFTY 50 names in the files: "S&P CNX Nifty" (to 2013-02-07), "CNX Nifty" (to 2015-11-06), "Nifty 50".
- An index name listed twice in one file is excluded (manifest `excluded_duplicate_names`), never picked.
- 11 sessions between 2013-10 and 2016-01 have no index file (404 on re-check); they stay missing.

## Binance spot daily candles (`src/trading_research/data/binance.py`, 2026-10-25)
- Source: Binance's official public archive `data.binance.vision`, `data/spot/monthly/klines/<PAIR>/1d/`, one
  zip per pair and month with a published SHA-256 `.CHECKSUM`; the S3 bucket listing
  (`s3-ap-northeast-1.amazonaws.com/data.binance.vision`) includes pairs Binance has delisted.
  `api.binance.com` is geo-blocked from this environment (HTTP 451) and is not used.
- Every USDT pair in the listing (677, 2026-10-25), minus stablecoins, fiat, gold tokens, wrapped/staked
  copies and leveraged tokens. Raw zips kept, checksums verified (a mismatch drops that month), per-pair
  manifest in `data/manifests/binance_spot_1d/` with missing days and excluded rows. Nothing is filled.
- Bars are UTC days (open 00:00 UTC = 05:30 IST), prices in USDT as traded; no adjustment needed.
  Timestamps are milliseconds before 2025 and microseconds from 2025-01-01; both are read.
- Known issues: some pairs have gaps (exchange suspensions, delist and relist); LUNAUSDT is a reused ticker
  (Terra Classic until 2022-05-13, Terra 2.0 from 2022-05-31). The crypto runner splits every series at a
  missing day so pieces never join. Volumes include wash trading; one exchange only.

## NSE F&O bhavcopy (`src/trading_research/data/fo_bhavcopy.py`, 2026-10-25)
- Source: NSE archive, one file per session: legacy `content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip`
  (to 2024-07-05) and UDiFF `content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip` (2024 on, preferred
  where it exists). Kept: NIFTY and BANKNIFTY index options and futures. Raw zip with SHA-256 and a manifest per
  date in `data/manifests/nse_fo_bhavcopy/`.
- A date mismatch fails closed; untraded contracts (zero OHLC) are kept with NSE's settlement price and
  `traded = False`; rows with inconsistent OHLC or duplicate contracts are excluded and listed. Nothing is filled.
- Legacy dates are `14-May-2012`, except some files with two-digit years (`14-May-12`, e.g. 2012-05-14); both
  are read. UDiFF turnover is in rupees (divided by 1e5 to lakh); `TtlTradgVol` is already in contracts.
  Legacy files carry no lot size; it is inferred from the near-month future (turnover / contracts / close,
  rounded to 25). NSE data is for educational/informational use only.

## Binance spot 5-minute candles (`src/trading_research/data/binance_intraday.py`, 2026-10-25)
- Same archive and checks as the daily loader: `data/spot/monthly/klines/<PAIR>/5m/`, SHA-256 `.CHECKSUM` per
  month, raw zips kept, manifest per pair in `data/manifests/binance_spot_5m/` listing every gap.
- Loaded BTCUSDT and ETHUSDT 2017-08..2024-12 only (773,880 bars each; 1,944 missing 5m bars each, the same
  exchange outages for both). 2025 onward is not downloaded (crypto intraday holdout).
- Bars are stamped with their UTC open time; 15m/1h bars are built only from complete groups of 5m bars.

## Pre-2011 store for the replication test (2026-10-26)
- Separate root `data/pre2011/` (git-ignored, same layout). NSE CM legacy bhavcopy 2005-07-01..2011-06-30:
  1,480 `ok` sessions, 82 weekdays `not_found` (holidays). These files have no ISIN or TOTALTRADES columns;
  `bhavcopy --root data/pre2011 --pre2011` accepts that, and only for that root and an end before 2011-07-01.
- Corporate actions (NSE MCP) appear to start about mid-2005 (INFY's 2004 bonus is missing; its 2006 bonus is
  listed). 1,576 symbols adjusted: 1,046 ok, 529 partial (618 unexplained jumps, 85 unadjusted price events,
  24 factor mismatches). Renames are confirmed by NSE's list plus date continuity only (no ISINs).
- NSE index files start in 2012; niftyindices.com is blocked by the network policy, so NIFTYBEES is the
  benchmark there (tracks the index within 0.01% a year in 2012–2014).
- Rebuild: `bhavcopy --start 2005-07-01 --end 2011-06-30 --root data/pre2011 --pre2011` (~55 min), then
  `adjust.run(symbols, 2005-07-01, 2011-06-30, root=data/pre2011, workers=6)` for the list from
  `run_factors_pre2011 --symbols` (~1 h; run with a long timeout).

## NIFTY intraday 1-minute bars (unofficial, 2026-11-02)
NSE has no free intraday history. `data/nifty_intraday.py` reads the MIT-licensed GitHub repo
`technovusin/nifty50-historical-data` (NIFTY 50 spot, 1-min, 2017-04-03..2026-11-02; commit and file SHA-256 in
`data/manifests/nifty_1min_unofficial/manifest.json`) and, as a cross-check only, `sandeepkapri/Nifty50-Minute-Data`
(2015-01..2024-03). The two agree within 1 point on ~97% of overlapping minutes. Every day used must pass
`day_check`: ≥ 370 of 375 bars, no gap > 5 min after 12:00, and 1-min high/low within 0.05% of the official NSE
daily index file; failing days are excluded, never repaired. Clone the repos into a scratch directory, then
`python -m trading_research.data.nifty_intraday --src <clone> --commit <sha> --cross-csv <csv>`.
NIFTY expiry days come from the F&O bhavcopy (`run_expiry_reversal.expiry_calendar`): a contract must trade on
its expiry date and never after (long-dated contracts can carry stale dates). Note: `fo_bhavcopy.load_day` skips a
day whose committed manifest says ok even if the parquet is missing, so load into a scratch root
(`load_day(d, root=data/fo_session)`) in a fresh container.

## NSE stock and BANK NIFTY 1-minute bars (unofficial, 2026-11-02)
`data/minute_vendor.py` reads two more GitHub vendors and keeps only days that match official NSE files:
* **Stocks:** `ShabbirHasan1/NSE-Data` (GPL-3.0), 126 large/mid caps (vendor's 2021 list, alphabetical to TATACHEM:
  survivorship bias), 1-min with volume, 2017-01..2020-12, split/bonus adjusted. Gate 1: the scale factors
  official/vendor for the day's high and low (NSE CM bhavcopy, EQ) must agree within 0.10%; real prices = vendor ×
  factor. 98,308 of 121,087 stock-days pass. Vendor names map to the NSE symbol of the date via `symbolchange.csv`.
* **BANK NIFTY:** `sandeepkapri/BankNifty-Data` (MIT) 1-min 2015-01..2026-04-22, `day_check` vs `ind_close_all`.
* The Shabbir NIFTY 50 file (2017–2020) is used only as the market filter for stocks.
Run: load the NSE bhavcopy 2016-11..2020-12 and index files into a scratch root (`data/s17`, ~10 min with 6
threads), fetch `symbolchange.csv` there, then `python -m trading_research.data.minute_vendor --shabbir <clone>
--banknifty <clone> --official-root data/s17` (~1.5 min). The Shabbir repo is ~2.7 GB: clone with
`--filter=blob:none --no-checkout` and sparse-checkout `/NSE Minute Data/` only (never `git ls-tree -l` on it,
which downloads every blob). Manifest: `data/manifests/intraday_minute_vendor/manifest.json`.
