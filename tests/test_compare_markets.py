"""Market-comparison helpers (tax models, timing curve). All series are SYNTHETIC fixtures."""

import numpy as np
import pandas as pd
import pytest

from trading_research.backtesting import compare_markets as cm


def trades(rows):
    return pd.DataFrame(rows, columns=["entry_date", "exit_date", "pnl"])


def test_crypto_tax_never_offsets_losses():
    t = trades([("2020-01-01", "2020-02-01", 1000.0), ("2020-01-05", "2020-02-01", -1000.0),
                ("2020-03-01", "2020-04-01", 500.0)])
    tax = cm.crypto_tax(t)
    assert tax.sum() == pytest.approx(1500 * 0.312)
    assert tax[pd.Timestamp("2020-02-01")] == pytest.approx(312.0)


def test_equity_tax_sets_off_and_carries_losses_by_financial_year():
    t = trades([("2020-05-01", "2020-06-01", 10_000.0), ("2020-07-01", "2020-08-01", -30_000.0),   # FY21: net -20k
                ("2021-05-01", "2021-06-01", 50_000.0),                                            # FY22: 50k - 20k carried
                ("2020-01-01", "2022-06-01", 200_000.0)])                                          # FY23: long term
    tax = cm.equity_tax(t, pd.Timestamp("2030-01-01"))
    assert pd.Timestamp("2021-03-31") not in tax.index
    assert tax[pd.Timestamp("2022-03-31")] == pytest.approx(30_000 * 0.208)
    assert tax[pd.Timestamp("2023-03-31")] == pytest.approx((200_000 - 125_000) * 0.13)


def test_short_term_loss_offsets_long_term_gain():
    t = trades([("2020-05-01", "2020-06-01", -100_000.0), ("2019-01-01", "2020-09-01", 300_000.0)])
    tax = cm.equity_tax(t, pd.Timestamp("2030-01-01"))
    assert tax.sum() == pytest.approx((200_000 - 125_000) * 0.13)


def test_tax_paid_after_the_window_end_is_charged_on_the_last_day():
    t = trades([("2024-05-01", "2024-06-01", 10_000.0)])
    tax = cm.equity_tax(t, pd.Timestamp("2024-12-31"))
    assert list(tax.index) == [pd.Timestamp("2024-12-31")]


def test_apply_taxes_scales_later_equity():
    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    eq = pd.Series([100.0, 110, 120, 130, 140], index=idx)
    after = cm.apply_taxes(eq, pd.Series({idx[2]: 12.0}))
    assert after.iloc[:2].tolist() == [100, 110] and after.iloc[2] == pytest.approx(108)
    assert after.iloc[4] == pytest.approx(140 * 0.9)


def test_timing_curve_waits_one_bar_and_pays_costs(monkeypatch):
    monkeypatch.setattr(cm, "WINDOW", ("2020-01-01", "2021-12-31"))
    idx = pd.date_range("2019-01-01", periods=900, freq="D")
    close = pd.Series(np.r_[np.linspace(100, 50, 450), np.linspace(50, 200, 450)], index=idx)
    eq, trips = cm.timing_curve(close, 0.001, 1.0, trend=True)
    sma = close.rolling(200).mean()
    first_up = close.index[(close > sma) & (close.index >= pd.Timestamp("2020-01-01"))][0]
    entry = trips["entry_date"].iloc[0]
    assert entry == close.index[close.index.get_loc(first_up) + 1]
    assert (eq.loc[:entry].iloc[:-1] == 1.0).all() and eq.loc[entry] == pytest.approx(0.999)
    bh, bh_trips = cm.timing_curve(close, 0.0, 1.0, trend=False)
    window = close[close.index >= pd.Timestamp("2020-01-01")]
    assert bh.iloc[-1] == pytest.approx(window.iloc[-1] / window.iloc[0])
    assert len(bh_trips) == 1 and bh_trips["pnl"].iloc[0] == pytest.approx(bh.iloc[-1] - 1)
