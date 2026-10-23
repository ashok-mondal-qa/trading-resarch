"""Gate-1 data-quality tests. Manifests and bars are SYNTHETIC fixtures, not NSE data."""

import json
from datetime import date, datetime, timezone

import pandas as pd

from trading_research.data import bhavcopy as bc
from trading_research.data import quality


def write_manifest(store, day, status, retrieved="2026-10-22T16:00:00+00:00"):
    path = store.manifest_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": status, "retrieved_at_utc": retrieved}))


def utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_fresh_when_latest_completed_session_is_loaded(tmp_path):
    store = bc.Store(root=tmp_path)
    write_manifest(store, date(2026, 10, 22), "ok")
    # 2026-10-23 04:30 UTC = 10:00 IST Friday: today's session not closed, so Thursday is the latest
    assert quality.check_freshness(store, utc("2026-10-23T04:30:00")).status == "ok"


def test_stale_when_closed_session_missing(tmp_path):
    store = bc.Store(root=tmp_path)
    write_manifest(store, date(2026, 10, 22), "ok")
    # 2026-10-23 12:00 UTC = 17:30 IST Friday: Friday's session closed and is not loaded
    result = quality.check_freshness(store, utc("2026-10-23T12:00:00"))
    assert result.status == "DATA INSUFFICIENT" and "2026-10-23" in result.reasons[0]


def test_holiday_only_counts_when_confirmed_after_publication(tmp_path):
    store = bc.Store(root=tmp_path)
    write_manifest(store, date(2026, 10, 19), "ok")
    write_manifest(store, date(2026, 10, 20), "not_found", retrieved="2026-10-20T10:00:00+00:00")  # 15:30 IST
    assert quality.check_freshness(store, utc("2026-10-21T04:00:00")).status == "DATA INSUFFICIENT"
    write_manifest(store, date(2026, 10, 20), "not_found", retrieved="2026-10-21T03:00:00+00:00")
    assert quality.check_freshness(store, utc("2026-10-21T04:00:00")).status == "ok"


def bars(dates, volume=1000.0):
    return pd.DataFrame({"date": pd.to_datetime(dates), "open": 10.0, "high": 11.0, "low": 9.0,
                         "close": 10.0, "volume": volume})


SESSIONS = [date(2026, 10, d) for d in (13, 14, 15, 16, 19, 21, 22)]


def test_clean_symbol_passes():
    result = quality.check_symbol_bars(bars(SESSIONS), SESSIONS)
    assert result.status == "ok" and result.details["window_sessions"] == 7


def test_missing_session_zero_volume_and_unusable_fail():
    gappy = bars([d for d in SESSIONS if d != date(2026, 10, 15)])
    result = quality.check_symbol_bars(gappy, SESSIONS)
    assert result.status == "DATA INSUFFICIENT" and result.details["missing_sessions"] == ["2026-10-15"]
    assert "zero" in quality.check_symbol_bars(bars(SESSIONS, volume=0.0), SESSIONS).reasons[0]
    adjusted = bars(SESSIONS).assign(usable=[False] + [True] * 6)
    assert "not usable" in quality.check_symbol_bars(adjusted, SESSIONS).reasons[0]
    # a window that starts after the unusable bar passes
    assert quality.check_symbol_bars(adjusted, SESSIONS, window=6).status == "ok"


def test_listing_date_is_not_a_gap():
    late = bars(SESSIONS[3:])
    assert quality.check_symbol_bars(late, SESSIONS).status == "ok"
