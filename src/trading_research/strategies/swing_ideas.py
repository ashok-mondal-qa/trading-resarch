"""Phase 11 strategies (spec: docs/strategy-specifications/swing-ideas.md, v0.1), long only.

* `displacement`: the EXP-0008 ablation unchanged. A bullish displacement bar (body >= 1.5 x the
  previous bar's ATR(14), close in the top 25% of the range); stop below the 5-session low; exit on a close
  below the 10-session low or after 40 sessions. Built by calling `pa_smc.stock_features` so the
  definition cannot drift from the one already tested.
* `st_reversal`: short-term reversal. RSI(2) below 10 in a stock above its 200-day SMA; stop 2.5 x ATR(14)
  below the close; exit on a close above the 5-day SMA or after 10 sessions.
* `momentum_12_1`: intermediate momentum. On the first session of each month, buy stocks in the top 10%
  of the liquid universe by 12-month return excluding the last month; stop 2.5 x ATR(14) below the
  close; exit at a later month start once the stock leaves the top 20% (or closes below its 200-day SMA),
  or after 126 sessions. The cross-sectional rank is computed by the runner with `momentum_rank`.

All three share the earlier context: stock close > SMA200, NIFTY 50 regime 'up' (applied by the runner),
₹50 raw-price floor, 20-day median traded value >= ₹5 crore, stop distance <= 10%. Every value at date t
uses bars up to t only; entry is at the next open.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from trading_research.indicators import core
from trading_research.strategies import pa_smc

SPEC_VERSION = "0.1"
STRATEGIES = ("displacement", "st_reversal", "momentum_12_1")


@dataclass(frozen=True)
class Params:
    trend_slow: int = 200
    atr_n: int = 14
    rs_lookback: int = 63            # ranking only for displacement and st_reversal
    max_stop_pct: float = 0.10
    min_price: float = 50.0
    min_median_traded_value: float = 5e7
    volume_lookback: int = 20
    max_new_per_day: int = 2
    # displacement: every value as in pa_smc.Params (EXP-0008 ablation)
    displacement_max_holding: int = 40
    # st_reversal
    rsi_n: int = 2
    rsi_entry: float = 10.0          # signal when RSI(2) < 10
    reversal_stop_atr: float = 2.5
    reversal_exit_sma: int = 5       # exit after a close above SMA(5)
    reversal_max_holding: int = 10
    # momentum_12_1
    mom_lookback: int = 252
    mom_skip: int = 21               # return from t-252 to t-21
    mom_entry_pct: float = 0.90      # top 10% of the liquid universe
    mom_exit_pct: float = 0.80       # leaves the top 20%
    mom_stop_atr: float = 2.5
    mom_max_holding: int = 126

    def as_dict(self) -> dict:
        return asdict(self)

    def max_holding(self, strategy: str) -> int:
        return {"displacement": self.displacement_max_holding, "st_reversal": self.reversal_max_holding,
                "momentum_12_1": self.mom_max_holding}[strategy]


def _common(bars: pd.DataFrame, benchmark_close: pd.Series, p: Params) -> pd.DataFrame:
    close = bars["close"]
    f = pd.DataFrame(index=bars.index)
    f["close"] = close
    f["sma_slow"] = core.sma(close, p.trend_slow)
    f["atr"] = core.atr(bars, p.atr_n)
    f["rs"] = core.relative_strength(close, benchmark_close, p.rs_lookback)
    f["median_traded_value"] = core.median_traded_value(bars["traded_value"], p.volume_lookback)
    price = bars["raw_close"] if "raw_close" in bars else close
    f["liquid"] = (f["median_traded_value"] >= p.min_median_traded_value) & (price >= p.min_price)
    f["context"] = close > f["sma_slow"]
    return f


def _finish(f: pd.DataFrame, inputs: list[str], p: Params) -> pd.DataFrame:
    f["stop_pct"] = (f["close"] - f["stop"]) / f["close"]
    f["stop_ok"] = (f["stop"] < f["close"]) & (f["stop_pct"] <= p.max_stop_pct)
    f["inputs_complete"] = f[inputs].notna().all(axis=1)
    f["eligible"] = f["inputs_complete"] & f["context"] & f["liquid"] & f["stop_ok"]
    return f


def stock_features(bars: pd.DataFrame, benchmark_close: pd.Series, strategy: str,
                   p: Params = Params()) -> pd.DataFrame:
    """Per-bar flags for one symbol (adjusted OHLCV indexed by date; `raw_close` optional).

    Columns used by the runner: signal, stop, exit_signal, rank_key, median_traded_value. For
    `momentum_12_1`, signal and exit_signal need the cross-sectional rank: see `apply_momentum`."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    if strategy == "displacement":
        f = pa_smc.stock_features(bars, benchmark_close, "smc_sweep", pa_smc.Params())
        f["signal"] = f["ablation"]
        f["rank_key"] = f["rs"]
        return f

    f = _common(bars, benchmark_close, p)
    close = bars["close"]
    if strategy == "st_reversal":
        f["rsi"] = core.rsi(close, p.rsi_n)
        f["stop"] = close - p.reversal_stop_atr * f["atr"]
        f = _finish(f, ["sma_slow", "atr", "rs", "median_traded_value", "rsi"], p)
        f["signal"] = f["eligible"] & (f["rsi"] < p.rsi_entry)
        f["exit_signal"] = close > core.sma(close, p.reversal_exit_sma)
        f["rank_key"] = f["rs"]
        return f

    f["mom"] = close.shift(p.mom_skip) / close.shift(p.mom_lookback) - 1
    f["stop"] = close - p.mom_stop_atr * f["atr"]
    f = _finish(f, ["sma_slow", "atr", "median_traded_value", "mom"], p)
    f["rank_key"] = f["mom"]
    return f


def month_starts(calendar) -> pd.DatetimeIndex:
    """First session of each calendar month in the market calendar (known at that session)."""
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(list(calendar))))
    first = pd.Series(cal.to_period("M"), index=cal)
    return cal[(first != first.shift(1)).to_numpy()]


def momentum_rank(mom: pd.DataFrame, rankable: pd.DataFrame) -> pd.DataFrame:
    """Percentile (0-1] of each symbol's momentum among the symbols rankable that day (rows = dates).
    A symbol that is not rankable on a date gets NaN."""
    return core.cross_sectional_rank(mom.where(rankable))


def apply_momentum(f: pd.DataFrame, pct: pd.Series, starts: pd.DatetimeIndex, p: Params = Params()) -> pd.DataFrame:
    """Signal and exit for one symbol from its rank series (`pct`, aligned to f's dates)."""
    f = f.copy()
    f["pct"] = pct.reindex(f.index)
    is_start = f.index.isin(starts)
    f["signal"] = f["eligible"] & is_start & (f["pct"] >= p.mom_entry_pct)
    f["exit_signal"] = is_start & ((f["pct"].isna()) | (f["pct"] < p.mom_exit_pct) | ~f["context"])
    return f
