"""Tests for EXP-0068..0070 rules (spec docs/strategy-specifications/sourced-intraday-ideas.md v0.1)."""

import numpy as np
import pandas as pd

from trading_research.strategies import sourced_intraday as si


def session(day="2019-03-04", base=100.0, vol=1000.0, overrides=None):
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min")
    df = pd.DataFrame({"open": base, "high": base + 0.05, "low": base - 0.05, "close": base, "volume": vol},
                      index=idx)
    for t, vals in (overrides or {}).items():
        for k, v in vals.items():
            df.loc[pd.Timestamp(f"{day} {t}"), k] = v
    return df


def test_momentum_long_signal_uses_0944_close_and_trades_1445_to_1515():
    day = session(base=102.0, overrides={"09:44": {"close": 101.0}, "14:45": {"open": 102.0},
                                         "15:15": {"open": 102.5}})
    r = si.momentum_day(day, prev_close=100.0)
    assert abs(r["r1"] - 0.01) < 1e-12
    assert r["side"] == 1 and r["entry"] == 102.0 and r["entry_min"] == 885
    assert r["reason"] == "time" and r["exit"] == 102.5 and r["exit_min"] == 915
    assert abs(r["stop"] - 102.0 * 0.99) < 1e-9


def test_momentum_signal_ignores_later_bars():
    """r1 must not change when bars after 09:44 change (no look-ahead)."""
    a = session(overrides={"09:44": {"close": 99.0}})
    b = session(overrides={"09:44": {"close": 99.0}, "09:45": {"close": 120.0}, "12:00": {"close": 50.0}})
    assert si.momentum_day(a, 100.0)["r1"] == si.momentum_day(b, 100.0)["r1"]
    assert si.momentum_day(a, 100.0)["side"] == -1


def test_momentum_stop_fills_at_gap_open():
    day = session(overrides={"09:44": {"close": 101.0}, "14:45": {"open": 100.0},
                             "14:50": {"open": 98.0, "low": 97.5}})
    r = si.momentum_day(day, 100.0)
    assert r["reason"] == "stop" and r["exit"] == 98.0 and r["exit_min"] == 890


def test_momentum_missing_bar_or_prev_close_gives_none():
    day = session().drop(pd.Timestamp("2019-03-04 09:44"))
    assert si.momentum_day(day, 100.0) is None
    assert si.momentum_day(session(), float("nan")) is None


def test_big_move_mask_uses_only_earlier_sessions():
    r1 = pd.Series(np.r_[np.linspace(0.001, 0.010, 200), [0.02]])
    m = si.big_move_mask(r1)
    assert not m.iloc[:si.BIG_MIN_HIST].any()      # not enough history
    assert m.iloc[-1]                               # biggest move clears the trailing 80th percentile
    r2 = r1.copy()
    r2.iloc[-1] = 0.5                               # changing today never changes earlier flags
    assert (si.big_move_mask(r2).iloc[:-1] == m.iloc[:-1]).all()


def test_rvol_excludes_today():
    v = pd.Series([100.0] * 14 + [300.0])
    rv = si.rvol_series(v)
    assert np.isnan(rv.iloc[9 - 1]) and rv.iloc[-1] == 3.0


def test_orb5_long_stop_at_first_bar_low_and_10r_target():
    o = {"09:15": {"open": 100.0, "low": 99.6}, "09:19": {"close": 100.4}, "09:20": {"open": 100.4}}
    day = session(overrides=o)
    f5 = si.first5(day)
    assert f5["low"] == 99.6 and f5["close"] == 100.4 and f5["volume"] == 5000.0
    t = si.orb5_trade(day, f5)
    assert t["side"] == 1 and t["stop"] == 99.6 and abs(t["target"] - (100.4 + 10 * 0.8)) < 1e-9
    assert t["reason"] == "time" and t["exit_min"] == 915


def test_orb5_short_and_stop_width_bounds():
    o = {"09:15": {"open": 100.0, "high": 100.5}, "09:19": {"close": 99.7}, "09:20": {"open": 99.7}}
    day = session(overrides=o)
    t = si.orb5_trade(day, si.first5(day))
    assert t["side"] == -1 and t["stop"] == 100.5
    tight = session(overrides={"09:15": {"open": 100.0}, "09:19": {"close": 100.04}, "09:20": {"open": 100.04}})
    assert si.orb5_trade(tight, si.first5(tight)) is None  # stop 0.09% < 0.20%
    doji = session()
    assert si.orb5_trade(doji, si.first5(doji)) is None


def test_orb5_stop_checked_before_target_in_same_bar():
    o = {"09:15": {"open": 100.0, "low": 99.6}, "09:19": {"close": 100.4}, "09:20": {"open": 100.4},
         "10:00": {"high": 120.0, "low": 99.0}}
    day = session(overrides=o)
    t = si.orb5_trade(day, si.first5(day))
    assert t["reason"] == "stop" and t["exit"] == 99.6 and t["gross_r"] == -1.0
