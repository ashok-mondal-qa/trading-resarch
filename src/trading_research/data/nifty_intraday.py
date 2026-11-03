"""NIFTY 50 spot index 1-minute bars from an UNOFFICIAL public source (spec nifty-expiry-reversal.md).

NSE publishes no free intraday history. The primary source is the MIT-licensed GitHub repo
`technovusin/nifty50-historical-data` (1min/<year>/*.csv, IST timestamps); `sandeepkapri/Nifty50-Minute-Data`
is a second vendor used only to cross-check. Raw CSVs are hashed into a manifest; nothing is repaired.
Every day used must pass `day_check` against the official NSE daily index file.

CLI:  python -m trading_research.data.nifty_intraday --src <clone of technovusin repo> [--commit <sha>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.config import REPO_ROOT

DATASET = "nifty_1min_unofficial"
SOURCE = "https://github.com/technovusin/nifty50-historical-data"
CROSS_SOURCE = "https://github.com/sandeepkapri/Nifty50-Minute-Data"
SESSION_MINUTES = 375  # 09:15..15:29


def paths(root: Path = REPO_ROOT / "data") -> dict[str, Path]:
    return {"bars": root / "processed" / DATASET / "nifty50_1min.parquet",
            "cross": root / "processed" / DATASET / "nifty50_1min_crosscheck.parquet",
            "manifest": root / "manifests" / DATASET / "manifest.json"}


def read_technovusin(src: Path) -> tuple[pd.DataFrame, list[dict]]:
    files = sorted((src / "1min").glob("*/*.csv"))
    frames, hashes = [], []
    for f in files:
        raw = f.read_bytes()
        hashes.append({"file": str(f.relative_to(src)), "sha256": hashlib.sha256(raw).hexdigest()})
        df = pd.read_csv(f)
        frames.append(pd.DataFrame({"ts": pd.to_datetime(df["Timestamp"]), "open": df["Open"], "high": df["High"],
                                    "low": df["Low"], "close": df["Close"]}))
    bars = pd.concat(frames, ignore_index=True)
    return clean(bars), hashes


def read_sandeepkapri(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv)
    ts = pd.to_datetime(df["Date"] + " " + df["Time"], format="%d-%m-%Y %H:%M:%S")
    return clean(pd.DataFrame({"ts": ts, "open": df["Open"], "high": df["High"], "low": df["Low"],
                               "close": df["Close"]}))


def clean(bars: pd.DataFrame) -> pd.DataFrame:
    """Drops (never repairs) duplicate timestamps and rows whose high/low do not bound open/close."""
    bars = bars.drop_duplicates("ts", keep=False)
    ok = (bars["high"] >= bars[["open", "close"]].max(axis=1)) & (bars["low"] <= bars[["open", "close"]].min(axis=1))
    ok &= bars[["open", "high", "low", "close"]].gt(0).all(axis=1)
    return bars[ok].sort_values("ts").set_index("ts")


def day_check(day: pd.DataFrame, official_high: float, official_low: float, tol_pct: float = 0.05,
              min_bars: int = 370, max_gap_min: int = 5) -> str:
    """'ok' or the reason the day fails gate 1 (spec): bar count, a gap 12:00-15:15, or high/low vs NSE."""
    session = day.between_time("09:15", "15:29")
    if len(session) < min_bars:
        return f"only {len(session)} bars"
    after = session.between_time("12:00", "15:15").index
    if len(after) and (after.to_series().diff().dt.total_seconds().max() or 0) > max_gap_min * 60:
        return "gap > 5 min after 12:00"
    if pd.isna(official_high) or pd.isna(official_low):
        return "no official high/low"
    if abs(session["high"].max() / official_high - 1) * 100 > tol_pct:
        return f"high {session['high'].max():.2f} vs NSE {official_high:.2f}"
    if abs(session["low"].min() / official_low - 1) * 100 > tol_pct:
        return f"low {session['low'].min():.2f} vs NSE {official_low:.2f}"
    return "ok"


def load(root: Path = REPO_ROOT / "data", cross: bool = False) -> pd.DataFrame:
    return pd.read_parquet(paths(root)["cross" if cross else "bars"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--commit", default="unknown")
    ap.add_argument("--cross-csv", type=Path)
    a = ap.parse_args(argv)
    p = paths()
    bars, hashes = read_technovusin(a.src)
    p["bars"].parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(p["bars"])
    manifest = {"dataset": DATASET, "provider": "technovusin (GitHub, MIT licence) - UNOFFICIAL", "source_url": SOURCE,
                "commit": a.commit, "instrument": "NIFTY 50 spot index", "exchange": "NSE", "timeframe": "1min",
                "first_bar_ist": str(bars.index.min()), "last_bar_ist": str(bars.index.max()), "rows": int(len(bars)),
                "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "price_adjustment": "none (index)", "files": hashes,
                "limitations": "unofficial vendor data; some missing minutes; every used day is checked against the "
                               "NSE daily index high/low (data/nifty_intraday.day_check)"}
    if a.cross_csv:
        raw = a.cross_csv.read_bytes()
        cross = read_sandeepkapri(a.cross_csv)
        cross.to_parquet(p["cross"])
        manifest["cross_check"] = {"source_url": CROSS_SOURCE, "sha256": hashlib.sha256(raw).hexdigest(),
                                   "first_bar_ist": str(cross.index.min()), "last_bar_ist": str(cross.index.max()),
                                   "rows": int(len(cross))}
    p["manifest"].parent.mkdir(parents=True, exist_ok=True)
    p["manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
