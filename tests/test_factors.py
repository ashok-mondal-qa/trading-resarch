import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_factors as rf
from trading_research.strategies import factors as fa

ZERO = {"brokerage_pct": 0.0, "brokerage_cap_inr": 0.0, "stt_pct_buy": 0.0, "stt_pct_sell": 0.0,
        "exchange_txn_pct": 0.0, "sebi_fee_pct": 0.0, "stamp_duty_pct_buy": 0.0, "gst_pct": 0.0,
        "dp_charge_inr_per_sell": 0.0}
SMALL = fa.Params(universe_size=3, holdings=2, min_history=20, liquidity_window=5, vol_window=20, mom_long=30,
                  mom_skip=5)


def market(n=320, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    vols = {"CALM": 0.002, "MID": 0.01, "WILD": 0.03, "THIN": 0.002}
    drift = {"CALM": 0.0005, "MID": 0.0, "WILD": -0.001, "THIN": 0.0}
    close = pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(drift[s], v, n))) for s, v in vols.items()}, index=idx)
    value = pd.DataFrame({"CALM": 5e7, "MID": 4e7, "WILD": 3e7, "THIN": 1e5}, index=idx)
    return close, close.shift(1).fillna(close.iloc[0]), value


def test_universe_needs_liquidity_and_history():
    close, _, value = market()
    t = close.index[100]
    assert list(fa.universe(close, value, t, SMALL)) == ["CALM", "MID", "WILD"]
    short = close.copy()
    short.loc[: close.index[90], "MID"] = np.nan                          # only 10 closes in the window
    assert "MID" not in fa.universe(short, value, t, SMALL)


def test_scores_rank_calm_first_and_ignore_future_bars():
    close, _, value = market()
    t = close.index[200]
    assert fa.targets("lowvol", close, value, t, SMALL) == ["CALM", "MID"]
    future = close.copy()
    future.iloc[201:] *= 5                                                 # anything after t
    for strategy in fa.STRATEGIES:
        assert fa.targets(strategy, close, value, t, SMALL) == fa.targets(strategy, future, value, t, SMALL)
    m = fa.scores("momentum", close, t, pd.Index(["CALM"]), SMALL)["CALM"]
    i = close.index.get_loc(t)
    assert m == pytest.approx(close["CALM"].iloc[i - 5] / close["CALM"].iloc[i - 30] - 1)


def test_simulate_trades_at_next_open_without_costs():
    close, open_, value = market()
    start, end = str(close.index[60].date()), str(close.index[-1].date())
    eq, lots = rf.simulate("lowvol", close, open_, value, start, end, ZERO, 1.0, SMALL)
    first = pd.Timestamp(start)
    held = fa.targets("lowvol", close, value, close.index[59], SMALL)
    units = {s: (rf.START_EQUITY / 2) / (1 + rf.SLIPPAGE_PCT / 100) / open_.at[first, s] for s in held}
    cash = rf.START_EQUITY - sum(units[s] * open_.at[first, s] for s in held) * (1 + rf.SLIPPAGE_PCT / 100)
    assert eq.iloc[0] == pytest.approx(cash + sum(units[s] * close.at[first, s] for s in held))
    assert (eq > 0).all() and lots["exit_date"].max() == close.index[-1]


def test_rebalance_sells_names_that_leave():
    close, open_, value = market()
    close.loc[close.index[150]:, "CALM"] *= np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.05, len(close) - 150)))
    start, end = str(close.index[60].date()), str(close.index[-1].date())
    _, lots = rf.simulate("lowvol", close, close.shift(1).fillna(close.iloc[0]), value, start, end, ZERO, 1.0, SMALL)
    calm_exits = lots[lots["symbol"] == "CALM"]["exit_date"]
    assert (calm_exits < close.index[-1]).any()                            # sold before the end once it got wild


def test_sharpe_diff_ci_and_verdict():
    r = pd.Series(np.random.default_rng(2).normal(0.01, 0.04, 120), index=pd.period_range("2013-01", periods=120, freq="M"))
    lo, hi = rf.sharpe_diff_ci(r, r)
    assert lo == pytest.approx(0) and hi == pytest.approx(0)
    good = {"sharpe_monthly": 1.0, "nifty_sharpe_monthly": 0.7, "max_drawdown": -0.2, "nifty_max_drawdown": -0.3,
            "strategy_after_tax": {"cagr": 0.15}, "nifty_after_tax": {"cagr": 0.1},
            f"sharpe_diff_ci_{1 - rf.ALPHA:.4f}": (0.05, 0.6)}
    res = {"1x": {s: good for s in rf.SPLITS}, "2x": {s: good for s in rf.SPLITS}}
    assert rf.verdict(res)["status"] == "HOLDOUT CANDIDATE"
    res["2x"]["dev_b"] = {**good, "sharpe_monthly": 0.6}
    assert rf.verdict(res)["status"] == "REJECTED"


def test_holdout_sealed():
    assert rf.DATA_END.isoformat() < rf.HOLDOUT[0]
    assert all(end < rf.HOLDOUT[0] for _, end in rf.SPLITS.values())


def test_forward_decision_waits_then_compares_with_nifty():
    good = {"strategy": {"cagr": 0.15}, "nifty": {"cagr": 0.12}, "sharpe_monthly": 1.0, "nifty_sharpe_monthly": 0.8,
            "max_drawdown": -0.2, "nifty_max_drawdown": -0.15}
    report = {"1x": good, "2x": good}
    assert rf.forward_decision(report, 23.9) == "tracking"
    assert rf.forward_decision(report, 24.0).startswith("PASSED")
    report["2x"] = {**good, "max_drawdown": -0.3}
    assert rf.forward_decision(report, 30) == "REJECTED"
    assert rf.FORWARD_START > rf.HOLDOUT[1]


def test_forward_refuses_dates_before_start():
    with pytest.raises(SystemExit):
        rf.forward("lowvol", pd.Timestamp("2026-10-30").date())


def test_error_segments_are_point_in_time():
    dates = pd.Series(pd.bdate_range("2020-01-01", periods=5))
    manifest = {"issues": [{"severity": "error", "date": "2020-01-03"}, {"severity": "warning", "date": "2020-01-02"},
                           {"severity": "error", "date": "2020-01-07"}]}
    assert list(rf.error_segments(dates, manifest, pd.Timestamp("2020-01-10").date())) == [0, 0, 0, 1, 1]
    assert list(rf.error_segments(dates, manifest, pd.Timestamp("2020-01-06").date())) == [0, 0, 0, 1, 1]
    assert list(rf.error_segments(dates, {}, pd.Timestamp("2020-01-10").date())) == [0] * 5


def test_later_error_keeps_earlier_history_but_resets_it_afterwards():
    close, _, value = market()
    seg = pd.DataFrame(0, index=close.index, columns=close.columns)
    k = 150
    seg.iloc[k + 1:, seg.columns.get_loc("CALM")] = 1                     # an error on day k
    before, after = close.index[120], close.index[k + 10]
    assert fa.targets("lowvol", close, value, before, SMALL, seg) == fa.targets("lowvol", close, value, before, SMALL)
    assert "CALM" in fa.targets("lowvol", close, value, before, SMALL, seg)
    assert "CALM" not in fa.targets("lowvol", close, value, after, SMALL, seg)   # only 10 bars since the error
    assert "CALM" in fa.targets("lowvol", close, value, close.index[k + 40], SMALL, seg)


def test_holdout_decision_needs_both_cost_levels():
    good = {"net_return": 0.12, "nifty_net_return": 0.08, "sharpe_daily": 1.1, "nifty_sharpe_daily": 0.9,
            "max_drawdown": -0.12, "nifty_max_drawdown": -0.1}
    assert rf.holdout_decision({"1x": good, "2x": good}) == "PASSED HOLDOUT"
    assert rf.holdout_decision({"1x": good, "2x": {**good, "net_return": 0.07}}) == "FAILED HOLDOUT"
    assert set(rf.HOLDOUT_EXPERIMENTS) == set(rf.FORWARD)
