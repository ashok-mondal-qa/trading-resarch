# Factor portfolios on unseen 2006–2011 NSE data (replication test, research only) — spec v0.1

Status: **pre-registered, not run** (2026-10-26). Written before the 2005–2011 data was downloaded. Only
three probe files (2001-01-02, 2005-01-03, 2010-06-01) were opened, to check their columns; no return from
the period has been computed.
Registry: EXP-0047..0049. Rules: `factor-portfolios.md` (EXP-0039..0041) **exactly**, code v0.1.1.
Runner: `src/trading_research/backtesting/run_factors_pre2011.py`.

**Why (model interpretation):** the Phase 18 portfolios failed only the significance check, because ten
years of monthly returns cannot prove a Sharpe gap of about 0.3. Every later NSE year has been used. The years
**before** our data (2005–2011) have never been loaded or looked at by any experiment, and they include the
2006–2007 boom and the 2008 crash (NIFTY fell about 60%; hypothesis from general knowledge, to be measured).
Running the frozen rules there is the cleanest extra evidence available today without waiting for forward
data. The owner asked (2026-10-25) for data-backed, verified strategies.

## Data (to be loaded; verified source)
* NSE CM legacy bhavcopy from the official archive (`nsearchives.nseindia.com/content/historical/EQUITIES/`),
  2005-07-01..2011-06-30, into a separate store `data/pre2011/` (git-ignored) so the main dataset is untouched.
  These files have no ISIN or trade-count columns (checked 2026-10-26 on 2001, 2005 and 2010 files); the
  loader accepts that **only** for this store. Same validation rules (no repairs, date must match).
* Corporate actions from the NSE MCP `get_corporate_actions`. Spot checks on 2026-10-26: RELIANCE 2009 bonus,
  INFY 2006 bonus, TCS 2006 bonus and SATYAMCOMP 2006 bonus are listed; INFY's 2004 bonus is not, so coverage
  appears to start around mid-2005. Hence the data start of 2005-07-01. The adjuster's checks (factor within
  25% of the ex-date gap; any move above 35% without an action cuts the series) apply unchanged.
* Renames: NSE's official symbol-change list. Without ISINs a rename is confirmed only by the list plus date
  continuity (old ticker's last bar before the effective date, new ticker's first bar on or after it).
* ETFs and funds are excluded: symbols with an INF ISIN in the first post-2011 bhavcopy (2011-07-01), plus any
  symbol containing BEES, ETF, GOLD, NIFTY, SENSEX, LIQUID or SHARIAH, plus M50 and QNIFTY.
* **Benchmark: NIFTYBEES** (the NIFTY 50 ETF, NSE prices), because NSE's daily index files start in 2012
  (earlier dates return 404, `data-sources.md`) and niftyindices.com is blocked by the network policy. Bought
  at the first open with the same costs, held, taxed at the end. Price only (no dividends) on both sides, as
  in Phase 18. Its tracking of the index is measured on 2012-02..2014-12, where both exist, and reported.

## Window
Test window **2006-07-01..2011-06-30** (60 months; the universe needs 240 closes, so the first portfolio is
formed at the close of 2006-06-30). Halves: 2006-07-01..2008-12-31 and 2009-01-01..2011-06-30. Bars after
2011-06-30 are not read. No other split; nothing here is tuned.

## Costs and tax (unverified assumptions)
As Phase 18: current delivery costs from `config/settings.yaml` + 0.10% slippage per side, 2× stress; current
equity tax rules (short term 20.8%, long term 13% above ₹1.25 lakh, set-off). The actual 2006–2011 rules
differed (lower short-term tax, no long-term tax); using today's keeps the comparison with Phase 18 like for
like.

## Decision (decided now, per strategy)
**REPLICATED** only if all hold, else **NOT REPLICATED**:
1. Whole window at 2× costs: Sharpe (monthly, rf 0) above NIFTYBEES's and after-tax CAGR above NIFTYBEES's.
2. Each half at 2× costs: Sharpe not below NIFTYBEES's.
3. Whole window at 2× costs: maximum drawdown at most 10 points worse than NIFTYBEES's.
Reported, not a gate: the 98.33% block-bootstrap interval (12-month blocks) of the Sharpe difference at 1×.

What it changes: nothing in the status of EXP-0039..0041 (REJECTED) or in the forward-tracking rule of
EXP-0042/0043 (decided only by forward data). A REPLICATED result is recorded evidence for the owner's later
decision on an investing policy; a NOT REPLICATED result counts against the two paper portfolios and will be
reported as such.

## Policy note
Research only, no orders, no alerts; no limit changes. The fully invested portfolios still do not fit the
0.5%-per-position swing policy.

## Known limitations
Benchmark is an ETF with thin early trading and an expense ratio; ETF exclusion by name is a heuristic;
corporate-action coverage before 2006 is thinner; the universe of 200 is a larger share of a smaller market
(about 900 EQ stocks then vs 1,600 later).

## Review (gate 8, 2026-10-26)
**Risk manager:** research only; nothing changes for paper or live use. Accepted.
**Independent auditor:** rules are frozen from Phase 18 and the period is unseen. Objection: the ETF
benchmark and the rename rule without ISINs are weaker than Phase 18's data; both are disclosed and measured
where possible. Not a veto.

## Changelog
- **v0.1 (2026-10-26):** initial spec, before any 2005–2011 data was loaded.
