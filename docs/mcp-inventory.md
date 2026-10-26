# MCP and data-provider inventory

Status values: **verified** (a real call returned data in this environment, with date) · **configured,
unverified** · **evaluated, not configured** · **rejected**.

## NSE `nse-bhavcopy` — verified 2026-10-23
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
- **Verification (2026-10-23, ~03:21–03:35 UTC, from the cloud environment with NSE hosts allowlisted):**
  - `initialize` → server `nse-bhavcopy-redis-mcp` 1.0.0, protocol 2025-03-26; `tools/list` → 21 tools
    (`get_stock_history`, `get_ltp_by_date`, `get_corporate_actions`, `get_market_breadth`,
    `get_index_history`, `get_bulk_quote`, `get_top_by_volume`, ...).
  - `get_stock_history RELIANCE endDate=2026-10-22` → 21 bars; the 2026-10-22 bar (O 1206.2 H 1208.0
    L 1184.5 C 1184.5 V 14,957,042) equals the archive bhavcopy
    `BhavCopy_NSE_CM_0_0_0_20261022_F_0000.csv.zip` row exactly.
  - Loader cross-check (`--cross-check`): RELIANCE, TCS, HDFCBANK OHLCV match the archive on all 15 sessions
    2026-10-01..22; RELIANCE/TCS match on 2023-10-20, 2024-07-05 and 2024-07-08. Results are stored in each
    date's manifest under `cross_checks`.
  - **Prices are unadjusted:** `get_ltp_by_date RELIANCE 2023-10-20` = 2299.1, same as the raw archive, i.e.
    before the 1:1 bonus. `get_corporate_actions` returns ex-dates and `adjustmentFactor` (RELIANCE bonus
    1:1 ex 2024-10-28 → 0.5) — candidate input for Phase 5 adjustment, to be cross-checked.
  - History window starts ~5 years back (RELIANCE history starts 2021-10-25 as of 2026-10-23).
  - `deliveryQty` and 52-week fields come back as 0 in history rows; do not use them.
- **Reliability quirks (observed 2026-10-23):** (1) the servers are load-balanced without session affinity;
  a `tools/call` often fails with `Session not found`, so the client re-initialises and retries.
  (2) Some backends lack older history: 6 of 10 identical calls for RELIANCE ending 2023-10-20 returned
  `{"error":"Symbol not found: RELIANCE"}` while the others returned 22 bars. Recent dates returned
  consistently (8/8). Errors are retried and never read as "no bar". Client:
  `src/trading_research/data/nse_mcp.py`.
- **`get_corporate_actions` (checked 2026-10-23 on the 20 most-traded stocks of 2026-10-22, 2021-10-25..2026-10-22):**
  correct factors for HDFCBANK bonus 1:1 (2025-08-26), BAJFINANCE bonus 4:1 + split 2:1 (2025-06-16, combined
  0.1), RELIANCE bonus 1:1 (2024-10-28) and others, all confirmed by the raw ex-date price drop.
  **Incomplete:** KOTAKBANK's raw price fell 2132.6 → 426.0 open on 2026-01-14 (≈ 5:1 split) but the server
  lists no action after mid-2025. Demerger (RELIANCE 2023-07-20) and rights (INDHOTEL 2021-11-11) come with
  factor 1.0. The adjuster flags all three and uses only the bars after them; it never guesses a factor.
- **Role:** cross-check and convenience queries. The primary store is the archive bhavcopy (see below),
  because files are hashable, re-downloadable and consistent.

## NSE `nse-cm-market` — verified 2026-10-23
- **URL:** `https://mcp.nseindia.in/cmmkt/mcp` (streamable HTTP), listed in `.mcp.json`
- **Official source:** https://www.nseindia.com/nse-mcp
- **Capabilities (per NSE page):** stock quotes, index data, gainers/losers, SME and equity listings, bond
  listings, a data-freshness status tool. 1–3 minutes behind real time.
- **Auth / terms:** same as above.
- **Verification (2026-10-23 ~03:22 UTC):** `initialize` → server `cm-market-mcp` 1.0.0; `tools/list` → 15
  tools; `cm_get_data_status` → gainers/losers last crawled 2026-10-23T03:21Z, crawl interval 5 min,
  cache TTL 15 min. Calls were before market open (09:15 IST), so live values were not judged.
  Same session-affinity quirk as above.
- **Use here:** freshness checks and context only. Not used for backtests (no history).

## Zerodha Kite Connect — evaluated, not configured
- **Source:** Zerodha support, "What are the charges for Kite APIs" (opened 2026-10-22)
- Personal plan: free, no historical or live data. Connect plan: ₹500/month per app, includes historical
  candles and WebSocket live data. No sandbox/paper mode is documented on that page.
- **Decision:** deferred. If adopted later it is for **data only**; order endpoints stay blocked.
  Requires owner sign-up and secrets in the environment store, never in chat or Git.

## Upstox MCP (`upstox-mcp` plugin) — configured, unverified (2026-10-26)
- **Installed:** `/plugin marketplace add upstox/upstox-plugin-marketplace` then
  `/plugin install upstox-mcp@upstox-plugins-official` at project scope (`.claude/settings.json`:
  `extraKnownMarketplaces` + `enabledPlugins`), at Ashok's request.
- **URL:** `https://mcp.upstox.com/mcp` (remote HTTP). Plugin source reviewed 2026-10-26
  (github.com/upstox/upstox-plugin-marketplace): only a `.mcp.json` pointing at that URL, no local code.
- **Capabilities (per Upstox README):** live NSE/BSE/MCX market data and **read-only** account access
  (holdings, positions, orders, funds and margin, profile). No order placement per Upstox.
- **Auth:** Upstox OAuth in the browser on first use; Upstox requires re-authorisation once per day.
  No tokens in chat or Git.
- **Not installed:** the sibling `upstox-skill` plugin, because it places, amends and cancels real orders
  (conflicts with CLAUDE.md rule 1). Revisit only with written live-trading authorization.
- **Status in the cloud environment (2026-10-26):** `mcp.upstox.com` is denied by the environment's network
  proxy (CONNECT 403), so no call has succeeded. Needs the host allowlisted, then a tool list and one
  quote cross-checked against the NSE archive before any use. Even if it ever exposed an order tool, the
  paper-only rule and `block_live_orders` hook still apply.

## Exchange filings / corporate announcements — to evaluate (Phase 8)
NSE/BSE corporate announcement pages. Access path not yet confirmed.

## NSE archive CM bhavcopy files — verified 2026-10-23 (primary EOD store)
- **Host:** `nsearchives.nseindia.com` (HTTP 200 with a browser-like User-Agent). `www.nseindia.com`
  itself returns 403 to scripted requests (bot protection); it is not needed.
- **Files:** UDiFF `/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` from 2024-07-05;
  legacy `/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip` up to 2024-07-05 (both exist for
  2024-07-05; legacy 404s from 2024-07-08; UDiFF 404s for 2023 dates). Non-trading days return 404.
- **Loader:** `python -m trading_research.data.bhavcopy --start YYYY-MM-DD --end YYYY-MM-DD
  [--cross-check SYM,SYM]`. Raw zips → `data/raw/`, normalised parquet → `data/processed/`, provenance
  manifest per date → `data/manifests/nse_cm_bhavcopy/` (committed).
- **Loaded so far (2026-10-23):** every weekday 2021-10-25..2026-10-22: 1,233 files, 71 weekdays with no
  file (exchange holidays; list = `not_found` manifests). Weekend special sessions (e.g. Muhurat trading)
  are not attempted yet. 217 rows were excluded, all series T0 (T+0 settlement segment), where high/low
  do not bound open/close; no EQ rows were excluded.

## NSE archive daily index file — verified 2026-10-23
- `nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv`: OHLC, volume, turnover, P/E, P/B,
  dividend yield for every NSE index (incl. NIFTY 50, NIFTY 500, India VIX) for one session.
- Loader: `python -m trading_research.data.indices --start .. --end ..` → `data/manifests/nse_index_close/`.
- Loaded 2026-10-23: one file for each of the 1,233 bhavcopy sessions 2021-10-25..2026-10-22, none extra.
- Quirk: three files (2023-04-06, 04-10, 04-11) write dates month-first (`04-06-2023`). The loader accepts
  them only when the month-first reading equals the date in the file name, and notes it in the manifest;
  their daily change matches the file's own Change(%) column (+0.24%, +0.14%, +0.56%).
- Cross-check: NIFTY 50 closes equal the bhavcopy MCP `get_index_history` on all 111 dates compared
  (Oct–Dec 2024, Jul–Oct 2026). For Apr–Jun 2023 the MCP answered "No data" on 8 of 8 tries, so the
  MCP index history does not cover (or reliably serve) 2023. Largest NIFTY 50 daily move in the series:
  −5.93% on 2024-06-04.
