---
name: daily-report
description: Produce the daily market report in the fixed 12-section format, from verified data and journal records only, ending in one final status. Use for each trading day's report.
---

# Daily market report

## Required sections (report fails validation if any is missing)
1. Report date and data timestamp (last bar date, retrieval time).
2. Market regime and benchmark context.
3. Data-quality status (pass/fail per check).
4. Number of candidates screened.
5. Shortlist: at most two, only if they qualify.
6. Per candidate: symbol, exchange, timeframe, setup, evidence, entry condition, invalidation, stop,
   target, position size, reward-to-risk, estimated costs, event risks.
7. Gate results (pass/fail per gate).
8. Auditor's and risk-manager's objections.
9. Final status: TRADE CANDIDATE / WATCHLIST / REJECTED / NO TRADE / DATA INSUFFICIENT.
10. Open virtual positions and aggregate planned risk vs the 2% cap.
11. Links to source evidence.
12. Limitations and unresolved uncertainties (always includes: cost rates verified or not;
    survivorship status; "paper trading only, not investment advice").

## Rules
- Generated from the journal and data files; no figure is typed by hand.
- If data is stale or missing: the report is still produced, with status DATA INSUFFICIENT and no candidates.
- No language implying certainty ("sure", "guaranteed", "high probability") unless sourced from calibration.
- Saved to `reports/YYYY-MM-DD.md`.

## Verification
- The report validator checks all 12 sections and the banned-phrase list.
