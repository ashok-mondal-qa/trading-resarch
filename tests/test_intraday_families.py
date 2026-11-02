"""Synthetic tests for the three intraday families (spec intraday-three-families.md)."""

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_intraday_families as run
from trading_research.strategies import intraday_families as fam


def day(path: dict[str, float], start: float = 100.0, date: str = "2019-01-04", vol: float = 1000.0) -> pd.DataFrame:
    idx = pd.date_range(f"{date} 09:15", f"{date} 15:29", freq="1min")
    px = pd.Series(float("nan"), index=idx)
    px.iloc[0] = start
    for hhmm, v in path.items():
        px[pd.Timestamp(f"{date} {hhmm}")] = v
    px = px.ffill()
    return pd.DataFrame({"open": px, "high": px + 0.05, "low": px - 0.05, "close": px, "volume": vol})


def one(bars, info=None, mkt=None):
    return fam.build_days(bars, info, mkt)[-1]


def info_for(date, **kw):
    base = {"prev_high": np.nan, "prev_low": np.nan, "prev_close": np.nan, "sma20": np.nan}
    base.update(kw)
    return pd.DataFrame([base], index=[pd.Timestamp(date)])


def test_orb_long_stop_other_side_and_2r_target():
    d = one(day({"09:20": 100.5, "09:25": 99.6, "09:40": 101.0, "10:30": 104.0}))
    sig = fam.first_signal(d, "orb", False)
    assert sig.side == 1 and d.m[sig.i] == 585  # signal bar 09:40-09:44 closes, entry at the 09:45 open
    assert sig.stop == pytest.approx(99.55)
    tr = fam.simulate(d, sig)
    assert tr["reason"] == "target" and tr["exit"] == pytest.approx(101.0 + 2 * (101.0 - 99.55))


def test_orb_only_first_breakout_counts():
    # first breakout (short) has a stop wider than 2% -> no trade even though a long breakout follows
    d = one(day({"09:20": 103.0, "09:25": 100.0, "09:40": 99.0, "10:00": 104.0}))
    assert fam.first_signal(d, "orb", False) is None


def test_breakout_retest_long_entry_and_stop():
    bars = day({"09:20": 100.5, "10:00": 101.5, "10:20": 101.05, "10:24": 101.3, "12:00": 102.0},
               date="2019-01-07")
    d = one(bars, info_for("2019-01-07", prev_high=101.0, prev_low=98.0))
    sig = fam.first_signal(d, "brt", False)
    assert sig.side == 1 and d.m[sig.i] == 625  # retest bar 10:20-10:24 closes above 101 -> 10:25 open
    assert sig.stop == pytest.approx(101.0 * (1 - fam.STOP_BUF))  # retest low 101.0 = level


def test_breakout_retest_invalidated_by_close_back_below_level():
    bars = day({"10:00": 101.5, "10:20": 100.5, "10:40": 101.05, "10:44": 101.3}, date="2019-01-07")
    d = one(bars, info_for("2019-01-07", prev_high=101.0, prev_low=98.0))
    assert fam.first_signal(d, "brt", False) is None


def test_breakout_retest_skips_gap_beyond_level():
    bars = day({"10:00": 102.5, "10:20": 101.05, "10:24": 101.3}, start=101.5, date="2019-01-07")
    d = one(bars, info_for("2019-01-07", prev_high=101.0, prev_low=98.0))
    assert fam.first_signal(d, "brt", False) is None


def random_days(n=4, seed=1):
    rng = np.random.default_rng(seed)
    frames = []
    px = 100.0
    for k, date in enumerate(pd.bdate_range("2019-02-04", periods=n)):
        idx = pd.date_range(f"{date.date()} 09:15", f"{date.date()} 15:29", freq="1min")
        steps = rng.normal(0.0004, 0.0015, len(idx))
        close = px * np.exp(np.cumsum(steps))
        op = np.r_[px, close[:-1]]
        hi = np.maximum(op, close) * 1.0004
        lo = np.minimum(op, close) * 0.9996
        frames.append(pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close,
                                    "volume": rng.integers(500, 5000, len(idx)).astype(float)}, index=idx))
        px = close[-1]
    return pd.concat(frames)


@pytest.mark.parametrize("rule", fam.RULES)
def test_no_lookahead_truncating_after_entry_keeps_the_signal(rule):
    found = 0
    for seed in range(1, 12):
        bars = random_days(seed=seed)
        last = bars.index.normalize().max()
        prev = bars[bars.index.normalize() < last]
        prev_day = prev[prev.index.normalize() == prev.index.normalize().max()]
        info = info_for(str(last.date()), prev_high=float(prev_day["high"].max()), prev_low=float(prev_day["low"].min()))
        full = fam.first_signal(one(bars, info), rule, False)
        if full is None:
            continue
        found += 1
        d_full = one(bars, info)
        cut = bars[bars.index <= last + pd.Timedelta(minutes=d_full.m[full.i])]  # up to the entry bar
        part = fam.first_signal(one(cut, info), rule, False)
        assert part is not None and (part.side, part.entry, part.stop) == (full.side, full.entry, full.stop)
    assert found > 0


def test_intrabar_entry_bar_can_stop_but_not_target():
    d = one(day({"10:00": 100.0}))
    sig = fam.Signal("ema", 1, 60, entry=100.0, stop=99.98, k=10, intrabar=True)  # bar low 99.95 <= stop
    tr = fam.simulate(d, sig)
    assert tr["reason"] == "stop" and tr["exit"] == pytest.approx(99.98)


def test_time_exit_at_1515_open():
    d = one(day({"10:00": 100.0}))
    tr = fam.simulate(d, fam.Signal("orb", 1, 60, 100.0, 99.0, 9))
    assert tr["reason"] == "time" and tr["exit_min"] == fam.EXIT_MIN


def test_charges_and_sizing_respect_300():
    buy = run.leg_charges(15_000, True)
    brok = 15.0
    assert buy == pytest.approx(brok + 15_000 * (0.0000297 + 0.000001 + 0.00003) + 0.18 * (brok + 15_000 * 0.0000307))
    q = run.size(500.0, 497.5, 1, 0.0002, None)
    rps = 2.5 + 0.0002 * 997.5
    assert q > 0 and q * rps + run.round_trip(q, 500.0, 497.5, 1) <= 300
    assert (q + 1) * rps + run.round_trip(q + 1, 500.0, 497.5, 1) > 300
    assert run.size(500.0, 497.5, 1, 0.0002, 15_000) <= 29


def test_one_trade_per_day_takes_earliest_then_rvol():
    t = pd.DataFrame({"date": ["2019-01-02"] * 3, "entry_min": [600, 590, 590], "rvol": [5.0, 1.0, 2.0],
                      "liq": [1, 1, 1], "inst": ["A", "B", "C"]})
    assert run.select_one_per_day(t)["inst"].tolist() == ["C"]
