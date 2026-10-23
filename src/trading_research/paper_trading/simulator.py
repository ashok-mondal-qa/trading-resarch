"""Paper broker: simulated orders and fills written to the journal. No network client, no credentials.

Obtain it through `paper_trading.guard.get_broker()`, which refuses anything but paper mode.

Rules are those of the backtest engine (backtesting/engine.py), applied one session at a time on raw
(unadjusted) daily bars:
  * an order comes only from a journal `signal` with status TRADE CANDIDATE; one position per symbol, so
    there is no averaging down;
  * entry at the next session's open plus slippage; skipped if that open is at or below the stop; sized
    by risk/sizing.py, and only if the 2% cap has room for a full 0.5% position;
  * held positions: a due exit (exit signal or time stop at the previous close) fills at the open; an open
    at or below the stop fills at the open (gap loss can exceed planned risk); a low touching the stop
    fills at the stop;
  * a stop can be raised, never lowered (no widening);
  * on a split/bonus ex-date the caller passes the factor; stop and quantity are rescaled and a
    `deviation` record says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_research.backtesting.costs import leg_costs
from trading_research.config import load_settings
from trading_research.paper_trading.journal import Journal, JournalError
from trading_research.risk.sizing import SizingRejected, size_long_position


class PaperOrderRejected(ValueError):
    pass


@dataclass
class OpenPosition:
    fill_id: str
    symbol: str
    strategy: str
    strategy_version: str
    entry_date: str
    entry: float
    qty: float
    stop: float
    planned_risk: float
    buy_costs: float


class PaperBroker:
    is_paper = True

    def __init__(self, journal: Journal | None = None, settings: dict | None = None):
        self.journal = journal or Journal()
        self.settings = settings or load_settings()
        self.slip = float(self.settings["execution_model"]["slippage_bps_per_side"]) / 10_000

    # ------------------------------------------------------------------ state from the journal
    def _replay(self):
        records = self.journal.records()
        orders, positions, realised = {}, {}, 0.0
        for r in records:
            d = r["data"]
            if r["type"] == "order":
                orders[r["id"]] = r
            elif r["type"] == "fill":
                orders.pop(r["refers_to"], None)
                positions[r["id"]] = OpenPosition(r["id"], d["symbol"], r["strategy"], r["strategy_version"],
                                                  d["date"], d["price"], d["qty"], d["stop"],
                                                  d["planned_risk_inr"], d["charges_inr"])
            elif r["type"] == "exit":
                positions.pop(r["refers_to"], None)
                realised += d["pnl_inr"]
            elif r["type"] == "deviation":
                if d.get("action") == "order cancelled":
                    orders.pop(r["refers_to"], None)
                elif d.get("action") in ("stop raised", "corporate action") and r["refers_to"] in positions:
                    p = positions[r["refers_to"]]
                    p.stop = d["new_stop"]
                    p.qty = d.get("new_qty", p.qty)
                    p.entry = d.get("new_entry", p.entry)
        return orders, positions, realised

    def pending_orders(self) -> list[dict]:
        return list(self._replay()[0].values())

    def open_positions(self) -> list[OpenPosition]:
        return list(self._replay()[1].values())

    def open_planned_risk(self) -> float:
        return sum(p.planned_risk for p in self.open_positions())

    def equity(self, marks: dict[str, float] | None = None) -> float:
        _, positions, realised = self._replay()
        start = float(self.settings["virtual_portfolio"]["starting_equity_inr"])
        unrealised = sum((marks or {}).get(p.symbol, p.entry) * p.qty - p.entry * p.qty - p.buy_costs
                         for p in positions.values())
        return start + realised + unrealised

    def cash(self) -> float:
        _, positions, realised = self._replay()
        start = float(self.settings["virtual_portfolio"]["starting_equity_inr"])
        return start + realised - sum(p.entry * p.qty + p.buy_costs for p in positions.values())

    # ------------------------------------------------------------------ actions
    def submit(self, signal_id: str) -> dict:
        """Create a simulated order for the next session's open from a TRADE CANDIDATE signal."""
        signal = self.journal.get(signal_id)
        d = signal["data"]
        if signal["type"] != "signal" or d.get("status") != "TRADE CANDIDATE":
            raise PaperOrderRejected("orders come only from TRADE CANDIDATE signals")
        orders, positions, _ = self._replay()
        held = {p.symbol for p in positions.values()} | {o["data"]["symbol"] for o in orders.values()}
        if d["symbol"] in held:
            raise PaperOrderRejected(f"{d['symbol']}: already held or ordered (no averaging down)")
        return self.journal.append("order", signal["strategy"], signal["strategy_version"], {
            "symbol": d["symbol"], "signal_date": d["signal_date"], "stop": d["stop"],
            "entry_rule": "next session open + slippage; skip if open <= stop"}, refers_to=signal_id)

    def raise_stop(self, fill_id: str, new_stop: float) -> dict:
        _, positions, _ = self._replay()
        if fill_id not in positions:
            raise JournalError(f"no open position for fill {fill_id}")
        p = positions[fill_id]
        if new_stop <= p.stop:
            raise PaperOrderRejected(f"{p.symbol}: stops may only be raised ({new_stop} <= {p.stop})")
        return self.journal.append("deviation", p.strategy, p.strategy_version, {
            "symbol": p.symbol, "action": "stop raised", "old_stop": p.stop, "new_stop": new_stop}, fill_id)

    def _exit(self, p: OpenPosition, day: str, price: float, reason: str) -> dict:
        costs = self.settings["costs"]
        fill = price * (1 - self.slip)
        sell = leg_costs("sell", fill, p.qty, costs).total
        pnl = (fill - p.entry) * p.qty - p.buy_costs - sell
        return self.journal.append("exit", p.strategy, p.strategy_version, {
            "symbol": p.symbol, "date": day, "price": fill, "reason": reason, "qty": p.qty,
            "charges_inr": p.buy_costs + sell, "pnl_inr": pnl, "r_multiple": pnl / p.planned_risk},
            refers_to=p.fill_id)

    def process_session(self, day: str, bars: dict[str, dict], exits_due: dict[str, str] | None = None,
                        factors: dict[str, float] | None = None) -> list[dict]:
        """Simulate one session. `bars[symbol]` = raw open/high/low/close for `day`; `exits_due[symbol]`
        = reason decided at the previous close; `factors[symbol]` = split/bonus factor if `day` is an
        ex-date (e.g. 0.5 for a 1:1 bonus)."""
        exits_due, factors, written = exits_due or {}, factors or {}, []
        orders, positions, _ = self._replay()
        for p in list(positions.values()):
            f = factors.get(p.symbol)
            if f and f != 1.0:
                written.append(self.journal.append("deviation", p.strategy, p.strategy_version, {
                    "symbol": p.symbol, "action": "corporate action", "factor": f, "date": day,
                    "new_stop": p.stop * f, "new_qty": p.qty / f, "new_entry": p.entry * f}, p.fill_id))
                p.stop, p.qty, p.entry = p.stop * f, p.qty / f, p.entry * f
            bar = bars.get(p.symbol)
            if bar is None:
                continue  # no trade today (suspension etc.): hold
            if p.symbol in exits_due:
                written.append(self._exit(p, day, bar["open"], exits_due[p.symbol]))
            elif bar["open"] <= p.stop:
                written.append(self._exit(p, day, bar["open"], "stop (gap)"))
            elif bar["low"] <= p.stop:
                written.append(self._exit(p, day, p.stop, "stop"))

        risk_cfg, costs = self.settings["risk"], self.settings["costs"]
        for order in orders.values():
            d, bar = order["data"], bars.get(order["data"]["symbol"])
            if bar is None or bar["open"] <= d["stop"]:
                reason = "no bar on entry day" if bar is None else "opened at/below stop"
                written.append(self.journal.append("deviation", order["strategy"], order["strategy_version"], {
                    "symbol": d["symbol"], "action": "order cancelled", "reason": reason, "date": day},
                    order["id"]))
                continue
            marks = {s: b["open"] for s, b in bars.items()}
            equity, open_risk = self.equity(marks), self.open_planned_risk()
            full = equity * float(risk_cfg["max_risk_per_position_pct"]) / 100
            cap = equity * float(risk_cfg["max_aggregate_open_risk_pct"]) / 100
            entry = bar["open"] * (1 + self.slip)
            reason = None
            if cap - open_risk < full:
                reason = "aggregate cap: no room for a full position"
            else:
                try:
                    plan = size_long_position(equity, self.cash(), entry, d["stop"], open_risk, self.settings)
                except SizingRejected as exc:
                    reason = f"sizing: {exc}"
            if reason:
                written.append(self.journal.append("deviation", order["strategy"], order["strategy_version"], {
                    "symbol": d["symbol"], "action": "order cancelled", "reason": reason, "date": day},
                    order["id"]))
                continue
            buy = leg_costs("buy", entry, plan.quantity, costs).total
            fill = self.journal.append("fill", order["strategy"], order["strategy_version"], {
                "symbol": d["symbol"], "date": day, "price": entry, "qty": plan.quantity, "stop": d["stop"],
                "rule": "session open + slippage", "slippage_bps": self.slip * 10_000,
                "charges_inr": buy, "planned_risk_inr": plan.planned_risk_inr}, order["id"])
            written.append(fill)
            if bar["low"] <= d["stop"]:
                p = self._replay()[1][fill["id"]]
                written.append(self._exit(p, day, d["stop"], "stop"))
        return written
