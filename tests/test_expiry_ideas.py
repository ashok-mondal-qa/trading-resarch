"""Synthetic-day tests for the five expiry-day ideas (spec nifty-expiry-ideas.md)."""

import pandas as pd
import pytest

from trading_research.strategies import expiry_ideas as ei


def day(path: dict[str, float], start: float = 100.0, date: str = "2024-01-04") -> pd.DataFrame:
    idx = pd.date_range(f"{date} 09:15", f"{date} 15:29", freq="1min")
    px = pd.Series(float("nan"), index=idx)
    px.iloc[0] = start
    for hhmm, v in path.items():
        px[pd.Timestamp(f"{date} {hhmm}")] = v
    px = px.ffill()
    return pd.DataFrame({"open": px, "high": px + 0.05, "low": px - 0.05, "close": px})


def test_orb_long_with_2r_target():
    bars = day({"09:20": 100.5, "09:25": 99.6, "09:40": 101.0, "10:30": 104.0})
    t = ei.orb(bars, {})
    assert t["side"] == "long" and t["entry_time"] == pd.Timestamp("2024-01-04 09:45")
    assert t["stop"] == pytest.approx(99.55 * (1 - ei.BUF))
    assert t["reason"] == "target" and t["exit"] == pytest.approx(101.0 + 2 * t["risk_pts"])


def test_gap_fade_targets_previous_close_and_gap_follow_is_opposite():
    bars = day({"09:30": 100.2, "10:00": 99.4}, start=100.5)       # gap up 0.5% over 100.0
    fade = ei.gap_fade(bars, {"prev_close": 100.0})
    assert fade["side"] == "short" and fade["reason"] == "target" and fade["exit"] == pytest.approx(100.0)
    assert ei.gap_follow(bars, {"prev_close": 100.0})["side"] == "long"
    assert ei.gap_fade(bars, {"prev_close": 100.4}) is None        # gap 0.1% < 0.30%


def test_late_trend_follows_morning_move_and_exits_1515():
    bars = day({"11:00": 100.5, "14:00": 101.0})
    t = ei.late_trend(bars, {})
    assert t["side"] == "long" and t["entry_time"] == pd.Timestamp("2024-01-04 13:30")
    assert t["reason"] == "time" and t["exit_time"] == pd.Timestamp("2024-01-04 15:15")


def test_vwap_cross_uses_only_closed_bars():
    bars = day({"10:00": 99.0, "11:00": 101.0, "12:30": 98.0})
    t = ei.vwap_trend(bars, {})
    assert t["side"] == "long" and t["entry_time"] == pd.Timestamp("2024-01-04 11:15")
    assert t["reason"] in ("signal", "stop")
