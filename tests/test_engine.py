"""Backtest engine tests against hand-computed trades. Bars are SYNTHETIC fixtures."""

import copy

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import engine, metrics
from trading_research.backtesting.costs import leg_costs
from trading_research.config import load_settings

DATES = pd.bdate_range("2025-01-06", periods=6)


@pytest.fixture
def settings():
    s = copy.deepcopy(load_settings())
    s["execution_model"]["slippage_bps_per_side"] = 0  # hand arithmetic without slippage
    return s


def frame(opens, highs, lows, closes, stop=95.0, exit_signal=None, factor=1.0):
    n = len(opens)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "adj_factor": factor, "stop": stop,
                         "exit_signal": exit_signal or [False] * n}, index=DATES[:n])


def run(frames, cands, settings, **kw):
    return engine.run(frames, cands, list(DATES), settings, start_equity=1_000_000,
                      max_holding_sessions=kw.pop("max_hold", 40), **kw)


def test_entry_next_open_and_stop_fill(settings):
    f = frame(opens=[100, 101, 102, 100, 99, 99], highs=[101, 103, 103, 101, 100, 100],
              lows=[99, 100, 101, 94, 98, 98], closes=[100, 102, 102, 96, 99, 99])
    res = run({"A": f}, {DATES[0]: ["A"]}, settings)
    t = res.trades.iloc[0]
    assert t["entry_date"] == DATES[1] and t["entry"] == 101          # next session's open
    assert t["exit_date"] == DATES[3] and t["exit"] == 95 and t["reason"] == "stop"
    # size: 0.5% of 1,000,000 = 5,000 budget; risk/share ~ 6 + charges -> 832 shares (sizer)
    qty = t["raw_qty"]
    costs = leg_costs("buy", 101, qty, settings["costs"]).total + leg_costs("sell", 95, qty, settings["costs"]).total
    assert t["pnl"] == pytest.approx((95 - 101) * qty - costs)
    assert t["planned_risk"] <= 5_000 and t["r_multiple"] == pytest.approx(t["pnl"] / t["planned_risk"])


def test_gap_through_stop_fills_at_open(settings):
    f = frame(opens=[100, 101, 90, 90, 90, 90], highs=[101, 102, 91, 91, 91, 91],
              lows=[99, 100, 88, 89, 89, 89], closes=[100, 101, 90, 90, 90, 90])
    t = run({"A": f}, {DATES[0]: ["A"]}, settings).trades.iloc[0]
    assert t["reason"] == "stop (gap)" and t["exit"] == 90 and t["r_multiple"] < -1  # worse than planned


def test_entry_skipped_when_open_below_stop(settings):
    f = frame(opens=[100, 94, 94, 94, 94, 94], highs=[101] * 6, lows=[93] * 6, closes=[100, 94, 94, 94, 94, 94])
    res = run({"A": f}, {DATES[0]: ["A"]}, settings)
    assert res.trades.empty and res.skipped.iloc[0]["reason"] == "opened at/below stop"


def test_exit_signal_fills_next_open_and_time_stop(settings):
    f = frame(opens=[100, 101, 104, 106, 107, 108], highs=[101, 105, 106, 108, 109, 109],
              lows=[99, 100, 103, 105, 106, 107], closes=[100, 104, 105, 107, 108, 108],
              exit_signal=[False, False, True, False, False, False])
    t = run({"A": f}, {DATES[0]: ["A"]}, settings).trades.iloc[0]
    assert t["exit_date"] == DATES[3] and t["exit"] == 106 and t["reason"] == "exit signal"
    f2 = f.assign(exit_signal=False)
    t2 = run({"A": f2}, {DATES[0]: ["A"]}, settings, max_hold=2).trades.iloc[0]
    assert t2["reason"] == "time stop" and t2["exit_date"] == DATES[3]


def test_split_during_trade_keeps_rupee_pnl(settings):
    # adjusted prices continuous; raw prices halve from DATES[3] (factor 0.5 before, 1.0 after)
    f = frame(opens=[100, 101, 102, 103, 104, 105], highs=[101, 102, 103, 104, 105, 106],
              lows=[99, 100, 101, 102, 103, 104], closes=[100, 101, 102, 103, 104, 105],
              exit_signal=[False, False, False, False, True, False])
    f["adj_factor"] = [0.5, 0.5, 0.5, 1.0, 1.0, 1.0]
    t = run({"A": f}, {DATES[0]: ["A"]}, settings).trades.iloc[0]
    # sized on raw entry 202 / raw stop 190 -> integer raw shares; adjusted qty = raw / 0.5
    qty_adj = t["raw_qty"] / 0.5
    gross = (105 - 101) * qty_adj
    assert t["pnl"] == pytest.approx(gross - t["costs"])


def test_aggregate_risk_cap_limits_positions(settings):
    frames = {s: frame(opens=[100] * 6, highs=[101] * 6, lows=[99] * 6, closes=[100] * 6) for s in "ABCDEF"}
    res = run(frames, {DATES[0]: list("ABCDEF")}, settings)
    # 0.5% each within a 2% aggregate cap -> at most 4 positions open at once
    assert len(res.trades) == 4
    assert sorted(res.skipped["symbol"]) == ["E", "F"]
    assert (res.skipped["reason"] == "aggregate cap: no room for a full position").all()


def test_no_partial_position_in_leftover_cap_room(settings):
    # A risks less than a full budget (stop far below, integer shares of an expensive stock); B, C, D take
    # full budgets; the room left (> 0 but < one full budget) must not be used for a small fifth position.
    frames = {s: frame(opens=[100] * 6, highs=[101] * 6, lows=[99] * 6, closes=[100] * 6) for s in "BCDE"}
    frames["A"] = frame(opens=[30000] * 6, highs=[30100] * 6, lows=[29900] * 6, closes=[30000] * 6,
                        stop=26500.0)
    res = run(frames, {DATES[0]: list("ABCDE")}, settings)
    risk = res.trades.set_index("symbol")["planned_risk"]
    assert risk["A"] < 4_000 and sorted(risk.index) == list("ABCD")
    assert res.skipped.set_index("symbol").loc["E", "reason"] == "aggregate cap: no room for a full position"


def test_cost_stress_lowers_pnl(settings):
    f = frame(opens=[100, 101, 104, 106, 107, 108], highs=[101, 105, 106, 108, 109, 109],
              lows=[99, 100, 103, 105, 106, 107], closes=[100, 104, 105, 107, 108, 108],
              exit_signal=[False, False, True, False, False, False])
    base = run({"A": f}, {DATES[0]: ["A"]}, settings).trades.iloc[0]
    stress = run({"A": f}, {DATES[0]: ["A"]}, settings, cost_multiplier=2.0).trades.iloc[0]
    assert stress["costs"] > base["costs"] * 1.9


def test_metrics_summary():
    trades = pd.DataFrame({"pnl": [100.0, -50, 200, -50], "r_multiple": [1.0, -0.5, 2.0, -0.5],
                           "reason": ["exit signal"] * 4, "sessions": [5, 3, 8, 2], "costs": [1.0] * 4})
    eq = pd.Series([100.0, 110, 99, 120])
    s = metrics.summarize(trades, eq, 100.0)
    assert s["win_rate"] == 0.5 and s["profit_factor"] == pytest.approx(3.0)
    assert s["expectancy_r"] == pytest.approx(0.5) and s["max_drawdown"] == pytest.approx(99 / 110 - 1)
    assert s["inconclusive_lt_30_trades"]


def test_profit_target_fills_at_target_or_gap_open(settings):
    f = frame(opens=[100, 101, 102, 104, 99, 99], highs=[101, 103, 106, 105, 100, 100],
              lows=[99, 100, 101, 103, 98, 98], closes=[100, 102, 105, 104, 99, 99])
    f["target"] = 105.0
    t = run({"A": f}, {DATES[0]: ["A"]}, settings).trades.iloc[0]
    assert t["exit_date"] == DATES[2] and t["exit"] == 105 and t["reason"] == "target"
    g = f.copy()
    g["open"] = [100, 101, 108, 104, 99, 99]
    g["high"] = [101, 103, 109, 105, 100, 100]
    t = run({"A": g}, {DATES[0]: ["A"]}, settings).trades.iloc[0]
    assert t["exit"] == 108 and t["reason"] == "target (gap)"   # gap above the target fills at the open


def test_stop_checked_before_target_on_the_same_day(settings):
    f = frame(opens=[100, 101, 100, 100, 100, 100], highs=[101, 102, 106, 101, 101, 101],
              lows=[99, 100, 94, 99, 99, 99], closes=[100, 101, 100, 100, 100, 100])
    f["target"] = 105.0
    t = run({"A": f}, {DATES[0]: ["A"]}, settings).trades.iloc[0]
    assert t["reason"] == "stop" and t["exit"] == 95
