"""Crypto runner tests (segmenting, delisting, costs, verdict). All bars are SYNTHETIC fixtures."""

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_crypto as rc
from trading_research.backtesting.costs import leg_costs
from trading_research.backtesting.run_swing_ideas import ci_key


def daily(start, n, price=10.0):
    d = pd.date_range(start, periods=n, freq="D")
    c = price * (1 + 0.001 * np.arange(n))
    return pd.DataFrame({"date": d, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                         "volume": 1000.0, "quote_volume": 1e7, "trades": 10})


def test_segments_split_at_gaps_and_never_join_a_reused_ticker():
    old, new = daily("2020-01-01", 300), daily("2021-03-01", 250, price=0.5)
    tiny = daily("2022-01-01", 20)
    pieces = rc.segments(pd.concat([old, new, tiny]), "LUNAUSDT", pd.Timestamp("2023-01-01"))
    assert [(n, len(b), gone) for n, b, gone in pieces] == [
        ("LUNAUSDT", 300, True), ("LUNAUSDT~2021-03-01", 250, True)]
    assert (pieces[1][1]["traded_value"] == 1e7).all() and (pieces[1][1]["raw_close"] == pieces[1][1]["close"]).all()


def test_segments_respect_the_split_end():
    pieces = rc.segments(daily("2020-01-01", 400), "BTCUSDT", pd.Timestamp("2020-12-31"))
    (name, bars, gone), = pieces
    assert bars.index.max() == pd.Timestamp("2020-12-31") and not gone   # running to the end is not a delisting


def test_delisting_blocks_late_signals_and_exits_on_the_last_bar():
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    f = pd.DataFrame({"signal": True, "exit_signal": False}, index=idx)
    g = rc.apply_delisting(f)
    assert not g["signal"].iloc[-rc.DELIST_NO_SIGNAL_BARS:].any() and g["signal"].iloc[:-rc.DELIST_NO_SIGNAL_BARS].all()
    assert g["exit_signal"].tolist() == [False] * 28 + [True, False]


def test_crypto_costs_are_fee_plus_gst_only():
    c = leg_costs("buy", 100.0, 1000, rc.CRYPTO_COSTS)
    assert c.total == pytest.approx(100_000 * 0.00118)
    assert leg_costs("sell", 100.0, 1000, rc.CRYPTO_COSTS).total == pytest.approx(c.total)


def test_holdout_is_not_reachable():
    with pytest.raises(SystemExit):
        rc.run_split("holdout")
    assert all(end < rc.HOLDOUT[0] for _, end in rc.SPLITS.values())


def _report(pt=40, pe=0.2, ppf=1.3, st=400, ci=(0.05, 0.3), se2=0.1, se2_all=0.1):
    return {"runs": {"portfolio_2x_costs": {"trades": pt, "expectancy_r": pe, "profit_factor": ppf},
                     "standalone_1x": {"trades": st, ci_key(rc.ALPHA): ci},
                     "standalone_2x_costs": {"expectancy_r": se2, "expectancy_r_all_incl_open": se2_all}}}


def test_verdict_rules():
    good = {s: _report() for s in rc.SPLITS}
    assert rc.verdict(good)["passed"]
    assert not rc.verdict({**good, "dev": _report(ci=(-0.01, 0.3))})["passed"]
    assert not rc.verdict({**good, "validation": _report(se2_all=-0.01)})["passed"]   # open trades count
    assert not rc.verdict({**good, "dev_b": _report(se2=-0.01)})["passed"]
    assert not rc.verdict({"dev": _report()})["passed"]


def test_annual_stats_uses_365_days():
    eq = pd.Series(1.1 ** (np.arange(366) / 365), index=pd.date_range("2020-01-01", periods=366, freq="D"))
    s = rc.annual_stats(eq)
    assert s["cagr"] == pytest.approx(0.1, abs=1e-3) and s["max_drawdown"] == pytest.approx(0.0, abs=1e-12)
