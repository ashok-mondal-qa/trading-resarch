# Execution engine: architecture

Status: **PAPER only.** LIVE_APPROVAL exists behind a hard gate (`src/config/liveGate.ts`) and cannot pass
today because no strategy in `experiments/registry.csv` is ACCEPTED (EXP-0006..0066 were all rejected after
charges). Nothing in this package places an order without a one-time Telegram approval from an allow-listed
user.

## Goals and non-goals
- Take one trade proposal per day from the research side, check it against fixed risk rules, ask the owner on
  Telegram, then execute it in PAPER (simulated) or LIVE_APPROVAL (Groww) mode.
- Never treat "order accepted" as "order filled". Fills come from the broker's trade list; the position comes
  from the broker's positions endpoint.
- Never call a position protected until the broker confirms the OCO is ACTIVE for the full confirmed quantity.
- Non-goals: signal generation (that is the Python research package), automatic entries, more than one trade
  per day, leverage, averaging down, widening stops.

## Components

```
 research scan (Python)            Telegram (owner's phone)
        │ TradeProposal JSON                ▲  │ Approve / Reject (one-time button)
        ▼                                   │  ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ ExecutionService (src/engine)                                 │
 │   1 RiskEngine.validate  ──► reject / continue                 │
 │   2 Store.claimDailySlot (one trade per IST day, DB key)       │
 │   3 ApprovalService.request ──► TelegramGateway                │
 │   4 on approval: RiskEngine.validate again (fresh data)        │
 │   5 BrokerPort.submitEntry                                     │
 │   6 Reconciler: order status + trade list + position           │
 │   7 OcoManager: create OCO for confirmed qty, confirm ACTIVE   │
 │   8 watch exits, alerts, square-off reminder                   │
 └──────────────┬─────────────────────────────┬──────────────────┘
                │ BrokerPort                   │ Store + AuditLog
        ┌───────┴────────┐               ┌─────┴──────────────┐
        │ PaperBroker    │               │ MemoryStore (tests) │
        │ GrowwBroker*   │               │ PostgresStore       │
        └────────────────┘               └────────────────────┘
   * built only after checkLiveGate() passes
```

| Module | Path | Responsibility |
| --- | --- | --- |
| Domain | `src/domain` | Types, trade state machine (`stateMachine.ts`) |
| Config | `src/config` | Env loading with hard ceilings (`config.ts`), live gate (`liveGate.ts`) |
| Risk | `src/risk` | Charges model, slippage, ₹300 planned-risk cap, 1:2 net R:R, notional cap, time window |
| Broker | `src/broker` | `BrokerPort` interface, `paper/PaperBroker`, `groww/*` (HTTP client, token manager, mapping, broker) |
| Approval | `src/approval` | One-time approvals bound to an intent hash; Telegram Bot API gateway |
| Store | `src/store` | `Store` interface, in-memory and PostgreSQL implementations |
| Audit | `src/audit` | Append-only, hash-chained audit trail (DB triggers refuse UPDATE/DELETE) |
| Engine | `src/engine` | `ExecutionService`, `Reconciler`, `OcoManager` |

## Trade lifecycle

```
PROPOSED ─► RISK_REJECTED
   └─► AWAITING_APPROVAL ─► APPROVAL_DENIED | APPROVAL_EXPIRED
          └─► APPROVED ─► (re-check fails) RISK_REJECTED
                 └─► ENTRY_SUBMITTING ─► ENTRY_REJECTED
                        ├─► ENTRY_UNCERTAIN (timeout) ─► looked up by clientRef, never resubmitted
                        └─► ENTRY_PENDING ─► ENTRY_CANCELLED (no fills by the window end)
                               └─► POSITION_UNPROTECTED (first confirmed fill)
                                      └─► PROTECTION_PENDING (OCO sent)
                                             ├─► PROTECTED (OCO ACTIVE, qty == position)
                                             │      └─► more fills ─► POSITION_UNPROTECTED (OCO qty raised)
                                             └─► PROTECTION_FAILED (retries exhausted) ─► alert, owner exits
                                      └─► CLOSED (position back to 0)
Any non-terminal state ─► HALTED (reconciliation mismatch, kill switch): automation stops, owner alerted.
```

## Safety invariants (each has a test)
1. **Approval before entry.** `submitEntry` is reachable only from a trade whose approval was consumed
   atomically (PENDING → APPROVED in one DB statement) by an allow-listed Telegram user in the allow-listed
   chat, before expiry, with a nonce matching the button and an intent hash matching the order about to go out.
   Approvals are single use. In PAPER mode the same approval is required, so the workflow is rehearsed.
2. **₹300 cap including costs.** planned risk = qty × |entry − stop| + slippage on entry and stop legs +
   round-trip charges at the stop (with a safety buffer while rates are unverified). Must be ≤ ₹300.
   Net reward at target ÷ planned risk must be ≥ 2. Re-checked after approval with fresh data.
3. **One trade per IST day per mode**, enforced by a primary key on `(mode, trading_day)`, claimed before the
   approval request goes out. A rejected or cancelled entry still uses the day's slot (no second attempt).
4. **No assumed fills.** Filled quantity = sum of the broker trade list for the entry order. Position = broker's
   net quantity. If they disagree, the trade is HALTED and the owner alerted; the actual position is still
   protected.
5. **Protection is confirmed, not assumed.** After a fill the OcoManager creates an OCO for the confirmed
   position, then polls it until ACTIVE. Only then PROTECTED. Rejection or timeout → bounded retries (each
   preceded by a lookup by reference id to avoid duplicates) → PROTECTION_FAILED with an urgent alert.
6. **Uncertain submits are never blindly retried.** A timeout leaves the trade ENTRY_UNCERTAIN; the reconciler
   looks the order up by `order_reference_id` until it is found or the window ends.
7. **No automatic exits or entries without approval.** The engine creates protective OCOs automatically (that
   is the approved trade's stop and target). Any other order (manual flatten, square-off) is sent only after a
   new one-time approval.
8. **Credentials never leave the process.** Secrets are wrapped (`util/secret.ts`) so logs, JSON, audit
   payloads and Telegram messages print `[REDACTED]`. Telegram messages are built from trade fields only.
9. **LIVE is fail-closed.** `checkLiveGate` must pass at start-up; otherwise the process refuses to construct
   `GrowwBroker`.

## Modes
- **PAPER** (default): `PaperBroker` simulates acceptance, partial fills, rejections and OCO behaviour from a
  price feed the caller supplies. Telegram approval is still required.
- **LIVE_APPROVAL**: `GrowwBroker`, gated as above. Even when the gate passes, every entry needs a fresh
  one-time approval.

## External interfaces
- Groww Trade API (`https://api.groww.in/v1`), shapes taken from Groww's official Python SDK `growwapi`
  1.5.0 (MIT, PyPI, published 2025-12-06). The docs site was not reachable from the build environment; see
  `docs/UNVERIFIED.md` for every field that still needs checking against the live docs.
- Telegram Bot API (long polling `getUpdates`, `sendMessage`, `editMessageText`, `answerCallbackQuery`).
- PostgreSQL 16 (`db/migrations`).
