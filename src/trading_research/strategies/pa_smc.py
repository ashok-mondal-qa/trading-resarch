"""Phase 8 strategies (spec: docs/strategy-specifications/pa-smc.md, v0.1), long only.

* `pa_pullback`: price action. In up-structure (higher high and higher low, confirmed swings), the bar
  touches the 20-EMA without closing below the last confirmed higher low, and closes above the previous
  bar's high (the pullback resumes). Ablation: the same without the up-structure requirement.
* `smc_sweep`: Smart Money Concepts. A sell-side liquidity sweep (low below the last confirmed swing
  low, close back above it) within the last few sessions, then a bullish displacement bar. Ablation: the
  displacement bar without the sweep.

Both share the baseline's context and plumbing: stock close > SMA200, NIFTY 50 regime 'up' (applied by
the runner), liquidity and raw-price floor, stop distance <= 10%, exit on a close below the 10-session low
or after 40 sessions. Every value at date t uses bars up to t; entry is at the next open.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from trading_research.indicators import core, structure

SPEC_VERSION = "0.1"
STRATEGIES = ("pa_pullback", "smc_sweep")


@dataclass(frozen=True)
class Params:
    trend_slow: int = 200
    swing_k: int = 3                 # pa_pullback and smc_sweep: swing confirmation lag
    ema_n: int = 20                  # pa_pullback
    stop_buffer_atr: float = 0.1     # stop = structural level - 0.1 x ATR
    sweep_window: int = 5            # smc_sweep: sweep within the last 5 sessions incl. today
    body_atr: float = 1.5            # smc_sweep: displacement body >= 1.5 x previous ATR(14)
    rs_lookback: int = 63            # ranking only (highest RS first), not a filter
    atr_n: int = 14
    max_stop_pct: float = 0.10
    min_price: float = 50.0
    min_median_traded_value: float = 5e7
    volume_lookback: int = 20
    exit_low_lookback: int = 10
    max_holding_sessions: int = 40
    max_new_per_day: int = 2

    def as_dict(self) -> dict:
        return asdict(self)


def stock_features(bars: pd.DataFrame, benchmark_close: pd.Series, strategy: str,
                   p: Params = Params()) -> pd.DataFrame:
    """Per-bar flags for one symbol (adjusted OHLCV indexed by date; `raw_close` optional).

    Columns used by the runner: signal, ablation, stop, exit_signal, rs, median_traded_value."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    close, low = bars["close"], bars["low"]
    f = pd.DataFrame(index=bars.index)
    f["close"] = close
    f["sma_slow"] = core.sma(close, p.trend_slow)
    f["atr"] = core.atr(bars, p.atr_n)
    f["rs"] = core.relative_strength(close, benchmark_close, p.rs_lookback)
    f["median_traded_value"] = core.median_traded_value(bars["traded_value"], p.volume_lookback)
    price = bars["raw_close"] if "raw_close" in bars else close
    f["liquid"] = (f["median_traded_value"] >= p.min_median_traded_value) & (price >= p.min_price)
    f["context"] = close > f["sma_slow"]
    state = structure.swing_state(bars, p.swing_k)

    if strategy == "pa_pullback":
        ema = core.ema(close, p.ema_n)
        higher_low = state["last_low"]
        touched = low <= ema
        held = close > higher_low                       # no close below the last confirmed higher low
        resumed = close > bars["high"].shift(1)
        f["event"] = touched & held & resumed
        f["filter"] = state["structure"] == "up"        # the price-action component under test
        f["stop"] = higher_low - p.stop_buffer_atr * f["atr"]
        inputs = ["sma_slow", "atr", "rs", "median_traded_value", "stop"]
    else:
        sweeps = structure.liquidity_sweeps(bars, p.swing_k)["sell_side"]
        disp = structure.displacement(bars, p.atr_n, p.body_atr)["bullish"]
        f["event"] = disp
        f["filter"] = sweeps.astype(int).rolling(p.sweep_window, min_periods=1).max().astype(bool)
        f["stop"] = low.rolling(p.sweep_window, min_periods=p.sweep_window).min() - p.stop_buffer_atr * f["atr"]
        inputs = ["sma_slow", "atr", "rs", "median_traded_value", "stop"]

    f["stop_pct"] = (close - f["stop"]) / close
    f["stop_ok"] = (f["stop"] < close) & (f["stop_pct"] <= p.max_stop_pct)
    f["inputs_complete"] = f[inputs].notna().all(axis=1)
    base = f["inputs_complete"] & f["context"] & f["liquid"] & f["stop_ok"] & f["event"].fillna(False)
    f["signal"] = base & f["filter"]
    f["ablation"] = base
    f["exit_low"] = low.shift(1).rolling(p.exit_low_lookback, min_periods=p.exit_low_lookback).min()
    f["exit_signal"] = close < f["exit_low"]
    return f
