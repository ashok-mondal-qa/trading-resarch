"""Index loader tests. Rows are SYNTHETIC fixtures, not NSE values."""

from datetime import date

import pytest

from trading_research.data import bhavcopy, indices

HEADER = ("Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
          "Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield")


def csv(rows):
    return ("\n".join([HEADER] + rows) + "\n").encode()


DAY = date(2026, 10, 22)
GOOD = csv(["Test Index A,22-10-2026,100,110,95,105,5,5.0,1000,10.5,20,3,1.2",
            "Test VIX,22-10-2026,15,16,14,15.5,0.5,3.3,-,-,-,-,-"])


def test_load_parse_and_read(tmp_path):
    manifest = indices.load_day(DAY, tmp_path, fetch=lambda url: GOOD)
    assert manifest["status"] == "ok" and manifest["rows"] == 2 and manifest["raw_sha256"]
    a = indices.read_index("test index a", DAY, DAY, tmp_path)
    assert a.loc["2026-10-22", "close"] == 105
    vix = indices.read_index("Test VIX", DAY, DAY, tmp_path)
    assert vix["volume"].isna().all()  # "-" stays missing, never zero


def test_missing_file_not_filled(tmp_path):
    assert indices.load_day(DAY, tmp_path, fetch=lambda url: None)["status"] == "not_found"
    assert indices.read_index("Test Index A", DAY, DAY, tmp_path).empty


def test_wrong_date_fails_closed(tmp_path):
    bad = csv(["Test Index A,21-10-2026,100,110,95,105,5,5.0,1000,10.5,20,3,1.2"])
    with pytest.raises(bhavcopy.BhavcopyError):
        indices.load_day(DAY, tmp_path, fetch=lambda url: bad)


def test_month_first_dates_accepted_only_when_they_match_the_file_date(tmp_path):
    swapped = csv(["Test Index A,10-22-2026,100,110,95,105,5,5.0,1000,10.5,20,3,1.2"])
    manifest = indices.load_day(DAY, tmp_path, fetch=lambda url: swapped)
    assert manifest["status"] == "ok" and manifest["date_format_note"]
    other = csv(["Test Index A,10-21-2026,100,110,95,105,5,5.0,1000,10.5,20,3,1.2"])
    with pytest.raises(bhavcopy.BhavcopyError):
        indices.load_day(DAY, tmp_path / "x", fetch=lambda url: other)


def test_slash_dates_accepted_only_when_they_match_the_file_date(tmp_path):
    slashed = csv(["Test Index A,22/10/2026,100,110,95,105,5,5.0,1000,10.5,20,3,1.2"])
    manifest = indices.load_day(DAY, tmp_path, fetch=lambda url: slashed)
    assert manifest["status"] == "ok" and "%d/%m/%Y" in manifest["date_format_note"]
    other = csv(["Test Index A,21/10/2026,100,110,95,105,5,5.0,1000,10.5,20,3,1.2"])
    with pytest.raises(bhavcopy.BhavcopyError):
        indices.load_day(DAY, tmp_path / "x", fetch=lambda url: other)


def test_nifty_50_read_under_its_former_names(tmp_path):
    days = [date(2013, 2, 7), date(2015, 11, 6), date(2015, 11, 9)]
    files = [csv(["S&P CNX Nifty,07-02-2013,90,95,88,92,1,1.0,1000,10.5,20,3,1.2"]),
             csv(["CNX Nifty,06-11-2015,100,110,95,105,5,5.0,1000,10.5,20,3,1.2"]),
             csv(["Nifty 50,09-11-2015,105,112,100,108,3,2.9,1000,10.5,20,3,1.2"])]
    for day, raw in zip(days, files):
        indices.load_day(day, tmp_path, fetch=lambda url, raw=raw: raw)
    nifty = indices.read_index("Nifty 50", days[0], days[-1], tmp_path)
    assert nifty["close"].tolist() == [92, 105, 108]


def test_duplicated_index_name_excluded_not_picked(tmp_path):
    dup = csv(["Test Index A,22-10-2026,100,110,95,105,5,5.0,1000,10.5,20,3,1.2",
               "Test Index A,22-10-2026,101,111,96,106,5,5.0,1000,10.5,20,3,1.2",
               "Test Index B,22-10-2026,50,55,45,52,2,4.0,1000,10.5,20,3,1.2"])
    manifest = indices.load_day(DAY, tmp_path, fetch=lambda url: dup)
    assert manifest["status"] == "ok" and manifest["excluded_duplicate_names"] == ["Test Index A"]
    assert indices.read_index("Test Index A", DAY, DAY, tmp_path).empty
    assert indices.read_index("Test Index B", DAY, DAY, tmp_path)["close"].tolist() == [52]
