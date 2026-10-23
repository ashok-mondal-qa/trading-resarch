"""Baseline strategy: trend + 20-day breakout, long only (spec:
docs/strategy-specifications/baseline-trend-breakout.md, v0.2).

This module produces signals and exit conditions only. Fills, costs, sizing and the portfolio are the
backtest engine's job (Phase 7). Every value at date t uses adjusted bars up to and including t; entry is
at the next session's open, decided after the close of t.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from trading_research.indicators import core, regime

SPEC_VERSION = "0.2"


@dataclass(frozen=True)
class Params:
    trend_fast: int = 50
    trend_slow: int = 200
    breakout_lookback: int = 20
    volume_ratio_min: float = 1.5
    volume_lookback: int = 20
    rs_lookback: int = 63
    atr_n: int = 14
    stop_atr: float = 2.0
    max_stop_pct: float = 0.10
    min_price: float = 50.0
    min_median_traded_value: float = 5e7  # INR, 20-day median (config execution_model)
    exit_low_lookback: int = 10
    max_holding_sessions: int = 40
    max_new_per_day: int = 2

    def as_dict(self) -> dict:
        return asdict(self)


def stock_features(bars: pd.DataFrame, benchmark_close: pd.Series, p: Params = Params()) -> pd.DataFrame:
    """Per-bar setup inputs and flags for one symbol (adjusted OHLCV indexed by date)."""
    close = bars["close"]
    f = pd.DataFrame(index=bars.index)
    f["close"] = close
    f["sma_fast"] = core.sma(close, p.trend_fast)
    f["sma_slow"] = core.sma(close, p.trend_slow)
    f["prior_high"] = bars["high"].shift(1).rolling(p.breakout_lookback, min_periods=p.breakout_lookback).max()
    f["volume_ratio"] = core.volume_ratio(bars["volume"], p.volume_lookback)
    f["rs"] = core.relative_strength(close, benchmark_close, p.rs_lookback)
    f["atr"] = core.atr(bars, p.atr_n)
    f["median_traded_value"] = core.median_traded_value(bars["traded_value"], p.volume_lookback)
    f["stop"] = close - p.stop_atr * f["atr"]
    f["stop_pct"] = (close - f["stop"]) / close

    f["trend_ok"] = (close > f["sma_slow"]) & (f["sma_fast"] > f["sma_slow"])
    f["breakout"] = close > f["prior_high"]
    f["volume_ok"] = f["volume_ratio"] >= p.volume_ratio_min
    f["rs_ok"] = f["rs"] > 0
    # the price floor is about tradability, so it uses the raw (unadjusted) close when supplied
    price = bars["raw_close"] if "raw_close" in bars else close
    f["liquid"] = (f["median_traded_value"] >= p.min_median_traded_value) & (price >= p.min_price)
    f["stop_ok"] = f["stop_pct"] <= p.max_stop_pct
    inputs = ["sma_slow", "prior_high", "volume_ratio", "rs", "atr", "median_traded_value"]
    f["inputs_complete"] = f[inputs].notna().all(axis=1)
    f["setup"] = f["inputs_complete"] & f["trend_ok"] & f["breakout"] & f["rs_ok"] & f["liquid"] & f["stop_ok"]
    f["signal"] = f["setup"] & f["volume_ok"]
    f["watchlist"] = f["setup"] & ~f["volume_ok"]  # gate 5 (confirmation) pending
    # exit condition, evaluated at each close; the exit fills at the next open
    f["exit_low"] = bars["low"].shift(1).rolling(p.exit_low_lookback, min_periods=p.exit_low_lookback).min()
    f["exit_signal"] = close < f["exit_low"]
    return f


def daily_candidates(features: dict[str, pd.DataFrame], benchmark_close: pd.Series,
                     p: Params = Params()) -> pd.DataFrame:
    """All symbols' signals per date, after the regime gate, ranked by RS; at most `max_new_per_day`
    become TRADE CANDIDATE, the rest of the signals WATCHLIST (never a third candidate).

    Regime not computable (benchmark missing or in warm-up) -> DATA INSUFFICIENT; regime not 'up' ->
    REJECTED. Callers pass only symbols that pass gate 1 (data.quality) at the dates concerned."""
    reg = regime.regime(benchmark_close)
    rows = []
    for symbol, f in features.items():
        hits = f[f["signal"] | f["watchlist"]]
        for date, r in hits.iterrows():
            rows.append({"date": date, "symbol": symbol, "signal": bool(r["signal"]), "rs": r["rs"],
                         "close": r["close"], "stop": r["stop"], "atr": r["atr"],
                         "volume_ratio": r["volume_ratio"]})
    out = pd.DataFrame(rows, columns=["date", "symbol", "signal", "rs", "close", "stop", "atr", "volume_ratio"])
    if out.empty:
        return out.assign(regime=pd.Series(dtype=str), status=pd.Series(dtype=str))
    out["regime"] = reg["trend"].reindex(out["date"]).to_numpy()
    known = out["regime"].isin(["up", "down", "range"])
    out["status"] = np.select(
        [~known, out["regime"] != "up", out["signal"]],
        ["DATA INSUFFICIENT", "REJECTED", "SIGNAL"], default="WATCHLIST")
    out = out.sort_values(["date", "status", "rs", "symbol"], ascending=[True, True, False, True])
    rank = out[out["status"] == "SIGNAL"].groupby("date").cumcount()
    out.loc[rank.index, "status"] = np.where(rank < p.max_new_per_day, "TRADE CANDIDATE", "WATCHLIST")
    return out.reset_index(drop=True)
