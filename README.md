# trading-research

A paper-only, evidence-first research system for swing trading Indian equities (NSE/BSE).
It is designed to stay inactive unless validated evidence supports a trade. It never places real orders.

Start with `CLAUDE.md`. Plan and audit: see the project doc "Swing-trading research system: audit and plan".

## Phases
| Phase | Status |
| --- | --- |
| 1 Audit | done |
| 2 Architecture | done (plan doc) |
| 3 Instructions, docs, safety guard, risk sizing, cost model | in progress |
| 4 NSE data integration | 5y bhavcopy history, MCP verified, split/bonus adjustment (2026-10-23); symbol-change mapping next |
| 5–10 | not started |

## Setup
```
uv venv .venv && uv pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```
