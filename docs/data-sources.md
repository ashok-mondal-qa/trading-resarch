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
