# Research source register

Owner rule (Ashok, 2026-11-03, "Mandatory research source library"): every strategy keeps a source register; every
factual research claim has a citation; nothing is invented; anything that cannot be checked is labelled
**UNVERIFIED**. Lower-tier claims never override contradictory higher-tier evidence.

* **Machine-readable register:** [`source-register.csv`](source-register.csv), one row per strategy, with all owner
  fields: strategy name, original creator, source title, direct URL, publication date, date accessed, tier, exact
  entry / exit / stop rules, market and timeframe, backtest period, cost assumptions, independent validation results,
  limitations. Backtest period, costs and results are copied verbatim from `experiments/registry.csv`.
* **Status words used:** VERIFIED = primary text read; SEARCH-VERIFIED = title/authors/venue/headline finding seen on
  web-search result pages, full text not read; UNVERIFIED = could not be checked; internal = the project's own
  hypothesis; owner = Ashok's own rule.
* **New strategy rule:** before a run, add the row here (SR-xxxx), a registry row and a pre-registered spec.

## Source tiers
| Tier | What | May it set a rule? |
| --- | --- | --- |
| 1 | Official exchange data, regulators (NSE, SEBI), peer-reviewed research | yes, after our own backtest |
| 2 | Reproducible independent quant research, broker education (Zerodha Varsity, Groww docs), working papers | yes, after our own backtest |
| 3 | Experienced traders, books, interviews, podcasts, detailed videos | as a hypothesis only |
| 4 | Reels, posts, anonymous systems, unverified performance claims | as a hypothesis only; claims never cited as evidence |

## Access check of the owner's library (2026-11-03, from this cloud environment)
The sandbox proxy refused every library host (HTTP CONNECT 403 or DNS blocked): groww.in (all three doc pages),
nse.in, nseindia.com/all-reports, zerodha.com/varsity (all three), tradingview.com, in.tradingview.com, doi.org,
sebi.gov.in, ssrn.com, youtube.com, instagram.com. **Nothing in the library was read in full.** Web search works
and returns result pages, so citations below are SEARCH-VERIFIED at most. Still reachable for data: NSE archives
(nsearchives.nseindia.com, bhavcopy and index files) and GitHub (vendor 1-minute data). The NSE MCP and Groww notes
from earlier threads stay as recorded in `docs/mcp-inventory.md` (NSE MCP intraday is delayed; not for live signals).

| # | Library source | Tier | Reached? | Used for |
| --- | --- | --- | --- | --- |
| 1–3 | Groww Trade API docs, backtesting candles, live data | 1 (broker official data) | no (proxy) | future live/paper feed; endpoints in `execution/docs/UNVERIFIED.md` (PR #24) |
| 4 | NSE MCP | 1 | earlier threads via MCP connector | delayed quotes, bhavcopy history |
| 5 | NSE all-reports | 1 | archive host only | bhavcopy, index closes, F&O bhavcopy, symbol changes |
| 6–8 | Zerodha Varsity (TA module, supplementary notes on VWAP/ADX) | 2 | no (proxy) | none yet — UNVERIFIED |
| 9–10 | TradingView, Indian ideas | 4 (public scripts/ideas) | no (proxy) | none; script titles seen in search only |
| 11 | Holmberg, Lönnbark & Lundström (2013), FRL 10(1) 27–33 | 1 | search only | SR-0061 (ORB precedent) |
| 12 | "What Drives Momentum and Reversal? Evidence from Day and Night Signals" (RFS 2026 per owner) | 1 if published | search only | not tested; see note |
| 13 | SEBI F&O study press release, 23 Sep 2024 | 1 | search only | context (SR-0029) |

Notes:
* **Item 12:** search found the paper as a working paper by Yashar Barardehi, Vincent Bogousslavsky and Dmitriy
  Muravyev (US stocks 1926–2019): portfolios sorted on past intraday returns show short-term reversal and momentum,
  sorted on past overnight returns show only long-term reversal. The RFS 2026 publication and DOI 10.1093/rfs/hhag036
  could not be confirmed (UNVERIFIED). It is a monthly cross-sectional signal, not an intraday trade; candidate for a
  later NSE portfolio test (needs fresh forward data, since all NSE history is used).
* **SEBI F&O study (search-verified headline):** 93% of over 1 crore individual equity F&O traders lost money FY22–FY24,
  aggregate losses above ₹1.8 lakh crore. **SEBI cash-segment intraday study (24 Jul 2024, search-verified via press
  coverage, not the SEBI page):** about 71% of individual intraday traders in equity cash lost money in FY23; among
  those with more than 500 trades a year, about 80%. Context for why costs and frequency matter; not a strategy.

## Register summary (details in the CSV)
| SR | Experiments | Strategy | Source (creator) | Tier | Source status | Our verdict |
| --- | --- | --- | --- | --- | --- | --- |
| SR-0005 | 0005–0006 | Trend breakout baseline | internal | – | n/a | REJECTED |
| SR-0007 | 0007 | PA 20-EMA pullback | generic price action | 4 | UNVERIFIED | REJECTED |
| SR-0008 | 0008, 0011 | SMC sweep + displacement | SMC/ICT-style online | 4 | UNVERIFIED | REJECTED |
| SR-0012 | 0012 | RSI(2) short-term reversal | Lehmann 1990; Jegadeesh 1990 | 1 | search-verified (Lehmann) | REJECTED |
| SR-0013 | 0013, 0014, 0026, 0028 | 12-1 momentum | Jegadeesh & Titman 1993 | 1 | search-verified | REJECTED (0028 forward tracking) |
| SR-0015 | 0015 | Gap-up drift | internal | – | n/a | REJECTED |
| SR-0016 | 0016, 0021, 0027 | Minervini Trend Template | Mark Minervini (book) | 3 | UNVERIFIED | REJECTED (0027 forward) |
| SR-0017 | 0017, 0022, 0036 | Supertrend(10,3) | Olivier Seban (attribution) | 4 | UNVERIFIED | REJECTED |
| SR-0018 | 0018, 0023 | 44 MA green candle | unknown (Indian social media) | 4 | UNVERIFIED | REJECTED |
| SR-0019 | 0019, 0024 | Turtle 55-day | Curtis Faith (book) | 3 | UNVERIFIED | REJECTED |
| SR-0020 | 0020, 0025 | Golden cross | generic | 4 | UNVERIFIED | REJECTED |
| SR-0029 | 0029–0032 | NIFTY option structures | generic; SEBI context | 1 / 4 | search-verified (SEBI) | REJECTED |
| SR-0033 | 0033–0035 | Crypto intraday ORB / EMA / BB-RSI | generic | 4 | UNVERIFIED | REJECTED |
| SR-0037 | 0037, 0038 | 9/15 EMA scalp | The Trade Room (Mayank Raj) | 4 | UNVERIFIED | REJECTED |
| SR-0039 | 0039–0051 | Low-vol / momentum / mix portfolios | Baker-Bradley-Wurgler 2011; J&T 1993; IIMA library | 1 / 2 | search-verified | REJECTED on significance; mix passed 2026 holdout; forward tracking 0042/0043 |
| SR-0052 | 0054, 0055 | Expiry-day failed breakout "8/10" | owner, from social media | 4 | UNVERIFIED | REJECTED (26% wins, not 80%) |
| SR-0056 | 0056–0060 | Expiry-day ORB / VWAP / gaps / late trend | generic | 4 | UNVERIFIED | REJECTED |
| SR-0061 | 0061–0066 | Owner brief: ORB, breakout-retest, EMA 9/15 | owner brief; Holmberg et al. 2013 | owner / 1 / 4 | partly unverified | REJECTED |
| SR-0068 | 0068, 0069 | Market intraday momentum | Gao, Han, Li & Zhou 2018 (JFE) | 1 | search-verified | REJECTED (no effect on NIFTY even gross) |
| SR-0070 | 0070 | 5-min ORB on stocks in play | Zarattini & Aziz 2023 (SSRN) | 2 | rules UNVERIFIED | REJECTED (negative gross in 3 of 4 years) |

Bookkeeping issues found while backfilling (not fixed here, to avoid rewriting other open PRs):
* **EXP-0052 and EXP-0053 are used twice** on two open branches: the 09:35 ORB scan forward test (PR #19) and the
  multibagger base rates (PR #20). Whichever merges second should renumber; they are not in this branch's registry.
* **EXP-0067** is the execution-engine infrastructure row (PR #24), so this branch starts at EXP-0068.
* Infrastructure rows (EXP-0000–0004, 0009, 0010) have no strategy and no register row.
