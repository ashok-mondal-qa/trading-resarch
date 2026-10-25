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
