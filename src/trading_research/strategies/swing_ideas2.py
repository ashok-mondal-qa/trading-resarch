"""Phase 12 strategies (spec: docs/strategy-specifications/swing-ideas-2.md, v0.1), long only.

* `momentum_weekly`: the 12-1 momentum rules of `swing_ideas.momentum_12_1`, checked on the first session
  of every week instead of every month (top 10% entry, exit below the top 20%, below SMA200 or after
  126 sessions; stop 2.5 x ATR(14)).
* `gap_drift`: a news-style gap. The day opens at least 4% above the previous close, closes at or above its
  open, on at least 3x the median volume of the previous 20 sessions. Stop below that day's low; exit on a
  close below the 10-session low or after 40 sessions.

Shared context as in Phase 11: close > SMA200, NIFTY 50 regime 'up' (applied by the runner), ₹50 raw
price floor, 20-day median traded value >= ₹5 crore, stop distance <= 10%. Values at t use bars up to t.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from trading_research.indicators import core
from trading_research.strategies import swing_ideas as si

SPEC_VERSION = "0.1"
STRATEGIES = ("momentum_weekly", "gap_drift")


@dataclass(frozen=True)
class Params:
    base: si.Params = si.Params()    # shared values and the momentum rules (mom_* fields)
    gap_min: float = 0.04            # open >= previous close x 1.04
    gap_volume_ratio: float = 3.0    # volume >= 3 x median of the 20 previous sessions
    gap_stop_buffer_atr: float = 0.1
    gap_exit_low_lookback: int = 10
    gap_max_holding: int = 40

    @property
    def max_new_per_day(self) -> int:
        return self.base.max_new_per_day

    def as_dict(self) -> dict:
        return asdict(self)

    def max_holding(self, strategy: str) -> int:
        return {"momentum_weekly": self.base.mom_max_holding, "gap_drift": self.gap_max_holding}[strategy]


def week_starts(calendar) -> pd.DatetimeIndex:
    """First session of each ISO week in the market calendar (known at that session)."""
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(list(calendar))))
    week = pd.Series(cal.to_period("W-SUN"), index=cal)
    return cal[(week != week.shift(1)).to_numpy()]


def stock_features(bars: pd.DataFrame, benchmark_close: pd.Series, strategy: str, p: Params = Params()) -> pd.DataFrame:
    """Per-bar flags for one symbol. For `momentum_weekly`, signal/exit need the cross-sectional rank
    (`swing_ideas.momentum_rank`, then `swing_ideas.apply_momentum` with `week_starts`)."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    if strategy == "momentum_weekly":
        return si.stock_features(bars, benchmark_close, "momentum_12_1", p.base)

    f = si._common(bars, benchmark_close, p.base)
    close, low = bars["close"], bars["low"]
    f["gap"] = bars["open"] / close.shift(1) - 1
    f["volume_ratio"] = core.volume_ratio(bars["volume"], p.base.volume_lookback)
    f["stop"] = low - p.gap_stop_buffer_atr * f["atr"]
    f = si._finish(f, ["sma_slow", "atr", "rs", "median_traded_value", "gap", "volume_ratio"], p.base)
    event = (f["gap"] >= p.gap_min) & (close >= bars["open"]) & (f["volume_ratio"] >= p.gap_volume_ratio)
    f["signal"] = f["eligible"] & event
    f["exit_low"] = low.shift(1).rolling(p.gap_exit_low_lookback, min_periods=p.gap_exit_low_lookback).min()
    f["exit_signal"] = close < f["exit_low"]
    f["rank_key"] = f["rs"]
    return f
