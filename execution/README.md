# Execution engine (TypeScript, Node 22)

Approval-gated order execution for AI Trading Desk India. **PAPER by default.** Nothing is sent to a broker
without a one-time Telegram approval, and LIVE_APPROVAL refuses to start unless the live gate passes (see
`docs/ARCHITECTURE.md`). As of 2026-11-03 it cannot pass: no strategy in `experiments/registry.csv` is ACCEPTED.

- Design and safety invariants: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Setup and deployment: [`docs/SETUP.md`](docs/SETUP.md)
- What still needs checking against Groww: [`docs/UNVERIFIED.md`](docs/UNVERIFIED.md)

```
npm ci
npm run typecheck
TEST_DATABASE_URL=postgres://user@host/db npm test   # without it the PostgreSQL suite is skipped
npm run build && npm run cli -- gate                  # prints why LIVE is closed
```

| Path | What |
| --- | --- |
| `src/risk` | ₹300 planned-risk cap incl. slippage + charges, 1:2 net R:R, cash cap, one trade/day, time window |
| `src/approval` | Telegram Bot API gateway and one-time approval service |
| `src/engine` | ExecutionService, Reconciler (broker truth), OcoManager (confirmed protection) |
| `src/broker/paper` | Simulated broker with failure scenarios |
| `src/broker/groww` | Groww auth, HTTP client, response mapping, read-only broker (`orders.ts` writer: not in this build) |
| `src/store`, `db/migrations` | MemoryStore, PostgresStore, schema with append-only audit and single-use approvals |
| `src/main.ts`, `src/cli.ts`, `src/intake.ts` | Process entry, operator commands, local proposal intake |
| `test/unit`, `test/integration`, `test/e2e` | Tests; integration uses a local mock Groww server and a real PostgreSQL |
