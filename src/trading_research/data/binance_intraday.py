"""Binance spot intraday candles (5-minute) from the official archive, data.binance.vision.

Source: data/spot/monthly/klines/<SYMBOL>/5m/<SYMBOL>-5m-YYYY-MM.zip with a published SHA-256 `.CHECKSUM`
(same provenance rules as `binance.py`: raw zip kept, checksum verified, a mismatch drops the month, nothing
filled). Bars are stamped with their UTC open time. Missing bars (exchange outages and maintenance) are listed
in the manifest and never filled; longer bars (15m, 1h) are built from complete 5m groups only.

CLI:  python -m trading_research.data.binance_intraday --symbols BTCUSDT ETHUSDT --end 2024-12
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import bhavcopy
from trading_research.data.binance import ARCHIVE, KLINE_COLUMNS, PREFIX, _fetch_month, http_fetch, list_keys

INTERVAL = "5m"
DATASET = f"binance_spot_{INTERVAL}"
BAR = pd.Timedelta(minutes=5)


def paths(root: Path, symbol: str) -> dict[str, Path]:
    return {"raw": root / "raw" / DATASET / symbol, "bars": root / "processed" / DATASET / f"{symbol}.parquet",
            "manifest": root / "manifests" / DATASET / f"{symbol}.json"}


def parse_klines(raw_zip: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise bhavcopy.BhavcopyError(f"expected one csv in the zip, found {names}")
        text = z.read(names[0])
    df = pd.read_csv(io.BytesIO(text), header=None)
    if not str(df.iloc[0, 0]).strip().lstrip("-").isdigit():
        df = df.iloc[1:]
    df = df.iloc[:, : len(KLINE_COLUMNS)]
    df.columns = KLINE_COLUMNS[: df.shape[1]]
    ts = pd.to_numeric(df["open_time"]).astype("int64")
    ts = ts.where(ts < 10**14, ts // 1000)                       # microseconds from 2025 -> milliseconds
    out = pd.DataFrame({"time": pd.to_datetime(ts, unit="ms")})
    for col in ("open", "high", "low", "close", "volume", "quote_volume", "trades"):
        out[col] = pd.to_numeric(df[col], errors="coerce").to_numpy()
    return out


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Drop unusable candles (never repaired). Zero-volume bars with valid prices are kept."""
    px = df[["open", "high", "low", "close"]]
    bad = (px.isna().any(axis=1) | (px <= 0).any(axis=1) | (df["high"] < px[["open", "close"]].max(axis=1))
           | (df["low"] > px[["open", "close"]].min(axis=1)) | df["volume"].isna() | (df["volume"] < 0)
           | (df["time"].dt.second != 0) | (df["time"].dt.minute % 5 != 0))
    dup = df["time"].duplicated(keep=False)
    excluded = [{"time": str(t), "reason": "duplicate time" if u else "invalid candle"}
                for t, u in zip(df.loc[bad | dup, "time"], dup[bad | dup])]
    return df[~(bad | dup)].reset_index(drop=True), excluded


def gaps(times: pd.Series) -> list[dict]:
    """Runs of missing 5m bars between the first and last bar."""
    t = times.sort_values().reset_index(drop=True)
    step = t.diff()
    out = []
    for i in step.index[step > BAR]:
        out.append({"after": str(t[i - 1]), "before": str(t[i]), "missing_bars": int(step[i] / BAR) - 1})
    return out


def load_symbol(symbol: str, end_month: str, root: Path = REPO_ROOT / "data", fetch=http_fetch,
                start_month: str = "2017-01") -> dict:
    p = paths(root, symbol)
    keys = [k for k in list_keys(f"{PREFIX}{symbol}/{INTERVAL}/", None, fetch) if k.endswith(".zip")]
    keys = sorted(k for k in keys if start_month <= k[-11:-4] <= end_month)
    frames, files, problems = [], [], []
    for key in keys:
        name, data, status = _fetch_month(key, p["raw"], fetch)
        if status != "ok":
            problems.append({"file": name, "status": status})
            continue
        frames.append(parse_klines(data))
        files.append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
    bars = pd.concat(frames, ignore_index=True).sort_values("time") if frames else pd.DataFrame()
    excluded, missing = [], []
    if len(bars):
        bars, excluded = validate(bars)
        missing = gaps(bars["time"])
        bars.insert(0, "symbol", symbol)
        p["bars"].parent.mkdir(parents=True, exist_ok=True)
        bars.to_parquet(p["bars"], index=False)
    manifest = {
        "dataset": DATASET, "provider": "Binance public data archive",
        "source": f"{ARCHIVE}/{PREFIX}{symbol}/{INTERVAL}/", "instrument": symbol, "exchange": "Binance spot",
        "timeframe": "5m, stamped with UTC open time", "first_bar": str(bars["time"].min()) if len(bars) else None,
        "last_bar": str(bars["time"].max()) if len(bars) else None, "end_month_requested": end_month,
        "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "rows": int(len(bars)),
        "gaps": missing, "missing_bars": int(sum(g["missing_bars"] for g in missing)), "excluded": excluded[:200],
        "excluded_count": len(excluded), "file_problems": problems, "files": files,
        "status": ("ok" if len(bars) and not problems else ("partial" if len(bars) else "DATA INSUFFICIENT")),
        "price_adjustment": "none (prices as traded in USDT)",
        "licence": "Binance public market data; research use. Not an endorsement of trading on Binance.",
    }
    p["manifest"].parent.mkdir(parents=True, exist_ok=True)
    p["manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_bars(symbol: str, root: Path = REPO_ROOT / "data", end: str | None = None) -> pd.DataFrame:
    """5m bars indexed by UTC open time, strictly before `end` (YYYY-MM-DD) if given."""
    bars = pd.read_parquet(paths(root, symbol)["bars"]).set_index("time").sort_index()
    return bars[bars.index < pd.Timestamp(end)] if end else bars


def resample(bars: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Longer bars from complete groups of 5m bars only (a group with a missing 5m bar is dropped)."""
    need = int(pd.Timedelta(rule) / BAR)
    g = bars.resample(rule, label="left", closed="left")
    out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
                 "quote_volume": "sum"})
    out["bars"] = g["close"].count()
    return out[out["bars"] == need].drop(columns="bars")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--end", required=True, help="last month to load, YYYY-MM")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args(argv)

    def one(s):
        try:
            m = load_symbol(s, args.end)
            return s, m["status"], m["rows"], m["missing_bars"]
        except Exception as exc:  # reported, never silently skipped
            return s, f"error: {exc}", 0, 0
    with ThreadPoolExecutor(args.workers) as pool:
        for row in pool.map(one, args.symbols):
            print(*row, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
