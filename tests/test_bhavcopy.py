"""Bhavcopy loader and MCP client tests.

All market rows below are SYNTHETIC test fixtures (fake symbols TESTA/TESTB/...), not NSE data.
No network access: fetchers and MCP transports are faked.
"""

import io
import json
import zipfile
from datetime import date

import pandas as pd
import pytest

from trading_research.data import bhavcopy as bc
from trading_research.data import nse_mcp

DAY = date(2026, 10, 22)
LEGACY_DAY = date(2023, 10, 20)

UDIFF_HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,"
    "StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,"
    "SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,"
    "Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)


def udiff_row(sym, series="EQ", o=100, h=110, l=95, c=105, vol=1000, day="2026-10-22"):
    return (f"{day},{day},CM,NSE,STK,1,INE000000001,{sym},{series},,,,,{sym} LTD,{o},{h},{l},{c},{c},"
            f"100,,{c},,,{vol},{vol * c},10,F1,1,,,,,")


def legacy_row(sym, series="EQ", o=100, h=110, l=95, c=105, vol=1000, day="20-OCT-2023"):
    return f"{sym},{series},{o},{h},{l},{c},{c},100,{vol},{vol * c},{day},10,INE000000001,"


def zipped(name, lines):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, "\n".join(lines) + "\n")
    return buf.getvalue()


def udiff_zip(rows):
    return zipped("BhavCopy.csv", [UDIFF_HEADER] + rows)


def legacy_zip(rows):
    header = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,"
    return zipped("cm20OCT2023bhav.csv", [header] + rows)


class FakeFetch:
    def __init__(self, files):
        self.files, self.calls = files, []

    def __call__(self, url):
        self.calls.append(url)
        for key, payload in self.files.items():
            if key in url:
                return payload
        return None


@pytest.fixture
def store(tmp_path):
    return bc.Store(root=tmp_path)


def test_candidate_urls_switch_format():
    assert [f for f, _ in bc.candidate_urls(DAY)] == ["udiff"]
    assert [f for f, _ in bc.candidate_urls(LEGACY_DAY)] == ["legacy"]
    assert [f for f, _ in bc.candidate_urls(date(2024, 7, 5))] == ["udiff", "legacy"]
    assert bc.candidate_urls(LEGACY_DAY)[0][1].endswith("/EQUITIES/2023/OCT/cm20OCT2023bhav.csv.zip")
    assert bc.candidate_urls(DAY)[0][1].endswith("BhavCopy_NSE_CM_0_0_0_20261022_F_0000.csv.zip")


def test_both_formats_normalise_to_same_schema():
    new = bc.parse_bhavcopy(udiff_zip([udiff_row("TESTA")]), "udiff")
    old = bc.parse_bhavcopy(legacy_zip([legacy_row("TESTA")]), "legacy")
    assert list(new.columns) == list(old.columns) == bc.COLUMNS
    for frame in (new, old):
        row = frame.iloc[0]
        assert (row.open, row.high, row.low, row.close, int(row.volume)) == (100, 110, 95, 105, 1000)
    assert old.iloc[0].date.date() == LEGACY_DAY


def test_load_day_writes_bars_raw_and_manifest(store):
    fetch = FakeFetch({"20261022": udiff_zip([udiff_row("TESTA"), udiff_row("TESTB", series="BE")])})
    manifest = bc.load_day(DAY, store, fetch)
    assert manifest["status"] == "ok"
    assert manifest["rows_kept"] == 2 and manifest["series_counts"] == {"BE": 1, "EQ": 1}
    assert manifest["price_adjustment"].startswith("none")
    assert manifest["raw_sha256"] and manifest["first_bar_ist"] == "2026-10-22T15:30:00+05:30"
    for key in ("provider", "source_url", "exchange", "timeframe", "retrieved_at_utc",
                "corporate_actions_applied", "duplicate_rows", "known_limitations", "terms"):
        assert key in manifest
    assert store.bars_path(DAY).exists() and store.manifest_path(DAY).exists()
    assert store.raw_path(DAY, manifest["source_url"]).exists()


def test_missing_file_is_not_filled(store):
    manifest = bc.load_day(DAY, store, FakeFetch({}))
    assert manifest["status"] == "not_found" and manifest["rows_kept"] == 0
    assert not store.bars_path(DAY).exists()
    assert bc.read_bars(DAY, DAY, store).empty


def test_date_mismatch_fails_closed(store):
    fetch = FakeFetch({"20261022": udiff_zip([udiff_row("TESTA", day="2026-10-21")])})
    with pytest.raises(bc.BhavcopyError, match="do not match"):
        bc.load_day(DAY, store, fetch)
    assert not store.manifest_path(DAY).exists()


def test_invalid_and_duplicate_rows_are_excluded_not_repaired(store):
    rows = [
        udiff_row("TESTA"),
        udiff_row("BADHL", h=90),           # high below open/close
        udiff_row("ZERO", o=0),             # non-positive price
        udiff_row("DUPE"), udiff_row("DUPE", c=106),
    ]
    manifest = bc.load_day(DAY, store, FakeFetch({"20261022": udiff_zip(rows)}))
    assert manifest["rows_in_file"] == 5 and manifest["rows_kept"] == 1
    assert manifest["duplicate_rows"] == 2 and manifest["invalid_rows"] == 2
    reasons = {e["symbol"]: e["reason"] for e in manifest["excluded"]}
    assert set(reasons) == {"BADHL", "ZERO", "DUPE"}
    assert list(bc.read_bars(DAY, DAY, store)["symbol"]) == ["TESTA"]


def test_reload_is_idempotent_unless_forced(store):
    fetch = FakeFetch({"20261022": udiff_zip([udiff_row("TESTA")])})
    bc.load_day(DAY, store, fetch)
    bc.load_day(DAY, store, fetch)
    assert len(fetch.calls) == 1
    bc.load_day(DAY, store, fetch, force=True)
    assert len(fetch.calls) == 2


def test_weekend_is_refused(store):
    with pytest.raises(bc.BhavcopyError, match="weekend"):
        bc.load_day(date(2026, 10, 24), store, FakeFetch({}))


def test_load_range_and_read_bars_filter_series(store):
    fetch = FakeFetch({
        "20261021": udiff_zip([udiff_row("TESTA", c=101, day="2026-10-21")]),
        "20261022": udiff_zip([udiff_row("TESTA"), udiff_row("TESTB", series="BE")]),
    })
    manifests = bc.load_range(date(2026, 10, 20), date(2026, 10, 25), store, fetch)
    assert [m["status"] for m in manifests] == ["not_found", "ok", "ok", "not_found"]  # 20,21,22,23
    bars = bc.read_bars(date(2026, 10, 20), date(2026, 10, 25), store)
    assert list(bars["symbol"]) == ["TESTA", "TESTA"] and list(bars["close"]) == [101, 105]
    assert len(bc.read_bars(date(2026, 10, 20), date(2026, 10, 25), store, series=None)) == 3


# ---------------------------------------------------------------- MCP client


class FakeTransport:
    """Simulates a load balancer that loses the session on the first tools/call."""

    def __init__(self, tool_text, lose_first=1):
        self.tool_text, self.lose = tool_text, lose_first

    def __call__(self, url, payload, session_id):
        method = payload["method"]
        if method == "initialize":
            return 200, {"mcp-session-id": "s1"}, json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        if method == "notifications/initialized":
            return 202, {}, ""
        if self.lose:
            self.lose -= 1
            return 404, {}, json.dumps({"message": "Session not found: s1"})
        result = {"content": [{"type": "text", "text": self.tool_text}], "isError": False}
        return 200, {}, "event:message\ndata:" + json.dumps({"jsonrpc": "2.0", "id": 2, "result": result})


def mcp_history(rows):
    return json.dumps({"symbol": "TESTA", "data": rows})


def test_call_tool_retries_lost_session_and_parses_sse():
    text = nse_mcp.call_tool("u", "t", {}, FakeTransport("hello", lose_first=2), pause_s=0)
    assert text == "hello"


def test_call_tool_gives_up():
    with pytest.raises(nse_mcp.McpError, match="after 2 attempts"):
        nse_mcp.call_tool("u", "t", {}, FakeTransport("x", lose_first=5), attempts=2, pause_s=0)


def test_cross_check_detects_match_and_mismatch(store):
    bc.load_day(DAY, store, FakeFetch({"20261022": udiff_zip([udiff_row("TESTA")])}))
    bars = pd.read_parquet(store.bars_path(DAY))
    good = {"date": "2026-10-22", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000}
    check = nse_mcp.cross_check_day(DAY, ["TESTA"], bars, FakeTransport(mcp_history([good]), 0), pause_s=0)
    assert check["status"] == "match"
    bad = dict(good, close=104.5)
    check = nse_mcp.cross_check_day(DAY, ["TESTA"], bars, FakeTransport(mcp_history([bad]), 0), pause_s=0)
    assert check["status"] == "mismatch" and check["mismatches"][0]["field"] == "close"
    manifest = bc.record_cross_check(DAY, check, store)
    assert manifest["cross_checks"][0]["status"] == "mismatch"


def test_cross_check_retries_backend_errors_and_reports_incomplete(store):
    bc.load_day(DAY, store, FakeFetch({"20261022": udiff_zip([udiff_row("TESTA")])}))
    bars = pd.read_parquet(store.bars_path(DAY))
    error = json.dumps({"error": "Symbol not found: TESTA"})
    check = nse_mcp.cross_check_day(DAY, ["TESTA"], bars, FakeTransport(error, 0), pause_s=0)
    assert check["status"] == "incomplete" and check["mismatches"] == []
    assert "Symbol not found" in check["unavailable"][0]["error"]
