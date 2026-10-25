"""NSE F&O end-of-day bhavcopy: NIFTY and BANKNIFTY index options and futures.

Sources (NSE archive, one file per session):
* legacy  nsearchives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip (to 2024-07-05)
* UDiFF   nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip (2024 on; carries lot size
          and the underlying's price)
UDiFF is used when it exists, else the legacy file. Same provenance rules as the CM loader: raw zip kept with
SHA-256, a manifest per date, a date mismatch fails closed, missing files are never filled, bad rows are
excluded and listed. Only index options/futures on SYMBOLS are kept in the parquet.

CLI:  python -m trading_research.data.fo_bhavcopy --start 2012-01-02 --end 2026-10-23 --workers 6
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import bhavcopy

DATASET = "nse_fo_bhavcopy"
SYMBOLS = ("NIFTY", "BANKNIFTY")
COLUMNS = ["date", "instrument", "symbol", "expiry", "strike", "option_type", "open", "high", "low", "close",
           "settle", "contracts", "value_lakh", "open_interest", "underlying", "lot_size"]
LEGACY_MAP = {"INSTRUMENT": "instrument", "SYMBOL": "symbol", "EXPIRY_DT": "expiry", "STRIKE_PR": "strike",
              "OPTION_TYP": "option_type", "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close",
              "SETTLE_PR": "settle", "CONTRACTS": "contracts", "VAL_INLAKH": "value_lakh", "OPEN_INT": "open_interest",
              "TIMESTAMP": "date"}
UDIFF_MAP = {"FinInstrmTp": "instrument", "TckrSymb": "symbol", "XpryDt": "expiry", "StrkPric": "strike",
             "OptnTp": "option_type", "OpnPric": "open", "HghPric": "high", "LwPric": "low", "ClsPric": "close",
             "SttlmPric": "settle", "TtlTradgVol": "contracts", "TtlTrfVal": "value_lakh", "OpnIntrst": "open_interest",
             "TradDt": "date", "UndrlygPric": "underlying", "NewBrdLotQty": "lot_size"}
INSTRUMENTS = {"OPTIDX": "OPT", "FUTIDX": "FUT", "IDO": "OPT", "IDF": "FUT"}


def urls(day: date) -> list[tuple[str, str]]:
    host, mon = bhavcopy.ARCHIVE_HOST, day.strftime("%b").upper()
    return [("udiff", f"{host}/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"),
            ("legacy", f"{host}/content/historical/DERIVATIVES/{day:%Y}/{mon}/fo{day:%d}{mon}{day:%Y}bhav.csv.zip")]


def paths(root: Path, day: date) -> dict[str, Path]:
    return {"raw": root / "raw" / DATASET / f"{day:%Y}" / f"{day.isoformat()}.zip",
            "bars": root / "processed" / DATASET / f"{day:%Y}" / f"{day.isoformat()}.parquet",
            "manifest": root / "manifests" / DATASET / f"{day:%Y}" / f"{day.isoformat()}.json"}


def _dates(values: pd.Series, fmt: str) -> pd.Series:
    """UDiFF uses ISO dates; legacy files use 14-May-2012, a few (e.g. 2012-05-14) 14-May-12."""
    if fmt == "udiff":
        return pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")
    long = pd.to_datetime(values.where(values.str.len() == 11), format="%d-%b-%Y", errors="coerce")
    short = pd.to_datetime(values.where(values.str.len() == 9), format="%d-%b-%y", errors="coerce")
    return long.fillna(short)


def parse(raw_zip: bytes, fmt: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as z:
        df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    mapping = UDIFF_MAP if fmt == "udiff" else LEGACY_MAP
    missing = [c for c in mapping if c not in df.columns]
    if missing:
        raise bhavcopy.BhavcopyError(f"{fmt} F&O file is missing columns {missing}")
    out = df[list(mapping)].rename(columns=mapping)
    for col in out.columns:
        out[col] = out[col].str.strip()
    out = out[out["instrument"].isin(INSTRUMENTS) & out["symbol"].isin(SYMBOLS)].copy()
    out["instrument"] = out["instrument"].map(INSTRUMENTS)
    for col in ("date", "expiry"):
        out[col] = _dates(out[col], fmt)
    for col in ("strike", "open", "high", "low", "close", "settle", "contracts", "value_lakh", "open_interest",
                "underlying", "lot_size"):
        if col not in out:
            out[col] = float("nan")
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if fmt == "udiff":
        out["value_lakh"] = out["value_lakh"] / 1e5           # UDiFF turnover is in rupees (notional, like legacy)
    out["option_type"] = out["option_type"].replace({"": "XX"})
    return out[COLUMNS].reset_index(drop=True)


def validate(df: pd.DataFrame, day: date) -> tuple[pd.DataFrame, list[dict]]:
    """Exclude rows that cannot be used (never repaired). A traded row needs low <= open/close <= high;
    an untraded row (all OHLC zero) is kept with its settlement price only."""
    if len(df) and (df["date"] != pd.Timestamp(day)).any():
        raise bhavcopy.BhavcopyError(f"F&O file date differs from {day}")
    traded = df[["open", "high", "low", "close"]].fillna(0).gt(0).all(axis=1)
    untraded = df[["open", "high", "low"]].fillna(0).eq(0).all(axis=1)
    bad_ohlc = traded & ((df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1)))
    bad = bad_ohlc | (~traded & ~untraded) | df["expiry"].isna() | df["settle"].isna()
    dup = df.duplicated(["instrument", "symbol", "expiry", "strike", "option_type"], keep=False)
    excluded = [{"row": r.to_dict(), "reason": "duplicate contract" if d else "invalid row"}
                for (_, r), d in zip(df[bad | dup].iterrows(), dup[bad | dup])]
    kept = df[~(bad | dup)].copy()
    kept["traded"] = traded[~(bad | dup)]
    return kept.reset_index(drop=True), excluded


def load_day(day: date, root: Path = REPO_ROOT / "data", fetch=bhavcopy.http_fetch) -> dict:
    p = paths(root, day)
    if p["manifest"].exists():
        m = json.loads(p["manifest"].read_text())
        if m["status"] == "ok":
            return m
    raw, fmt, url = None, None, None
    for kind, u in urls(day):
        raw = fetch(u)
        if raw is not None:
            fmt, url = kind, u
            break
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if raw is None:
        m = {"dataset": DATASET, "date": day.isoformat(), "status": "not_found", "retrieved_at_utc": now}
    else:
        bars, excluded = validate(parse(raw, fmt), day)
        p["raw"].parent.mkdir(parents=True, exist_ok=True)
        p["raw"].write_bytes(raw)
        p["bars"].parent.mkdir(parents=True, exist_ok=True)
        bars.to_parquet(p["bars"], index=False)
        m = {"dataset": DATASET, "date": day.isoformat(), "status": "ok", "format": fmt, "source_url": url,
             "sha256": hashlib.sha256(raw).hexdigest(), "retrieved_at_utc": now, "rows": int(len(bars)),
             "options": int((bars["instrument"] == "OPT").sum()), "futures": int((bars["instrument"] == "FUT").sum()),
             "excluded": excluded[:50], "excluded_count": len(excluded), "symbols": list(SYMBOLS),
             "price_adjustment": "none (index derivatives)",
             "licence": "NSE archive data; educational/informational use only"}
    p["manifest"].parent.mkdir(parents=True, exist_ok=True)
    p["manifest"].write_text(json.dumps(m, indent=2, default=str) + "\n", encoding="utf-8")
    return m


def read(start: date, end: date, root: Path = REPO_ROOT / "data") -> pd.DataFrame:
    frames = []
    for day in bhavcopy.weekdays(start, end):
        p = paths(root, day)
        if p["manifest"].exists() and json.loads(p["manifest"].read_text())["status"] == "ok":
            frames.append(pd.read_parquet(p["bars"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS + ["traded"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    days = list(bhavcopy.weekdays(args.start, args.end))

    def one(d):
        try:
            m = load_day(d)
            return d, m["status"], m.get("rows", 0)
        except Exception as exc:  # reported, never silently skipped
            return d, f"error: {exc}", 0
    with ThreadPoolExecutor(args.workers) as pool:
        for d, status, rows in pool.map(one, days):
            print(d, status, rows, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
