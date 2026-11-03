"""Five NIFTY expiry-day intraday ideas (spec docs/strategy-specifications/nifty-expiry-ideas.md, v0.1).

Research only; nothing here orders. Each rule takes one session of 1-minute bars (IST DatetimeIndex,
open/high/low/close) and returns a trade dict in the same shape as `expiry_reversal.simulate`, or None.
"""

from __future__ import annotations

from datetime import time

import pandas as pd

from trading_research.strategies.expiry_reversal import EXIT_TIME

SPEC_VERSION = "0.1"
BUF = 0.02 / 100
GAP_MIN = 0.30 / 100
LATE_MIN = 0.30 / 100
LATE_STOP = 0.25 / 100


def bars_tf(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    out = bars.resample(f"{minutes}min", origin="start_day", offset="15min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    out["end"] = out.index + pd.Timedelta(minutes=minutes)
    return out


def walk(bars: pd.DataFrame, entry_ts, side: str, stop: float, target: float | None,
         exit_times: list | None = None) -> dict | None:
    """Enter at the open of the first 1-min bar at/after entry_ts; stop first, then target, then an exit signal
    (fill at the open of the bar at that time), else the 15:15 open."""
    after = bars[(bars.index >= entry_ts) & (bars.index.time < EXIT_TIME)]
    if after.empty:
        return None
    entry_ts, entry = after.index[0], float(after["open"].iloc[0])
    short = side == "short"
    sgn = -1 if short else 1
    risk = (entry - stop) * sgn
    if risk <= 0 or (target is not None and (target - entry) * sgn <= 0):
        return None
    exits = sorted(t for t in (exit_times or []) if t > entry_ts)
    px = ts = reason = None
    for t, b in after.iterrows():
        if exits and t >= exits[0]:
            px, ts, reason = float(b["open"]), t, "signal"
            break
        if (b["high"] >= stop) if short else (b["low"] <= stop):
            px, ts, reason = (max(stop, b["open"]) if short else min(stop, b["open"])), t, "stop"
            break
        if target is not None and ((b["low"] <= target) if short else (b["high"] >= target)):
            px, ts, reason = target, t, "target"
            break
    if px is None:
        tail = bars[bars.index.time >= EXIT_TIME]
        px, ts = (float(tail["open"].iloc[0]), tail.index[0]) if not tail.empty else (float(after["close"].iloc[-1]), after.index[-1])
        reason = "time"
    return {"side": side, "entry_time": entry_ts, "entry": entry, "stop": float(stop), "target": target,
            "risk_pts": float(risk), "exit_time": ts, "exit": float(px), "reason": reason,
            "gross_pts": float((px - entry) * sgn), "reached_opposite": bool(reason == "target")}


def orb(bars: pd.DataFrame, ctx: dict) -> dict | None:
    rng = bars.between_time("09:15", "09:29")
    if rng.empty:
        return None
    hi, lo = float(rng["high"].max()), float(rng["low"].min())
    for _, b in bars_tf(bars[bars.index.time >= time(9, 30)], 5).iterrows():
        if b["end"].time() > time(12, 0):
            break
        if b["close"] > hi:
            stop = lo * (1 - BUF)
            entry = _next_open(bars, b["end"])
            return entry and walk(bars, b["end"], "long", stop, entry + 2 * (entry - stop))
        if b["close"] < lo:
            stop = hi * (1 + BUF)
            entry = _next_open(bars, b["end"])
            return entry and walk(bars, b["end"], "short", stop, entry - 2 * (stop - entry))
    return None


def _next_open(bars: pd.DataFrame, ts) -> float | None:
    nxt = bars[bars.index >= ts]
    return float(nxt["open"].iloc[0]) if len(nxt) else None


def session_average(bars: pd.DataFrame) -> pd.Series:
    """Time-weighted average of typical price from 09:15, known at each 1-min bar's close (TWAP proxy)."""
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3
    return tp.expanding().mean()


def vwap_trend(bars: pd.DataFrame, ctx: dict) -> dict | None:
    avg = session_average(bars)
    q = bars_tf(bars, 15)
    q["avg"] = [avg[avg.index < e].iloc[-1] for e in q["end"]]
    q["side"] = (q["close"] > q["avg"]).map({True: 1, False: -1})
    rows = list(q.iterrows())
    for i in range(1, len(rows)):
        _, b = rows[i]
        _, prev = rows[i - 1]
        if not (time(10, 15) <= b["end"].time() <= time(13, 30)) or b["side"] == prev["side"]:
            continue
        side = "long" if b["side"] > 0 else "short"
        stop = (min(b["low"], prev["low"]) * (1 - BUF)) if side == "long" else (max(b["high"], prev["high"]) * (1 + BUF))
        later = q[q.index > rows[i][0]]
        exits = list(later.loc[later["side"] != b["side"], "end"])
        return walk(bars, b["end"], side, stop, None, exits)
    return None


def _gap(bars: pd.DataFrame, ctx: dict):
    pc = ctx.get("prev_close")
    first = bars.between_time("09:15", "09:19")
    if pc is None or pd.isna(pc) or first.empty or bars.index[0].time() != time(9, 15):
        return None
    gap = float(bars["open"].iloc[0]) / pc - 1
    if abs(gap) < GAP_MIN:
        return None
    return gap, float(first["high"].max()), float(first["low"].min()), float(pc)


def gap_fade(bars: pd.DataFrame, ctx: dict) -> dict | None:
    g = _gap(bars, ctx)
    if g is None:
        return None
    gap, hi, lo, pc = g
    t = bars.index[0].normalize() + pd.Timedelta(hours=9, minutes=20)
    if gap > 0:
        return walk(bars, t, "short", hi * (1 + BUF), pc)
    return walk(bars, t, "long", lo * (1 - BUF), pc)


def gap_follow(bars: pd.DataFrame, ctx: dict) -> dict | None:
    g = _gap(bars, ctx)
    if g is None:
        return None
    gap, hi, lo, _ = g
    t = bars.index[0].normalize() + pd.Timedelta(hours=9, minutes=20)
    if gap > 0:
        return walk(bars, t, "long", lo * (1 - BUF), None)
    return walk(bars, t, "short", hi * (1 + BUF), None)


def late_trend(bars: pd.DataFrame, ctx: dict) -> dict | None:
    t = bars.index[0].normalize() + pd.Timedelta(hours=13, minutes=30)
    before = bars[bars.index < t]
    if before.empty or bars.index[0].time() != time(9, 15):
        return None
    move = float(before["close"].iloc[-1]) / float(bars["open"].iloc[0]) - 1
    if abs(move) < LATE_MIN:
        return None
    entry = _next_open(bars, t)
    if entry is None:
        return None
    if move > 0:
        return walk(bars, t, "long", entry * (1 - LATE_STOP), None)
    return walk(bars, t, "short", entry * (1 + LATE_STOP), None)


RULES = {"EXP-0056": ("orb", orb), "EXP-0057": ("vwap_trend_twap", vwap_trend), "EXP-0058": ("gap_fade", gap_fade),
         "EXP-0059": ("gap_follow", gap_follow), "EXP-0060": ("late_trend", late_trend)}
