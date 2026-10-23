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
