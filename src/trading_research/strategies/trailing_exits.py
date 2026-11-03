"""Trailing-stop and partial exits for long intraday entries on 1-minute bars (spec trailing-exits.md, EXP-0082).

Research only; nothing here orders. `walk` takes one day's 1-minute bars after the scan time plus the day's 5-minute
indicator columns and returns the exit legs for one exit rule. Every stop update uses completed bars only and applies
from the next 1-minute bar, so nothing looks ahead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

OPEN_MIN = 9 * 60 + 15
EXIT_MIN = 15 * 60 + 10


@dataclass(frozen=True)
class Exit:
    name: str
    target_r: float | None = None   # full exit at this R (fixed rules)
    trail: str | None = None        # None, "be", "ladder", "atr", "swing", "ema"
    partial_r: float | None = None  # sell half here, rest follows `trail`
    atr_mult: float = 2.0
    swing_bars: int = 3


EXITS = (
    Exit("F1 1R", target_r=1.0),
    Exit("F2 2R", target_r=2.0),
    Exit("F3 3R", target_r=3.0),
    Exit("F0 no target"),
    Exit("T1 breakeven", trail="be"),
    Exit("T2 ladder", trail="ladder"),
    Exit("T3 ATR trail", trail="atr"),
    Exit("T4 swing trail", trail="swing"),
    Exit("T5 EMA9 trail", trail="ema"),
    Exit("P1 half 2R + breakeven", trail="be", partial_r=2.0),
    Exit("P2 half 2R + ATR trail", trail="atr", partial_r=2.0),
    Exit("P3 half 2R + swing trail", trail="swing", partial_r=2.0),
)
BASELINE = "F2 2R"
TRAILING = tuple(e.name for e in EXITS if e.trail is not None)


def five_minute_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    """5-minute bars (anchored 09:15) of every session in `bars` (columns date, minute, open, high, low, close),
    with EMA9 of closes and ATR14 (simple mean of 14 true ranges), both running across sessions.
    Index: (date, end minute)."""
    slot = (bars["minute"].to_numpy() - OPEN_MIN) // 5
    g = bars.assign(slot=slot).groupby(["date", "slot"], sort=True)
    f = g.agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    f["ema9"] = f["close"].ewm(span=9, adjust=False).mean()
    prev_c = f["close"].shift(1)
    tr = pd.concat([f["high"] - f["low"], (f["high"] - prev_c).abs(), (f["low"] - prev_c).abs()], axis=1).max(axis=1)
    f["atr14"] = tr.rolling(14, min_periods=14).mean()
    f = f.reset_index()
    f["end"] = OPEN_MIN + (f["slot"] + 1) * 5
    return f.drop(columns="slot").set_index(["date", "end"])


def walk(m: np.ndarray, o: np.ndarray, h: np.ndarray, lo: np.ndarray, i: int, fill: float, entry: float,
         stop: float, rule: Exit, five: dict[int, tuple[float, float, float, float]] | None = None,
         intrabar: bool = False, can_partial: bool = True, tick: float = 0.05) -> list[tuple[float, float, str, int]]:
    """Exit legs [(fraction, price, reason, minute)] for a long filled at bar i.

    `entry`/`stop` are the planned levels (R = entry - stop); `fill` is the actual fill. `five` maps a 5-minute bar's
    end minute to (low, close, ema9, atr14) of that completed bar, real prices. Rules: stop before target inside a
    bar; a bar opening through the stop fills at its open; a bar opening through a target fills at the target; on an
    intrabar entry the entry bar can stop out but cannot reach a target or move the stop; 15:10 bar open otherwise."""
    r = entry - stop
    if r <= 0:
        raise ValueError("stop must be below entry")
    five = five or {}
    lows = {e: v[0] for e, v in five.items()}
    cur = stop
    hh = -math.inf
    reached = False
    pending_exit = False
    left = 1.0
    legs: list[tuple[float, float, str, int]] = []
    target = None if rule.target_r is None else _round_up(entry + rule.target_r * r, tick)
    part = None if (rule.partial_r is None or not can_partial) else _round_up(entry + rule.partial_r * r, tick)
    for j in range(i, len(m)):
        mj = int(m[j])
        if mj >= EXIT_MIN:
            legs.append((left, float(o[j]), "time", mj))
            return legs
        if pending_exit:
            legs.append((left, float(o[j]), "trail (EMA9)", mj))
            return legs
        entry_bar = j == i and intrabar
        if lo[j] <= cur:
            px = cur if entry_bar else min(cur, float(o[j]))
            reason = "stop" if cur == stop else "trail stop"
            legs.append((left, px, reason, mj))
            return legs
        if not entry_bar:
            if target is not None and h[j] >= target:
                legs.append((left, target, "target", mj))
                return legs
            if part is not None and left == 1.0 and h[j] >= part:
                legs.append((0.5, part, "partial", mj))
                left = 0.5
            # ---- updates from this completed bar, used from the next bar
            hh = max(hh, float(h[j]))
            if hh >= entry + r:
                reached = True
            if rule.trail is not None and reached:
                cur = max(cur, entry)
                if rule.trail == "ladder":
                    k = math.floor((hh - entry) / r + 1e-9)
                    cur = max(cur, entry + (k - 1) * r)
                end = mj + 1
                if (end - OPEN_MIN) % 5 == 0 and end in five:
                    low5, close5, ema9, atr = five[end]
                    if rule.trail == "atr" and atr == atr:
                        cur = max(cur, hh - rule.atr_mult * atr)
                    elif rule.trail == "swing":
                        prior = [lows.get(end - 5 * n) for n in range(rule.swing_bars)]
                        if all(v is not None for v in prior):
                            cur = max(cur, min(prior))
                    elif rule.trail == "ema" and ema9 == ema9 and close5 < ema9:
                        pending_exit = True
    legs.append((left, float(o[-1]), "time_last_bar", int(m[-1])))
    return legs


def max_favourable_r(m: np.ndarray, h: np.ndarray, lo: np.ndarray, i: int, entry: float, stop: float,
                     intrabar: bool = False) -> float:
    """Best high (in R from the planned entry) reached before the original stop or 15:10, whichever is first."""
    r = entry - stop
    best = 0.0
    for j in range(i, len(m)):
        if m[j] >= EXIT_MIN or lo[j] <= stop:
            break
        if not (j == i and intrabar):
            best = max(best, (float(h[j]) - entry) / r)
    return best


def _round_up(x: float, tick: float) -> float:
    return round(math.ceil(round(x / tick, 6)) * tick, 2)
