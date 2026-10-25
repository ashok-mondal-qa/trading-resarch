"""Phase 12 strategy tests. All bars are SYNTHETIC fixtures, not market data."""

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting.run_swing_ideas2 import verdict
from trading_research.indicators import core
from trading_research.strategies import swing_ideas as si, swing_ideas2 as s2
from tests.test_strategy_pa_smc import BENCH, perturb_after, trend_bars


def gap_bars(seed=0):
    """Trend bars with a few gap-up days on heavy volume that hold their open."""
    b = trend_bars(seed=seed)
    for i in range(230, 315, 17):
        prev = b["close"].iloc[i - 1]
        o = prev * 1.06
        c = o * 1.01
        b.iloc[i, b.columns.get_loc("open")] = o
        b.iloc[i, b.columns.get_loc("close")] = c
        b.iloc[i, b.columns.get_loc("high")] = c * 1.002
        b.iloc[i, b.columns.get_loc("low")] = o * 0.99
        b.iloc[i, b.columns.get_loc("volume")] = b["volume"].iloc[i - 20:i].median() * 4
    b["traded_value"] = b["volume"] * b["close"]
    return b


@pytest.mark.parametrize("strategy", s2.STRATEGIES)
@pytest.mark.parametrize("t", [270, 300])
def test_features_ignore_future_bars(strategy, t):
    bars = gap_bars()
    full = s2.stock_features(bars, BENCH, strategy)
    changed = s2.stock_features(perturb_after(bars, t), BENCH, strategy)
    truncated = s2.stock_features(bars.iloc[:t + 1], BENCH, strategy)
    upto = bars.index[:t + 1]
    pd.testing.assert_frame_equal(full.loc[upto], changed.loc[upto])
    pd.testing.assert_frame_equal(full.loc[upto], truncated)


def test_gap_drift_conditions_on_signal_bars():
    found = 0
    for seed in range(6):
        bars = gap_bars(seed)
        f = s2.stock_features(bars, BENCH, "gap_drift")
        sig = f.index[f["signal"]]
        assert (bars.loc[sig, "open"] >= 1.04 * bars["close"].shift(1)[sig] - 1e-9).all()
        assert (bars.loc[sig, "close"] >= bars.loc[sig, "open"]).all()
        assert (core.volume_ratio(bars["volume"], 20)[sig] >= 3).all()
        assert (f.loc[sig, "close"] > f.loc[sig, "sma_slow"]).all() and (f.loc[sig, "stop_pct"] <= 0.10).all()
        assert np.allclose(f.loc[sig, "stop"], bars.loc[sig, "low"] - 0.1 * f.loc[sig, "atr"])
        found += len(sig)
    assert found > 0


def test_momentum_weekly_uses_the_monthly_feature_definition():
    bars = trend_bars(seed=2)
    pd.testing.assert_frame_equal(s2.stock_features(bars, BENCH, "momentum_weekly"),
                                  si.stock_features(bars, BENCH, "momentum_12_1"))


def test_week_starts():
    cal = pd.to_datetime(["2024-01-04", "2024-01-05", "2024-01-09", "2024-01-10", "2024-01-15"])
    assert list(s2.week_starts(cal)) == list(pd.to_datetime(["2024-01-04", "2024-01-09", "2024-01-15"]))


def _report(pt=40, pe=0.2, ppf=1.3, st=200, ci=(0.05, 0.3), se2=0.1):
    return {"runs": {"portfolio_2x_costs": {"trades": pt, "expectancy_r": pe, "profit_factor": ppf},
                     "standalone_1x": {"trades": st, "expectancy_r_ci97.5_month_clustered": ci},
                     "standalone_2x_costs": {"expectancy_r": se2}}}


def test_verdict_rules():
    good = {s: _report() for s in ("early", "presample", "train", "validation")}
    assert verdict(good)["passed"]
    assert not verdict({**good, "early": _report(ci=(-0.01, 0.3))})["passed"]
    assert not verdict({**good, "early": _report(ppf=1.05)})["passed"]
    assert not verdict({**good, "presample": _report(se2=-0.01)})["passed"]
    assert not verdict({"early": _report()})["passed"]
