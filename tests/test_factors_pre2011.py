"""Pre-2011 replication runner and the loader's opt-in for ISIN-less legacy files.
All rows are SYNTHETIC fixtures (fake symbols), not NSE data."""

import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from trading_research.backtesting import run_factors_pre2011 as pre
from trading_research.data import bhavcopy as bc

OLD_HEADER = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,"


def old_zip(day="03-JAN-2006"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cm03JAN2006bhav.csv", "\n".join([OLD_HEADER, f"TESTA,EQ,10,11,9,10.5,10.5,10,100,1050,{day},"]) + "\n")
    return buf.getvalue()


def test_isin_less_files_fail_closed_unless_opted_in():
    with pytest.raises(bc.BhavcopyError):
        bc.parse_bhavcopy(old_zip(), "legacy")
    df = bc.parse_bhavcopy(old_zip(), "legacy", ("ISIN", "TOTALTRADES"))
    assert df.loc[0, "isin"] == "" and pd.isna(df.loc[0, "trades"]) and df.loc[0, "close"] == 10.5


def test_load_day_opt_in_and_cli_guard(tmp_path):
    store = bc.Store(root=tmp_path / "pre2011")
    m = bc.load_day(date(2006, 1, 3), store, fetch=lambda url: old_zip(), optional=("ISIN", "TOTALTRADES"))
    assert m["status"] == "ok"
    with pytest.raises(SystemExit):
        bc.main(["--start", "2006-01-03", "--pre2011"])                          # no pre2011 root
    with pytest.raises(SystemExit):
        bc.main(["--start", "2011-07-01", "--root", str(tmp_path / "pre2011"), "--pre2011"])


def test_etf_symbols_by_name_and_isin(tmp_path):
    day = pre.FIRST_ISIN_DAY
    path = bc.Store(root=tmp_path).bars_path(day)
    path.parent.mkdir(parents=True)
    pd.DataFrame({"symbol": ["FUNDX", "TESTA"], "isin": ["INF000000001", "INE000000001"]}).to_parquet(path)
    got = pre.etf_symbols(["NIFTYBEES", "KOTAKGOLD", "M50", "FUNDX", "TESTA", "GOLDIAM"], tmp_path)
    assert got == {"NIFTYBEES", "KOTAKGOLD", "M50", "FUNDX", "GOLDIAM"}     # name rule is broad by design


def test_verdict_needs_every_check():
    good = {"sharpe_monthly": 0.9, "nifty_sharpe_monthly": 0.6, "max_drawdown": -0.55, "nifty_max_drawdown": -0.6,
            "strategy_after_tax": {"cagr": 0.2}, "nifty_after_tax": {"cagr": 0.1}}
    res = {"2x": {s: good for s in pre.SPLITS}}
    assert pre.verdict(res)["status"] == "REPLICATED"
    res["2x"]["first_half"] = {**good, "sharpe_monthly": 0.5}
    assert pre.verdict(res)["status"] == "NOT REPLICATED"


def test_window_is_before_the_main_data():
    assert pre.DATA_END < date(2011, 7, 1) and all(e <= "2011-06-30" for _, e in pre.SPLITS.values())
    assert pre.DATA_START == date(2005, 7, 1)
