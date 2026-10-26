import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_intraday as ri
from trading_research.data import binance_intraday as bi
from trading_research.strategies import intraday as it

NO_COST = it.Params(fee_pct=0.0, slip_bps=0.0, min_stop_pct=0.0)


def bars5(closes, start="2020-01-01 00:00", spread=0.5):
    idx = pd.date_range(start, periods=len(closes), freq="5min")
    c = pd.Series(closes, index=idx, dtype=float)
    o = c.shift(1).fillna(c.iloc[0])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + spread, "low": np.minimum(o, c) - spread, "close": c,
                         "volume": 1.0, "quote_volume": 1.0})


def kline_zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("X-5m.csv", "\n".join(",".join(str(v) for v in r) for r in rows))
    return buf.getvalue()


def test_parse_reads_ms_and_us_and_lists_gaps():
    ms = 1577836800000                                                  # 2020-01-01 00:00 UTC
    rows = [[ms, 1, 2, 0.5, 1.5, 10, ms + 299999, 15, 3, 0, 0, 0],
            [(ms + 300000) * 1000, 1.5, 2, 1, 1.2, 10, 0, 12, 3, 0, 0, 0],          # microseconds
            [ms + 1200000, 1.2, 1.3, 1.1, 1.25, 10, 0, 12, 3, 0, 0, 0]]             # 2 bars missing before it
    df = bi.parse_klines(kline_zip(rows))
    assert list(df["time"]) == [pd.Timestamp("2020-01-01 00:00"), pd.Timestamp("2020-01-01 00:05"),
                                pd.Timestamp("2020-01-01 00:20")]
    assert bi.gaps(df["time"]) == [{"after": "2020-01-01 00:05:00", "before": "2020-01-01 00:20:00", "missing_bars": 2}]
    kept, excluded = bi.validate(df)
    assert len(kept) == 3 and not excluded


def test_resample_keeps_only_complete_groups():
    b = bars5(range(24))
    b = b.drop(b.index[14])                                             # 15m group 12..14 incomplete
    r = bi.resample(b, "15min")
    assert len(r) == 7 and pd.Timestamp("2020-01-01 01:00") not in r.index
    first = r.iloc[0]
    assert first["open"] == b["open"].iloc[0] and first["close"] == b["close"].iloc[2]
    assert first["high"] == b["high"].iloc[:3].max()


def test_simulate_fills_next_open_and_stops_at_min_open_stop():
    closes = [100] * 5 + [101, 102, 103, 90, 89]
    b = bars5(closes, spread=0.1)
    sig = pd.DataFrame({"entry": False, "stop": 95.0, "exit": False, "close": b["close"]}, index=b.index)
    sig.iloc[4, 0] = True
    t = it.simulate("ema_cross", b, sig, "5min", it.Params(fee_pct=0.1, gst_pct=0, slip_bps=0, min_stop_pct=0))
    row = t.iloc[0]
    assert row["entry_time"] == b.index[5] and row["entry"] == pytest.approx(100.0)   # open of bar 5
    assert row["reason"] == "stop" and row["exit"] == pytest.approx(95.0)              # bar 8 opens 103, low 89.9
    assert row["r_multiple"] == pytest.approx((95 - 100 - 0.001 * 195) / 5)
    gap = b.copy()
    gap.iloc[8, gap.columns.get_loc("open")] = 92.0                                       # gaps through the stop
    gap.iloc[8, gap.columns.get_loc("high")] = 92.1
    assert it.simulate("ema_cross", gap, sig, "5min", NO_COST).iloc[0]["exit"] == pytest.approx(92.0)


def test_exit_signal_fills_at_next_open_and_minimum_stop_skips():
    b = bars5([100.0] * 12, spread=0.1)
    sig = pd.DataFrame({"entry": False, "stop": 99.0, "exit": False, "close": b["close"]}, index=b.index)
    sig.iloc[2, 0] = True
    sig.iloc[6, 2] = True
    t = it.simulate("ema_cross", b, sig, "5min", NO_COST).iloc[0]
    assert t["exit_time"] == b.index[7] and t["reason"] == "signal"
    assert it.simulate("ema_cross", b, sig, "5min", it.Params(min_stop_pct=1.5)).empty


def test_orb_range_entry_and_day_end():
    closes = [100.0] * 12 + [100.0] * 6 + [102.0] + [103.0] * 269 + [104.0]   # 00:00..23:55, then 00:00 next day
    b = bars5(closes, spread=0.2)
    sig = it.signals("orb", b, b, NO_COST)
    assert sig["entry"].sum() == 1 and sig.index[sig["entry"]][0] == pd.Timestamp("2020-01-01 01:30")
    assert sig.loc["2020-01-01 01:30", "stop"] == pytest.approx(99.8)
    t = it.simulate("orb", b, sig, "5min", NO_COST).iloc[0]
    assert t["entry_time"] == pd.Timestamp("2020-01-01 01:35") and t["exit_time"] == pd.Timestamp("2020-01-02 00:00")
    assert t["reason"] == "day end" and t["exit"] == pytest.approx(103.0)


@pytest.mark.parametrize("strategy", ["ema_cross", "bb_rsi", "supertrend"])
def test_signals_use_only_past_bars(strategy):
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 3000)))
    b = bi.resample(bars5(closes), "15min")
    full = it.signals(strategy, b, b)
    cut = it.signals(strategy, b.iloc[:700], b.iloc[:700])
    pd.testing.assert_frame_equal(full.iloc[:700], cut)


def test_after_tax_only_cuts_gains():
    b = bars5([100.0] * 4 + [110.0] * 4, spread=0.1)
    sig = pd.DataFrame({"entry": False, "stop": 95.0, "exit": False, "close": b["close"]}, index=b.index)
    sig.iloc[1, 0] = True
    sig.iloc[5, 2] = True
    t = it.simulate("ema_cross", b, sig, "5min", NO_COST).iloc[0]
    assert t["r_after_tax"] == pytest.approx(t["r_multiple"] * (1 - 0.312))


def test_verdict_and_sealed_holdout():
    good = {"trades": 200, "expectancy_r": 0.2, "expectancy_r_after_tax": 0.1, "profit_factor": 1.5,
            f"ci_{1 - ri.ALPHA:.4f}": (0.05, 0.3)}
    res = {"1x": {s: good for s in ri.SPLITS}, "2x": {s: good for s in ri.SPLITS}}
    assert ri.verdict(res)["status"] == "HOLDOUT CANDIDATE"
    res["1x"]["dev"] = {**good, "expectancy_r_after_tax": -0.01}
    assert ri.verdict(res)["status"] == "REJECTED"
    assert ri.DATA_END <= ri.HOLDOUT[0]


def test_scalp_target_stop_first_and_daily_cap():
    b = bars5([100.0] * 30, spread=0.1)
    sig = pd.DataFrame({"entry": False, "stop": 99.0, "exit": False, "close": b["close"]}, index=b.index)
    sig.iloc[2, 0] = True
    up = b.copy()
    up.iloc[6, up.columns.get_loc("high")] = 102.5                          # reaches 100 + 2 x 1
    t = it.simulate("ema_scalp", up, sig, "5min", NO_COST).iloc[0]
    assert t["reason"] == "target" and t["exit"] == pytest.approx(102.0) and t["r_multiple"] == pytest.approx(2.0)
    both = up.copy()
    both.iloc[6, both.columns.get_loc("low")] = 98.5                        # stop and target in one bar
    assert it.simulate("ema_scalp", both, sig, "5min", NO_COST).iloc[0]["reason"] == "stop"
    many = pd.DataFrame({"entry": True, "stop": 99.0, "exit": False, "close": b["close"]}, index=b.index)
    quick = up.copy()
    quick["low"] = 98.0                                                      # every trade stops on its entry bar
    trades = it.simulate("ema_scalp", quick, many, "5min", NO_COST)
    assert len(trades) == 5 and (trades["reason"] == "stop").all()


def test_scalp_minimum_stop_variant_skips_tight_stops():
    b = bars5([100.0] * 300, spread=0.1)                                 # runs past the next 00:00 UTC
    sig = pd.DataFrame({"entry": False, "stop": 99.8, "exit": False, "close": b["close"]}, index=b.index)
    sig.iloc[2, 0] = True
    assert len(it.simulate("ema_scalp", b, sig, "5min", it.Params(slip_bps=0))) == 1
    assert it.simulate("ema_scalp_minstop", b, sig, "5min", it.Params(slip_bps=0)).empty


def test_scalp_signal_needs_rising_slow_ema():
    v_turn = list(np.linspace(110, 100, 40)) + [100.5, 101.5, 102.5, 103.5]
    assert it.signals("ema_scalp", bars5(v_turn), None)["entry"].sum() == 0     # EMA15 still falling at the cross
    trend = list(np.linspace(100, 130, 60)) + list(np.linspace(128, 120, 5)) + list(np.linspace(121, 140, 15))
    b = bars5(trend)
    sig = it.signals("ema_scalp", b, None)
    assert sig["entry"].sum() == 1
    t = sig.index[sig["entry"]][0]
    assert sig.loc[t, "stop"] == pytest.approx(b.loc[t, "low"])
