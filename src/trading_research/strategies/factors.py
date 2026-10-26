"""Monthly factor portfolios on NSE stocks (spec docs/strategy-specifications/factor-portfolios.md, v0.1).
Research and paper only; nothing here orders.

At each month's last session t the universe is the `universe_size` most traded stocks (63-session median traded
value) with at least `min_history` closes in the last 260 sessions and a bar on t. Scores use adjusted closes up
to t only:

* `lowvol`: minus the standard deviation of the last 252 daily returns (calmest first).
* `momentum`: close 21 sessions ago / close 252 sessions ago - 1 (12-1 month momentum).
* `mom_lowvol`: mean of the two percentile ranks within the universe.

The portfolio holds the top `holdings` names, equal weight at entry (drift allowed between rebalances).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

SPEC_VERSION = "0.1"
STRATEGIES = ("lowvol", "momentum", "mom_lowvol")


@dataclass(frozen=True)
class Params:
    universe_size: int = 200
    holdings: int = 30
    min_history: int = 240
    liquidity_window: int = 63
    vol_window: int = 252
    mom_long: int = 252
    mom_skip: int = 21
    min_median_value: float = 0.0       # liquidity floor on the median traded value (0 = none, as on NSE)
    value_on_t: bool = False            # also need a traded value on t (crypto blanks it for announced delistings)

    def as_dict(self) -> dict:
        return asdict(self)


def month_ends(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(index, index=index)
    return list(s.groupby(index.to_period("M")).max())


def universe(close: pd.DataFrame, traded_value: pd.DataFrame, t: pd.Timestamp, p: Params = Params()) -> pd.Index:
    i = close.index.get_loc(t)
    window = close.iloc[max(0, i - 259): i + 1]
    history = window.notna().sum()
    liq = traded_value.iloc[max(0, i - p.liquidity_window + 1): i + 1].median()
    ok = (history >= p.min_history) & close.loc[t].notna() & liq.notna() & (liq >= p.min_median_value)
    if p.value_on_t:
        ok &= traded_value.loc[t].notna()
    return liq[ok].sort_values(ascending=False).index[: p.universe_size]


def scores(strategy: str, close: pd.DataFrame, t: pd.Timestamp, names: pd.Index, p: Params = Params()) -> pd.Series:
    i = close.index.get_loc(t)
    c = close[names].iloc[max(0, i - p.mom_long): i + 1]
    vol = c.pct_change(fill_method=None).iloc[-p.vol_window:].std()
    lowvol = -vol
    if strategy == "lowvol":
        return lowvol.dropna()
    mom = c.iloc[-1 - p.mom_skip] / c.iloc[0] - 1 if len(c) > p.mom_long else pd.Series(np.nan, index=names)
    if strategy == "momentum":
        return mom.dropna()
    both = pd.concat([lowvol.rank(pct=True), mom.rank(pct=True)], axis=1).dropna()
    return both.mean(axis=1)


def targets(strategy: str, close: pd.DataFrame, traded_value: pd.DataFrame, t: pd.Timestamp,
            p: Params = Params()) -> list[str]:
    names = universe(close, traded_value, t, p)
    s = scores(strategy, close, t, names, p)
    return list(s.sort_values(ascending=False, kind="mergesort").index[: p.holdings])
