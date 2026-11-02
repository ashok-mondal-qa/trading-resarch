"""Synthetic-day tests for the NIFTY expiry-day failed breakout (spec nifty-expiry-reversal.md)."""

from dataclasses import replace

import pandas as pd
import pytest

from trading_research.data.nifty_intraday import day_check
from trading_research.strategies import expiry_reversal as er


def day(path: dict[str, float], default: float = 100.0, date: str = "2024-01-04") -> pd.DataFrame:
    """1-minute bars 09:15..15:29; `path` maps 'HH:MM' -> price from that minute on (flat bars, width 0.1),
    except that the 09:15..11:59 range is fixed at 99..101."""
    idx = pd.date_range(f"{date} 09:15", f"{date} 15:29", freq="1min")
    px = pd.Series(float("nan"), index=idx)
    px.iloc[0] = default
    for hhmm, v in path.items():
        px[pd.Timestamp(f"{date} {hhmm}")] = v
    px = px.ffill()
    bars = pd.DataFrame({"open": px, "high": px + 0.05, "low": px - 0.05, "close": px})
    morning = bars.index.time < er.RANGE_END
    bars.loc[bars.index[morning][10], "high"] = 101.0
    bars.loc[bars.index[morning][20], "low"] = 99.0
    return bars


def test_failed_breakout_up_goes_short_and_hits_range_low():
    bars = day({"12:20": 101.5, "12:32": 100.5, "13:00": 98.0})   # break at 12:20, 12:30 bar closes 100.5 < 101
    t = er.simulate(bars, er.BASE)
    assert t["side"] == "short"
    assert t["signal_end"] == pd.Timestamp("2024-01-04 12:45")   # 15-min bar 12:30-12:45 is the first close < RH
    assert t["entry"] == pytest.approx(100.5)
    assert t["stop"] == pytest.approx(101.55 * 1.0002)
    assert t["reason"] == "target" and t["exit"] == pytest.approx(99.0)
    assert t["reached_opposite"]


def test_wick_bar_itself_can_be_the_signal_but_not_in_close_mode():
    bars = day({"12:20": 101.5, "12:22": 100.5})                   # same 12:15 bar breaks and closes back below
    assert er.signal(bars, er.BASE)["signal_end"] == pd.Timestamp("2024-01-04 12:30")
    assert er.signal(bars, replace(er.BASE, confirm="close")) is None


def test_failed_breakdown_goes_long_and_stop_fills_at_gap_open():
    bars = day({"12:05": 98.5, "12:20": 99.5, "12:50": 97.0})     # 12:00 bar breaks low and closes 98.5 (< RL)
    t = er.simulate(bars, er.BASE)                                   # 12:15 bar closes 99.5 > RL -> long
    assert t["side"] == "long" and t["entry"] == pytest.approx(99.5)
    assert t["reason"] == "stop" and t["exit"] == pytest.approx(97.0)   # bar opens below the stop -> open fill
    assert t["gross_pts"] == pytest.approx(-2.5)


def test_no_lookahead_signal_ignores_bars_after_signal():
    bars = day({"12:20": 101.5, "12:32": 100.5})
    s1 = er.signal(bars)
    later = bars.copy()
    later.loc[later.index > s1["signal_end"], ["open", "high", "low", "close"]] = 500.0
    assert er.signal(later) == s1


def test_time_exit_and_no_signal_after_15():
    bars = day({"14:50": 101.5, "15:05": 100.5})                   # failure close at 15:15 > 15:00 -> no trade
    assert er.signal(bars) is None
    bars = day({"12:20": 101.5, "12:32": 100.5, "13:00": 100.0})
    t = er.simulate(bars, replace(er.BASE, target="time"))
    assert t["reason"] == "time" and t["exit_time"] == pd.Timestamp("2024-01-04 15:15")
    assert t["gross_pts"] == pytest.approx(0.5)


def test_grid_has_32_unique_variants():
    g = er.grid()
    assert len(g) == 32 and len({p.name for p in g}) == 32 and er.BASE in g


def test_futures_costs_scale_and_double():
    one = er.futures_cost_points(25000, 24950, "short", lot=75)
    assert 7 < one < 10                      # ~5 pts STT + 2 pts slippage + fees
    assert er.futures_cost_points(25000, 24950, "short", 75, mult=2) == pytest.approx(2 * one)


def test_day_check_flags_mismatch_and_missing_bars():
    bars = day({})
    assert day_check(bars, 101.0, 99.0) == "ok"
    assert day_check(bars, 102.0, 99.0).startswith("high")
    assert day_check(bars.iloc[::2], 101.0, 99.0).startswith("only")
