---
name: indian-market-research
description: NSE/BSE market structure facts needed for research and simulation - sessions, delivery settlement, circuit bands, corporate actions, holidays, gaps. Use when a backtest, fill model or report depends on an exchange rule.
---

# Indian market research

## Responsibility
Supply exchange facts that affect simulation and risk, each with a source and as-of date.
This skill never supplies prices; prices come from the data pipeline.

## Workflow
1. Identify the rule the task depends on (session times, pre-open auction, T+1 settlement,
   price bands / circuit limits, surveillance frameworks such as ASM/GSM, trading holidays,
   corporate-action ex-dates, delivery vs intraday charges).
2. Look it up on an official page (NSE, BSE, SEBI circulars). Open the page; a search snippet is
   not a source.
3. Record the fact in `docs/research/market-rules.md` as: rule, value, source URL, date checked.
4. Translate it into a simulation constraint (e.g. a stock locked at its upper circuit cannot be
   bought at the open in the simulator; a stop on a lower-circuit day may not fill).
5. If a rule cannot be verified, mark it UNVERIFIED and make the simulator take the conservative side.

## Must-know items to keep current
- Normal session and pre-open session timings (IST); special sessions.
- Settlement cycle for equity delivery.
- Price band categories and how bands change; stocks in trade-for-trade segments.
- Trading-holiday calendar for the backtest range (needed to detect missing bars vs holidays).
- Corporate actions: splits, bonuses, rights, dividends, mergers, symbol changes.

## Verification
- Every fact has a URL and a checked-on date.
- No rule older than 12 months is used without re-checking.
