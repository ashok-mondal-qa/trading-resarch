"""Binance archive loader tests. Every candle and listing here is a SYNTHETIC fixture, not market data."""

import hashlib
import io
import json
import zipfile

import pandas as pd
import pytest

from trading_research.data import binance

DAY_MS = 86_400_000
JAN_2024 = 1_704_067_200_000      # 2024-01-01 00:00 UTC, ms
JAN_2025 = 1_735_689_600_000      # 2025-01-01 00:00 UTC, ms


def kline_zip(start_ms, n, unit=1, name="X-1d.csv", header=False, bad_row=None):
    lines = ["open_time,open,high,low,close,volume,close_time,quote_volume,count,tbb,tbq,ignore"] if header else []
    for i in range(n):
        t = (start_ms + i * DAY_MS) * unit
        o, h, l, c = 10 + i, 12 + i, 9 + i, 11 + i
        if i == bad_row:
            h = c - 1                      # high below close: not a valid candle
        lines.append(f"{t},{o},{h},{l},{c},100,{t + DAY_MS * unit - 1},1000,5,50,500,0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, "\n".join(lines) + "\n")
    return buf.getvalue()


def test_parse_reads_milliseconds_microseconds_and_headers():
    ms = binance.parse_klines(kline_zip(JAN_2024, 3))
    us = binance.parse_klines(kline_zip(JAN_2025, 3, unit=1000, header=True))
    assert list(ms["date"]) == list(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    assert list(us["date"]) == list(pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]))
    assert us["close"].tolist() == [11, 12, 13]


def test_validate_excludes_bad_and_duplicate_rows_without_repair():
    df = binance.parse_klines(kline_zip(JAN_2024, 5, bad_row=2))
    df = pd.concat([df, df.iloc[[4]]], ignore_index=True)
    kept, excluded = binance.validate(df)
    assert len(kept) == 3 and {e["reason"] for e in excluded} == {"invalid candle", "duplicate date"}


@pytest.mark.parametrize("symbol,ok", [("BTCUSDT", True), ("USDCUSDT", False), ("BTCUPUSDT", False),
                                       ("ETHBTC", False), ("WBTCUSDT", False), ("EURUSDT", False)])
def test_research_pairs(symbol, ok):
    assert binance.is_research_pair(symbol) is ok


def listing(keys, truncated=False, next_marker=""):
    body = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in keys)
    return (f'<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated><NextMarker>{next_marker}</NextMarker>"
            f"{body}</ListBucketResult>").encode()


def fake_archive(files, corrupt=()):
    """files: {month 'YYYY-MM': zip bytes}. Serves a two-page listing, the zips and their checksums."""
    keys = [f"{binance.PREFIX}TESTUSDT/1d/TESTUSDT-1d-{m}.zip" for m in sorted(files)]
    def fetch(url):
        if url.startswith(binance.LISTING):
            first = url.endswith("marker=") or "marker=&" in url
            half = len(keys) // 2
            return listing(keys[:half], True, keys[half - 1]) if first else listing(keys[half:])
        for m, data in files.items():
            if url.endswith(f"TESTUSDT-1d-{m}.zip"):
                return data
            if url.endswith(f"TESTUSDT-1d-{m}.zip.CHECKSUM"):
                digest = "0" * 64 if m in corrupt else hashlib.sha256(data).hexdigest()
                return f"{digest}  TESTUSDT-1d-{m}.zip".encode()
        return None
    return fetch


def test_load_symbol_verifies_checksums_and_reports_gaps(tmp_path):
    feb = JAN_2024 + 31 * DAY_MS
    files = {"2024-01": kline_zip(JAN_2024, 31), "2024-02": kline_zip(feb + 2 * DAY_MS, 27)}   # Feb 1-2 missing
    m = binance.load_symbol("TESTUSDT", "2024-12", tmp_path, fake_archive(files))
    assert m["status"] == "partial" and m["missing_days"] == ["2024-02-01", "2024-02-02"]
    assert m["rows"] == 58 and len(m["files"]) == 2
    saved = json.loads((tmp_path / "manifests" / binance.DATASET / "TESTUSDT.json").read_text())
    assert saved["files"][0]["sha256"] == hashlib.sha256(files["2024-01"]).hexdigest()


def test_checksum_mismatch_fails_closed(tmp_path):
    files = {"2024-01": kline_zip(JAN_2024, 31), "2024-02": kline_zip(JAN_2024 + 31 * DAY_MS, 29)}
    m = binance.load_symbol("TESTUSDT", "2024-12", tmp_path, fake_archive(files, corrupt={"2024-02"}))
    assert m["file_problems"] == [{"file": "TESTUSDT-1d-2024-02.zip", "status": "checksum mismatch"}]
    assert m["rows"] == 31 and m["status"] == "partial"
    assert not (tmp_path / "raw" / binance.DATASET / "TESTUSDT" / "TESTUSDT-1d-2024-02.zip").exists()


def test_end_month_limits_what_is_loaded(tmp_path):
    files = {"2024-01": kline_zip(JAN_2024, 31), "2024-02": kline_zip(JAN_2024 + 31 * DAY_MS, 29)}
    m = binance.load_symbol("TESTUSDT", "2024-01", tmp_path, fake_archive(files))
    assert m["last_bar"] == "2024-01-31"
