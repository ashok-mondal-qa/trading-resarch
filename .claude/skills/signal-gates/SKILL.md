---
name: signal-gates
description: Run a candidate through gates 1-9 with fixed, documented criteria and assign exactly one status (TRADE CANDIDATE, WATCHLIST, REJECTED, NO TRADE, DATA INSUFFICIENT). Use whenever a candidate is evaluated or a daily shortlist is produced.
---

# Signal validation and scoring

## Gates (all mandatory; the first failure decides the status)
| Gate | Question | Fail -> |
| --- | --- | --- |
| 1 Data validity | Bars complete, fresh, provenance recorded, no unexplained jumps? | DATA INSUFFICIENT |
| 2 Regime | Today's regime is in the spec's allowed list? (`market-regime`) | REJECTED |
| 3 Higher timeframe | Weekly structure agrees with the trade direction? | REJECTED |
| 4 Setup | Every entry condition in the spec is true? | REJECTED (or WATCHLIST if only the trigger is pending) |
| 5 Confirmation | The spec's objective confirmation (volume, close location, etc.) present? | WATCHLIST |
| 6 Risk/reward | Sizer accepts; R:R after costs >= spec minimum; stop at a structural level? | REJECTED |
| 7 Event and liquidity | No blocking event (`event-fundamental-risk`); liquidity floor met; source checked? | REJECTED / DATA INSUFFICIENT |
| 8 Independent challenge | Auditor and risk-manager raise no material objection? | REJECTED |
| 9 Final | All pass, and fewer than 2 candidates already selected today? | NO TRADE if none qualify |

## Rules
- Missing input is never a pass. It is DATA INSUFFICIENT.
- Scores are rank-ordering aids only. A score is not a probability. A probability may be stated only
  from calibrated out-of-sample results recorded in `docs/validation/`, with the sample size.
- If more than 2 candidates pass, keep the 2 with the best pre-registered ranking rule; the rest are
  WATCHLIST. Never add a third.
- Contradictory inputs (e.g. two data sources disagree on the close) -> DATA INSUFFICIENT.

## Verification
- Each candidate record lists every gate with pass/fail and the evidence used.
- A fixture with one missing field must produce DATA INSUFFICIENT (test).
