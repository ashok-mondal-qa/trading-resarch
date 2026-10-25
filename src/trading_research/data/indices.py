"""NSE end-of-day index values (NIFTY 50, NIFTY 500, India VIX, ...) from the NSE archive.

Source: nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv, one file per session with
every NSE index. Same storage and provenance rules as the bhavcopy loader: raw file kept with SHA-256,
normalised parquet, one manifest per date, missing files never filled.

CLI:  python -m trading_research.data.indices --start 2021-10-25 --end 2026-10-22
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import bhavcopy

DATASET = "nse_index_close"
COLUMNS = ["date", "index", "open", "high", "low", "close", "volume", "turnover_cr", "pe", "pb", "div_yield"]
SOURCE_MAP = {
    "Index Name": "index", "Index Date": "date", "Open Index Value": "open", "High Index Value": "high",
    "Low Index Value": "low", "Closing Index Value": "close", "Volume": "volume",
    "Turnover (Rs. Cr.)": "turnover_cr", "P/E": "pe", "P/B": "pb", "Div Yield": "div_yield",
}


ALTERNATE_DATE_FORMATS = ("%m-%d-%Y", "%d/%m/%Y")
# NIFTY 50 was "S&P CNX Nifty" in files up to 2013-02-07, "CNX Nifty" until 2015-11-06 and "Nifty 50" from
# 2015-11-09 (names as they appear in the archive files).
FORMER_NAMES = {"nifty 50": ("cnx nifty", "s&p cnx nifty")}


def url_for(day: date) -> str:
    return f"{bhavcopy.ARCHIVE_HOST}/content/indices/ind_close_all_{day:%d%m%Y}.csv"


def paths(root: Path, day: date) -> dict[str, Path]:
    return {
        "raw": root / "raw" / DATASET / f"{day:%Y}" / f"ind_close_all_{day:%d%m%Y}.csv",
        "bars": root / "processed" / DATASET / f"{day:%Y}" / f"{day.isoformat()}.parquet",
        "manifest": root / "manifests" / DATASET / f"{day:%Y}" / f"{day.isoformat()}.json",
    }


def parse(raw: bytes, date_format: str = "%d-%m-%Y") -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in SOURCE_MAP if c not in df.columns]
    if missing:
        raise bhavcopy.BhavcopyError(f"index file is missing columns {missing}")
    out = df[list(SOURCE_MAP)].rename(columns=SOURCE_MAP)
    out["index"] = out["index"].str.strip()
    out["date"] = pd.to_datetime(out["date"].str.strip(), format=date_format, errors="coerce")
    for col in COLUMNS[2:]:
        out[col] = pd.to_numeric(out[col].str.strip(), errors="coerce")  # "-" -> NaN (e.g. VIX volume)
    return out[COLUMNS].reset_index(drop=True)


def load_day(day: date, root: Path = REPO_ROOT / "data", fetch=bhavcopy.http_fetch, force: bool = False) -> dict:
    p = paths(root, day)
    if p["manifest"].exists() and not force:
        existing = json.loads(p["manifest"].read_text(encoding="utf-8"))
        if existing["status"] == "ok" and p["bars"].exists():
            return existing
    url = url_for(day)
    raw = fetch(url)
    manifest = {
        "dataset": DATASET, "provider": "NSE archive", "source_url": url, "trade_date": day.isoformat(),
        "retrieved_at_utc": bhavcopy._utc_now(), "terms": bhavcopy.TERMS_NOTE,
        "price_adjustment": "none (index values as published)",
    }
    if raw is None:
        manifest.update(status="not_found", rows=0)
    else:
        frame, note = parse(raw), None
        dates = set(frame["date"].dt.date)
        if dates != {day}:
            # Some files use another date layout: 2023 files with MM-DD-YYYY (ind_close_all_06042023.csv
            # says 04-06-2023), some 2015 files with DD/MM/YYYY. Accept one only if reading the file that
            # way gives exactly the requested date.
            for fmt in ALTERNATE_DATE_FORMATS:
                other = parse(raw, fmt)
                if set(other["date"].dt.date) == {day}:
                    frame, note = other, f"file uses {fmt} dates; read that way it matches the file name"
                    break
            else:
                raise bhavcopy.BhavcopyError(f"index file dates {sorted(dates)} do not match {day}")
        # An index name listed twice (e.g. "CNX Alpha Index" in ind_close_all_08022013.csv) is excluded,
        # never de-duplicated by picking a row; every other index in the file is kept.
        dup_mask = frame["index"].duplicated(keep=False)
        excluded = sorted(frame.loc[dup_mask, "index"].unique())
        frame = frame[~dup_mask].reset_index(drop=True)
        for key in ("raw", "bars"):
            p[key].parent.mkdir(parents=True, exist_ok=True)
        p["raw"].write_bytes(raw)
        frame.to_parquet(p["bars"], index=False)
        manifest.update(status="ok", rows=int(len(frame)), date_format_note=note,
                        excluded_duplicate_names=excluded, raw_sha256=hashlib.sha256(raw).hexdigest(),
                        first_bar_ist=f"{day.isoformat()}T{bhavcopy.SESSION_CLOSE_IST}",
                        last_bar_ist=f"{day.isoformat()}T{bhavcopy.SESSION_CLOSE_IST}")
    bhavcopy._write_json(p["manifest"], manifest)
    return manifest


def load_range(start: date, end: date, root: Path = REPO_ROOT / "data", fetch=bhavcopy.http_fetch,
               pause_s: float = 0.3) -> list[dict]:
    out = []
    for day in bhavcopy.weekdays(start, end):
        out.append(load_day(day, root, fetch))
        if fetch is bhavcopy.http_fetch and pause_s:
            time.sleep(pause_s)
    return out


def read_index(name: str, start: date, end: date, root: Path = REPO_ROOT / "data") -> pd.DataFrame:
    """One index's daily bars indexed by date (case-insensitive name, e.g. 'Nifty 50')."""
    frames = []
    for day in bhavcopy.weekdays(start, end):
        p = paths(root, day)
        if p["manifest"].exists() and json.loads(p["manifest"].read_text())["status"] == "ok":
            frame = pd.read_parquet(p["bars"])
            names = (name.lower(),) + FORMER_NAMES.get(name.lower(), ())
            frames.append(frame[frame["index"].str.lower().isin(names)])
    if not frames:
        return pd.DataFrame(columns=COLUMNS).set_index("date")
    return pd.concat(frames).set_index("date").sort_index()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load NSE daily index closes")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    args = parser.parse_args(argv)
    for m in load_range(args.start, args.end or args.start):
        print(f"{m['trade_date']}  {m['status']:<9} rows={m['rows']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
