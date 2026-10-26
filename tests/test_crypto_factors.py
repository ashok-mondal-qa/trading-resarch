import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import run_crypto_factors as rcf
from trading_research.backtesting import run_factors as rf
from trading_research.strategies import factors as fa

SMALL = fa.Params(universe_size=3, holdings=2, min_history=20, liquidity_window=5, vol_window=20, mom_long=30,
                  mom_skip=5, min_median_value=1e6, value_on_t=True)


def bars(start, n, drift, vol, quote, seed):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    return pd.DataFrame({"date": pd.date_range(start, periods=n, freq="D"), "open": np.r_[100, close[:-1]],
                         "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e4,
                         "quote_volume": quote})


def test_floor_and_value_on_t_drop_thin_and_delisting_coins():
    idx = pd.date_range("2021-01-01", periods=60, freq="D")
    close = pd.DataFrame(100.0, index=idx, columns=["A", "B", "THIN", "GONE"])
    value = pd.DataFrame({"A": 5e6, "B": 4e6, "THIN": 5e5, "GONE": 3e6}, index=idx)
    t = idx[40]
    value.loc[idx[38]:, "GONE"] = np.nan                                  # delisting announced
    assert list(fa.universe(close, value, t, SMALL)) == ["A", "B"]
    nse_like = fa.Params(universe_size=3, min_history=20, liquidity_window=5)
    assert "GONE" in fa.universe(close, value, t, nse_like)              # defaults keep the NSE rule unchanged
    assert fa.Params().min_median_value == 0 and not fa.Params().value_on_t


def test_load_splits_pieces_blanks_delisting_and_skips_bkrw(tmp_path):
    d = tmp_path / "processed" / "binance_spot_1d"
    d.mkdir(parents=True)
    bars("2020-01-01", 400, 0.001, 0.02, 2e7, 0).to_parquet(d / "BTCUSDT.parquet")
    bars("2020-01-01", 300, 0.0, 0.03, 1e7, 1).to_parquet(d / "OLDUSDT.parquet")      # delisted after 300 days
    bars("2020-01-01", 400, 0.0, 0.001, 1e7, 2).to_parquet(d / "BKRWUSDT.parquet")
    close, open_, value, btc = rcf.load(tmp_path, end=pd.Timestamp("2021-02-03").date())
    assert "BKRWUSDT" not in close.columns and list(btc.columns) == ["open", "close"]
    old = value["OLDUSDT"].dropna()
    assert close["OLDUSDT"].notna().sum() == 300 and len(old) == 300 - 7
    assert close.index.equals(pd.date_range("2020-01-01", "2021-02-03", freq="D"))


def test_verdict_against_btc():
    good = {"sharpe_monthly": 1.2, "btc_sharpe_monthly": 0.9, "max_drawdown": -0.5, "btc_max_drawdown": -0.45,
            "strategy_after_tax": {"cagr": 0.5}, "btc_after_tax": {"cagr": 0.3},
            f"sharpe_diff_ci_{1 - rcf.ALPHA:.4f}": (0.1, 0.9)}
    res = {"1x": {s: good for s in rcf.SPLITS}, "2x": {s: good for s in rcf.SPLITS}}
    assert rcf.verdict(res)["status"] == "HOLDOUT CANDIDATE"
    res["2x"]["validation"] = {**good, "max_drawdown": -0.6}
    assert rcf.verdict(res)["status"] == "REJECTED"


def test_simulate_holds_at_most_ten_and_btc_benchmark_costs():
    close = pd.DataFrame({f"C{i}": 100 * np.exp(np.cumsum(np.random.default_rng(i).normal(0, 0.01 * (i + 1), 120)))
                          for i in range(4)}, index=pd.date_range("2021-01-01", periods=120, freq="D"))
    open_, value = close.shift(1).fillna(close.iloc[0]), pd.DataFrame(5e6, index=close.index, columns=close.columns)
    eq, lots = rf.simulate("lowvol", close, open_, value, "2021-03-01", "2021-04-30", rcf.COSTS, 1.0, SMALL)
    assert set(lots["symbol"]) <= {"C0", "C1"} and (eq > 0).all()
    btc = pd.DataFrame({"open": open_["C0"], "close": close["C0"]})
    beq, _ = rf.nifty_curve(btc, "2021-03-01", "2021-04-30", rcf.COSTS)
    side = 0.10 * 1.18 / 100 + rf.SLIPPAGE_PCT / 100
    first = pd.Timestamp("2021-03-01")
    expect = rf.START_EQUITY / (1 + side) / open_.at[first, "C0"] * close.at[first, "C0"]
    assert beq.iloc[0] == pytest.approx(expect)


def test_crypto_holdout_sealed():
    assert rcf.DATA_END.isoformat() < rcf.HOLDOUT[0]
    assert all(end < rcf.HOLDOUT[0] for _, end in rcf.SPLITS.values())
