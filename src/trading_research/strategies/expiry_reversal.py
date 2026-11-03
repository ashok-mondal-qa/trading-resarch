"""NIFTY expiry-day failed breakout of the 12:00 range (spec docs/strategy-specifications/nifty-expiry-reversal.md).

Research only; nothing here orders. Works on one session of 1-minute bars (DatetimeIndex in IST, columns
open/high/low/close). Prices are index points.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import time

import pandas as pd

SPEC_VERSION = "0.1"
RANGE_END = time(12, 0)
LAST_SIGNAL_CLOSE = time(15, 0)
EXIT_TIME = time(15, 15)


@dataclass(frozen=True)
class Params:
    tf: int = 15                  # minutes
    confirm: str = "wick"         # wick | close
    stop: str = "extreme"         # extreme | fixed
    target: str = "range"         # range | 1R | 2R | time
    stop_buffer_pct: float = 0.02
    fixed_stop_pct: float = 0.25

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def name(self) -> str:
        return f"tf{self.tf}_{self.confirm}_{self.stop}_{self.target}"


BASE = Params()


def grid() -> list[Params]:
    return [replace(BASE, tf=tf, confirm=c, stop=s, target=t) for tf in (5, 15) for c in ("wick", "close")
            for s in ("extreme", "fixed") for t in ("range", "1R", "2R", "time")]


def resample(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Bars from 12:00 on, labelled by start time; `end` = start + minutes (the time the close is known)."""
    after = bars[bars.index.time >= RANGE_END]
    out = after.resample(f"{minutes}min", origin="start_day", offset="15min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    out["end"] = out.index + pd.Timedelta(minutes=minutes)
    return out


def signal(bars: pd.DataFrame, p: Params = BASE) -> dict | None:
    """First failed breakout of the 09:15-11:59 range. Uses only bars closed by the signal time."""
    rng = bars[bars.index.time < RANGE_END]
    if rng.empty:
        return None
    rh, rl = float(rng["high"].max()), float(rng["low"].min())
    up = dn = up_closed = dn_closed = False
    ext_hi, ext_lo = -float("inf"), float("inf")
    for start, b in resample(bars, p.tf).iterrows():
        if b["end"].time() > LAST_SIGNAL_CLOSE:
            break
        ext_hi, ext_lo = max(ext_hi, b["high"]), min(ext_lo, b["low"])
        up_before, dn_before = up_closed, dn_closed
        up |= b["high"] > rh
        dn |= b["low"] < rl
        short = up and b["close"] < rh and (p.confirm == "wick" or up_before)
        long_ = dn and b["close"] > rl and (p.confirm == "wick" or dn_before)
        up_closed |= b["close"] > rh
        dn_closed |= b["close"] < rl
        if short and long_:
            return {"side": "skip", "reason": "both sides on one bar", "signal_end": b["end"], "rh": rh, "rl": rl}
        if short or long_:
            side = "short" if short else "long"
            return {"side": side, "signal_end": b["end"], "rh": rh, "rl": rl,
                    "extreme": float(ext_hi if short else ext_lo)}
    return None


def simulate(bars: pd.DataFrame, p: Params = BASE) -> dict | None:
    sig = signal(bars, p)
    if sig is None or sig["side"] == "skip":
        return sig
    after = bars[(bars.index >= sig["signal_end"]) & (bars.index.time < EXIT_TIME)]
    if after.empty:
        return {**sig, "side": "skip", "reason": "no bar after signal"}
    entry_ts, entry = after.index[0], float(after["open"].iloc[0])
    short = sig["side"] == "short"
    sgn = -1 if short else 1
    if p.stop == "extreme":
        stop = sig["extreme"] * (1 + sgn * -1 * p.stop_buffer_pct / 100)
    else:
        stop = entry * (1 - sgn * p.fixed_stop_pct / 100)
    risk = (stop - entry) * -sgn
    if risk <= 0:
        return {**sig, "side": "skip", "reason": "entry beyond stop"}
    if p.target == "range":
        target = sig["rl"] if short else sig["rh"]
    elif p.target in ("1R", "2R"):
        target = entry + sgn * risk * int(p.target[0])
    else:
        target = None
    if target is not None and (target - entry) * sgn <= 0:
        return {**sig, "side": "skip", "reason": "entry beyond target"}
    opposite = sig["rl"] if short else sig["rh"]
    exit_px, exit_ts, reason, reached_opp = None, None, None, False
    for ts, b in after.iterrows():
        hit_stop = b["high"] >= stop if short else b["low"] <= stop
        if hit_stop:
            exit_px = max(stop, b["open"]) if short else min(stop, b["open"])
            exit_ts, reason = ts, "stop"
            break
        reached_opp |= bool(b["low"] <= opposite if short else b["high"] >= opposite)
        if target is not None and (b["low"] <= target if short else b["high"] >= target):
            exit_px, exit_ts, reason = target, ts, "target"
            break
    if exit_px is None:
        tail = bars[bars.index.time >= EXIT_TIME]
        if not tail.empty:
            exit_px, exit_ts = float(tail["open"].iloc[0]), tail.index[0]
        else:
            exit_px, exit_ts = float(after["close"].iloc[-1]), after.index[-1]
        reason = "time"
    return {**sig, "entry_time": entry_ts, "entry": entry, "stop": float(stop), "target": target, "risk_pts": float(risk),
            "exit_time": exit_ts, "exit": float(exit_px), "reason": reason, "gross_pts": float((exit_px - entry) * sgn),
            "reached_opposite": reached_opp}


# ---- costs (per unit, index points) ----
@dataclass(frozen=True)
class FutCosts:
    brokerage_per_order: float = 20.0
    stt_sell_pct: float = 0.02
    exchange_pct: float = 0.00173
    sebi_fraction: float = 1e-6
    stamp_buy_pct: float = 0.002
    gst_pct: float = 18.0
    slip_points: float = 1.0


def futures_cost_points(entry: float, exit_: float, side: str, lot: float, c: FutCosts = FutCosts(),
                        mult: float = 1.0) -> float:
    """Round-trip charges + slippage in index points per unit (one lot)."""
    buy_px, sell_px = (entry, exit_) if side == "long" else (exit_, entry)
    fees = 2 * c.brokerage_per_order / lot + (buy_px + sell_px) * (c.exchange_pct / 100 + c.sebi_fraction)
    gst = fees * c.gst_pct / 100
    taxes = sell_px * c.stt_sell_pct / 100 + buy_px * c.stamp_buy_pct / 100
    return (fees + gst + taxes + 2 * c.slip_points) * mult


def etf_cost_inr(notional: float, gross_pct: float, mult: float = 1.0) -> float:
    """₹15k-style NIFTYBEES intraday round trip: ₹20/order, STT 0.025% sell, exchange 0.00297%, SEBI, stamp
    0.003% buy, GST 18%, slippage 0.02% per side (spec)."""
    exit_notional = notional * (1 + gross_pct / 100)
    turnover = notional + exit_notional
    fees = 40 + turnover * (0.00297 / 100 + 1e-6)
    return (fees * 1.18 + exit_notional * 0.025 / 100 + notional * 0.003 / 100 + turnover * 0.02 / 100) * mult
