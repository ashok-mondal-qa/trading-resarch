import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_trailing as rt
from trading_research.strategies import trailing_exits as tx

RULES = {e.name: e for e in tx.EXITS}
ENTRY, STOP = 100.0, 99.0          # R = 1.0


def bars(points, start=9 * 60 + 35, price=100.2):
    """1-minute arrays from 09:35 to 15:29; `points` maps minute -> (open, high, low); flat elsewhere at the last
    price."""
    m = np.arange(start, 15 * 60 + 30)
    o, h, lo = (np.full(len(m), price) for _ in range(3))
    last = price
    for k, mm in enumerate(m):
        if mm in points:
            o[k], h[k], lo[k] = points[mm]
            last = (h[k] + lo[k]) / 2
        else:
            o[k] = h[k] = lo[k] = last
    return m, o, h, lo


def run(name, points, five=None, intrabar=False, can_partial=True):
    m, o, h, lo = bars(points)
    return tx.walk(m, o, h, lo, 0, ENTRY, ENTRY, STOP, RULES[name], five, intrabar, can_partial)


def test_fixed_2r_target_and_stop_first():
    legs = run("F2 2R", {600: (100.5, 102.1, 100.4)})
    assert legs == [(1.0, 102.0, "target", 600)]
    # stop and target in the same bar: the stop wins
    legs = run("F2 2R", {600: (100.5, 102.1, 98.9)})
    assert legs[0][1:3] == (99.0, "stop")


def test_time_exit_at_1510_open():
    legs = run("F0 no target", {})
    assert legs[-1][2:] == ("time", 15 * 60 + 10)


def test_breakeven_after_1r_applies_from_next_bar():
    # bar 600 reaches +1.2R and dips to 99.5 in the same bar: no exit (old stop 99 still in force)
    legs = run("T1 breakeven", {600: (100.2, 101.2, 99.5), 601: (100.5, 100.6, 99.9)})
    assert legs == [(1.0, 100.0, "trail stop", 601)]


def test_ladder_locks_one_r_after_two_and_a_half():
    legs = run("T2 ladder", {600: (100.5, 102.5, 100.4), 610: (101.5, 101.5, 100.8)})
    assert legs == [(1.0, 101.0, "trail stop", 610)]


def test_gap_through_trailing_stop_fills_at_open():
    legs = run("T2 ladder", {600: (100.5, 102.5, 100.4), 610: (100.6, 100.7, 100.5)})
    assert legs == [(1.0, 100.6, "trail stop", 610)]


def test_partial_half_at_2r_then_breakeven():
    legs = run("P1 half 2R + breakeven", {600: (100.5, 102.2, 100.4), 620: (100.3, 100.4, 99.95)})
    assert legs == [(0.5, 102.0, "partial", 600), (0.5, 100.0, "trail stop", 620)]
    # one share cannot be split: the whole position follows the breakeven trail
    legs = run("P1 half 2R + breakeven", {600: (100.5, 102.2, 100.4), 620: (100.3, 100.4, 99.95)},
               can_partial=False)
    assert legs == [(1.0, 100.0, "trail stop", 620)]


def test_intrabar_entry_bar_cannot_reach_target_or_move_stop():
    m, o, h, lo = bars({575: (99.8, 102.5, 99.7)})
    legs = tx.walk(m, o, h, lo, 0, ENTRY, ENTRY, STOP, RULES["F2 2R"], None, intrabar=True)
    assert legs[0][2] == "time"
    legs = tx.walk(m, o, h, lo, 0, ENTRY, ENTRY, STOP, RULES["T1 breakeven"], None, intrabar=True)
    assert legs[0][2] == "time"   # stop never moved, so the flat day ends at 15:10


def test_ema_trail_exits_next_bar_open_after_close_below_ema():
    # +1R reached at 600; the 5-minute bar ending 610 closes below EMA9 -> exit at the 610 bar's open
    five = {610: (100.9, 101.0, 101.3, 0.5)}
    legs = run("T5 EMA9 trail", {600: (100.5, 101.5, 100.4), 609: (101.2, 101.2, 101.0), 610: (101.05, 101.1, 101.0)},
               five=five)
    assert legs == [(1.0, 101.05, "trail (EMA9)", 610)]


def test_atr_trail_uses_highest_high_minus_two_atr():
    five = {605: (100.9, 101.8, 101.0, 0.4)}  # completed bar ending 09:..605 -> stop = 102.0 - 0.8 = 101.2
    legs = run("T3 ATR trail", {600: (100.5, 102.0, 100.4), 604: (101.8, 101.8, 101.7),
                                606: (101.5, 101.5, 101.1)}, five=five)
    assert legs == [(1.0, 101.2, "trail stop", 606)]


def test_swing_trail_needs_three_completed_bars():
    five = {595: (100.1, 100.2, 100.0, 0.3), 600: (100.4, 100.6, 100.2, 0.3), 605: (100.8, 101.4, 100.5, 0.3)}
    legs = run("T4 swing trail", {600: (100.5, 101.5, 100.4), 604: (101.4, 101.4, 101.3),
                                  606: (100.3, 100.3, 100.05)}, five=five)
    # after 605: stop = max(entry, min(100.1, 100.4, 100.8)) = 100.1; bar 606 opens at 100.3 and trades 100.05
    assert legs == [(1.0, 100.1, "trail stop", 606)]


def test_max_favourable_r_stops_at_original_stop():
    m, o, h, lo = bars({600: (100.5, 101.5, 100.4), 610: (99.5, 99.5, 98.9), 620: (103, 104, 103)})
    assert tx.max_favourable_r(m, h, lo, 0, ENTRY, STOP) == pytest.approx(1.5)


def test_money_partial_pays_a_third_order():
    legs_full = [(1.0, 102.0, "target", 600)]
    legs_part = [(0.5, 102.0, "partial", 600), (0.5, 100.0, "trail stop", 620)]
    g1, c1, n1 = rt.money(10, 100.0, legs_full, slip=0.0)
    g2, c2, n2 = rt.money(10, 100.0, legs_part, slip=0.0)
    assert g1 == pytest.approx(20.0) and g2 == pytest.approx(10.0)
    assert c2 > c1                     # three orders: the minimum brokerage applies twice on the sell side
    assert n1 == pytest.approx(g1 - c1)


def test_groww_leg_matches_schedule():
    # Rs 15,000 buy: brokerage min(20, 15) = 15; GST on brokerage and fees; stamp 0.003%
    v = 15000.0
    expected = 15 + v * 0.0000297 + v * 0.000001 + 0.18 * (15 + v * 0.0000297 + v * 0.000001) + v * 0.00003
    assert rt.groww_leg(v, True) == pytest.approx(expected)


def test_five_minute_indicators_anchor_and_ema():
    rows = []
    for d in ("2019-01-01", "2019-01-02", "2019-01-03"):
        for mm in range(9 * 60 + 15, 9 * 60 + 45):
            rows.append({"date": pd.Timestamp(d), "minute": mm, "open": 1.0, "high": 2.0, "low": 1.0, "close": 1.5})
    f = tx.five_minute_indicators(pd.DataFrame(rows))
    assert list(f.loc[pd.Timestamp("2019-01-01")].index[:2]) == [9 * 60 + 20, 9 * 60 + 25]
    assert f["ema9"].iloc[-1] == pytest.approx(1.5)
    assert f["atr14"].isna().sum() == 13 and f["atr14"].iloc[-1] == pytest.approx(1.0)
