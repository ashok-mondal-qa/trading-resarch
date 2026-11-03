"""Three intraday strategy families (spec docs/strategy-specifications/intraday-three-families.md, v0.1).

Opening Range Breakout (EXP-0061/0064), Breakout and Retest (0062/0065), EMA 9/15 Trend Pullback (0063/0066).
Research only; nothing here orders. Prices here are in the vendor's scale; the runner converts to rupees.

A `Day` holds one instrument-session: 1-minute bars (minute of day 555 = 09:15) and 5-minute bars with indicators
that use only data up to each 5-minute close. Each rule yields candidate signals in time order; `first_signal`
applies the shared stop-width check and (for the filtered variants) the filter, and `simulate` walks the exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SPEC_VERSION = "0.1"
OPEN_MIN = 555          # 09:15
OR_END = 570            # 09:30
ORB_LAST_END = 660      # 11:00
BRT_LAST_END = 810      # 13:30
EMA_FIRST_END = 585     # 09:45
EMA_LAST_END = 865      # 14:25
LAST_ENTRY = 870        # 14:30
EXIT_MIN = 915          # 15:15
TARGET_R = 2.0
MIN_STOP, MAX_STOP = 0.20 / 100, 2.0 / 100
RETEST_BARS = 12
RETEST_TOL = 0.10 / 100
STOP_BUF = 0.05 / 100
RVOL_MIN = 1.5
RULES = ("orb", "brt", "ema")


@dataclass
class Signal:
    rule: str
    side: int               # +1 long, -1 short
    i: int                  # index of the 1-min entry bar
    entry: float            # fill before slippage
    stop: float
    k: int                  # index of the trigger 5-min bar
    intrabar: bool = False  # True for a stop-order fill inside bar i
    rvol: float = float("nan")


@dataclass
class Day:
    date: pd.Timestamp
    m: list                 # minute of day per 1-min bar
    o: list
    h: list
    l: list
    c: list
    b_end: list             # 5-min bar end minute
    bo: list
    bh: list
    bl: list
    bc: list
    ema9: list
    ema15: list
    ema15_lag3: list
    vwap: list
    rvol: list | None = None
    prev_high: float = float("nan")
    prev_low: float = float("nan")
    prev_close: float = float("nan")
    sma20: float = float("nan")
    mkt: dict = field(default_factory=dict)  # 5-min bar end minute -> +1 / -1 / 0 (NIFTY vs its 09:15 open)


# ------------------------------------------------------------------ building days


def five_minute(bars: pd.DataFrame) -> pd.DataFrame:
    """5-min bars of one session from 1-min bars; volume summed when present."""
    mins = bars.index.hour * 60 + bars.index.minute
    slot = (mins - OPEN_MIN) // 5
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in bars:
        agg["volume"] = "sum"
    out = bars.groupby(slot.values).agg(agg)
    out["end"] = OPEN_MIN + (out.index + 1) * 5
    return out


def build_days(bars: pd.DataFrame, prev_info: pd.DataFrame | None = None,
               mkt: dict | None = None) -> list[Day]:
    """Days for one instrument. `bars`: 1-min OHLC(V) of gate-passing days only (IST, naive). `prev_info`: per
    date prev_high/prev_low/prev_close/sma20 (vendor scale). `mkt`: date -> {bar end -> +1/-1/0}."""
    key = bars.index.normalize()
    has_vol = "volume" in bars and float(bars["volume"].sum()) > 0
    fives, onemins = [], []
    for d, day in bars.groupby(key):
        f = five_minute(day)
        f["date"] = d
        fives.append(f)
        onemins.append((d, day))
    if not fives:
        return []
    allf = pd.concat(fives, ignore_index=True)
    allf["ema9"] = allf["close"].ewm(span=9, adjust=False).mean()
    allf["ema15"] = allf["close"].ewm(span=15, adjust=False).mean()
    allf["ema15_lag3"] = allf["ema15"].shift(3)
    if has_vol:
        piv = allf.pivot_table(index="date", columns="end", values="volume", aggfunc="sum")
        base = piv.shift(1).rolling(20, min_periods=10).mean()
        rv = (piv / base.replace(0, np.nan)).stack().rename("rvol")
        allf = allf.join(rv, on=["date", "end"])
    days = []
    by_date = dict(tuple(allf.groupby("date")))
    for d, day in onemins:
        f = by_date[d]
        mins = (day.index.hour * 60 + day.index.minute).to_numpy()
        tp = ((day["high"] + day["low"] + day["close"]) / 3).to_numpy()
        if has_vol and float(day["volume"].sum()) > 0:
            v = day["volume"].to_numpy()
            cum_pv, cum_v = np.cumsum(tp * v), np.cumsum(v)
        else:
            cum_pv, cum_v = np.cumsum(tp), np.arange(1, len(tp) + 1, dtype=float)
        ends = f["end"].to_numpy()
        pos = np.searchsorted(mins, ends, side="left") - 1  # last 1-min bar before each 5-min end
        with np.errstate(invalid="ignore", divide="ignore"):
            vw = np.where(cum_v[pos] > 0, cum_pv[pos] / cum_v[pos], np.nan)
        pi = prev_info.loc[d] if prev_info is not None and d in prev_info.index else None
        days.append(Day(
            date=d, m=mins.tolist(), o=day["open"].tolist(), h=day["high"].tolist(), l=day["low"].tolist(),
            c=day["close"].tolist(), b_end=ends.tolist(), bo=f["open"].tolist(), bh=f["high"].tolist(),
            bl=f["low"].tolist(), bc=f["close"].tolist(), ema9=f["ema9"].tolist(), ema15=f["ema15"].tolist(),
            ema15_lag3=f["ema15_lag3"].tolist(), vwap=vw.tolist(),
            rvol=f["rvol"].tolist() if "rvol" in f else None,
            prev_high=float(pi["prev_high"]) if pi is not None else float("nan"),
            prev_low=float(pi["prev_low"]) if pi is not None else float("nan"),
            prev_close=float(pi["prev_close"]) if pi is not None else float("nan"),
            sma20=float(pi["sma20"]) if pi is not None else float("nan"),
            mkt=(mkt or {}).get(d, {})))
    return days


def market_direction(bars: pd.DataFrame) -> dict:
    """date -> {5-min bar end -> sign(NIFTY close at that end - NIFTY 09:15 open)}."""
    out = {}
    for d, day in bars.groupby(bars.index.normalize()):
        if day.index[0].hour * 60 + day.index[0].minute != OPEN_MIN:
            continue
        f = five_minute(day)
        op = float(day["open"].iloc[0])
        out[d] = {int(e): int(np.sign(c - op)) for e, c in zip(f["end"], f["close"])}
    return out


# ------------------------------------------------------------------ helpers


def _entry_index(day: Day, end_min: int) -> int | None:
    for i, mm in enumerate(day.m):
        if mm >= end_min:
            return i if mm <= LAST_ENTRY else None
    return None


def _rv(day: Day, k: int) -> float:
    return float(day.rvol[k]) if day.rvol is not None and day.rvol[k] == day.rvol[k] else float("nan")


# ------------------------------------------------------------------ rules (candidate generators)


def orb(day: Day):
    if not day.b_end or day.b_end[0] != OPEN_MIN + 5:
        return
    n_or = sum(1 for e in day.b_end if e <= OR_END)
    if n_or < 3:
        return
    hi, lo = max(day.bh[:n_or]), min(day.bl[:n_or])
    for k in range(n_or, len(day.b_end)):
        if day.b_end[k] > ORB_LAST_END:
            return
        side = 1 if day.bc[k] > hi else -1 if day.bc[k] < lo else 0
        if side:
            i = _entry_index(day, day.b_end[k])
            if i is not None:
                yield Signal("orb", side, i, day.o[i], lo if side > 0 else hi, k, rvol=_rv(day, k))
            return  # first breakout only


def brt(day: Day):
    if day.prev_high != day.prev_high or not day.bo:
        return
    found = []
    for side, level in ((1, day.prev_high), (-1, day.prev_low)):
        if (day.bo[0] - level) * side >= 0:
            continue  # opened beyond the level: not an intraday breakout
        k_brk = None
        for k, e in enumerate(day.b_end):
            if e > BRT_LAST_END:
                break
            if e >= OR_END + 5 and (day.bc[k] - level) * side > 0:
                k_brk = k
                break
        if k_brk is None:
            continue
        for k in range(k_brk + 1, min(k_brk + 1 + RETEST_BARS, len(day.b_end))):
            if (day.bc[k] - level * (1 - RETEST_TOL * side)) * side < 0:
                break  # closed back through the level: failed breakout
            touch = day.bl[k] <= level * (1 + RETEST_TOL) if side > 0 else day.bh[k] >= level * (1 - RETEST_TOL)
            if touch and (day.bc[k] - level) * side > 0:
                i = _entry_index(day, day.b_end[k])
                if i is not None:
                    ext = min(day.bl[k], level) if side > 0 else max(day.bh[k], level)
                    stop = ext * (1 - STOP_BUF * side)
                    found.append(Signal("brt", side, i, day.o[i], stop, k, rvol=_rv(day, k_brk)))
                break
    yield from sorted(found, key=lambda s: s.i)


def ema(day: Day):
    n = len(day.b_end)
    for k in range(n):
        e = day.b_end[k]
        if e < EMA_FIRST_END or e > EMA_LAST_END:
            continue
        e9, e15, lag, vw = day.ema9[k], day.ema15[k], day.ema15_lag3[k], day.vwap[k]
        if lag != lag or vw != vw:
            continue
        for side in (1, -1):
            trend = (e9 - e15) * side > 0 and (e15 - lag) * side > 0 and (day.bc[k] - vw) * side > 0
            if not trend:
                continue
            pull = day.bl[k] <= e9 if side > 0 else day.bh[k] >= e9
            if not (pull and (day.bc[k] - e15) * side > 0):
                continue
            trig = day.bh[k] if side > 0 else day.bl[k]
            stop = day.bl[k] * (1 - STOP_BUF) if side > 0 else day.bh[k] * (1 + STOP_BUF)
            for i, mm in enumerate(day.m):
                if mm < e:
                    continue
                if mm >= e + 5 or mm > LAST_ENTRY:
                    break
                if (side > 0 and day.h[i] >= trig) or (side < 0 and day.l[i] <= trig):
                    fill = max(trig, day.o[i]) if side > 0 else min(trig, day.o[i])
                    yield Signal("ema", side, i, fill, stop, k, intrabar=fill != day.o[i], rvol=_rv(day, k))
                    break


GENERATORS = {"orb": orb, "brt": brt, "ema": ema}


def passes_filter(day: Day, sig: Signal, use_rvol: bool) -> bool:
    if day.prev_close != day.prev_close or day.sma20 != day.sma20:
        return False
    if (day.prev_close - day.sma20) * sig.side <= 0:
        return False
    if day.mkt.get(day.b_end[sig.k], 0) * sig.side <= 0:
        return False
    if use_rvol and not (sig.rvol >= RVOL_MIN):
        return False
    return True


def first_signal(day: Day, rule: str, filtered: bool, use_rvol: bool = True) -> Signal | None:
    for sig in GENERATORS[rule](day):
        width = abs(sig.entry - sig.stop) / sig.entry
        if (sig.entry - sig.stop) * sig.side <= 0 or not (MIN_STOP <= width <= MAX_STOP):
            if rule == "orb":
                return None
            continue
        if filtered and not passes_filter(day, sig, use_rvol):
            if rule == "orb":
                return None
            continue
        return sig
    return None


def simulate(day: Day, sig: Signal) -> dict:
    """Exit walk on 1-min bars: stop before target in a bar; a bar opening through the stop fills at its open;
    on an intrabar (stop-order) entry the entry bar can stop out but not reach the target; 15:15 open otherwise."""
    s, entry, stop = sig.side, sig.entry, sig.stop
    target = entry + TARGET_R * (entry - stop)
    px = reason = None
    j_exit = None
    for j in range(sig.i, len(day.m)):
        if day.m[j] >= EXIT_MIN:
            px, reason, j_exit = day.o[j], "time", j
            break
        if (day.l[j] <= stop) if s > 0 else (day.h[j] >= stop):
            if j == sig.i and sig.intrabar:
                px = stop
            else:
                px = min(stop, day.o[j]) if s > 0 else max(stop, day.o[j])
            reason, j_exit = "stop", j
            break
        if not (j == sig.i and sig.intrabar) and ((day.h[j] >= target) if s > 0 else (day.l[j] <= target)):
            px, reason, j_exit = target, "target", j
            break
    if px is None:
        j_exit = len(day.m) - 1
        px, reason = day.c[j_exit], "time_last_bar"
    return {"date": day.date, "rule": sig.rule, "side": s, "entry_min": day.m[sig.i], "entry": entry,
            "stop": stop, "target": target, "exit_min": day.m[j_exit], "exit": px, "reason": reason,
            "gross_r": (px - entry) * s / abs(entry - stop), "rvol": sig.rvol}
