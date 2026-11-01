"""Synthetic checks for the multibagger base-rate study (EXP-0052): split adjustment via NSE prev_close,
rename chaining, and the summary maths. No real market data."""
import pandas as pd

from trading_research.backtesting import multibagger_base_rates as mb


def _day(d, rows):
    return pd.DataFrame([{"date": pd.Timestamp(d), "symbol": s, "series": "EQ", "isin": "INE000000000",
                          "close": c, "prev_close": p, "volume": 1, "traded_value": 1e7, "high": c, "low": c}
                         for s, c, p in rows])


def test_split_is_adjusted_and_rename_is_chained(tmp_path):
    # AAA trades 100 -> 110, then a 1:10 split (NSE restates prev_close to 11), then renames to BBB.
    _day("2020-01-01", [("AAA", 100.0, 100.0)]).to_parquet(tmp_path / "1.parquet")
    _day("2020-01-02", [("AAA", 110.0, 100.0)]).to_parquet(tmp_path / "2.parquet")
    _day("2020-01-03", [("AAA", 12.1, 11.0)]).to_parquet(tmp_path / "3.parquet")
    _day("2020-01-06", [("BBB", 13.31, 12.1)]).to_parquet(tmp_path / "4.parquet")
    changes = pd.DataFrame({"old_symbol": ["AAA"], "new_symbol": ["BBB"],
                            "effective_date": [pd.Timestamp("2020-01-06")]})
    panel = mb.build_panel(tmp_path, changes)
    assert set(panel["symbol"]) == {"BBB"}
    growth = (panel["cum"].iloc[-1] - panel["cum"].iloc[0])
    assert abs(pd.Series([growth]).apply(lambda x: __import__("math").exp(x)).iloc[0] - 1.331) < 1e-9
    assert not panel["suspect"].any()


def test_unadjusted_jump_is_flagged(tmp_path):
    _day("2020-01-01", [("CCC", 10.0, 10.0)]).to_parquet(tmp_path / "1.parquet")
    _day("2020-01-02", [("CCC", 50.0, 10.0)]).to_parquet(tmp_path / "2.parquet")
    panel = mb.build_panel(tmp_path, pd.DataFrame(columns=["old_symbol", "new_symbol", "effective_date"]))
    assert panel["suspect"].any()


def test_summarise_counts():
    rows = pd.DataFrame({"ratio": [12.0, 6.0, 1.0, 0.4], "peak": [12.0, 11.0, 1.0, 1.0],
                         "gone": [False, False, False, True]})
    s = mb.summarise(rows)
    assert s["n"] == 4 and s["pct_10x"] == 25.0 and s["pct_5x"] == 50.0 and s["pct_peak_10x"] == 50.0
    assert s["pct_lost_half"] == 25.0 and s["pct_gone"] == 25.0
