"""Tests for the 30-minute NIFTY ORB grid (spec nifty-orb30.md v0.1)."""

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_orb30 as run
from trading_research.strategies import orb30 as orb


def session(path: dict[int, float], base: float = 100.0, day: str = "2024-03-05", vol: bool = False) -> pd.DataFrame:
    """1-min bars 09:15..15:29; close follows `path` (minute -> close, forward-filled), +-0.01 high/low."""
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min")
    mins = idx.hour * 60 + idx.minute
    c = pd.Series([np.nan] * len(idx), index=mins, dtype=float)
    for m, v in path.items():
        c.loc[m] = v
    c.iloc[0] = c.iloc[0] if c.iloc[0] == c.iloc[0] else base
    c = c.ffill().to_numpy()
    o = np.concatenate([[c[0]], c[:-1]])
    df = pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.01, "low": np.minimum(o, c) - 0.01, "close": c},
                      index=idx)
    if vol:
        df["volume"] = 100.0
    return df


CTX = pd.Series({"atr14": 2.0, "adx14": 30.0})


def test_opening_range_uses_first_30_minutes_only():
    d = orb.build_day(session({555: 100, 570: 100.5, 584: 99.6, 585: 100, 600: 100}), CTX)
    assert d.or_hi == pytest.approx(100.51) and d.or_lo == pytest.approx(99.59)
    assert d.side == 0  # never closed outside


def test_first_breakout_long_enters_next_minute_open():
    d = orb.build_day(session({555: 100, 570: 100.5, 584: 100, 597: 100.8, 620: 101.2}), CTX)
    assert d.side == 1 and d.sig_end == 600          # 5-min bar 09:55-09:59 closes 100.8 > OR high
    assert d.m[d.i] == 600 and d.sig_close == pytest.approx(100.8)


def test_signal_ignores_bars_after_signal_close():
    a = session({555: 100, 570: 100.5, 584: 100, 597: 100.8, 620: 101.2})
    b = a.copy()
    b.loc[b.index[46]:, ["open", "high", "low", "close"]] = 50.0  # rewrite everything from 10:01
    da, db = orb.build_day(a, CTX), orb.build_day(b, CTX)
    assert (da.side, da.sig_end, da.twap, da.or_hi) == (db.side, db.sig_end, db.twap, db.or_hi)


def test_only_first_breakout_counts_even_if_filtered():
    # first breakout short at 09:50, later long: long-only config must have no trade
    d = orb.build_day(session({555: 100, 570: 100.5, 584: 100, 587: 99.0, 600: 101.5}), CTX)
    assert d.side == -1
    assert orb.trade(d, "V0", "range", 2.0, "long") is None
    assert orb.trade(d, "V0", "range", 2.0, "short") is not None


def test_range_stop_target_and_time_exit():
    d = orb.build_day(session({555: 100, 570: 100.5, 584: 100, 597: 100.8, 700: 103.0}), CTX)
    t = orb.trade(d, "V0", "range", 2.0)
    entry = d.o[d.i]
    assert t["stop"] == pytest.approx(d.or_lo)
    assert t["target"] == pytest.approx(entry + 2 * (entry - d.or_lo))
    assert t["reason"] == "target" and t["gross_r"] == pytest.approx(2.0)
    flat = orb.build_day(session({555: 100, 570: 100.5, 584: 100, 597: 100.8}), CTX)
    assert orb.trade(flat, "V0", "range", 3.0)["reason"] == "time"


def test_stop_checked_before_target_and_gap_fills_at_open():
    df = session({555: 100, 570: 100.5, 584: 100, 597: 100.8})
    j = df.index.get_loc(pd.Timestamp("2024-03-05 10:30"))
    df.iloc[j, :] = [100.8, 110.0, 90.0, 100.0]  # one bar spans stop and target
    t = orb.trade(orb.build_day(df, CTX), "V0", "range", 2.0)
    assert t["reason"] == "stop" and t["exit"] == pytest.approx(t["stop"])
    df2 = session({555: 100, 570: 100.5, 584: 100, 597: 100.8})
    df2.iloc[j:, :] = 98.0  # opens below the stop
    t2 = orb.trade(orb.build_day(df2, CTX), "V0", "range", 2.0)
    assert t2["exit"] == pytest.approx(98.0) and t2["gross_r"] < -1


def test_atr_stop_and_width_check():
    d = orb.build_day(session({555: 100, 570: 100.5, 584: 100, 597: 100.8}), CTX)
    t = orb.trade(d, "V0", "atr", 2.0)
    assert t["entry"] - t["stop"] == pytest.approx(0.5 * 2.0)
    wide = orb.build_day(session({555: 100, 570: 100.5, 584: 100, 597: 100.8}), pd.Series({"atr14": 10.0,
                                                                                            "adx14": 1.0}))
    assert orb.trade(wide, "V0", "atr", 2.0) is None  # 5 points = 5% > 2% max


def test_variant_filters():
    d = orb.build_day(session({555: 100, 570: 100.5, 584: 100, 597: 100.8}), CTX)
    assert d.or_width_atr == pytest.approx((d.or_hi - d.or_lo) / 2.0)
    assert orb.passes(d, "V2", "both")          # breakout close above TWAP
    d.twap = 101.0
    assert not orb.passes(d, "V2", "both")
    d.atr14 = 10.0                              # OR width / ATR ~ 0.1 < 0.25
    assert not orb.passes(d, "V4", "both")
    assert not orb.passes(d, "V1", "both")      # no volume -> no rvol


def test_volume_rvol_and_vwap():
    df = session({555: 100, 570: 100.5, 584: 100, 597: 100.8}, vol=True)
    base = pd.Series({600: 250.0})
    d = orb.build_day(df, CTX, base)
    assert d.rvol == pytest.approx(500 / 250)
    assert d.vwap == pytest.approx(d.twap)  # equal volume -> VWAP equals TWAP
    assert orb.passes(d, "V1", "both") and orb.passes(d, "V3", "both")


def test_daily_context_uses_previous_sessions_only():
    idx = pd.bdate_range("2024-01-01", periods=60)
    rng = np.random.default_rng(1)
    c = 100 + rng.normal(0, 1, 60).cumsum()
    off = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c}, index=idx)
    ctx = orb.daily_context(off)
    changed = off.copy()
    changed.iloc[-1] = [500, 600, 400, 500]
    assert ctx["atr14"].iloc[-1] == pytest.approx(orb.daily_context(changed)["atr14"].iloc[-1])
    a = orb.adx(off)
    assert a.dropna().between(0, 100).all() and a.notna().sum() > 20


def test_grid_and_walk_forward_windows():
    assert len(orb.configs()) == 72 and len(orb.configs(eligible_only=True)) == 36
    w = run.wf_windows()
    assert len(w) == 10 and w[0] == ("2020-01-01", "2021-12-31", "2022-01-01", "2022-06-30")
    assert w[-1][2:] == ("2026-07-01", "2026-10-30")
    for tr_a, tr_b, te_a, te_b in w:
        assert tr_b < te_a  # training always ends before testing starts


def test_money_adds_feasibility_columns():
    d = orb.build_day(session({555: 25000, 570: 25100, 584: 25000, 597: 25150, 700: 25600}, base=25000), CTX)
    t = run.run_cfg([d], ("V0", "range", 2.0, "both"))
    m = run.money(t)
    assert m["fut_lot_risk_now"].iloc[0] == pytest.approx(m["stop_pts"].iloc[0] * 65)
    assert m["planned_risk"].iloc[0] <= 300 + 1e-9 and m["qty"].iloc[0] > 0
