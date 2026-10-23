"""Market regime labels from benchmark index closes (market-regime skill, v0.1).

trend:      'up'   close > SMA200 and SMA50 slope over 20 sessions > 0
            'down' close < SMA200 and SMA50 slope < 0
            'range' otherwise; 'unknown' during warm-up
volatility: 20-day realised volatility percentile over the trailing `vol_window` sessions
            (default 756 = ~3 years): 'high' >= 0.80, 'low' <= 0.20, else 'normal'; 'unknown' in warm-up.
Each label at date t uses closes up to t only. The event-driven flag needs official event dates and is
not implemented yet; no strategy may rely on it until it is.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trading_research.indicators import core


def regime(close: pd.Series, vol_window: int = 756) -> pd.DataFrame:
    sma200 = core.sma(close, 200)
    slope50 = core.slope(core.sma(close, 50), 20)
    up = (close > sma200) & (slope50 > 0)
    down = (close < sma200) & (slope50 < 0)
    trend = np.select([up, down], ["up", "down"], default="range")
    trend = np.where(sma200.isna() | slope50.isna(), "unknown", trend)

    pct = core.rolling_percentile(core.realized_vol(close, 20), vol_window)
    vol = np.select([pct >= 0.8, pct <= 0.2], ["high", "low"], default="normal")
    vol = np.where(pct.isna(), "unknown", vol)
    return pd.DataFrame({"trend": trend, "volatility": vol, "sma200": sma200, "sma50_slope20": slope50,
                         "vol_percentile": pct}, index=close.index)
