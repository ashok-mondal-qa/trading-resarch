"""Phase 13 strategy tests. All bars are SYNTHETIC fixtures, not market data."""

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting.run_social import ALPHA, verdict
from trading_research.backtesting.run_swing_ideas import ci_key
from trading_research.indicators import core
from trading_research.strategies import social
from tests.test_strategy_pa_smc import BENCH, perturb_after, trend_bars


def bars(seed=0, n=320):
    return trend_bars(n=n, seed=seed)


def leader_bars(seed=0):
    """A strong uptrend whose new 20-session highs come on doubled volume (Minervini-style breakouts)."""
    b = trend_bars(n=420, drift=0.003, seed=seed)
    new_high = b["close"] > b["high"].shift(1).rolling(20).max()
    b.loc[new_high, "volume"] *= 2.5
    b["traded_value"] = b["volume"] * b["close"]
    return b


@pytest.mark.parametrize("strategy", social.STRATEGIES)
@pytest.mark.parametrize("t", [270, 300])
def test_features_ignore_future_bars(strategy, t):
    b = bars()
    full = social.stock_features(b, BENCH, strategy)
    changed = social.stock_features(perturb_after(b, t), BENCH, strategy)
    truncated = social.stock_features(b.iloc[:t + 1], BENCH, strategy)
    upto = b.index[:t + 1]
    pd.testing.assert_frame_equal(full.loc[upto], changed.loc[upto])
    pd.testing.assert_frame_equal(full.loc[upto], truncated)


@pytest.mark.parametrize("strategy", social.STRATEGIES)
def test_signals_respect_shared_rules(strategy):
    found = 0
    for seed in range(10):
        f = social.stock_features(leader_bars(seed) if strategy == "minervini" else bars(seed), BENCH, strategy)
        sig = f[f["signal"]]
        assert (sig["stop"] < sig["close"]).all() and (sig["stop_pct"] <= 0.10 + 1e-9).all()
        assert sig["liquid"].all()
        found += len(sig)
    if strategy != "golden_cross":   # crosses are rare in 320-bar fixtures
        assert found > 0


def test_supertrend_entry_is_a_flip_up_with_stop_on_the_line():
    for seed in range(6):
        b = bars(seed)
        f = social.stock_features(b, BENCH, "supertrend")
        st = core.supertrend(b, 10, 3.0)
        sig = f.index[f["signal"]]
        assert (st.loc[sig, "direction"] == 1).all() and (st["direction"].shift(1)[sig] == -1).all()
        assert np.allclose(f.loc[sig, "stop"], st.loc[sig, "line"])
        assert (f["exit_signal"] == (st["direction"] == -1)).all()


def test_ma44_hand_built_candle_and_confirmation():
    b = bars(1)
    sma = core.sma(b["close"], 44)
    f = social.stock_features(b, BENCH, "ma44")
    sig = f.index[f["event"].fillna(False).astype(bool)]
    assert len(sig)
    pos = [b.index.get_loc(d) for d in sig]
    prev = b.index[[i - 1 for i in pos]]
    assert (b.loc[prev, "low"].to_numpy() <= sma[prev].to_numpy()).all()
    assert (b.loc[prev, "close"].to_numpy() > b.loc[prev, "open"].to_numpy()).all()
    assert (b.loc[sig, "close"].to_numpy() > b.loc[prev, "high"].to_numpy()).all()
    rng = b.loc[prev, "high"].to_numpy() - b.loc[prev, "low"].to_numpy()
    assert np.allclose(f.loc[sig, "target"], b.loc[prev, "high"].to_numpy() + 2 * rng)
    assert np.allclose(f.loc[sig, "stop"], b.loc[prev, "low"].to_numpy())


def test_minervini_rank_condition():
    f = social.stock_features(leader_bars(0), BENCH, "minervini")
    assert f["signal"].any()
    pct = pd.Series(0.5, index=f.index)
    assert not social.apply_rs_rank(f, pct)["signal"].any()
    pct[:] = 0.9
    pd.testing.assert_series_equal(social.apply_rs_rank(f, pct)["signal"], f["signal"], check_names=False)


def _report(pt=40, pe=0.2, ppf=1.3, st=400, ci=(0.05, 0.3), se2=0.1):
    return {"runs": {"portfolio_2x_costs": {"trades": pt, "expectancy_r": pe, "profit_factor": ppf},
                     "standalone_1x": {"trades": st, ci_key(ALPHA): ci},
                     "standalone_2x_costs": {"expectancy_r": se2}}}


def test_verdict_rules():
    good = {s: _report() for s in ("dev", "early", "presample", "train", "validation")}
    assert verdict(good)["passed"]
    assert not verdict({**good, "dev": _report(ci=(-0.01, 0.3))})["passed"]
    assert not verdict({**good, "dev": _report(st=299)})["passed"]
    assert not verdict({**good, "validation": _report(se2=-0.01)})["passed"]
    assert not verdict({"dev": _report()})["passed"]
