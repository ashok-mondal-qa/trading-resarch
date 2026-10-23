"""Data-quality checks behind gate 1 (data validity). Any failure -> DATA INSUFFICIENT.

* Freshness: the last loaded session must be the most recent completed NSE session. A weekday counts as
  a non-trading day only if its bhavcopy was confirmed absent by a fetch made after the file would have
  been published (PUBLISH_CUTOFF_IST); otherwise its absence means stale data.
* Symbol bars: within the checked window, no session missing between the symbol's first and last bar,
  no zero or missing volume, no duplicate dates, no non-positive prices, and the adjusted series must be
  usable (see data.adjust).

The session calendar is the set of dates with an `ok` bhavcopy manifest: it comes from NSE's own files,
not from a holiday list we maintain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from trading_research.data import bhavcopy

IST = ZoneInfo("Asia/Kolkata")
SESSION_CLOSE_IST = time(15, 30)
PUBLISH_CUTOFF_IST = time(20, 0)  # bhavcopy is normally out by early evening; checked conservatively


@dataclass
class QualityResult:
    status: str  # "ok" | "DATA INSUFFICIENT"
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def sessions(store: bhavcopy.Store, start: date, end: date) -> list[date]:
    out = []
    for day in bhavcopy.weekdays(start, end):
        manifest = store.read_manifest(day)
        if manifest and manifest["status"] == "ok":
            out.append(day)
    return out


def _confirmed_holiday(manifest: dict | None, day: date) -> bool:
    if not manifest or manifest["status"] != "not_found":
        return False
    fetched = datetime.fromisoformat(manifest["retrieved_at_utc"]).astimezone(IST)
    return fetched >= datetime.combine(day, PUBLISH_CUTOFF_IST, tzinfo=IST)


def check_freshness(store: bhavcopy.Store, now_utc: datetime | None = None,
                    lookback_days: int = 10) -> QualityResult:
    """Is the newest loaded session the most recent completed one, as of `now_utc`?"""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(IST)
    day = now.date() if now.time() >= SESSION_CLOSE_IST else now.date() - timedelta(days=1)
    for _ in range(lookback_days):
        if day.weekday() < 5:
            manifest = store.read_manifest(day)
            if manifest and manifest["status"] == "ok":
                return QualityResult("ok", details={"latest_session": day.isoformat(),
                                                    "as_of_ist": now.isoformat(timespec="minutes")})
            if not _confirmed_holiday(manifest, day):
                return QualityResult("DATA INSUFFICIENT", [
                    f"{day.isoformat()} is a weekday whose session has closed, but its bhavcopy is not "
                    "loaded or not confirmed absent; data may be stale"],
                    {"as_of_ist": now.isoformat(timespec="minutes")})
        day -= timedelta(days=1)
    return QualityResult("DATA INSUFFICIENT", [f"no loaded session in the last {lookback_days} days"])


def check_symbol_bars(bars: pd.DataFrame, session_dates: list[date], window: int = 260) -> QualityResult:
    """Integrity of one symbol's bars over its last `window` sessions of the calendar.

    `bars` has a date column (or DatetimeIndex) and volume/open/high/low/close; adjusted bars from
    data.adjust may also carry `usable`."""
    df = bars.reset_index() if "date" not in bars.columns else bars
    if df.empty:
        return QualityResult("DATA INSUFFICIENT", ["no bars"])
    dates = pd.to_datetime(df["date"])
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(session_dates)))
    calendar = calendar[(calendar >= dates.min()) & (calendar <= dates.max())][-window:]
    reasons, details = [], {}
    in_window = dates.isin(calendar)
    sub = df[in_window.to_numpy()]

    duplicated = sub["date"][pd.to_datetime(sub["date"]).duplicated()]
    if len(duplicated):
        reasons.append(f"{len(duplicated)} duplicate dates")
    missing = calendar.difference(pd.DatetimeIndex(pd.to_datetime(sub["date"])))
    if len(missing):
        reasons.append(f"{len(missing)} sessions missing, e.g. {missing[0].date().isoformat()}")
        details["missing_sessions"] = [d.date().isoformat() for d in missing[:20]]
    volume = sub["adj_volume"] if "adj_volume" in sub else sub["volume"]
    zero_volume = int((volume.fillna(0) <= 0).sum())
    if zero_volume:
        reasons.append(f"{zero_volume} sessions with zero or missing volume")
    price_cols = [c for c in ("open", "high", "low", "close") if c in sub]
    if (sub[price_cols] <= 0).any().any() or sub[price_cols].isna().any().any():
        reasons.append("non-positive or missing prices")
    if "usable" in sub and not bool(sub["usable"].all()):
        reasons.append("adjusted series not usable over the whole window (see adjustment manifest)")
    if len(calendar) < window:
        details["note"] = f"only {len(calendar)} sessions of history in window (asked {window})"
    details.update({"window_sessions": int(len(calendar)), "first": calendar[0].date().isoformat() if len(
        calendar) else None, "last": calendar[-1].date().isoformat() if len(calendar) else None})
    return QualityResult("DATA INSUFFICIENT" if reasons else "ok", reasons, details)


def gate1_series(dates: pd.DatetimeIndex, volume: pd.Series, session_dates: list, window: int = 260) -> pd.Series:
    """Vectorised gate-1 bar checks for backtests: True at each of the symbol's dates when, over the last
    `window` sessions since its first bar, no session is missing and no volume is zero or missing.
    (`dates`/`volume` should already be restricted to usable adjusted bars.)"""
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(session_dates)))
    if len(dates) == 0:
        return pd.Series(dtype=bool)
    calendar = calendar[(calendar >= dates.min()) & (calendar <= dates.max())]
    present = pd.Series(calendar.isin(dates), index=calendar)
    vol = volume.reindex(calendar)
    bad = (~present) | vol.isna() | (vol <= 0)
    bad_recent = bad.astype(int).rolling(window, min_periods=1).sum()
    return (bad_recent == 0).reindex(dates).fillna(False).astype(bool)
