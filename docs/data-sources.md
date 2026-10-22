# Data sources and data-quality contract

No dataset has been ingested yet (2026-10-22). See `docs/mcp-inventory.md` for provider status.

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
