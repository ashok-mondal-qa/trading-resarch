---
name: event-fundamental-risk
description: Check verified exchange filings, results dates, corporate actions, dilution, pledges and governance flags that make holding a position overnight riskier. Use at gate 7 and before any candidate is published.
---

# Fundamental and event risk

## Responsibility
Decide whether known events make the overnight/multi-day holding risk unacceptable. This is a filter,
not a stock-picking engine.

## Checks (each needs a filing or official link, or is reported as UNKNOWN)
1. Results / board-meeting date within the planned holding period -> REJECT by default
   (a spec may opt in to earnings trades explicitly).
2. Corporate action ex-date in the holding period (split, bonus, rights, large dividend) -> adjust
   the plan or REJECT.
3. Recent material announcements (regulatory action, auditor resignation, default, fraud allegation,
   large block deals, promoter pledge increase) -> REJECT unless resolved.
4. Dilution: QIP, preferential allotment, warrant conversion announced -> flag.
5. Exchange surveillance (ASM/GSM, trade-for-trade) -> REJECT.

## Rules
- Use exchange filings or company releases. News items need a publication timestamp and a link.
- Never infer an event from price movement.
- If the filings source is unavailable, the event gate returns DATA INSUFFICIENT, not PASS.

## Verification
- Every flag in a report has a link and timestamp.
- "No events found" states which source and date range were checked.
