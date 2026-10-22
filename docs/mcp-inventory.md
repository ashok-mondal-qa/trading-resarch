# MCP and data-provider inventory

Status values: **verified** (a real call returned data in this environment, with date) · **configured,
unverified** · **evaluated, not configured** · **rejected**.

## NSE `nse-bhavcopy` — configured, unverified
- **URL:** `https://mcp.nseindia.in/bhavcopy/cm/mcp` (streamable HTTP), listed in `.mcp.json`
- **Official source:** https://www.nseindia.com/nse-mcp (opened 2026-10-22)
- **Capabilities (per NSE page):** end-of-day equity OHLCV, market breadth, price performance, volume
  analysis, bulk quotes, gainers/losers by date, comparisons, 52-week highs/lows. ~5 years of history,
  updated with the previous session's final numbers.
- **Auth:** none. **Cost:** free.
- **Terms:** "strictly for educational and informational purposes"; not for real-time trading, investment
  advice, commercial deployment, or AI training. Subject to NSE Terms of Use and Disclaimer.
- **Security:** read-only market data; no credentials involved.
- **Failure behaviour:** if unreachable or stale, the pipeline returns `DATA INSUFFICIENT`.
- **Fallback:** NSE archive CM bhavcopy CSVs (nsearchives.nseindia.com), same terms.
- **Verification procedure:** list tools; fetch one known date for one liquid symbol; compare OHLCV with
  the archive bhavcopy for the same date; record in this file with the date.
- **Current blocker (2026-10-22):** the cloud environment's network policy returns 403 for
  `mcp.nseindia.in`, `www.nseindia.com` and `nsearchives.nseindia.com`. Needs an allowlist change.

## NSE `nse-cm-market` — configured, unverified
- **URL:** `https://mcp.nseindia.in/cmmkt/mcp` (streamable HTTP), listed in `.mcp.json`
- **Official source:** https://www.nseindia.com/nse-mcp
- **Capabilities (per NSE page):** stock quotes, index data, gainers/losers, SME and equity listings, bond
  listings, a data-freshness status tool. 1–3 minutes behind real time.
- **Auth / terms / blocker:** same as above.
- **Use here:** freshness checks and context only. Not used for backtests (no history).

## Zerodha Kite Connect — evaluated, not configured
- **Source:** Zerodha support, "What are the charges for Kite APIs" (opened 2026-10-22)
- Personal plan: free, no historical or live data. Connect plan: ₹500/month per app, includes historical
  candles and WebSocket live data. No sandbox/paper mode is documented on that page.
- **Decision:** deferred. If adopted later it is for **data only**; order endpoints stay blocked.
  Requires owner sign-up and secrets in the environment store, never in chat or Git.

## Exchange filings / corporate announcements — to evaluate (Phase 8)
NSE/BSE corporate announcement pages. Access path not yet confirmed.
