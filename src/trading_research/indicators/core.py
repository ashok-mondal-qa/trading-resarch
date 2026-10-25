"""Core indicators: pure functions of bars up to and including each date (no look-ahead).

Inputs are one symbol's series indexed by date, ascending. Warm-up bars are NaN, never backfilled.
Callers use adjusted prices (see `ohlcv`) for indicator continuity; fills use raw prices elsewhere.

Warm-up (first non-NaN position, 0-based): sma/ema/atr n-1 · roc/slope/realized_vol n ·
median_volume n-1 · volume_ratio n · distance_from_high n-1 · rolling_percentile window-1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def ohlcv(adjusted: pd.DataFrame, usable_only: bool = True) -> pd.DataFrame:
    """Adjusted bars (from data.adjust) as open/high/low/close/volume/traded_value indexed by date."""
    df = adjusted[adjusted["usable"]] if usable_only and "usable" in adjusted else adjusted
    out = pd.DataFrame({
        "open": df["adj_open"].to_numpy(), "high": df["adj_high"].to_numpy(),
        "low": df["adj_low"].to_numpy(), "close": df["adj_close"].to_numpy(),
        "volume": df["adj_volume"].to_numpy(dtype=float),
        "traded_value": df["traded_value"].to_numpy(dtype=float),
    }, index=pd.DatetimeIndex(df["date"], name="date"))
    return out.sort_index()


# ---------------------------------------------------------------- trend


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """EMA seeded with the SMA of the first n values, then alpha = 2 / (n + 1)."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) >= n:
        alpha = 2.0 / (n + 1)
        out[n - 1] = values[:n].mean()
        for i in range(n, len(values)):
            out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def slope(series: pd.Series, n: int) -> pd.Series:
    """Fractional change of a series (e.g. an MA) over n bars."""
    return series / series.shift(n) - 1


# ---------------------------------------------------------------- range and volatility


def true_range(bars: pd.DataFrame) -> pd.Series:
    prev_close = bars["close"].shift(1)
    ranges = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev_close).abs(),
                        (bars["low"] - prev_close).abs()], axis=1)
    return ranges.max(axis=1, skipna=True)


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ATR: first value is the mean of the first n true ranges, then (prev*(n-1) + TR) / n."""
    tr = true_range(bars).to_numpy(dtype=float)
    out = np.full(len(tr), np.nan)
    if len(tr) >= n:
        out[n - 1] = tr[:n].mean()
        for i in range(n, len(tr)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return pd.Series(out, index=bars.index)


def atr_pct(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    return atr(bars, n) / bars["close"]


def realized_vol(close: pd.Series, n: int = 20) -> pd.Series:
    """Annualised standard deviation of daily log returns over n returns."""
    returns = np.log(close / close.shift(1))
    return returns.rolling(n, min_periods=n).std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """Share of the trailing `window` values (current included) that are <= the current value."""
    def pct(values: np.ndarray) -> float:
        return float((values <= values[-1]).mean())
    return series.rolling(window, min_periods=window).apply(pct, raw=True)


# ---------------------------------------------------------------- momentum and relative strength


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI: first average gain/loss is the mean of the first n changes, then (prev*(n-1) + x) / n.
    100 when there are no losses in the average, 0 when there are no gains."""
    change = close.diff().to_numpy(dtype=float)
    out = np.full(len(change), np.nan)
    if len(change) > n:
        gain, loss = np.clip(change, 0, None), np.clip(-change, 0, None)
        avg_g, avg_l = gain[1:n + 1].mean(), loss[1:n + 1].mean()
        for i in range(n, len(change)):
            if i > n:
                avg_g = (avg_g * (n - 1) + gain[i]) / n
                avg_l = (avg_l * (n - 1) + loss[i]) / n
            out[i] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1 + avg_g / avg_l)
    return pd.Series(out, index=close.index)


def roc(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1


def distance_from_high(bars: pd.DataFrame, n: int = 252) -> pd.Series:
    """close / highest high of the last n bars (current included) - 1; 0 means at the high."""
    return bars["close"] / bars["high"].rolling(n, min_periods=n).max() - 1


def relative_strength(close: pd.Series, benchmark_close: pd.Series, n: int) -> pd.Series:
    """(1 + stock n-bar return) / (1 + benchmark n-bar return) - 1, on the stock's dates.

    Both returns are measured over the same calendar dates; a benchmark gap gives NaN, not a fill."""
    bench = benchmark_close.reindex(close.index)
    start_dates = pd.Series(close.index, index=close.index).shift(n)
    bench_start = benchmark_close.reindex(start_dates.to_numpy()).to_numpy()
    bench_ret = bench.to_numpy() / bench_start - 1
    return (1 + roc(close, n)) / (1 + pd.Series(bench_ret, index=close.index)) - 1


def cross_sectional_rank(wide: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank (0-1] across symbols for each date (rows = dates, columns = symbols)."""
    return wide.rank(axis=1, pct=True)


# ---------------------------------------------------------------- volume and liquidity


def median_volume(volume: pd.Series, n: int = 20) -> pd.Series:
    return volume.rolling(n, min_periods=n).median()


def median_traded_value(traded_value: pd.Series, n: int = 20) -> pd.Series:
    return traded_value.rolling(n, min_periods=n).median()


def volume_ratio(volume: pd.Series, n: int = 20) -> pd.Series:
    """Today's volume / median volume of the n PRIOR sessions (today excluded from the yardstick)."""
    return volume / median_volume(volume, n).shift(1)


# ---------------------------------------------------------------- multi-timeframe


def weekly(bars: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Weekly bars (weeks ending Friday) from daily bars; a week is kept only once it is complete,
    i.e. `as_of` (default: last daily bar) is on or after that week's Friday. Indexed by week end."""
    as_of = pd.Timestamp(as_of) if as_of is not None else bars.index.max()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    for col in ("volume", "traded_value"):
        if col in bars:
            agg[col] = "sum"
    out = bars.resample("W-FRI").agg(agg).dropna(subset=["close"])
    out["sessions"] = bars["close"].resample("W-FRI").count()
    return out[out.index <= as_of]
