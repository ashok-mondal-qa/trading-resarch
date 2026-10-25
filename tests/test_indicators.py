"""Indicator and structure tests. All bars are SYNTHETIC fixtures (seeded random walk or hand-built),
never market data."""

import numpy as np
import pandas as pd
import pytest

from trading_research.indicators import core, structure


def random_bars(n=300, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    open_ = close * np.exp(rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    volume = rng.integers(1_000, 10_000, n).astype(float)
    idx = pd.bdate_range("2024-01-01", periods=n, name="date")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume,
                         "traded_value": volume * close}, index=idx)


def hand_bars(highs, lows, closes=None, opens=None):
    closes = closes or [(h + l) / 2 for h, l in zip(highs, lows)]
    opens = opens or closes
    idx = pd.bdate_range("2025-01-01", periods=len(highs), name="date")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "volume": 1000.0}, index=idx)


# ---------------------------------------------------------------- no look-ahead, every indicator

BENCH = random_bars(seed=11)["close"]

PER_BAR = {
    "sma": lambda b: core.sma(b["close"], 20),
    "ema": lambda b: core.ema(b["close"], 20),
    "slope": lambda b: core.slope(core.sma(b["close"], 50), 20),
    "atr": lambda b: core.atr(b, 14),
    "atr_pct": lambda b: core.atr_pct(b, 14),
    "realized_vol": lambda b: core.realized_vol(b["close"], 20),
    "vol_percentile": lambda b: core.rolling_percentile(core.realized_vol(b["close"], 20), 100),
    "roc": lambda b: core.roc(b["close"], 20),
    "rsi": lambda b: core.rsi(b["close"], 2),
    "supertrend": lambda b: core.supertrend(b, 10, 3.0),
    "distance_from_high": lambda b: core.distance_from_high(b, 100),
    "relative_strength": lambda b: core.relative_strength(b["close"], BENCH, 20),
    "median_traded_value": lambda b: core.median_traded_value(b["traded_value"], 20),
    "volume_ratio": lambda b: core.volume_ratio(b["volume"], 20),
    "swing_state": lambda b: structure.swing_state(b, 3),
    "displacement": lambda b: structure.displacement(b, 14),
    "sweeps": lambda b: structure.liquidity_sweeps(b, 3),
}

EVENTS = {
    "swings": (lambda b: structure.swings(b, 3), "confirmed_at"),
    "breaks": (lambda b: structure.structure_breaks(b, 3), "date"),
    "fvg": (lambda b: structure.fair_value_gaps(b), "known_at"),
}


def perturb_after(bars, t):
    """Replace every bar after position t with a different random path."""
    other = random_bars(len(bars), seed=99) * 1.3
    out = bars.copy()
    out.iloc[t + 1:] = other.iloc[t + 1:].to_numpy()
    return out


@pytest.mark.parametrize("name", PER_BAR)
@pytest.mark.parametrize("t", [60, 150, 250])
def test_per_bar_outputs_ignore_future_bars(name, t):
    bars = random_bars()
    fn = PER_BAR[name]
    full, changed, truncated = fn(bars), fn(perturb_after(bars, t)), fn(bars.iloc[:t + 1])
    upto = bars.index[:t + 1]
    pd.testing.assert_frame_equal(pd.DataFrame(full.loc[upto]), pd.DataFrame(changed.loc[upto]))
    pd.testing.assert_frame_equal(pd.DataFrame(full.loc[upto]), pd.DataFrame(truncated))


@pytest.mark.parametrize("name", EVENTS)
@pytest.mark.parametrize("t", [60, 150, 250])
def test_events_known_by_t_ignore_future_bars(name, t):
    bars = random_bars()
    fn, known_col = EVENTS[name]
    cutoff = bars.index[t]

    def known(df):
        return df[df[known_col] <= cutoff].reset_index(drop=True)

    full = known(fn(bars))
    assert len(full) > 0
    pd.testing.assert_frame_equal(full, known(fn(perturb_after(bars, t))))
    pd.testing.assert_frame_equal(full, known(fn(bars.iloc[:t + 1])))


# ---------------------------------------------------------------- hand-computed values


def test_sma_ema_warmup_and_values():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert core.sma(s, 3).tolist()[2:] == [2, 3, 4] and core.sma(s, 3).isna().sum() == 2
    e = core.ema(s, 3)  # seed 2, alpha 0.5
    assert e.isna().sum() == 2 and e.tolist()[2:] == [2, 3, 4]


def test_wilder_atr_hand_computed():
    bars = hand_bars(highs=[10, 12, 11, 13], lows=[8, 9, 9, 10], closes=[9, 11, 10, 12])
    # TR: 2, max(3, 3, 0)=3, max(2, 0, 2)=2, max(3, 3, 0)=3
    assert core.true_range(bars).tolist() == [2, 3, 2, 3]
    a = core.atr(bars, 3)
    assert np.isnan(a.iloc[1]) and a.iloc[2] == pytest.approx(7 / 3)
    assert a.iloc[3] == pytest.approx((7 / 3 * 2 + 3) / 3)


def test_wilder_rsi_hand_computed():
    s = pd.Series([10.0, 11, 10, 12, 12, 11])
    # changes: +1, -1, +2, 0, -1. n=2: seed gain (1+0)/2=0.5, loss (0+1)/2=0.5 -> 50 at index 2
    r = core.rsi(s, 2)
    assert r.iloc[:2].isna().all() and r.iloc[2] == pytest.approx(50)
    # i=3: gain (0.5+2)/2=1.25, loss 0.25 -> 100-100/6; i=4: 0.625, 0.125 -> same; i=5: 0.3125, 0.5625
    assert r.iloc[3] == pytest.approx(100 - 100 / 6) and r.iloc[4] == pytest.approx(100 - 100 / 6)
    assert r.iloc[5] == pytest.approx(100 - 100 / (1 + 0.3125 / 0.5625))
    assert core.rsi(pd.Series([1.0, 2, 3, 4]), 2).iloc[-1] == 100


def test_supertrend_flips_on_band_cross():
    # flat bars (range 2, ATR 2) then a collapse: the lower band (hl2 - 3 x ATR = 94) is broken on day 13
    highs = [101.0] * 12 + [101, 90, 89]
    lows = [99.0] * 12 + [99, 88, 87]
    closes = [100.0] * 12 + [100, 89, 88]
    st = core.supertrend(hand_bars(highs, lows, closes), n=10, mult=3.0)
    assert st["direction"].iloc[:9].isna().all() and (st["direction"].iloc[9:13] == 1).all()
    assert st["line"].iloc[12] == pytest.approx(94)
    assert st["direction"].iloc[13] == -1 and st["line"].iloc[13] > closes[13]


def test_volume_ratio_excludes_today_from_median():
    v = pd.Series([100.0, 100, 100, 400])
    assert core.volume_ratio(v, 3).iloc[3] == pytest.approx(4.0)


def test_relative_strength_and_rank():
    idx = pd.bdate_range("2025-01-01", periods=3)
    stock = pd.Series([100.0, 105, 110], index=idx)
    bench = pd.Series([100.0, 100, 105], index=idx)
    assert core.relative_strength(stock, bench, 2).iloc[2] == pytest.approx(1.10 / 1.05 - 1)
    gap = bench.drop(idx[0])
    assert np.isnan(core.relative_strength(stock, gap, 2).iloc[2])  # no fill across a benchmark gap
    ranks = core.cross_sectional_rank(pd.DataFrame({"A": [0.1], "B": [0.3], "C": [0.2]}))
    assert ranks.iloc[0].tolist() == pytest.approx([1 / 3, 1, 2 / 3])


def test_weekly_drops_incomplete_week():
    bars = random_bars(n=8)  # Mon 2024-01-01 .. Wed 2024-01-10
    w = core.weekly(bars)
    assert list(w.index.strftime("%Y-%m-%d")) == ["2024-01-05"]
    assert w.iloc[0]["high"] == bars["high"].iloc[:5].max() and w.iloc[0]["sessions"] == 5
    assert len(core.weekly(bars, as_of=pd.Timestamp("2024-01-12"))) == 2


def test_swings_confirmation_lag():
    bars = hand_bars(highs=[10, 11, 15, 12, 11, 13, 9], lows=[9, 10, 12, 10, 8, 11, 7])
    s = structure.swings(bars, k=2)
    high = s[s["kind"] == "high"].iloc[0]
    assert high["price"] == 15 and high["date"] == bars.index[2] and high["confirmed_at"] == bars.index[4]


def test_bos_and_choch_labels():
    # higher highs/lows build up-structure; a close above the last swing high (14) is a bullish BOS;
    # later, still in up-structure, a close below the last higher low (10.5) is a bearish CHoCH.
    highs = [10, 12, 11, 10, 14, 12, 11, 16, 17, 15, 13, 12, 11, 10, 9, 10, 11, 12]
    lows = [9, 10, 9.5, 9.6, 11, 10.5, 10.6, 13, 14, 12, 10, 9.5, 9, 8, 7, 8, 9, 10]
    closes = [9.5, 11, 10, 9.8, 13, 11, 10.8, 15.5, 16, 13, 11, 10, 9.5, 9, 8, 9.5, 10.5, 11.5]
    bars = hand_bars(highs, lows, closes)
    breaks = structure.structure_breaks(bars, k=1)
    got = [(d.strftime("%Y-%m-%d"), r, k, lvl) for d, r, k, lvl in breaks.itertuples(index=False)]
    assert got == [("2025-01-10", "bullish", "BOS", 14.0), ("2025-01-16", "bearish", "CHoCH", 10.5)]


def test_fvg_known_at_third_bar():
    bars = hand_bars(highs=[10, 13, 14], lows=[9, 10, 11])
    f = structure.fair_value_gaps(bars)
    assert len(f) == 1 and f.iloc[0]["direction"] == "bullish"
    assert (f.iloc[0]["bottom"], f.iloc[0]["top"]) == (10, 11) and f.iloc[0]["known_at"] == bars.index[2]


def test_sell_side_sweep():
    bars = hand_bars(highs=[12, 11, 12, 13, 12.5], lows=[10, 9, 10, 11, 8.5],
                     closes=[11, 10, 11, 12, 10])
    sweeps = structure.liquidity_sweeps(bars, k=1)
    assert bool(sweeps["sell_side"].iloc[4]) and not sweeps["sell_side"].iloc[:4].any()
