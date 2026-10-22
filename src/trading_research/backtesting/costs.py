"""Indian equity-delivery transaction cost model.

Rates come from config/settings.yaml `costs`. They are placeholders until
`costs.verified` is true; reports must say so while it is false.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    exchange_txn: float
    sebi_fee: float
    stamp_duty: float
    gst: float
    dp_charge: float

    @property
    def total(self) -> float:
        return (self.brokerage + self.stt + self.exchange_txn + self.sebi_fee
                + self.stamp_duty + self.gst + self.dp_charge)


def leg_costs(side: str, price: float, quantity: int, costs: dict[str, Any]) -> CostBreakdown:
    """Charges for one leg (side 'buy' or 'sell') of a delivery trade, in INR."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    if price <= 0 or quantity <= 0:
        raise ValueError("price and quantity must be positive")
    turnover = price * quantity
    pct = lambda key: turnover * float(costs[key]) / 100.0  # noqa: E731

    brokerage = pct("brokerage_pct")
    cap = float(costs.get("brokerage_cap_inr") or 0.0)
    if cap > 0:
        brokerage = min(brokerage, cap)
    stt = pct("stt_pct_buy" if side == "buy" else "stt_pct_sell")
    exchange = pct("exchange_txn_pct")
    sebi = pct("sebi_fee_pct")
    stamp = pct("stamp_duty_pct_buy") if side == "buy" else 0.0
    gst = (brokerage + exchange + sebi) * float(costs["gst_pct"]) / 100.0
    dp = float(costs["dp_charge_inr_per_sell"]) if side == "sell" else 0.0
    return CostBreakdown(brokerage, stt, exchange, sebi, stamp, gst, dp)


def round_trip_cost(entry: float, exit_: float, quantity: int, costs: dict[str, Any]) -> float:
    return leg_costs("buy", entry, quantity, costs).total + leg_costs("sell", exit_, quantity, costs).total
