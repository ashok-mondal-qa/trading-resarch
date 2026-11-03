"""Intraday ideas from the research source library (spec docs/strategy-specifications/sourced-intraday-ideas.md v0.1).

EXP-0068/0069: market intraday momentum (Gao, Han, Li, Zhou 2018) on NIFTY; EXP-0070: 5-minute opening range breakout
on "stocks in play" (reconstruction of Zarattini & Aziz; exact rules UNVERIFIED). Research only; nothing here orders.
Bars are 1-minute, IST, naive timestamps; minute of day 555 = 09:15. Prices stay in the input's scale.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SPEC_VERSION = "0.1"
OPEN_MIN = 555            # 09:15
SIGNAL_MIN = 585          # 09:45: momentum signal = close of the 09:44 bar
MOM_ENTRY, MOM_EXIT = 885, 915     # 14:45 open .. 15:15 open
PAPER_ENTRY, PAPER_LAST = 900, 929  # 15:00 open .. 15:29 close (paper window, gross diagnostic)
MOM_STOP = 1.0 / 100
BIG_PCT, BIG_LOOKBACK, BIG_MIN_HIST = 0.80, 250, 120
ORB5_ENTRY = 560          # 09:20
ORB5_TARGET_R = 10.0
RVOL_LOOKBACK, RVOL_MIN_HIST, RVOL_MIN = 14, 10, 1.0
MIN_STOP, MAX_STOP = 0.20 / 100, 2.0 / 100
EXIT_MIN = 915


def _minutes(day: pd.DataFrame) -> np.ndarray:
    return (day.index.hour * 60 + day.index.minute).to_numpy()


def walk_exit(m, o, h, l, c, i: int, side: int, stop: float, target: float | None, exit_min: int) -> tuple:
    """Exit walk from 1-min bar i (entry at o[i]): stop before target in a bar; a bar opening through the stop fills
    at its open; time exit at the open of the first bar at or after exit_min; else the last bar's close."""
    for j in range(i, len(m)):
        if m[j] >= exit_min:
            return o[j], "time", m[j]
        if (l[j] <= stop) if side > 0 else (h[j] >= stop):
            return (min(stop, o[j]) if side > 0 else max(stop, o[j])), "stop", m[j]
        if target is not None and ((h[j] >= target) if side > 0 else (l[j] <= target)):
            return target, "target", m[j]
    return c[-1], "time_last_bar", m[-1]


# ------------------------------------------------------------------ EXP-0068 / 0069 market intraday momentum


def momentum_day(day: pd.DataFrame, prev_close: float) -> dict | None:
    """One NIFTY session -> r1 and the 14:45-15:15 trade (None if a needed bar is missing)."""
    if not prev_close == prev_close or prev_close <= 0:
        return None
    m = _minutes(day)
    o, h, l, c = (day[k].to_numpy() for k in ("open", "high", "low", "close"))
    sig = np.flatnonzero(m == SIGNAL_MIN - 1)
    ent = np.flatnonzero(m == MOM_ENTRY)
    if len(sig) == 0 or len(ent) == 0:
        return None
    r1 = float(c[sig[0]] / prev_close - 1.0)
    out = {"date": day.index[0].normalize(), "r1": r1}
    pe = np.flatnonzero(m == PAPER_ENTRY)
    pl = np.flatnonzero(m == PAPER_LAST)
    out["paper_window_ret"] = float(c[pl[0]] / o[pe[0]] - 1.0) if len(pe) and len(pl) else np.nan
    side = 1 if r1 > 0 else (-1 if r1 < 0 else 0)
    if side == 0:
        return out | {"side": 0}
    i = int(ent[0])
    entry = float(o[i])
    stop = entry * (1 - MOM_STOP * side)
    px, reason, xm = walk_exit(m, o, h, l, c, i, side, stop, None, MOM_EXIT)
    return out | {"side": side, "entry_min": int(m[i]), "entry": entry, "stop": stop, "target": np.nan,
                  "exit_min": int(xm), "exit": float(px), "reason": reason,
                  "gross_r": (px - entry) * side / abs(entry - stop)}


def big_move_mask(r1: pd.Series) -> pd.Series:
    """True where |r1| >= the 80th percentile of |r1| over the previous 250 valid sessions (>= 120 needed)."""
    a = r1.abs()
    thr = a.shift(1).rolling(BIG_LOOKBACK, min_periods=BIG_MIN_HIST).quantile(BIG_PCT)
    return (a >= thr) & thr.notna()


# ------------------------------------------------------------------ EXP-0070 5-minute ORB on stocks in play


def first5(day: pd.DataFrame) -> dict | None:
    """First 5-minute bar (09:15-09:19) of a session; None unless all five 1-min bars exist."""
    m = _minutes(day)
    k = (m >= OPEN_MIN) & (m < OPEN_MIN + 5)
    if k.sum() != 5:
        return None
    f = day[k]
    return {"open": float(f["open"].iloc[0]), "high": float(f["high"].max()), "low": float(f["low"].min()),
            "close": float(f["close"].iloc[-1]), "volume": float(f["volume"].sum()) if "volume" in f else np.nan}


def rvol_series(first_vol: pd.Series) -> pd.Series:
    """First-5-min volume / mean of the previous 14 sessions (>= 10 needed). Index = session dates in order."""
    base = first_vol.shift(1).rolling(RVOL_LOOKBACK, min_periods=RVOL_MIN_HIST).mean()
    return first_vol / base.replace(0, np.nan)


def orb5_trade(day: pd.DataFrame, f5: dict) -> dict | None:
    """Direction of the first 5-min bar; entry 09:20 open; stop = other extreme of that bar; 10R target; 15:15."""
    side = 1 if f5["close"] > f5["open"] else (-1 if f5["close"] < f5["open"] else 0)
    if side == 0:
        return None
    m = _minutes(day)
    ent = np.flatnonzero(m == ORB5_ENTRY)
    if len(ent) == 0:
        return None
    o, h, l, c = (day[k].to_numpy() for k in ("open", "high", "low", "close"))
    i = int(ent[0])
    entry = float(o[i])
    stop = f5["low"] if side > 0 else f5["high"]
    dist = (entry - stop) * side
    if dist <= 0 or not (MIN_STOP <= dist / entry <= MAX_STOP):
        return None
    target = entry + ORB5_TARGET_R * dist * side
    px, reason, xm = walk_exit(m, o, h, l, c, i, side, stop, target, EXIT_MIN)
    return {"date": day.index[0].normalize(), "side": side, "entry_min": int(m[i]), "entry": entry, "stop": stop,
            "target": target, "exit_min": int(xm), "exit": float(px), "reason": reason,
            "gross_r": (px - entry) * side / dist}
