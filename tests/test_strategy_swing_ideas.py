"""Phase 11 strategy tests. All bars are SYNTHETIC fixtures, not market data."""

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import metrics
from trading_research.backtesting.run_swing_ideas import standalone, verdict
from trading_research.config import load_settings
from trading_research.indicators import core
from trading_research.strategies import pa_smc, swing_ideas as si
from tests.test_strategy_pa_smc import BENCH, perturb_after, trend_bars


@pytest.mark.parametrize("strategy", si.STRATEGIES)
@pytest.mark.parametrize("t", [270, 300])
def test_features_ignore_future_bars(strategy, t):
    bars = trend_bars()
    full = si.stock_features(bars, BENCH, strategy)
    changed = si.stock_features(perturb_after(bars, t), BENCH, strategy)
    truncated = si.stock_features(bars.iloc[:t + 1], BENCH, strategy)
    upto = bars.index[:t + 1]
    pd.testing.assert_frame_equal(full.loc[upto], changed.loc[upto])
    pd.testing.assert_frame_equal(full.loc[upto], truncated)


def test_displacement_is_the_tested_smc_ablation():
    for seed in range(4):
        bars = trend_bars(seed=seed)
        f = si.stock_features(bars, BENCH, "displacement")
        old = pa_smc.stock_features(bars, BENCH, "smc_sweep")
        assert (f["signal"] == old["ablation"]).all()
        pd.testing.assert_series_equal(f["stop"], old["stop"])
        pd.testing.assert_series_equal(f["exit_signal"], old["exit_signal"])


def test_st_reversal_conditions_on_signal_bars():
    found = 0
    for seed in range(8):
        bars = trend_bars(seed=seed)
        f = si.stock_features(bars, BENCH, "st_reversal")
        sig = f[f["signal"]]
        rsi = core.rsi(bars["close"], 2)
        assert (rsi[sig.index] < 10).all()
        assert (sig["close"] > sig["sma_slow"]).all() and (sig["stop_pct"] <= 0.10).all()
        assert np.allclose(sig["stop"], sig["close"] - 2.5 * sig["atr"])
        assert (f["exit_signal"] == (bars["close"] > core.sma(bars["close"], 5))).all()
        found += len(sig)
    assert found > 0


def test_month_starts():
    cal = pd.to_datetime(["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02", "2024-03-04"])
    assert list(si.month_starts(cal)) == list(pd.to_datetime(["2024-01-30", "2024-02-01", "2024-03-04"]))


def test_momentum_rank_and_rules():
    idx = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-02"])
    mom = pd.DataFrame({"A": [0.5, 0.9, 0.9], "B": [0.1, 0.1, 0.1], "C": [0.2, 0.3, 0.3]}, index=idx)
    rankable = pd.DataFrame(True, index=idx, columns=mom.columns)
    rankable.loc["2024-02-01", "C"] = False
    pct = si.momentum_rank(mom, rankable)
    assert pct.loc["2024-02-01", "A"] == 1.0 and np.isnan(pct.loc["2024-02-01", "C"])
    f = pd.DataFrame({"eligible": True, "context": [True, True, False]}, index=idx)
    starts = si.month_starts(idx)
    a = si.apply_momentum(f, pct["A"], starts, si.Params())
    assert a["signal"].tolist() == [True, True, False]       # top of the universe on month starts only
    b = si.apply_momentum(f, pct["B"], starts, si.Params())
    assert b["signal"].sum() == 0 and b["exit_signal"].tolist() == [True, True, False]
    c = si.apply_momentum(f, pct["C"], starts, si.Params())
    assert c["exit_signal"].loc["2024-02-01"]                 # not rankable on a month start -> exit


def test_momentum_signals_ignore_future_bars():
    bars = {s: trend_bars(seed=s) for s in range(5)}
    starts = si.month_starts(bars[0].index)

    def signals(cut):
        fs = {s: si.stock_features(b.iloc[:cut], BENCH, "momentum_12_1") for s, b in bars.items()}
        mom = pd.DataFrame({s: f["mom"] for s, f in fs.items()})
        rankable = pd.DataFrame({s: f["inputs_complete"] & f["liquid"] for s, f in fs.items()})
        pct = si.momentum_rank(mom, rankable)
        return pd.DataFrame({s: si.apply_momentum(f, pct[s], starts)["signal"] for s, f in fs.items()})

    full, part = signals(320), signals(290)
    assert part.to_numpy().any()  # not vacuous
    pd.testing.assert_frame_equal(full.loc[part.index], part)


def test_cluster_bootstrap_is_wider_than_iid_for_clustered_trades():
    rng = np.random.default_rng(1)
    month_effect = rng.normal(0, 1, 40)
    clusters = np.repeat(np.arange(40), 10)
    values = month_effect[clusters] + rng.normal(0, 0.2, 400)
    lo_c, hi_c = metrics.cluster_bootstrap_ci(values, clusters)
    lo_i, hi_i = metrics.bootstrap_ci(values)
    assert lo_c <= values.mean() <= hi_c
    assert (hi_c - lo_c) > 1.5 * (hi_i - lo_i)


def test_standalone_skips_signals_while_the_symbol_is_in_a_trade():
    bars = trend_bars(seed=0)
    f = si.stock_features(bars, BENCH, "st_reversal")
    frame = pd.DataFrame({"open": bars["open"], "high": bars["high"], "low": bars["low"], "close": bars["close"],
                          "adj_factor": 1.0, "stop": f["stop"], "exit_signal": f["exit_signal"]})
    days = list(bars.index[220:300])
    sig = pd.DataFrame({"date": days[:20], "symbol": "X", "signal": True, "rs": 0.0})
    trend = pd.Series("up", index=bars.index)
    t = standalone({"X": frame}, sig, trend, days, load_settings(), 10, 1.0)
    assert len(t) >= 1
    entries, exits = pd.to_datetime(t["entry_date"]).tolist(), pd.to_datetime(t["exit_date"]).tolist()
    for i in range(1, len(t)):
        assert entries[i] > exits[i - 1]  # no overlapping standalone trades in one symbol


def _report(pt=40, pe=0.2, ppf=1.3, st=200, ci=(0.05, 0.3), se2=0.1):
    lo_key = "expectancy_r_ci98.3_month_clustered"
    return {"runs": {"portfolio_2x_costs": {"trades": pt, "expectancy_r": pe, "profit_factor": ppf},
                     "standalone_1x": {"trades": st, lo_key: ci},
                     "standalone_2x_costs": {"expectancy_r": se2}}}


def test_verdict_rules():
    good = {"presample": _report(), "train": _report(), "validation": _report()}
    assert verdict(good)["passed_presample_rules"]
    assert not verdict({**good, "presample": _report(ci=(-0.01, 0.3))})["passed_presample_rules"]
    assert not verdict({**good, "presample": _report(pt=29)})["passed_presample_rules"]
    assert not verdict({**good, "presample": _report(st=99)})["passed_presample_rules"]
    assert not verdict({**good, "validation": _report(se2=-0.01)})["passed_presample_rules"]
    assert not verdict({"presample": _report()})["passed_presample_rules"]  # train/validation required
