"""Popular Indian influencer intraday setups (spec docs/strategy-specifications/influencer-intraday.md, v0.1).

Rules, reconstructed from public descriptions (sources and ambiguities in the spec and the source register):
  * ``ema5``  - Power of Stocks "5 EMA" (Subhashish Pani): sell on 5-min bars, buy on 15-min bars (EXP-0073);
  * ``st_flip`` / ``st_2r`` - Supertrend(10, 3) on 5-min bars, exit on the opposite flip, with or without a 2R
    target (EXP-0074 / EXP-0075);
  * ``ohol``  - Open = High / Open = Low of the first 15 minutes (EXP-0076);
  * ``cpr``   - narrow Central Pivot Range breakout (Frank Ochoa, popularised in India) (EXP-0077).
Research only; nothing here orders. Prices are in the vendor's scale; the runner converts to rupees.

An ``IDay`` holds one instrument-session: 1-minute bars (minute of day 555 = 09:15), 5-minute and 15-minute bars
whose indicators (EMA 5, Supertrend) run continuously across sessions and use only bars closed so far. Every rule
yields candidate signals in time order; ``first_signal`` applies the stop-width check and ``simulate`` walks the
exit on 1-minute bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SPEC_VERSION = "0.1"
OPEN_MIN = 555          # 09:15
OHOL_END = 570          # 09:30: first 15 minutes 09:15-09:29
ST_FIRST_END = 585      # Supertrend: flips on 5-min bars ending 09:45 or later
CPR_LAST_END = 780      # 13:00
LAST_ENTRY = 870        # 14:30
EXIT_MIN = 915          # 15:15 (MIS square-off)
MIN_STOP, MAX_STOP = 0.10 / 100, 2.0 / 100
OHOL_TOL = 0.02 / 100   # open counts as the 15-min high/low if within 0.02%
EMA5_TARGET_R = 3.0
TARGET_R = 2.0
ST_ATR, ST_MULT = 10, 3.0
CPR_LOOKBACK, CPR_MIN_HIST, CPR_PCTL = 20, 20, 0.25  # LuxAlgo-style: bottom quartile of the last 20 widths
CPR_FIRST_END = 585     # first 15-min close after the opening candle (09:30-09:44 bar)
RULES = ("ema5", "st_flip", "st_2r", "ohol", "cpr")


@dataclass
class Signal:
    rule: str
    side: int               # +1 long, -1 short
    i: int                  # index of the 1-min entry bar
    entry: float            # fill before slippage
    stop: float
    target_r: float | None  # None: no target (exit by flip / time)
    intrabar: bool = False  # True for a stop-order fill inside bar i
    rvol: float = float("nan")
    flip_exit_min: int | None = None  # exit at the open of the first 1-min bar at/after this minute


@dataclass
class IDay:
    date: pd.Timestamp
    m: list
    o: list
    h: list
    l: list
    c: list
    f5: pd.DataFrame        # end, open, high, low, close, ema5, st_dir, st_line (today's 5-min bars)
    f15: pd.DataFrame       # end, open, high, low, close, ema5 (today's 15-min bars)
    rvol15: float = float("nan")  # first-15-min volume / mean of the previous 20 sessions' first 15 minutes
    cpr: dict = field(default_factory=dict)  # top, bot, width, narrow (from the previous session only)


# ------------------------------------------------------------------ indicators


def resample(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Session-anchored bars of `minutes` from 1-min bars of many sessions (09:15 anchor)."""
    mins = bars.index.hour * 60 + bars.index.minute
    slot = (mins - OPEN_MIN) // minutes
    date = bars.index.normalize()
    g = bars.groupby([date, slot.values])
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in bars:
        agg["volume"] = "sum"
    out = g.agg(agg)
    out.index = out.index.set_names(["date", "slot"])
    out = out.reset_index()
    out["end"] = OPEN_MIN + (out["slot"] + 1) * minutes
    return out


def supertrend(f: pd.DataFrame, n: int = ST_ATR, mult: float = ST_MULT) -> tuple[np.ndarray, np.ndarray]:
    """Classic Supertrend on consecutive bars (Wilder ATR). Returns (direction +1/-1, line); nan before warm-up."""
    h, l, c = f["high"].to_numpy(float), f["low"].to_numpy(float), f["close"].to_numpy(float)
    k = len(c)
    tr = np.empty(k)
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = np.full(k, np.nan)
    if k >= n:
        atr[n - 1] = tr[:n].mean()
        for j in range(n, k):
            atr[j] = (atr[j - 1] * (n - 1) + tr[j]) / n
    mid = (h + l) / 2
    ub, lb = mid + mult * atr, mid - mult * atr
    fub, flb = ub.copy(), lb.copy()
    d = np.full(k, np.nan)
    line = np.full(k, np.nan)
    for j in range(k):
        if np.isnan(atr[j]):
            continue
        if j > 0 and not np.isnan(atr[j - 1]):
            fub[j] = ub[j] if (ub[j] < fub[j - 1] or c[j - 1] > fub[j - 1]) else fub[j - 1]
            flb[j] = lb[j] if (lb[j] > flb[j - 1] or c[j - 1] < flb[j - 1]) else flb[j - 1]
            prev = d[j - 1]
            if prev == 1:
                d[j] = -1 if c[j] < flb[j] else 1
            else:
                d[j] = 1 if c[j] > fub[j] else -1
        else:
            d[j] = 1 if c[j] >= mid[j] else -1
        line[j] = flb[j] if d[j] == 1 else fub[j]
    return d, line


def cpr_levels(prev_high: float, prev_low: float, prev_close: float) -> tuple[float, float, float]:
    """(pivot, top, bottom) of the Central Pivot Range from the previous session."""
    p = (prev_high + prev_low + prev_close) / 3
    bc = (prev_high + prev_low) / 2
    tc = 2 * p - bc
    return p, np.maximum(tc, bc), np.minimum(tc, bc)


# ------------------------------------------------------------------ building days


def build_days(bars: pd.DataFrame, daily: pd.DataFrame | None = None) -> list[IDay]:
    """Days for one instrument. `bars`: 1-min OHLC(V) of gate-passing days (IST, naive). `daily`: per date the
    session's high/low/close in the same scale (official or vendor), used for the CPR of the NEXT session."""
    if bars.empty:
        return []
    f5 = resample(bars, 5)
    f5["ema5"] = f5["close"].ewm(span=5, adjust=False).mean()
    f5["st_dir"], f5["st_line"] = supertrend(f5)
    f15 = resample(bars, 15)
    f15["ema5"] = f15["close"].ewm(span=5, adjust=False).mean()
    has_vol = "volume" in bars and float(bars["volume"].sum()) > 0
    rv = {}
    if has_vol:
        first = f15[f15["slot"] == 0].set_index("date")["volume"]
        base = first.shift(1).rolling(20, min_periods=10).mean()
        rv = (first / base.replace(0, np.nan)).to_dict()
    cpr = {}
    if daily is not None and len(daily):
        dl = daily.sort_index()
        p, top, bot = cpr_levels(dl["high"], dl["low"], dl["close"])
        width = (top - bot) / p
        hist = width.rolling(CPR_LOOKBACK, min_periods=CPR_MIN_HIST).quantile(CPR_PCTL)
        for j in range(1, len(dl)):  # levels of session j come from session j-1 only
            d = dl.index[j]
            w, q = float(width.iloc[j - 1]), hist.iloc[j - 2] if j >= 2 else np.nan
            cpr[d] = {"top": float(top.iloc[j - 1]), "bot": float(bot.iloc[j - 1]), "width": w,
                      "narrow": bool(q == q and w <= q)}
    by5, by15 = dict(tuple(f5.groupby("date"))), dict(tuple(f15.groupby("date")))
    days = []
    for d, day in bars.groupby(bars.index.normalize()):
        mins = (day.index.hour * 60 + day.index.minute).tolist()
        days.append(IDay(date=d, m=mins, o=day["open"].tolist(), h=day["high"].tolist(), l=day["low"].tolist(),
                         c=day["close"].tolist(), f5=by5[d].reset_index(drop=True),
                         f15=by15[d].reset_index(drop=True), rvol15=float(rv.get(d, np.nan)),
                         cpr=cpr.get(d, {})))
    return days


# ------------------------------------------------------------------ helpers


def _entry_index(day: IDay, end_min: int) -> int | None:
    for i, mm in enumerate(day.m):
        if mm >= end_min:
            return i if mm <= LAST_ENTRY else None
    return None


def _stop_fill(day: IDay, start_min: int, end_min: int, side: int, trig: float):
    """First 1-min bar in [start_min, end_min) that trades through `trig` (buy stop above / sell stop below).
    Returns (index, fill, intrabar) or None. A bar opening beyond the trigger fills at its open."""
    for i, mm in enumerate(day.m):
        if mm < start_min:
            continue
        if mm >= end_min or mm > LAST_ENTRY:
            return None
        if (side > 0 and day.h[i] >= trig) or (side < 0 and day.l[i] <= trig):
            fill = max(trig, day.o[i]) if side > 0 else min(trig, day.o[i])
            return i, fill, fill != day.o[i]
    return None


# ------------------------------------------------------------------ rules (candidate generators)


def _ema5_side(day: IDay, f: pd.DataFrame, side: int, width: int):
    """Alert candle entirely beyond EMA 5 (low > EMA for sells, high < EMA for buys); the NEXT bar breaking the
    alert's low (high) triggers; a next bar that is itself an alert without breaking replaces it; else it lapses."""
    alert = None
    for k in range(len(f)):
        r = f.iloc[k]
        if alert is not None:
            trig = alert["low"] if side < 0 else alert["high"]
            hit = _stop_fill(day, int(r["end"]) - width, int(r["end"]), side, trig)
            if hit is not None:
                i, fill, intra = hit
                stop = alert["high"] if side < 0 else alert["low"]
                yield Signal("ema5", side, i, fill, stop, EMA5_TARGET_R, intrabar=intra)
                alert = None
                continue
        is_alert = (r["low"] > r["ema5"]) if side < 0 else (r["high"] < r["ema5"])
        alert = r if is_alert else None


def ema5(day: IDay):
    found = list(_ema5_side(day, day.f5, -1, 5)) + list(_ema5_side(day, day.f15, 1, 15))
    yield from sorted(found, key=lambda s: (s.i, s.side))


def _st(day: IDay, rule: str, target_r: float | None):
    f = day.f5
    for k in range(1, len(f)):
        end = int(f.at[k, "end"])
        if end < ST_FIRST_END:
            continue
        d0, d1 = f.at[k - 1, "st_dir"], f.at[k, "st_dir"]
        if d0 != d0 or d1 == d0:
            continue
        side = int(d1)
        i = _entry_index(day, end)
        if i is None:
            return
        flip = None
        for kk in range(k + 1, len(f)):
            if f.at[kk, "st_dir"] != d1:
                flip = int(f.at[kk, "end"])
                break
        yield Signal(rule, side, i, day.o[i], float(f.at[k, "st_line"]), target_r, flip_exit_min=flip)


def st_flip(day: IDay):
    yield from _st(day, "st_flip", None)


def st_2r(day: IDay):
    yield from _st(day, "st_2r", TARGET_R)


def ohol(day: IDay):
    n = sum(1 for mm in day.m if mm < OHOL_END)
    if n < 13 or day.m[0] != OPEN_MIN:
        return
    op, hi, lo = day.o[0], max(day.h[:n]), min(day.l[:n])
    is_low, is_high = lo >= op * (1 - OHOL_TOL), hi <= op * (1 + OHOL_TOL)
    if is_low == is_high:
        return  # neither, or a flat first 15 minutes
    side = 1 if is_low else -1
    i = _entry_index(day, OHOL_END)
    if i is not None:
        yield Signal("ohol", side, i, day.o[i], lo if side > 0 else hi, TARGET_R, rvol=day.rvol15)


def cpr(day: IDay):
    """Narrow CPR day: the first 15-min close (from the bar ending 09:45) beyond the CPR sets the side; stop at the
    other side of the CPR; 2R target. A day that opens beyond the CPR and stays there signals at 09:45."""
    lv = day.cpr
    if not lv or not lv["narrow"]:
        return
    f = day.f15
    for k in range(len(f)):
        end, close = int(f.at[k, "end"]), float(f.at[k, "close"])
        if end < CPR_FIRST_END:
            continue
        if end > CPR_LAST_END:
            return
        side = 1 if close > lv["top"] else -1 if close < lv["bot"] else 0
        if side:
            i = _entry_index(day, end)
            if i is None:
                return
            yield Signal("cpr", side, i, day.o[i], lv["bot"] if side > 0 else lv["top"], TARGET_R, rvol=day.rvol15)
            return  # first close beyond the CPR only


GENERATORS = {"ema5": ema5, "st_flip": st_flip, "st_2r": st_2r, "ohol": ohol, "cpr": cpr}
FIRST_ONLY = {"ohol", "cpr"}  # rules whose single daily signal is not replaced by a later one


def first_signal(day: IDay, rule: str, check_width: bool = True) -> Signal | None:
    for sig in GENERATORS[rule](day):
        width = abs(sig.entry - sig.stop) / sig.entry
        ok = (sig.entry - sig.stop) * sig.side > 0 and (not check_width or MIN_STOP <= width <= MAX_STOP)
        if ok:
            return sig
        if rule in FIRST_ONLY:
            return None
    return None


def simulate(day: IDay, sig: Signal) -> dict:
    """Exit walk on 1-min bars: stop before target within a bar; a bar opening through the stop fills at its open;
    on an intrabar (stop-order) entry the entry bar can stop out but not reach the target; flip exit at the open
    of the first bar at/after the flip bar's end; 15:15 open otherwise."""
    s, entry, stop = sig.side, sig.entry, sig.stop
    target = entry + sig.target_r * (entry - stop) if sig.target_r else None
    px = reason = j_exit = None
    for j in range(sig.i, len(day.m)):
        if day.m[j] >= EXIT_MIN:
            px, reason, j_exit = day.o[j], "time", j
            break
        if sig.flip_exit_min is not None and day.m[j] >= sig.flip_exit_min and j > sig.i:
            px, reason, j_exit = day.o[j], "flip", j
            break
        if (day.l[j] <= stop) if s > 0 else (day.h[j] >= stop):
            if j == sig.i and sig.intrabar:
                px = stop
            else:
                px = min(stop, day.o[j]) if s > 0 else max(stop, day.o[j])
            reason, j_exit = "stop", j
            break
        if target is not None and not (j == sig.i and sig.intrabar) and \
                ((day.h[j] >= target) if s > 0 else (day.l[j] <= target)):
            px, reason, j_exit = target, "target", j
            break
    if px is None:
        j_exit = len(day.m) - 1
        px, reason = day.c[j_exit], "time_last_bar"
    return {"date": day.date, "rule": sig.rule, "side": s, "entry_min": day.m[sig.i], "entry": entry,
            "stop": stop, "target": target if target is not None else float("nan"), "exit_min": day.m[j_exit],
            "exit": px, "reason": reason, "gross_r": (px - entry) * s / abs(entry - stop), "rvol": sig.rvol}
