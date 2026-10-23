"""Phase 8 strategy tests. All bars are SYNTHETIC fixtures, not market data."""

import numpy as np
import pandas as pd
import pytest

from trading_research.indicators import core, structure
from trading_research.strategies import pa_smc


def trend_bars(n=320, drift=0.0015, seed=3, start="2023-01-02"):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.015, n)))
    open_ = close * np.exp(rng.normal(0, 0.006, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    # occasional strong up bars (open low, close at the high) so displacement can occur
    for i in range(17, n, 23):
        open_[i], close[i:] = close[i - 1], close[i:] * 1.05
        high[i], low[i] = close[i], min(low[i], open_[i])
        high[i + 1:] *= 1.05; low[i + 1:] *= 1.05; open_[i + 1:] *= 1.05
    volume = rng.integers(400_000, 800_000, n).astype(float)
    idx = pd.bdate_range(start, periods=n, name="date")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume,
                         "traded_value": volume * close}, index=idx)


BENCH = trend_bars(drift=0.0005, seed=5)["close"]


def perturb_after(bars, t):
    out = bars.copy()
    out.iloc[t + 1:] = trend_bars(len(bars), drift=-0.01, seed=42).iloc[t + 1:].to_numpy()
    return out


@pytest.mark.parametrize("strategy", pa_smc.STRATEGIES)
@pytest.mark.parametrize("t", [230, 290])
def test_features_ignore_future_bars(strategy, t):
    bars = trend_bars()
    full = pa_smc.stock_features(bars, BENCH, strategy)
    changed = pa_smc.stock_features(perturb_after(bars, t), BENCH, strategy)
    truncated = pa_smc.stock_features(bars.iloc[:t + 1], BENCH, strategy)
    upto = bars.index[:t + 1]
    pd.testing.assert_frame_equal(full.loc[upto], changed.loc[upto])
    pd.testing.assert_frame_equal(full.loc[upto], truncated)


@pytest.mark.parametrize("strategy", pa_smc.STRATEGIES)
def test_signal_is_ablation_plus_filter(strategy):
    found = 0
    for seed in range(8):
        f = pa_smc.stock_features(trend_bars(seed=seed), BENCH, strategy)
        assert (f["signal"] == (f["ablation"] & f["filter"])).all()
        sig = f[f["signal"]]
        assert (sig["stop"] < sig["close"]).all() and (sig["stop_pct"] <= 0.10).all()
        assert (sig["close"] > sig["sma_slow"]).all()
        found += len(sig)
    assert found > 0  # the fixtures do produce signals, so the checks above are not vacuous


def test_pa_pullback_conditions_on_signal_bars():
    bars = trend_bars(seed=0)
    f = pa_smc.stock_features(bars, BENCH, "pa_pullback")
    state = structure.swing_state(bars, 3)
    ema = core.ema(bars["close"], 20)
    sig = f.index[f["signal"]]
    assert len(sig)
    assert (state.loc[sig, "structure"] == "up").all()
    assert (bars.loc[sig, "low"] <= ema[sig]).all()
    assert (bars.loc[sig, "close"] > bars["high"].shift(1)[sig]).all()
    assert (bars.loc[sig, "close"] > state.loc[sig, "last_low"]).all()
    assert np.allclose(f.loc[sig, "stop"], state.loc[sig, "last_low"] - 0.1 * f.loc[sig, "atr"])


def test_smc_sweep_hand_built_sequence():
    # flat bars with a swing low at day 5 (low 98), a sweep on day 12 (low 97, close 99.5 back above 98),
    # then a bullish displacement on day 14 (body 4 > 1.5 x ATR ~1.6, close at the high)
    n = 16
    o = np.full(n, 100.0); c = np.full(n, 100.2); h = np.full(n, 100.8); low = np.full(n, 99.0)
    low[5] = 98.0
    o[12], c[12], h[12], low[12] = 99.8, 99.5, 100.0, 97.0
    o[14], c[14], h[14], low[14] = 100.0, 104.0, 104.0, 99.8
    idx = pd.bdate_range("2024-01-01", periods=n, name="date")
    bars = pd.DataFrame({"open": o, "high": h, "low": low, "close": c, "volume": 1e6,
                         "traded_value": 1e8}, index=idx)
    bench = pd.Series(np.linspace(100, 101, n), index=idx)
    p = pa_smc.Params(trend_slow=5, rs_lookback=5, atr_n=5, volume_lookback=5)
    f = pa_smc.stock_features(bars, bench, "smc_sweep", p)
    sweeps = structure.liquidity_sweeps(bars, 3)["sell_side"]
    assert sweeps.iloc[12] and sweeps.sum() == 1
    assert f["filter"].iloc[12:17].all() and not f["filter"].iloc[11]
    assert f["event"].iloc[14] and f["signal"].iloc[14] and f["signal"].sum() == 1
    assert f["stop"].iloc[14] == pytest.approx(97.0 - 0.1 * f["atr"].iloc[14])


def test_unknown_strategy_rejected():
    with pytest.raises(ValueError):
        pa_smc.stock_features(trend_bars(), BENCH, "guesswork")
