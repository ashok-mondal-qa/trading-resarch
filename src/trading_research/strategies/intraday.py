"""Crypto intraday rules and their 5m-bar trade simulator (spec docs/strategy-specifications/crypto-intraday.md,
v0.1). Research only: long only, spot, nothing here orders.

Each `*_signals` function returns, on its own timeframe's bars (indexed by bar open time), `entry` (bool),
`stop` (planned stop, known at the bar's close) and `exit` (bool, exit at the next bar's open); `signals` adds
the bar's `close`. `simulate`
walks the 5m bars to fill entries at the next open, check stops on every 5m bar and apply exits.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from trading_research.indicators import core

SPEC_VERSION = "0.2"
STRATEGIES = {"orb": "5min", "ema_cross": "15min", "bb_rsi": "1h", "supertrend": "1h", "ema_scalp": "5min",
              "ema_scalp_minstop": "5min"}
DAY_END = ("orb", "ema_scalp", "ema_scalp_minstop")          # flat at the next 00:00 UTC open
FIVE = pd.Timedelta(minutes=5)


@dataclass(frozen=True)
class Params:
    fee_pct: float = 0.10
    gst_pct: float = 18.0
    slip_bps: float = 3.0
    min_stop_pct: float = 0.6
    tax_pct: float = 31.2
    orb_last_entry: str = "11:55"
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 200
    ema_stop_bars: int = 10
    bb_n: int = 20
    bb_k: float = 2.0
    rsi_n: int = 14
    rsi_max: float = 30.0
    atr_n: int = 14
    atr_mult: float = 2.0
    bb_max_bars: int = 48
    st_n: int = 10
    st_mult: float = 3.0
    scalp_fast: int = 9
    scalp_slow: int = 15
    scalp_slope_bars: int = 3
    scalp_target_r: float = 2.0
    scalp_max_per_day: int = 5

    def as_dict(self) -> dict:
        return asdict(self)


def orb_signals(b5: pd.DataFrame, p: Params = Params()) -> pd.DataFrame:
    day = b5.index.normalize()
    first_hour = b5.index.hour == 0
    g = b5[first_hour].groupby(day[first_hour])
    rng = pd.DataFrame({"hi": g["high"].max(), "lo": g["low"].min(), "n": g["close"].count()})
    rng = rng[rng["n"] == 12]
    hi, lo = rng["hi"].reindex(day).to_numpy(), rng["lo"].reindex(day).to_numpy()
    tod = b5.index - day
    window = (tod >= pd.Timedelta(hours=1)) & (tod <= pd.Timedelta(p.orb_last_entry + ":00"))
    above = window & (b5["close"].to_numpy() > hi)
    first = pd.Series(above, index=b5.index).groupby(day).cumsum().eq(1).to_numpy() & above
    return pd.DataFrame({"entry": first, "stop": lo, "exit": False}, index=b5.index)


def ema_cross_signals(bars: pd.DataFrame, p: Params = Params()) -> pd.DataFrame:
    fast, slow = core.ema(bars["close"], p.ema_fast), core.ema(bars["close"], p.ema_slow)
    trend = core.ema(bars["close"], p.ema_trend)
    above = fast > slow
    up = above & ~above.shift(1, fill_value=True) & slow.shift(1).notna()
    down = ~above & above.shift(1, fill_value=False) & fast.notna()
    stop = bars["low"].rolling(p.ema_stop_bars, min_periods=p.ema_stop_bars).min()
    return pd.DataFrame({"entry": up & (bars["close"] > trend), "stop": stop, "exit": down}, index=bars.index)


def bb_rsi_signals(bars: pd.DataFrame, p: Params = Params()) -> pd.DataFrame:
    mid = core.sma(bars["close"], p.bb_n)
    sd = bars["close"].rolling(p.bb_n, min_periods=p.bb_n).std(ddof=0)
    rsi = core.rsi(bars["close"], p.rsi_n)
    trend = core.ema(bars["close"], 200)
    entry = (bars["close"] < mid - p.bb_k * sd) & (rsi < p.rsi_max) & (bars["close"] > trend)
    stop = bars["close"] - p.atr_mult * core.atr(bars, p.atr_n)
    return pd.DataFrame({"entry": entry, "stop": stop, "exit": bars["close"] >= mid}, index=bars.index)


def supertrend_signals(bars: pd.DataFrame, p: Params = Params()) -> pd.DataFrame:
    st = core.supertrend(bars, p.st_n, p.st_mult)
    d = st["direction"]
    return pd.DataFrame({"entry": (d == 1) & (d.shift(1) == -1), "stop": st["line"],
                         "exit": (d == -1) & (d.shift(1) == 1)}, index=bars.index)


def ema_scalp_signals(bars: pd.DataFrame, p: Params = Params()) -> pd.DataFrame:
    """9/15 EMA scalp (EXP-0037/0038): EMA9 crosses above EMA15 while EMA15 is rising; stop at the signal
    candle's low; target `scalp_target_r` x risk; at most `scalp_max_per_day` trades per UTC day."""
    fast, slow = core.ema(bars["close"], p.scalp_fast), core.ema(bars["close"], p.scalp_slow)
    above = fast > slow
    up = above & ~above.shift(1, fill_value=True) & slow.shift(1).notna()
    rising = slow > slow.shift(p.scalp_slope_bars)
    return pd.DataFrame({"entry": up & rising, "stop": bars["low"], "exit": False}, index=bars.index)


def signals(strategy: str, b5: pd.DataFrame, bars: pd.DataFrame, p: Params = Params()) -> pd.DataFrame:
    if strategy == "orb":
        out, src = orb_signals(b5, p), b5
    elif strategy.startswith("ema_scalp"):
        out, src = ema_scalp_signals(b5, p), b5
    else:
        funcs = {"ema_cross": ema_cross_signals, "bb_rsi": bb_rsi_signals, "supertrend": supertrend_signals}
        out, src = funcs[strategy](bars, p), bars
    out["close"] = src["close"]
    return out


def simulate(strategy: str, b5: pd.DataFrame, sig: pd.DataFrame, tf: str, p: Params = Params(),
             mult: float = 1.0, symbol: str = "") -> pd.DataFrame:
    step = pd.Timedelta(tf)
    t5 = b5.index.to_numpy()
    o5, l5, h5 = b5["open"].to_numpy(float), b5["low"].to_numpy(float), b5["high"].to_numpy(float)
    min_stop = 0.0 if strategy == "ema_scalp" else p.min_stop_pct          # the scalp as described has none
    target_r = p.scalp_target_r if strategy.startswith("ema_scalp") else None
    per_day = p.scalp_max_per_day if strategy.startswith("ema_scalp") else None
    taken: dict = {}
    slip = p.slip_bps / 1e4 * mult
    fee = p.fee_pct / 100 * (1 + p.gst_pct / 100) * mult
    entries = sig.index[sig["entry"].to_numpy(bool)]
    exit_close = (sig.index[sig["exit"].to_numpy(bool)] + step).to_numpy()   # exit at the open after these closes
    out, free_from = [], np.datetime64("NaT", "ns")
    for t in entries:
        if not np.isnat(free_from) and t.to_datetime64() < free_from:
            continue
        stop = float(sig.at[t, "stop"])
        ref = float(sig.at[t, "close"])
        if not np.isfinite(stop) or stop >= ref or (ref - stop) / ref * 100 < min_stop:
            continue
        if per_day is not None and taken.get(t.normalize(), 0) >= per_day:
            continue
        start = t + step
        i = np.searchsorted(t5, start.to_datetime64())
        if i >= len(t5) or t5[i] != start.to_datetime64():
            continue                                                  # next bar missing: no trade
        entry = o5[i] * (1 + slip)
        if entry <= stop:
            continue
        if strategy in DAY_END:
            planned = (start.normalize() + pd.Timedelta(days=1)).to_datetime64()
        else:
            k = np.searchsorted(exit_close, start.to_datetime64(), side="right")
            planned = exit_close[k] if k < len(exit_close) else np.datetime64("NaT", "ns")
            if strategy == "bb_rsi":
                cap = (start + p.bb_max_bars * step).to_datetime64()
                planned = cap if np.isnat(planned) or cap < planned else planned
        j_end = np.searchsorted(t5, planned) if not np.isnat(planned) else len(t5)
        hit = np.nonzero(l5[i:j_end] <= stop)[0]
        target = entry + target_r * (entry - stop) if target_r else np.inf
        reach = np.nonzero(h5[i:j_end] >= target)[0]
        if len(reach) and (not len(hit) or reach[0] < hit[0]):    # same bar: the stop is assumed first
            j = i + reach[0]
            px, reason, exit_time = max(o5[j], target) * (1 - slip), "target", t5[j]
        elif len(hit):
            j = i + hit[0]
            px, reason = min(o5[j], stop) * (1 - slip), "stop"
            exit_time = t5[j]
        elif j_end < len(t5):
            px, reason, exit_time = o5[j_end] * (1 - slip), ("day end" if strategy in DAY_END else "signal"), t5[j_end]
            if strategy == "bb_rsi" and exit_time >= (start + p.bb_max_bars * step).to_datetime64():
                reason = "time"
        else:
            continue                                                  # still open at the end of the data
        risk = entry - stop
        pnl = px - entry - fee * (entry + px)
        after_tax = pnl * (1 - p.tax_pct / 100) if pnl > 0 else pnl
        out.append({"symbol": symbol, "strategy": strategy, "signal_time": t, "entry_time": start,
                    "exit_time": pd.Timestamp(exit_time), "entry": entry, "stop": stop, "exit": px, "risk": risk,
                    "risk_pct": risk / entry * 100, "pnl_pct": pnl / entry * 100, "r_multiple": pnl / risk,
                    "r_after_tax": after_tax / risk, "reason": reason})
        free_from = exit_time
        taken[t.normalize()] = taken.get(t.normalize(), 0) + 1
    return pd.DataFrame(out)
