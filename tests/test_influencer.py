"""Synthetic tests for the influencer intraday rules (spec influencer-intraday.md)."""

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_influencer as run
from trading_research.strategies import influencer as inf


def day(path: dict[str, float], start: float = 100.0, date: str = "2019-01-04", vol: float = 1000.0,
        spread: float = 0.05) -> pd.DataFrame:
    idx = pd.date_range(f"{date} 09:15", f"{date} 15:29", freq="1min")
    px = pd.Series(float("nan"), index=idx)
    px.iloc[0] = start
    for hhmm, v in path.items():
        px[pd.Timestamp(f"{date} {hhmm}")] = v
    px = px.ffill()
    return pd.DataFrame({"open": px, "high": px + spread, "low": px - spread, "close": px, "volume": vol})


def test_supertrend_flips_up_on_rally():
    f = pd.DataFrame({"high": [101.0] * 20 + [110.0], "low": [99.0] * 20 + [108.0], "close": [100.0] * 20 + [109.0]})
    d, line = inf.supertrend(f)
    assert np.isnan(d[:9]).all()
    assert d[-1] == 1 and line[-1] < 109.0


def test_cpr_levels():
    p, top, bot = inf.cpr_levels(110.0, 90.0, 105.0)
    assert p == pytest.approx(305 / 3)
    assert bot == pytest.approx(100.0) and top == pytest.approx(2 * 305 / 3 - 100.0)


def test_ohol_long_when_open_is_low_of_first_15_minutes():
    bars = day({"09:16": 100.3, "09:20": 100.8, "09:29": 101.0, "09:30": 101.1, "11:00": 104.0}, spread=0.0)
    d = inf.build_days(bars)[-1]
    sig = inf.first_signal(d, "ohol")
    assert sig.side == 1 and d.m[sig.i] == 570 and sig.entry == pytest.approx(101.1)
    assert sig.stop == pytest.approx(100.0)
    tr = inf.simulate(d, sig)
    assert tr["reason"] == "target" and tr["exit"] == pytest.approx(101.1 + 2 * 1.1)


def test_ohol_none_when_open_is_inside_range():
    bars = day({"09:16": 99.0, "09:20": 101.0}, spread=0.0)
    assert inf.first_signal(inf.build_days(bars)[-1], "ohol") is None


def test_ema5_sell_alert_breaks_low_with_stop_at_alert_high():
    # flat, then a spike 09:45-09:49 lifts a 5-min bar entirely above EMA 5; the next bar breaks its low
    bars = day({"09:45": 102.0, "09:50": 101.0, "10:30": 95.0}, spread=0.05)
    d = inf.build_days(bars)[-1]
    sig = inf.first_signal(d, "ema5")
    assert sig.side == -1 and d.m[sig.i] == 590
    assert sig.entry == pytest.approx(101.05) or sig.entry == pytest.approx(101.0)
    assert sig.stop == pytest.approx(102.05)
    assert sig.target_r == inf.EMA5_TARGET_R


def test_simulate_flip_exit():
    bars = day({"10:00": 101.0, "11:00": 101.5})
    d = inf.build_days(bars)[-1]
    sig = inf.Signal("st_flip", 1, 50, d.o[50], 99.0, None, flip_exit_min=650)
    tr = inf.simulate(d, sig)
    assert tr["reason"] == "flip" and tr["exit_min"] == 650


def test_cpr_breakout_only_on_narrow_day():
    days = []
    for k, date in enumerate(pd.bdate_range("2019-01-01", periods=70)):
        days.append(day({}, start=100.0 + (k % 3), date=str(date.date())))
    bars = pd.concat(days)
    daily = pd.DataFrame({"high": 102.0, "low": 98.0, "close": [101.0 + 0.1 * (k % 7) for k in range(70)]},
                         index=pd.bdate_range("2019-01-01", periods=70))
    daily.iloc[-2] = [100.2, 99.8, 100.1]  # narrowest CPR for the last session
    out = inf.build_days(bars, daily)
    assert out[-1].cpr["narrow"] and not out[-2].cpr["narrow"]
    assert not out[0].cpr and "narrow" in out[1].cpr and not out[1].cpr["narrow"]  # no history yet


def test_windows_cover_split_range():
    w = run.windows("stocks")
    assert w[0][0] == "2017-01-01" and w[-1][1] == "2020-12-31" and len(w) == 8


def test_cpr_signal_first_15min_close_beyond_with_stop_other_side():
    bars = day({"09:20": 100.05, "09:35": 100.6, "11:00": 102.0}, date="2019-01-04")
    d = inf.build_days(bars)[-1]
    d.cpr = {"top": 100.2, "bot": 99.9, "width": 0.003, "narrow": True}
    sig = inf.first_signal(d, "cpr")
    assert sig.side == 1 and d.m[sig.i] == 585 and sig.stop == pytest.approx(99.9)
    d.cpr["narrow"] = False
    assert inf.first_signal(d, "cpr") is None
