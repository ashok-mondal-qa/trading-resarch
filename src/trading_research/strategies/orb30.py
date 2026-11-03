"""30-minute NIFTY Opening Range Breakout grid (spec docs/strategy-specifications/nifty-orb30.md v0.1, EXP-0071/0072).

Research only; nothing here orders. Prices are NIFTY index points; the runner converts them to an ETF notional.

`build_day` turns one gate-passing session of 1-minute bars into an `OrbDay`: the 09:15-09:44 opening range, the
first 5-minute close beyond it (bars ending 09:50-13:00) and everything a filter needs, each value computed only
from data available at the signal bar's close (daily ATR/ADX come from earlier sessions). `trade` applies one grid
configuration (variant, stop, target, direction) and walks the exit on 1-minute bars.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trading_research.indicators.core import atr as wilder_atr

SPEC_VERSION = "0.1"
OPEN_MIN = 555            # 09:15
OR_LAST_MIN = 584         # 09:44 (last 1-min bar in the range)
OR_MIN_BARS = 28
SIG_FIRST_END = 590       # first 5-min bar that can signal ends 09:50
SIG_LAST_END = 780        # last ends 13:00
EXIT_MIN = 915            # 15:15
MIN_STOP, MAX_STOP = 0.20 / 100, 2.0 / 100
ATR_STOP_MULT = 0.5
ORW_LO, ORW_HI = 0.25, 0.60
RVOL_MIN = 1.5

VARIANTS = ("V0", "V2", "V4")          # selection grid (V1/V3 need volume: EXP-0072, 2026 only)
VOLUME_VARIANTS = ("V1", "V3")
STOPS = ("range", "atr")
TARGETS = (1.0, 1.5, 2.0, 3.0)
DIRECTIONS = ("both", "long", "short")


@dataclass
class OrbDay:
    date: pd.Timestamp
    m: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    or_hi: float
    or_lo: float
    atr14: float = float("nan")     # previous sessions only
    adx14: float = float("nan")     # previous sessions only
    side: int = 0                   # first breakout: +1 / -1 / 0 none
    sig_end: int = 0                # signal 5-min bar end minute
    sig_close: float = float("nan")
    twap: float = float("nan")      # time-weighted typical price 09:15..signal close (VWAP proxy)
    vwap: float = float("nan")      # volume-weighted, only when volume exists
    rvol: float = float("nan")      # signal bar volume / same-slot 20-session mean
    i: int = -1                     # 1-min entry bar index
    day_open: float = float("nan")
    day_close: float = float("nan")
    day_high: float = float("nan")
    day_low: float = float("nan")

    @property
    def or_width_atr(self) -> float:
        return (self.or_hi - self.or_lo) / self.atr14 if self.atr14 == self.atr14 and self.atr14 > 0 else float("nan")

    @property
    def trend_day_expost(self) -> bool:
        rng = self.day_high - self.day_low
        return bool(rng > 0 and abs(self.day_close - self.day_open) >= 0.6 * rng)


# ------------------------------------------------------------------ daily indicators (official NSE daily bars)


def adx(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ADX(n) from daily high/low/close."""
    h, l, c = bars["high"].to_numpy(float), bars["low"].to_numpy(float), bars["close"].to_numpy(float)
    up, dn = np.diff(h, prepend=np.nan), -np.diff(l, prepend=np.nan)
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.roll(c, 1)
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) < 2 * n + 1:
        return pd.Series(out, index=bars.index)

    def wilder(x: np.ndarray) -> np.ndarray:
        s = np.full(len(x), np.nan)
        s[n] = x[1:n + 1].sum()
        for i in range(n + 1, len(x)):
            s[i] = s[i - 1] - s[i - 1] / n + x[i]
        return s

    atr_s, p_s, n_s = wilder(tr), wilder(pdm), wilder(ndm)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi, ndi = 100 * p_s / atr_s, 100 * n_s / atr_s
        dx = 100 * abs(pdi - ndi) / (pdi + ndi)
    out[2 * n] = np.nanmean(dx[n + 1:2 * n + 1])
    for i in range(2 * n + 1, len(c)):
        out[i] = (out[i - 1] * (n - 1) + dx[i]) / n
    return pd.Series(out, index=bars.index)


def daily_context(official: pd.DataFrame) -> pd.DataFrame:
    """Per date: ATR14 and ADX14 known before that session's open (computed through the previous session)."""
    off = official[["open", "high", "low", "close"]].astype(float).sort_index()
    out = pd.DataFrame(index=off.index)
    out["atr14"] = wilder_atr(off, 14).shift(1)
    out["adx14"] = adx(off, 14).shift(1)
    return out


# ------------------------------------------------------------------ building a day


def five_minute(day: pd.DataFrame) -> pd.DataFrame:
    mins = day.index.hour * 60 + day.index.minute
    slot = (mins - OPEN_MIN) // 5
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in day:
        agg["volume"] = "sum"
    f = day.groupby(slot.values).agg(agg)
    f["end"] = OPEN_MIN + (f.index + 1) * 5
    return f


def build_day(day: pd.DataFrame, ctx: pd.Series | None = None, slot_base: pd.Series | None = None) -> OrbDay | None:
    """One session (1-min bars, naive IST index). `slot_base`: 5-min bar end -> mean volume of that slot over the
    previous 20 sessions (only when volume exists). Returns None if the opening range is incomplete."""
    mins = (day.index.hour * 60 + day.index.minute).to_numpy()
    in_or = (mins >= OPEN_MIN) & (mins <= OR_LAST_MIN)
    if in_or.sum() < OR_MIN_BARS or mins[0] != OPEN_MIN:
        return None
    o, h, l, c = (day[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    d = OrbDay(date=day.index[0].normalize(), m=mins, o=o, h=h, l=l, c=c,
               or_hi=float(h[in_or].max()), or_lo=float(l[in_or].min()),
               day_open=float(o[0]), day_close=float(c[-1]), day_high=float(h.max()), day_low=float(l.min()))
    if ctx is not None:
        d.atr14, d.adx14 = float(ctx["atr14"]), float(ctx["adx14"])
    f = five_minute(day)
    has_vol = "volume" in day and float(day["volume"].sum()) > 0
    tp = (h + l + c) / 3
    for _, b in f.iterrows():
        end = int(b["end"])
        if end < SIG_FIRST_END:
            continue
        if end > SIG_LAST_END:
            break
        side = 1 if b["close"] > d.or_hi else -1 if b["close"] < d.or_lo else 0
        if not side:
            continue
        nxt = np.flatnonzero(mins >= end)
        if not len(nxt) or mins[nxt[0]] >= EXIT_MIN:
            return d
        upto = mins < end
        d.side, d.sig_end, d.sig_close, d.i = side, end, float(b["close"]), int(nxt[0])
        d.twap = float(tp[upto].mean())
        if has_vol:
            v = day["volume"].to_numpy(float)[upto]
            d.vwap = float((tp[upto] * v).sum() / v.sum()) if v.sum() > 0 else float("nan")
            if slot_base is not None and end in slot_base.index and slot_base[end] > 0:
                d.rvol = float(b["volume"] / slot_base[end])
        return d  # first breakout only
    return d


# ------------------------------------------------------------------ one configuration


def passes(d: OrbDay, variant: str, direction: str) -> bool:
    if d.side == 0:
        return False
    if direction == "long" and d.side < 0 or direction == "short" and d.side > 0:
        return False
    if variant in ("V2", "V3"):
        ref = d.vwap if variant == "V3" else d.twap
        if not (ref == ref and (d.sig_close - ref) * d.side > 0):
            return False
    if variant in ("V1", "V3") and not (d.rvol >= RVOL_MIN):
        return False
    if variant == "V4":
        w = d.or_width_atr
        if not (w == w and ORW_LO <= w <= ORW_HI):
            return False
    return True


def trade(d: OrbDay, variant: str, stop_kind: str, target_r: float, direction: str = "both") -> dict | None:
    """The day's trade for one configuration, or None. Stop before target in a bar; a bar opening beyond the stop
    fills at its open; time exit at the 15:15 bar open."""
    if not passes(d, variant, direction):
        return None
    s, entry = d.side, float(d.o[d.i])
    if stop_kind == "range":
        stop = d.or_lo if s > 0 else d.or_hi
    else:
        if not (d.atr14 == d.atr14 and d.atr14 > 0):
            return None
        stop = entry - s * ATR_STOP_MULT * d.atr14
    risk = (entry - stop) * s
    if risk <= 0 or not (MIN_STOP <= risk / entry <= MAX_STOP):
        return None
    target = entry + s * target_r * risk
    px = reason = None
    j = d.i
    for j in range(d.i, len(d.m)):
        if d.m[j] >= EXIT_MIN:
            px, reason = d.o[j], "time"
            break
        if (d.l[j] <= stop) if s > 0 else (d.h[j] >= stop):
            px = min(stop, d.o[j]) if s > 0 else max(stop, d.o[j])
            reason = "stop"
            break
        if (d.h[j] >= target) if s > 0 else (d.l[j] <= target):
            px, reason = target, "target"
            break
    if px is None:
        px, reason = d.c[-1], "time_last_bar"
    return {"date": d.date, "side": s, "entry_min": int(d.m[d.i]), "entry": entry, "stop": stop, "target": target,
            "exit_min": int(d.m[j]), "exit": float(px), "reason": reason, "gross_r": (px - entry) * s / risk,
            "stop_pts": risk, "or_width_atr": d.or_width_atr, "adx14": d.adx14,
            "trend_day_expost": d.trend_day_expost}


def configs(eligible_only: bool = False) -> list[tuple[str, str, float, str]]:
    return [(v, st, t, dr) for v in VARIANTS for st in STOPS for t in TARGETS for dr in DIRECTIONS
            if not eligible_only or t >= 2.0]


def cfg_name(cfg: tuple) -> str:
    v, st, t, dr = cfg
    return f"{v}|{st}|{t:g}R|{dr}"
