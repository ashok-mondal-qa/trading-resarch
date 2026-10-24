"""NSE capital-market (CM) end-of-day bhavcopy loader with provenance manifests.

Source: NSE archive files on nsearchives.nseindia.com (official, educational/informational use only).
Two file formats exist:
  * UDiFF  (from 2024-07-05):  /content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
  * legacy (up to 2024-07-05): /content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip
Both are normalised to one schema. Prices are stored raw (unadjusted); adjustment happens later.

Rules enforced here (docs/data-sources.md):
  * never fill missing candles: a date with no file gets a `not_found` manifest and no bars;
  * invalid or duplicated rows are excluded (not repaired) and listed in the manifest;
  * a file whose trade date differs from the requested date fails closed.

CLI:  python -m trading_research.data.bhavcopy --start 2026-10-01 --end 2026-10-22 [--cross-check RELIANCE,TCS]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from trading_research.config import REPO_ROOT

LOADER_VERSION = "0.1.0"
DATASET = "nse_cm_bhavcopy"
ARCHIVE_HOST = "https://nsearchives.nseindia.com"
UDIFF_FIRST_DATE = date(2024, 7, 5)
LEGACY_LAST_DATE = date(2024, 7, 5)
SESSION_CLOSE_IST = "15:30:00+05:30"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) trading-research/0.1 (educational research)"

COLUMNS = [
    "date", "symbol", "series", "isin", "open", "high", "low", "close", "last",
    "prev_close", "volume", "traded_value", "trades",
]
PRICE_COLUMNS = ["open", "high", "low", "close", "last", "prev_close"]

UDIFF_MAP = {
    "TradDt": "date", "TckrSymb": "symbol", "SctySrs": "series", "ISIN": "isin",
    "OpnPric": "open", "HghPric": "high", "LwPric": "low", "ClsPric": "close", "LastPric": "last",
    "PrvsClsgPric": "prev_close", "TtlTradgVol": "volume", "TtlTrfVal": "traded_value",
    "TtlNbOfTxsExctd": "trades",
}
LEGACY_MAP = {
    "TIMESTAMP": "date", "SYMBOL": "symbol", "SERIES": "series", "ISIN": "isin",
    "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close", "LAST": "last",
    "PREVCLOSE": "prev_close", "TOTTRDQTY": "volume", "TOTTRDVAL": "traded_value",
    "TOTALTRADES": "trades",
}

KNOWN_LIMITATIONS = [
    "Prices are raw (unadjusted) for splits, bonuses and dividends.",
    "All CM series are kept (EQ, BE, SM, GS, ...); universe/series selection happens downstream.",
    "No delivery quantity (that is in a separate NSE file).",
    "Universe is the set of securities traded that day, not point-in-time index membership.",
]
TERMS_NOTE = (
    "NSE data, published for educational and informational use only; not for commercial use or "
    "redistribution. Raw and processed files stay git-ignored. See NSE Terms of Use."
)

Fetcher = Callable[[str], "bytes | None"]


class BhavcopyError(RuntimeError):
    pass


# ---------------------------------------------------------------- URLs and fetching


def candidate_urls(day: date) -> list[tuple[str, str]]:
    """(format, url) pairs to try for a trade date, preferred first."""
    udiff = f"{ARCHIVE_HOST}/content/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    mon = day.strftime("%b").upper()
    legacy = f"{ARCHIVE_HOST}/content/historical/EQUITIES/{day:%Y}/{mon}/cm{day:%d}{mon}{day:%Y}bhav.csv.zip"
    urls = []
    if day >= UDIFF_FIRST_DATE:
        urls.append(("udiff", udiff))
    if day <= LEGACY_LAST_DATE:
        urls.append(("legacy", legacy))
    return urls


def http_fetch(url: str, retries: int = 3, timeout: float = 30.0) -> bytes | None:
    """GET a URL. Returns None on 404 (no file for that date); raises on other failures."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == retries or exc.code < 500:
                raise BhavcopyError(f"HTTP {exc.code} for {url}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == retries:
                raise BhavcopyError(f"network error for {url}: {exc}") from exc
        time.sleep(2 ** (attempt + 1))
    return None


# ---------------------------------------------------------------- parsing and validation


def parse_bhavcopy(raw_zip: bytes, fmt: str) -> pd.DataFrame:
    """Unzip one bhavcopy and normalise it to COLUMNS. No rows are dropped here."""
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise BhavcopyError(f"expected one CSV in archive, found {names}")
        df = pd.read_csv(zf.open(names[0]), dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    mapping = UDIFF_MAP if fmt == "udiff" else LEGACY_MAP
    missing = [c for c in mapping if c not in df.columns]
    if missing:
        raise BhavcopyError(f"{fmt} bhavcopy is missing columns {missing}")
    if fmt == "udiff":
        df = df[(df["Sgmt"] == "CM")]
    out = df[list(mapping)].rename(columns=mapping)
    for col in ("symbol", "series", "isin"):
        out[col] = out[col].str.strip()
    if fmt == "udiff":
        out["date"] = pd.to_datetime(out["date"].str.strip(), format="%Y-%m-%d")
    else:
        # A few legacy files (e.g. 2020-07-13) write a two-digit year ("13-Jul-20"); the trade-date check in
        # validate_bars still has to match the requested date.
        text = out["date"].str.strip()
        four = pd.to_datetime(text, format="%d-%b-%Y", errors="coerce")
        out["date"] = four if four.notna().all() else pd.to_datetime(text, format="%d-%b-%y")
    for col in PRICE_COLUMNS + ["traded_value"]:
        out[col] = pd.to_numeric(out[col].str.strip(), errors="coerce")
    for col in ("volume", "trades"):
        out[col] = pd.to_numeric(out[col].str.strip(), errors="coerce").astype("Int64")
    return out[COLUMNS].reset_index(drop=True)


@dataclass
class ValidationResult:
    bars: pd.DataFrame
    excluded: list[dict] = field(default_factory=list)
    duplicate_rows: int = 0
    invalid_rows: int = 0


def validate_bars(df: pd.DataFrame, trade_date: date) -> ValidationResult:
    """Exclude (never repair) rows that fail basic integrity checks. Fails closed on a date mismatch."""
    dates = set(df["date"].dt.date.unique())
    if dates != {trade_date}:
        raise BhavcopyError(f"file trade dates {sorted(dates)} do not match requested {trade_date}")

    excluded: list[dict] = []
    key = ["symbol", "series"]
    dup_mask = df.duplicated(key, keep=False)
    for (sym, srs), _ in df[dup_mask].groupby(key):
        excluded.append({"symbol": sym, "series": srs, "reason": "duplicate symbol/series rows"})

    ohlc = df[["open", "high", "low", "close"]]
    reasons = pd.Series("", index=df.index)
    reasons[ohlc.isna().any(axis=1) | df["volume"].isna()] = "missing OHLC or volume"
    reasons[(reasons == "") & (ohlc <= 0).any(axis=1)] = "non-positive price"
    bad_range = (df["high"] < ohlc.max(axis=1)) | (df["low"] > ohlc.min(axis=1))
    reasons[(reasons == "") & bad_range] = "OHLC inconsistent (high/low do not bound open/close)"
    reasons[(reasons == "") & (df["volume"] < 0)] = "negative volume"
    invalid_mask = (reasons != "") & ~dup_mask
    for idx in df.index[invalid_mask]:
        excluded.append({"symbol": df.at[idx, "symbol"], "series": df.at[idx, "series"],
                         "reason": reasons[idx]})

    keep = ~(dup_mask | invalid_mask)
    bars = df[keep].sort_values(key).reset_index(drop=True)
    return ValidationResult(bars, excluded, int(dup_mask.sum()), int(invalid_mask.sum()))


# ---------------------------------------------------------------- storage and manifests


@dataclass
class Store:
    root: Path = REPO_ROOT / "data"

    def raw_path(self, day: date, url: str) -> Path:
        return self.root / "raw" / DATASET / f"{day:%Y}" / url.rsplit("/", 1)[-1]

    def bars_path(self, day: date) -> Path:
        return self.root / "processed" / DATASET / f"{day:%Y}" / f"{day.isoformat()}.parquet"

    def manifest_path(self, day: date) -> Path:
        return self.root / "manifests" / DATASET / f"{day:%Y}" / f"{day.isoformat()}.json"

    def read_manifest(self, day: date) -> dict | None:
        path = self.manifest_path(day)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_manifest(day: date, status: str, *, fmt: str | None = None, url: str | None = None,
                   attempted_urls: list[str] | None = None, raw: bytes | None = None,
                   rows_in_file: int = 0, result: ValidationResult | None = None) -> dict:
    bars = result.bars if result is not None else None
    stamp = f"{day.isoformat()}T{SESSION_CLOSE_IST}" if bars is not None and len(bars) else None
    return {
        "dataset": DATASET,
        "loader_version": LOADER_VERSION,
        "status": status,  # ok | not_found
        "provider": "NSE (National Stock Exchange of India) archive",
        "source_url": url,
        "attempted_urls": attempted_urls or ([url] if url else []),
        "file_format": fmt,
        "raw_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        "exchange": "NSE",
        "segment": "CM (capital market)",
        "instruments": "all securities in the CM bhavcopy for the date",
        "timeframe": "1D",
        "trade_date": day.isoformat(),
        "first_bar_ist": stamp,
        "last_bar_ist": stamp,
        "retrieved_at_utc": _utc_now(),
        "price_adjustment": "none (raw, unadjusted)",
        "corporate_actions_applied": [],
        "rows_in_file": rows_in_file,
        "rows_kept": int(len(bars)) if bars is not None else 0,
        "series_counts": (bars["series"].value_counts().sort_index().to_dict() if bars is not None else {}),
        "duplicate_rows": result.duplicate_rows if result else 0,
        "invalid_rows": result.invalid_rows if result else 0,
        "excluded": result.excluded if result else [],
        "missing_note": ("no file published for this date (holiday, non-trading day or not yet "
                         "published); no bars were created" if status == "not_found" else None),
        "known_limitations": KNOWN_LIMITATIONS,
        "terms": TERMS_NOTE,
        "cross_checks": [],
    }


def load_day(day: date, store: Store | None = None, fetch: Fetcher = http_fetch,
             force: bool = False) -> dict:
    """Fetch, validate and store one trade date. Returns the manifest written for it."""
    store = store or Store()
    if day.weekday() >= 5:
        raise BhavcopyError(f"{day} is a weekend; NSE CM does not trade")
    existing = store.read_manifest(day)
    if existing and existing["status"] == "ok" and not force and store.bars_path(day).exists():
        return existing

    attempted: list[str] = []
    for fmt, url in candidate_urls(day):
        attempted.append(url)
        raw = fetch(url)
        if raw is None:
            continue
        frame = parse_bhavcopy(raw, fmt)
        result = validate_bars(frame, day)
        raw_path = store.raw_path(day, url)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
        bars_path = store.bars_path(day)
        bars_path.parent.mkdir(parents=True, exist_ok=True)
        result.bars.to_parquet(bars_path, index=False)
        manifest = build_manifest(day, "ok", fmt=fmt, url=url, attempted_urls=attempted, raw=raw,
                                  rows_in_file=len(frame), result=result)
        _write_json(store.manifest_path(day), manifest)
        return manifest

    manifest = build_manifest(day, "not_found", attempted_urls=attempted)
    _write_json(store.manifest_path(day), manifest)
    return manifest


def weekdays(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def load_range(start: date, end: date, store: Store | None = None, fetch: Fetcher = http_fetch,
               force: bool = False, pause_s: float = 0.5) -> list[dict]:
    store = store or Store()
    manifests = []
    for day in weekdays(start, end):
        manifests.append(load_day(day, store, fetch, force))
        if fetch is http_fetch and pause_s:
            time.sleep(pause_s)  # be polite to the archive
    return manifests


def read_bars(start: date, end: date, store: Store | None = None,
              series: Iterable[str] | None = ("EQ",)) -> pd.DataFrame:
    """Concatenate stored bars for [start, end]. Dates without an `ok` manifest are simply absent."""
    store = store or Store()
    frames = []
    for day in weekdays(start, end):
        manifest = store.read_manifest(day)
        if manifest and manifest["status"] == "ok":
            frames.append(pd.read_parquet(store.bars_path(day)))
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    bars = pd.concat(frames, ignore_index=True)
    if series is not None:
        bars = bars[bars["series"].isin(list(series))]
    return bars.sort_values(["symbol", "series", "date"]).reset_index(drop=True)


def record_cross_check(day: date, check: dict, store: Store | None = None) -> dict:
    store = store or Store()
    manifest = store.read_manifest(day)
    if manifest is None:
        raise BhavcopyError(f"no manifest for {day}")
    manifest["cross_checks"].append(check)
    _write_json(store.manifest_path(day), manifest)
    return manifest


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--force", action="store_true", help="re-download even if already loaded")
    parser.add_argument("--cross-check", default="",
                        help="comma-separated symbols to compare against the NSE bhavcopy MCP server")
    args = parser.parse_args(argv)
    end = args.end or args.start
    store = Store()
    for manifest in load_range(args.start, end, store, force=args.force):
        print(f"{manifest['trade_date']}  {manifest['status']:<9}  rows_kept={manifest['rows_kept']:<5} "
              f"excluded={len(manifest['excluded'])}")
        symbols = [s.strip().upper() for s in args.cross_check.split(",") if s.strip()]
        if manifest["status"] == "ok" and symbols:
            from trading_research.data.nse_mcp import cross_check_day

            day = date.fromisoformat(manifest["trade_date"])
            check = cross_check_day(day, symbols, pd.read_parquet(store.bars_path(day)))
            record_cross_check(day, check, store)
            print(f"            cross-check vs MCP: {check['status']} "
                  f"{check['mismatches'] or check['unavailable'] or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
