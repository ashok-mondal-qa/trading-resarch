"""Baseline strategy and regime tests. All bars are SYNTHETIC fixtures, not market data."""

import numpy as np
import pandas as pd
import pytest

from trading_research.indicators import regime
from trading_research.strategies import baseline_trend_breakout as strat


def trend_bars(n=320, drift=0.002, seed=3, start="2023-01-02", base=100.0):
    rng = np.random.default_rng(seed)
    close = base * np.exp(np.cumsum(drift + rng.normal(0, 0.012, n)))
    open_ = close * np.exp(rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.008, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.008, n))
    volume = rng.integers(200_000, 400_000, n).astype(float)
    volume[::7] *= 2.5  # periodic volume spikes so confirmation can occur
    idx = pd.bdate_range(start, periods=n, name="date")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume,
                         "traded_value": volume * close}, index=idx)


BENCH = trend_bars(drift=0.001, seed=5)["close"]


def test_regime_labels_and_warmup():
    up = regime.regime(trend_bars(drift=0.004)["close"], vol_window=100)
    # SMA200 first exists at position 199 (SMA50 slope already at 69)
    assert (up["trend"].iloc[:199] == "unknown").all() and up["trend"].iloc[199] != "unknown"
    assert (up["trend"].iloc[-50:] == "up").mean() > 0.9
    down = regime.regime(trend_bars(drift=-0.004)["close"], vol_window=100)
    assert (down["trend"].iloc[-50:] == "down").mean() > 0.9
    assert set(up["volatility"].unique()) <= {"unknown", "low", "normal", "high"}


def perturb_after(bars, t, seed=42):
    other = trend_bars(len(bars), drift=-0.01, seed=seed)
    out = bars.copy()
    out.iloc[t + 1:] = other.iloc[t + 1:].to_numpy()
    return out


@pytest.mark.parametrize("t", [230, 280, 310])
def test_features_ignore_future_bars(t):
    bars = trend_bars()
    full = strat.stock_features(bars, BENCH)
    changed = strat.stock_features(perturb_after(bars, t), BENCH)
    truncated = strat.stock_features(bars.iloc[:t + 1], BENCH)
    upto = bars.index[:t + 1]
    pd.testing.assert_frame_equal(full.loc[upto], changed.loc[upto])
    pd.testing.assert_frame_equal(full.loc[upto], truncated)


def test_regime_ignores_future_bars():
    full = regime.regime(BENCH, vol_window=100)
    trunc = regime.regime(BENCH.iloc[:260], vol_window=100)
    pd.testing.assert_frame_equal(full.iloc[:260], trunc)


def test_signal_needs_every_condition():
    bars = trend_bars(drift=0.004)
    f = strat.stock_features(bars, BENCH)
    assert f["signal"].any(), "fixture should produce at least one breakout signal"
    sig = f[f["signal"]]
    assert (sig["close"] > sig["prior_high"]).all() and (sig["close"] > sig["sma_slow"]).all()
    assert (sig["volume_ratio"] >= 1.5).all() and (sig["rs"] > 0).all()
    assert (sig["stop"] < sig["close"]).all() and (sig["stop_pct"] <= 0.10).all()
    assert not f["signal"].iloc[:200].any()  # warm-up never signals


def test_illiquid_or_cheap_stock_never_signals():
    cheap = trend_bars(drift=0.004, base=20.0)
    assert not strat.stock_features(cheap, BENCH)["signal"].any()
    thin = trend_bars(drift=0.004)
    thin["traded_value"] = 1e6
    assert not strat.stock_features(thin, BENCH)["signal"].any()


def fake_features(dates, rs_values):
    f = pd.DataFrame(index=pd.DatetimeIndex(dates, name="date"))
    f["signal"], f["watchlist"] = True, False
    f["rs"], f["close"], f["stop"], f["atr"], f["volume_ratio"] = rs_values, 100.0, 95.0, 2.5, 2.0
    return f


def test_at_most_two_candidates_per_day_ranked_by_rs():
    bench = trend_bars(drift=0.004, seed=8)["close"]
    day = bench.index[-1]
    feats = {s: fake_features([day], rs) for s, rs in {"A": 0.1, "B": 0.3, "C": 0.2, "D": 0.05}.items()}
    out = strat.daily_candidates(feats, bench)
    chosen = out[out["status"] == "TRADE CANDIDATE"]["symbol"].tolist()
    assert chosen == ["B", "C"]
    assert (out[out["symbol"].isin(["A", "D"])]["status"] == "WATCHLIST").all()


def test_regime_gate_rejects_and_missing_benchmark_is_data_insufficient():
    down = trend_bars(drift=-0.004, seed=8)["close"]
    day = down.index[-1]
    out = strat.daily_candidates({"A": fake_features([day], [0.2])}, down)
    assert out["status"].tolist() == ["REJECTED"]
    gap_day = day + pd.offsets.BDay(5)
    out = strat.daily_candidates({"A": fake_features([gap_day], [0.2])}, down)
    assert out["status"].tolist() == ["DATA INSUFFICIENT"]
