"""Price-action and SMC structure, coded from the definitions in the price-action-structure and
smc-concepts skills (v0.1). Every event carries the date it becomes known (`confirmed_at` / `known_at`),
and per-bar outputs at date t use only bars up to t.

These are hypothesis inputs, not evidence: a concept enters a strategy only through a tested spec.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trading_research.indicators.core import atr


def swings(bars: pd.DataFrame, k: int = 3) -> pd.DataFrame:
    """Swing highs/lows: bar i's high (low) strictly above (below) the k bars on each side.

    Known only at bar i+k, so `confirmed_at` = date of bar i+k. Columns: date, confirmed_at, kind, price."""
    high, low, dates = bars["high"].to_numpy(), bars["low"].to_numpy(), bars.index
    rows = []
    for i in range(k, len(bars) - k):
        left_h, right_h = high[i - k:i], high[i + 1:i + k + 1]
        left_l, right_l = low[i - k:i], low[i + 1:i + k + 1]
        if high[i] > left_h.max() and high[i] > right_h.max():
            rows.append((dates[i], dates[i + k], "high", high[i]))
        if low[i] < left_l.min() and low[i] < right_l.min():
            rows.append((dates[i], dates[i + k], "low", low[i]))
    return pd.DataFrame(rows, columns=["date", "confirmed_at", "kind", "price"])


def swing_state(bars: pd.DataFrame, k: int = 3) -> pd.DataFrame:
    """Per bar: last and previous confirmed swing high/low as known at that bar's close, and the
    structure label ('up': higher high and higher low; 'down': lower high and lower low; else 'none')."""
    events = swings(bars, k).sort_values(["confirmed_at", "date"], kind="stable")
    state = pd.DataFrame(index=bars.index, dtype=float)
    for kind in ("high", "low"):
        ev = events[events["kind"] == kind]
        seq = pd.DataFrame({"confirmed_at": ev["confirmed_at"].to_numpy(), "last": ev["price"].to_numpy(),
                            "prev": ev["price"].shift(1).to_numpy()})
        per_day = seq.groupby("confirmed_at").last()  # several on one day: the latest in order wins
        per_day = per_day.reindex(bars.index).ffill()
        state[f"last_{kind}"] = per_day["last"].astype(float)
        state[f"prev_{kind}"] = per_day["prev"].astype(float)
    state = state[["last_high", "prev_high", "last_low", "prev_low"]]
    up = (state["last_high"] > state["prev_high"]) & (state["last_low"] > state["prev_low"])
    down = (state["last_high"] < state["prev_high"]) & (state["last_low"] < state["prev_low"])
    state["structure"] = np.select([up, down], ["up", "down"], default="none")
    return state


def structure_breaks(bars: pd.DataFrame, k: int = 3) -> pd.DataFrame:
    """BOS / CHoCH events on closes.

    Bullish: the first close above the most recent confirmed swing high (as known at the previous bar).
    It is a BOS if structure at the previous bar was 'up', a CHoCH if it was 'down'; with no structure
    it is not labelled. A swing level can be broken once. Bearish is the mirror on swing lows."""
    state = swing_state(bars, k)
    close = bars["close"]
    rows = []
    broken = {"high": None, "low": None}
    for i in range(1, len(bars)):
        prev = state.iloc[i - 1]
        date = bars.index[i]
        level_h, level_l = prev["last_high"], prev["last_low"]
        if not np.isnan(level_h) and close.iloc[i] > level_h and broken["high"] != level_h:
            broken["high"] = level_h
            label = {"up": "BOS", "down": "CHoCH"}.get(prev["structure"])
            if label:
                rows.append((date, "bullish", label, level_h))
        if not np.isnan(level_l) and close.iloc[i] < level_l and broken["low"] != level_l:
            broken["low"] = level_l
            label = {"down": "BOS", "up": "CHoCH"}.get(prev["structure"])
            if label:
                rows.append((date, "bearish", label, level_l))
    return pd.DataFrame(rows, columns=["date", "direction", "kind", "level"])


def fair_value_gaps(bars: pd.DataFrame) -> pd.DataFrame:
    """Bullish FVG at middle bar i: low(i+1) > high(i-1), zone [high(i-1), low(i+1)].
    Bearish: high(i+1) < low(i-1), zone [high(i+1), low(i-1)]. Known at the close of i+1."""
    high, low, dates = bars["high"].to_numpy(), bars["low"].to_numpy(), bars.index
    rows = []
    for i in range(1, len(bars) - 1):
        if low[i + 1] > high[i - 1]:
            rows.append((dates[i], dates[i + 1], "bullish", high[i - 1], low[i + 1]))
        if high[i + 1] < low[i - 1]:
            rows.append((dates[i], dates[i + 1], "bearish", high[i + 1], low[i - 1]))
    return pd.DataFrame(rows, columns=["date", "known_at", "direction", "bottom", "top"])


def displacement(bars: pd.DataFrame, n: int = 14, body_atr: float = 1.5) -> pd.DataFrame:
    """Bullish: body >= body_atr x ATR(n) and close in the top 25% of the bar's range; bearish mirror.

    The ATR yardstick is the PREVIOUS bar's ATR, so a large bar does not inflate its own threshold."""
    yardstick = atr(bars, n).shift(1)
    body = (bars["close"] - bars["open"]).abs()
    span = (bars["high"] - bars["low"]).replace(0, np.nan)
    location = (bars["close"] - bars["low"]) / span
    big = body >= body_atr * yardstick
    return pd.DataFrame({
        "bullish": big & (bars["close"] > bars["open"]) & (location >= 0.75),
        "bearish": big & (bars["close"] < bars["open"]) & (location <= 0.25),
    }, index=bars.index)


def liquidity_sweeps(bars: pd.DataFrame, k: int = 3) -> pd.DataFrame:
    """Sell-side sweep: low trades below the last confirmed swing low (known at the previous bar) and
    the bar closes back above it. Buy-side sweep is the mirror on swing highs."""
    state = swing_state(bars, k).shift(1)
    return pd.DataFrame({
        "sell_side": (bars["low"] < state["last_low"]) & (bars["close"] > state["last_low"]),
        "buy_side": (bars["high"] > state["last_high"]) & (bars["close"] < state["last_high"]),
    }, index=bars.index)
