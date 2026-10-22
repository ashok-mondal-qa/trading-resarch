---
name: paper-journal
description: Record every signal, rejected candidate, simulated order, fill, exit, cost, deviation and lesson in an append-only paper-trading journal, with the signal snapshot written before the outcome is known. Use for any paper-trading step.
---

# Paper trading and trade journal

## Records (JSON Lines under `journal/`, one file per month, append-only)
- `signal`: timestamp, data timestamp, strategy + version, symbol, gate results, entry condition,
  stop, target, size, planned risk, costs estimate, status. Written BEFORE the next session.
- `rejection`: same fields plus the failing gate and reason.
- `order` (simulated): created from a TRADE CANDIDATE only, via `get_broker()` (paper only).
- `fill`: simulated price, rule used (e.g. next open, gap-through-stop at open), slippage, charges.
- `exit`: reason (stop, target, time, invalidation), price, P&L after costs, R multiple.
- `deviation`: any difference between plan and simulation, and why.
- `lesson`: what was learned; links to the experiment registry if it triggers a change.

## Rules
- Never edit or delete a past record. Corrections are new records referencing the original id.
- Each record stores the hash of the previous record (tamper-evidence).
- Strategy version is mandatory on every record.
- The journal never contains credentials or account identifiers.

## Verification
- Hash chain validates (test).
- Every `fill` references an `order`, every `order` a `signal` with status TRADE CANDIDATE.
