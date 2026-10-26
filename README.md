# trading-research

A paper-only, evidence-first research system for swing trading Indian equities (NSE/BSE).
It is designed to stay inactive unless validated evidence supports a trade. It never places real orders.

Start with `CLAUDE.md`. Plan and audit: see the project doc "Swing-trading research system: audit and plan".

## Phases
| Phase | Status |
| --- | --- |
| 1 Audit | done |
| 2 Architecture | done (plan doc) |
| 3 Instructions, docs, safety guard, risk sizing, cost model | done (cost rates still unverified) |
| 4 NSE data integration | 5y bhavcopy history, MCP verified, split/bonus adjustment, symbol changes (2026-10-23); done |
| 5 Validation and indicators | data checks, indicator + structure library, no-lookahead tests (2026-10-23) |
| 6 Baseline strategy | spec v0.1 written and reviewed, signal code + tests; no backtest yet (2026-10-23) |
| 7 Backtesting | event-driven engine (next-open fills, gaps, costs, splits); baseline v0.2 **REJECTED** on train + 2025 validation, holdout unused (2026-10-23, `reports/backtests/EXP-0006-report.md`) |
| 8 PA / SMC strategies | PA pullback and SMC sweep pre-registered and tested; both **REJECTED**, holdout unused (2026-10-23, `reports/backtests/EXP-0007-0008-report.md`) |
| 9 Paper trading | paper broker (simulated fills, journal only), hash-chained journal, daily 12-section report with gates 1–9 (2026-10-23) |
| 10 End-to-end | synthetic full-cycle test (signal → order → fill → exit), live-mode refusal, source scan for order code, report field checks; runbook `docs/operations.md` (2026-10-23) |
| 11 More swing ideas | displacement, short-term reversal and 12-1 momentum pre-registered and tested on a never-evaluated 2016–2022 presample; all three **REJECTED**, holdout unused (2026-10-24, `reports/backtests/EXP-0011-0013-report.md`) |
| 12 Swing ideas round 2 | weekly 12-1 momentum and gap-up drift tested on a never-evaluated 2013–2015 split; both **REJECTED** (momentum consistent but regime-dependent), holdout unused (2026-10-25, `reports/backtests/EXP-0014-0015-report.md`) |
| 13 Popular social-media strategies | Minervini, Supertrend, 44-MA, Turtle 55, golden cross pre-registered and tested on 2013–2025 with a 16-way correction; all five **REJECTED**, none beat NIFTY 50 buy and hold, holdout unused (2026-10-25, `reports/backtests/EXP-0016-0020-report.md`) |
| 14 Crypto vs Indian equities | Binance spot daily loader (official archive, checksums, delisted pairs); the same six rule sets on crypto (EXP-0021..0026) all **REJECTED**, holdout 2025-01..2026-09 sealed; market comparison: no tested rule beats buy and hold in either market (2026-10-25, `reports/market-comparison-2026-10-25.md`) |
| 15 Forward tracking | crypto Minervini (EXP-0027) and NSE weekly momentum (EXP-0028) tracked on new data from 2026-10-26 with frozen rules; shadow only, monthly checks (`docs/strategy-specifications/forward-tracking.md`) |
| 16 NIFTY options (research only) | NSE F&O bhavcopy loader 2012–2026; iron condor, short strangle, covered call and breakout call buying tested as EXP-0029..0032 on 2012–2024: all four **REJECTED** (selling premium wins ~70% of months but loses on expectancy; covered call trails buy and hold); derivatives stay banned for paper/live, holdout 2025-01..2026-10 sealed (2026-10-25, `reports/backtests/EXP-0029-0032-report.md`) |
| 17 Crypto intraday | Binance 5m loader (BTC, ETH, 2017–2024); opening-range breakout, 9/21 EMA cross, Bollinger+RSI and Supertrend tested as EXP-0033..0036 on 2018–2024 with Indian tax in the pass rule: all four **REJECTED** (costs and the 31.2% per-trade tax sink frequent trading; Supertrend nearest miss); the 9/15 EMA scalp (The Trade Room style, EXP-0037/0038) also **REJECTED**; holdout 2025-01..2026-09 not downloaded (2026-10-25, `reports/backtests/EXP-0033-0036-report.md`) |
| 18 Data-first research | exploration of dev data (overnight vs daytime, calendar, stock factors; `docs/validation/exploration-2026-10-25.md`); low-volatility, momentum and combined 30-stock monthly portfolios tested as EXP-0039..0041: all **REJECTED** under the rules, but low volatility and the mix had a Sharpe at least NIFTY's in every period incl. unseen 2023–2025 and failed only the significance check (figures corrected 2026-10-26 for a data look-ahead, v0.1.2); both go to forward paper tracking (2026-10-25, `reports/backtests/EXP-0039-0041-report.md`); NSE 2026 holdout still sealed |
| 19 Crypto factor replication | the Phase 18 low-volatility, momentum and combined rules, unchanged, on the 50 most traded Binance coins (hold 10, monthly) vs BTC held, EXP-0044..0046: all **REJECTED**; low volatility beat BTC in dev but lost in unseen 2024, momentum lost 92% in 2022 (2026-10-26, `reports/backtests/EXP-0044-0046-report.md`); also fixed the NIFTY benchmark curve (Phase 18 verdicts unchanged) |
| 20 Unseen 2006–2011 replication | NSE bhavcopy 2005-07..2011-06 loaded into a separate store; frozen Phase 18 rules vs the NIFTY ETF, EXP-0047..0049: low volatility and the mix **REPLICATED** (17.3% and 18.1% a year at 2× costs vs 12.5%), momentum not (−75% in 2008); also fixed a look-ahead in the factor loader (2026-10-26, `reports/backtests/EXP-0047-0049-report.md`) |
| 21 2026 holdout (one use, owner-approved) | frozen rules on 2026-01..10-22, a falling market (NIFTY −13.7%), EXP-0050/0051: the mix **PASSED** (−13.2% vs −13.7%), low volatility **FAILED** on the Sharpe check despite losing less (−12.3%); NSE holdout now used up (2026-10-26, `reports/backtests/EXP-0050-0051-holdout-report.md`) |

## Daily report (paper only)
```
.venv/bin/python -m trading_research.reporting.daily            # after 20:00 IST; fetches what it needs
```
Writes `reports/YYYY-MM-DD.md` and journal records under `journal/`. No order leaves the machine: the paper
broker only writes journal records. While no strategy is ACCEPTED in `experiments/registry.csv` and the event
screen is missing, the final status can only be NO TRADE or DATA INSUFFICIENT.

## Setup
```
uv venv .venv && uv pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```
