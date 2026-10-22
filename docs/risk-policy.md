# Risk policy — paper research phase (v0.1, 2026-10-22)

These are experimental planning limits for a **virtual** portfolio. They are not a promise that losses
cannot exceed them: overnight gaps, trading halts, circuit locks and execution failures can produce
larger losses. Enforcement lives in `src/trading_research/config.py` and `src/trading_research/risk/sizing.py`.

| Rule | Value | Enforced by |
| --- | --- | --- |
| Mode | paper only | `config.validate_settings`, `paper_trading.guard`, `.claude/hooks/block_live_orders.py` |
| Planned risk per position | ≤ 0.5% of virtual equity | `size_long_position` |
| Aggregate open planned risk | ≤ 2% of virtual equity | `size_long_position` (headroom) |
| New candidates per day | ≤ 2 (ceiling, not quota) | config validation; gate 9 (Phase 8) |
| Leverage / margin / derivatives | not allowed | config validation |
| Averaging down | not allowed | config validation; journal check (Phase 9) |
| Widening a stop | not allowed | config validation; journal check (Phase 9) |
| Liquidity | 20-day median traded value ≥ ₹5 crore | gate 7 (Phase 8) |

## Planned risk definition
`qty × [(entry − stop) + slippage on both legs] + round-trip charges at the stop`.
Entries are modelled at the next session open; a gap through the stop fills at the open.

## Costs
Rates in `config/settings.yaml` are placeholders (`costs.verified: false`) until checked against the
broker's and NSE's current schedules. Reports must state this while it is false. All backtests also run
with 2× costs as a stress test.

## Changing this policy
Only the project owner can loosen a limit. Any change gets a registry row and a new version here.
