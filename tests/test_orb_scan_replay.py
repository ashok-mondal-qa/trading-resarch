import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_orb_scan_replay as r


def day_bars(path):
    """1-minute bars 09:15..15:29 from a list of (minute_of_day, open, high, low, close); flat fill between."""
    mins = list(range(r.OPEN_MIN, 15 * 60 + 30))
    pts = dict((m, (o, h, lo, c)) for m, o, h, lo, c in path)
    rows, last = [], path[0][1]
    for m in mins:
        o, h, lo, c = pts.get(m, (last, last, last, last))
        rows.append({"minute": m, "open": o, "high": h, "low": lo, "close": c, "volume": 100000.0})
        last = c
    return pd.DataFrame(rows)


def hist(prev_close=100.0, prev_high=101.0, rng=4.0):
    out = []
    for i in range(20):
        out.append({"date": f"2019-01-{i + 1:02d}", "open": prev_close, "high": prev_close + rng / 2,
                    "low": prev_close - rng / 2, "close": prev_close})
    out[-1]["high"] = prev_high
    return out


def opening(extra):
    # 09:15 open 101.5, range 101.0..102.4, last 102.3 at 09:34: +2.3%, above prev high 101, near the high
    base = [(r.OPEN_MIN, 101.5, 101.6, 101.0, 101.5), (9 * 60 + 25, 102.0, 102.4, 101.9, 102.3),
            (9 * 60 + 34, 102.3, 102.35, 102.25, 102.3)]
    return base + extra


TODAY = {"date": pd.Timestamp("2019-01-21"), "prev_close": 100.0}


def test_factor_needs_both_extremes_to_agree():
    assert r.factor(100, 90, 200, 180) == pytest.approx(2.0)
    assert r.factor(100, 90, 200, 181) is None


def test_name_on_uses_old_ticker_before_the_change():
    links = [{"old_symbol": "OLD", "new_symbol": "NEW", "effective_date": pd.Timestamp("2019-06-01")}]
    assert r.name_on(pd.Timestamp("2019-01-02"), "NEW", links) == "OLD"
    assert r.name_on(pd.Timestamp("2019-06-01"), "NEW", links) == "NEW"


def test_replay_day_trades_the_live_rule_and_exits_each_target():
    # entry 102.4 * 1.0005 = 102.451 -> 102.50 (rounded up to the tick); stop 100.95; risk 1.55; 2R 105.60, 3R 107.15
    path = opening([(600, 102.3, 102.6, 102.2, 102.5), (700, 102.5, 105.7, 102.5, 105.4),
                    (800, 105.4, 106.0, 105.0, 105.8)])
    row = r.replay_day(day_bars(path), 1.0, "AAA", TODAY, hist())
    assert row["entry"] == 102.5 and row["stop"] == 100.95 and row["outcome"] == "triggered"
    assert row["1R_reason"] == "target" and row["2R_reason"] == "target" and row["2R_exit"] == 105.6
    assert row["3R_reason"] == "time" and row["no target_reason"] == "time"
    assert row["3R_exit"] == pytest.approx(105.8)


def test_stop_before_entry_cancels_the_idea():
    path = opening([(600, 102.0, 102.1, 100.9, 101.0), (700, 101.0, 103.0, 101.0, 103.0)])
    assert r.replay_day(day_bars(path), 1.0, "AAA", TODAY, hist())["outcome"] == "invalidated before entry"


def test_bar_touching_entry_and_stop_counts_as_a_loss():
    path = opening([(600, 102.3, 102.6, 100.9, 101.0)])
    row = r.replay_day(day_bars(path), 1.0, "AAA", TODAY, hist())
    assert row["outcome"] == "triggered" and row["2R_reason"] == "stop" and row["2R_exit"] == 100.95


def test_screen_rejects_a_stock_not_above_previous_high():
    path = opening([(700, 102.5, 106.0, 102.5, 106.0)])
    assert r.replay_day(day_bars(path), 1.0, "AAA", TODAY, hist(prev_high=103.0)) is None


def test_factor_scales_prices_to_real_rupees():
    path = opening([(700, 102.5, 106.0, 102.5, 106.0)])
    t = {"date": TODAY["date"], "prev_close": 200.0}
    h2 = [{k: (v * 2 if k != "date" else v) for k, v in b.items()} for b in hist()]
    row = r.replay_day(day_bars(path), 2.0, "AAA", t, h2)
    assert row["entry"] == pytest.approx(204.95) and row["stop"] == pytest.approx(201.95)


def test_pick_and_stats():
    base = {"risk": 1.5, "fill": 102.45, "charges_ok": True, "outcome": "triggered"}
    rows = []
    for d, v, ex in (("2019-01-21", 50, 105.45), ("2019-01-21", 80, 100.95), ("2019-01-22", 30, 105.45)):
        row = dict(base, date=d, value_cr=v, qty=100, symbol=f"S{v}")
        for t in r.TARGETS:
            row[f"{r.tkey(t)}_exit"] = ex
            row[f"{r.tkey(t)}_reason"] = "target" if ex > 102.45 else "stop"
        rows.append(row)
    picks = r.pick_one_per_day(pd.DataFrame(rows))
    assert list(picks["value_cr"]) == [80, 30]          # most traded per day
    st = r.stats(picks, 2.0, ci=True)
    assert st["trades"] == 2 and st["mean_gross_inr"] == pytest.approx((300 - 150) / 2)
    assert st["mean_net_inr"] < st["mean_gross_inr"] and st["mean_net_inr_2x"] < st["mean_net_inr"]
    assert st["longest_losing_streak"] == 1 and len(st["ci95_mean_net_inr"]) == 2
    assert np.isfinite(st["max_drawdown_inr"])
