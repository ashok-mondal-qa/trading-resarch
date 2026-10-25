"""Event-driven daily backtest engine (long only, paper research).

Execution model (docs/risk-policy.md, quant-backtesting skill):
  * decisions at the close of day t; entries and signal exits fill at the open of the next session
    on which the symbol trades;
  * slippage per side from config, full Indian delivery costs (backtesting/costs.py);
  * a stop is a fixed price level, never widened. If a day opens at or below it, the fill is the open
    (gap loss can exceed planned risk); else if the day's low touches it, the fill is the stop;
  * an entry whose open is at or below its stop is skipped;
  * optional profit target (frame column `target`, fixed at the signal like the stop): if a day opens at
    or above it the fill is the open, else if the high reaches it the fill is the target. The stop is
    checked first, so a day that touches both counts as a stop (conservative);
  * sizing by risk/sizing.py within the 0.5% / 2% caps; cash is respected; one position per symbol;
  * a new position is opened only when the aggregate cap still has room for a full per-position risk
    budget. Leftover room is never used for a smaller position (otherwise the cap fills with many tiny
    positions that each count as a trade but carry almost no risk).

Prices are simulated in split/bonus-adjusted terms; quantities are converted so that traded value equals
the raw traded value (adj_price x adj_qty = raw_price x raw_qty), so costs and sizing see raw rupees.
Circuit-locked days are not detected yet (fills on them may be optimistic): disclosed in reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from trading_research.backtesting.costs import leg_costs
from trading_research.risk.sizing import SizingRejected, size_long_position

REQUIRED = ["open", "high", "low", "close", "adj_factor", "stop", "exit_signal"]


@dataclass
class Position:
    symbol: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry: float          # adjusted, after slippage
    stop: float           # adjusted
    qty: float            # adjusted shares
    raw_qty: int
    planned_risk: float   # INR
    buy_costs: float
    sessions: int = 0
    pending_exit: str | None = None
    target: float = float("nan")  # adjusted; NaN = no target


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.Series
    skipped: pd.DataFrame
    open_at_end: int


@dataclass
class Order:
    symbol: str
    signal_date: pd.Timestamp
    stop: float
    target: float = float("nan")


def run(frames: dict[str, pd.DataFrame], candidates: dict[pd.Timestamp, list[str]], calendar: list,
        settings: dict, start_equity: float, max_holding_sessions: int,
        cost_multiplier: float = 1.0) -> Result:
    """Simulate. `frames[sym]`: adjusted OHLC, adj_factor, stop, exit_signal, indexed by its trading dates.
    `candidates[date]`: symbols selected at the close of `date` (already gated and ranked)."""
    for sym, f in frames.items():
        missing = [c for c in REQUIRED if c not in f]
        if missing:
            raise ValueError(f"{sym}: frame lacks {missing}")
    costs = {k: (v * cost_multiplier if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
             for k, v in settings["costs"].items()}
    slip = float(settings["execution_model"]["slippage_bps_per_side"]) / 10_000 * cost_multiplier
    sizing_settings = {**settings, "costs": costs,
                       "execution_model": {**settings["execution_model"],
                                           "slippage_bps_per_side": slip * 10_000}}

    cash = float(start_equity)
    positions: dict[str, Position] = {}
    pending: list[Order] = []
    trades, skipped, equity_curve = [], [], {}

    def close_position(p: Position, date, price_adj: float, reason: str):
        nonlocal cash
        fill = price_adj * (1 - slip)
        sell = leg_costs("sell", fill, p.qty, costs).total
        cash += fill * p.qty - sell
        pnl = (fill - p.entry) * p.qty - p.buy_costs - sell
        trades.append({
            "symbol": p.symbol, "signal_date": p.signal_date, "entry_date": p.entry_date,
            "exit_date": date, "entry": p.entry, "exit": fill, "stop": p.stop, "raw_qty": p.raw_qty,
            "sessions": p.sessions, "reason": reason, "costs": p.buy_costs + sell, "pnl": pnl,
            "planned_risk": p.planned_risk, "r_multiple": pnl / p.planned_risk,
        })
        del positions[p.symbol]

    last_close: dict[str, float] = {}
    for date in calendar:
        date = pd.Timestamp(date)
        # 1. exits for positions held from earlier sessions
        for sym, p in list(positions.items()):
            f = frames[sym]
            if date not in f.index:
                continue  # no trade in this symbol today (suspension etc.): hold
            bar = f.loc[date]
            p.sessions += 1
            if p.pending_exit:
                close_position(p, date, bar["open"], p.pending_exit)
            elif bar["open"] <= p.stop:
                close_position(p, date, bar["open"], "stop (gap)")
            elif bar["low"] <= p.stop:
                close_position(p, date, p.stop, "stop")
            elif bar["open"] >= p.target:
                close_position(p, date, bar["open"], "target (gap)")
            elif bar["high"] >= p.target:
                close_position(p, date, p.target, "target")

        # 2. entries ordered at the previous close
        open_risk = sum(p.planned_risk for p in positions.values())
        equity_now = cash + sum(p.qty * last_close.get(s, p.entry) for s, p in positions.items())
        risk_cfg = settings["risk"]
        full_budget = equity_now * float(risk_cfg["max_risk_per_position_pct"]) / 100
        aggregate_cap = equity_now * float(risk_cfg["max_aggregate_open_risk_pct"]) / 100
        for order in pending:
            f = frames[order.symbol]
            if date not in f.index:
                skipped.append({"date": date, "symbol": order.symbol, "reason": "no bar on entry day"})
                continue
            bar = f.loc[date]
            if order.symbol in positions:
                continue
            if bar["open"] <= order.stop:
                skipped.append({"date": date, "symbol": order.symbol, "reason": "opened at/below stop"})
                continue
            if aggregate_cap - open_risk < full_budget:
                skipped.append({"date": date, "symbol": order.symbol,
                                "reason": "aggregate cap: no room for a full position"})
                continue
            factor = bar["adj_factor"]
            entry_adj = bar["open"] * (1 + slip)
            try:
                plan = size_long_position(equity_now, cash, entry_adj / factor, order.stop / factor,
                                          open_risk, sizing_settings)
            except SizingRejected as exc:
                skipped.append({"date": date, "symbol": order.symbol, "reason": f"sizing: {exc}"})
                continue
            qty = plan.quantity / factor
            buy = leg_costs("buy", entry_adj, qty, costs).total
            cash -= entry_adj * qty + buy
            open_risk += plan.planned_risk_inr
            positions[order.symbol] = Position(order.symbol, order.signal_date, date, entry_adj, order.stop,
                                               qty, plan.quantity, plan.planned_risk_inr, buy,
                                               sessions=1, target=order.target)
            # same-day stop, then target, on the entry day (the open was the entry)
            if bar["low"] <= order.stop:
                close_position(positions[order.symbol], date, order.stop, "stop")
            elif bar["high"] >= order.target > entry_adj:
                close_position(positions[order.symbol], date, order.target, "target")
        pending = []

        # 3. end of day: marks, exit signals, new orders
        for sym, p in positions.items():
            f = frames[sym]
            if date in f.index:
                bar = f.loc[date]
                last_close[sym] = bar["close"]
                if bool(bar["exit_signal"]):
                    p.pending_exit = "exit signal"
                elif p.sessions >= max_holding_sessions:
                    p.pending_exit = "time stop"
        equity_curve[date] = cash + sum(p.qty * last_close.get(s, p.entry) for s, p in positions.items())
        for sym in candidates.get(date, []):
            if sym not in positions:
                row = frames[sym].loc[date]
                target = float(row["target"]) if "target" in row.index and pd.notna(row["target"]) else float("nan")
                pending.append(Order(sym, date, float(row["stop"]), target))

    # mark open positions at the last close (flagged, not counted as closed trades)
    open_at_end = len(positions)
    for sym, p in list(positions.items()):
        close_position(p, pd.Timestamp(calendar[-1]), last_close.get(sym, p.entry), "open at end (marked)")
    return Result(pd.DataFrame(trades), pd.Series(equity_curve, name="equity"), pd.DataFrame(skipped),
                  open_at_end)
