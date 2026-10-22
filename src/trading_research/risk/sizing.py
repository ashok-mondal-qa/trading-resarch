"""Position sizing under the paper-phase risk caps.

Planned risk per share = (entry - stop) + slippage on both legs + per-share charges.
The planned risk is what the stop costs if it fills at the stop price. Gaps through
the stop can lose more; the caps are planning limits, not guarantees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from trading_research.backtesting.costs import round_trip_cost


class SizingRejected(ValueError):
    """The trade cannot be sized within the rules. Record it as REJECTED."""


@dataclass(frozen=True)
class PositionPlan:
    quantity: int
    entry: float
    stop: float
    risk_per_share: float
    planned_risk_inr: float
    planned_risk_pct: float


def size_long_position(
    equity: float,
    cash_available: float,
    entry: float,
    stop: float,
    open_planned_risk_inr: float,
    settings: dict[str, Any],
) -> PositionPlan:
    risk_cfg = settings["risk"]
    slippage = float(settings["execution_model"]["slippage_bps_per_side"]) / 10_000.0
    if equity <= 0:
        raise SizingRejected("equity must be positive")
    if not (entry > 0 and stop > 0):
        raise SizingRejected("entry and stop must be positive prices")
    if stop >= entry:
        raise SizingRejected("stop must be below entry for a long position")

    budget = equity * float(risk_cfg["max_risk_per_position_pct"]) / 100.0
    aggregate_cap = equity * float(risk_cfg["max_aggregate_open_risk_pct"]) / 100.0
    headroom = aggregate_cap - open_planned_risk_inr
    if headroom <= 0:
        raise SizingRejected("aggregate open-risk cap already reached")
    budget = min(budget, headroom)

    # Charges scale almost linearly with size; estimate per share from a 1-share quote
    # at the stop, ignoring the fixed DP charge, then check the exact total below.
    costs = settings["costs"]
    variable_cost_per_share = round_trip_cost(entry, stop, 1, {**costs, "dp_charge_inr_per_sell": 0.0})
    risk_per_share = (entry - stop) + slippage * (entry + stop) + variable_cost_per_share

    qty = min(math.floor((budget - float(costs["dp_charge_inr_per_sell"])) / risk_per_share),
              math.floor(cash_available / (entry * (1 + slippage))))
    while qty > 0:
        exact = qty * ((entry - stop) + slippage * (entry + stop)) + round_trip_cost(entry, stop, qty, costs)
        if exact <= budget:
            break
        qty -= 1
    if qty < 1:
        raise SizingRejected("risk budget or cash too small for one share")

    planned = qty * ((entry - stop) + slippage * (entry + stop)) + round_trip_cost(entry, stop, qty, costs)
    return PositionPlan(qty, entry, stop, risk_per_share, planned, 100.0 * planned / equity)
