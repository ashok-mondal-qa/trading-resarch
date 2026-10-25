"""Phase 13: popular strategies from trading books, YouTube and Instagram (spec:
docs/strategy-specifications/social-strategies.md, v0.1), long only, daily bars.

* `minervini`: Mark Minervini's Trend Template (price above rising 150/200-day SMAs, 50 > 150 > 200, at least
  30% above the 52-week low and within 25% of the high, relative-strength rank >= 70) plus a pivot breakout
  (close above the 20-session high on >= 1.5x volume). Stop 8% below the close; exit on a close below SMA50.
* `supertrend`: Supertrend(10, 3) flips from down to up. Stop at the Supertrend line; exit when it flips down.
* `ma44`: the "44-moving-average" setup: a rising 44-day SMA, a green candle whose low touches the SMA and
  closes above it; the next session must close above that candle's high. Stop at the candle's low, target
  2x the candle's range above its high.
* `turtle55`: the Turtle traders' System 2: close above the 55-session high. Stop 2 x ATR(20); exit on a close
  below the 20-session low.
* `golden_cross`: SMA50 crosses above SMA200. Stop 10% below the close; exit when SMA50 crosses back below.

Shared context (applied here or by the runner): NIFTY 50 regime 'up', ₹50 raw-price floor, 20-day median
traded value >= ₹5 crore, stop below the close and at most 10% away. Every value at t uses bars up to t.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from trading_research.indicators import core

SPEC_VERSION = "0.1"
STRATEGIES = ("minervini", "supertrend", "ma44", "turtle55", "golden_cross")
MAX_HOLDING = {"minervini": 126, "supertrend": 126, "ma44": 40, "turtle55": 252, "golden_cross": 252}


@dataclass(frozen=True)
class Params:
    atr_n: int = 14
    rs_lookback: int = 63
    max_stop_pct: float = 0.10
    min_price: float = 50.0
    min_median_traded_value: float = 5e7
    volume_lookback: int = 20
    max_new_per_day: int = 2
    # minervini
    mv_rs_min: float = 0.70
    mv_breakout_n: int = 20
    mv_volume_ratio: float = 1.5
    mv_stop_pct: float = 0.08
    # supertrend
    st_n: int = 10
    st_mult: float = 3.0
    # ma44
    ma44_n: int = 44
    ma44_rising: int = 5             # SMA44 above its value 5 sessions ago
    ma44_target_r: float = 2.0
    # turtle55
    turtle_entry_n: int = 55
    turtle_exit_n: int = 20
    turtle_atr_n: int = 20
    turtle_stop_atr: float = 2.0
    # golden_cross
    gc_fast: int = 50
    gc_slow: int = 200
    gc_stop_pct: float = 0.10

    def as_dict(self) -> dict:
        return asdict(self)

    def max_holding(self, strategy: str) -> int:
        return MAX_HOLDING[strategy]


def ibd_rs_score(close: pd.Series) -> pd.Series:
    """IBD-style relative-strength score (latest quarter weighted double): 2 x ROC63 + ROC126 + ROC189 + ROC252.
    The cross-sectional percentile of this score is the RS rank."""
    return 2 * core.roc(close, 63) + core.roc(close, 126) + core.roc(close, 189) + core.roc(close, 252)


def stock_features(bars: pd.DataFrame, benchmark_close: pd.Series, strategy: str, p: Params = Params()) -> pd.DataFrame:
    """Per-bar flags for one symbol. Columns used by the runner: signal, stop, target (NaN if none),
    exit_signal, rank_key, median_traded_value, eligible. For `minervini` the RS-rank condition is added by
    `apply_rs_rank` (cross-sectional)."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    close, high, low, open_ = bars["close"], bars["high"], bars["low"], bars["open"]
    f = pd.DataFrame(index=bars.index)
    f["close"] = close
    f["atr"] = core.atr(bars, p.atr_n)
    f["rs"] = core.relative_strength(close, benchmark_close, p.rs_lookback)
    f["median_traded_value"] = core.median_traded_value(bars["traded_value"], p.volume_lookback)
    price = bars["raw_close"] if "raw_close" in bars else close
    f["liquid"] = (f["median_traded_value"] >= p.min_median_traded_value) & (price >= p.min_price)
    f["target"] = np.nan
    f["rank_key"] = f["rs"]
    inputs = ["median_traded_value", "rs"]

    if strategy == "minervini":
        sma50, sma150, sma200 = core.sma(close, 50), core.sma(close, 150), core.sma(close, 200)
        low52, high52 = low.rolling(252, min_periods=252).min(), high.rolling(252, min_periods=252).max()
        template = ((close > sma150) & (close > sma200) & (sma150 > sma200) & (sma200 > sma200.shift(21))
                    & (sma50 > sma150) & (close > sma50) & (close >= 1.30 * low52) & (close >= 0.75 * high52))
        breakout = close > high.shift(1).rolling(p.mv_breakout_n, min_periods=p.mv_breakout_n).max()
        vol_ok = core.volume_ratio(bars["volume"], p.volume_lookback) >= p.mv_volume_ratio
        f["rs_score"] = ibd_rs_score(close)
        f["event"] = template & breakout & vol_ok
        f["stop"] = close * (1 - p.mv_stop_pct)
        f["exit_signal"] = close < sma50
        f["sma50"], f["sma200"], f["low52"] = sma50, sma200, low52
        inputs += ["sma200", "low52", "rs_score"]
        f["rank_key"] = f["rs_score"]
    elif strategy == "supertrend":
        st = core.supertrend(bars, p.st_n, p.st_mult)
        f["st_line"], f["st_dir"] = st["line"], st["direction"]
        f["event"] = (st["direction"] == 1) & (st["direction"].shift(1) == -1)
        f["stop"] = st["line"]
        f["exit_signal"] = st["direction"] == -1
        inputs += ["st_line"]
    elif strategy == "ma44":
        sma = core.sma(close, p.ma44_n)
        candle = (low <= sma) & (close > sma) & (close > open_) & (sma > sma.shift(p.ma44_rising))
        prev = candle.shift(1, fill_value=False).astype(bool)
        f["event"] = prev & (close > high.shift(1))              # confirmation: close above the candle's high
        candle_high, candle_low = high.shift(1), low.shift(1)
        f["stop"] = candle_low
        f["target"] = candle_high + p.ma44_target_r * (candle_high - candle_low)
        f["exit_signal"] = False
        f["sma44"] = sma
        inputs += ["sma44"]
    elif strategy == "turtle55":
        ta = core.atr(bars, p.turtle_atr_n)
        f["event"] = close > high.shift(1).rolling(p.turtle_entry_n, min_periods=p.turtle_entry_n).max()
        f["stop"] = close - p.turtle_stop_atr * ta
        f["exit_signal"] = close < low.shift(1).rolling(p.turtle_exit_n, min_periods=p.turtle_exit_n).min()
        f["turtle_atr"] = ta
        inputs += ["turtle_atr"]
    else:  # golden_cross
        fast, slow = core.sma(close, p.gc_fast), core.sma(close, p.gc_slow)
        f["event"] = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        f["stop"] = close * (1 - p.gc_stop_pct)
        f["exit_signal"] = fast < slow
        f["sma_slow"] = slow
        inputs += ["sma_slow"]

    f["stop_pct"] = (close - f["stop"]) / close
    f["stop_ok"] = (f["stop"] < close) & (f["stop_pct"] <= p.max_stop_pct + 1e-9)
    f["inputs_complete"] = f[inputs].notna().all(axis=1)
    f["eligible"] = f["inputs_complete"] & f["liquid"] & f["stop_ok"]
    f["signal"] = f["eligible"] & f["event"].fillna(False).astype(bool)
    f["exit_signal"] = f["exit_signal"].fillna(False).astype(bool)
    return f


def apply_rs_rank(f: pd.DataFrame, pct: pd.Series, p: Params = Params()) -> pd.DataFrame:
    """Minervini's RS-rank condition: the symbol's RS percentile among liquid stocks that day >= 70."""
    f = f.copy()
    f["rs_pct"] = pct.reindex(f.index)
    f["signal"] = f["signal"] & (f["rs_pct"] >= p.mv_rs_min)
    return f
