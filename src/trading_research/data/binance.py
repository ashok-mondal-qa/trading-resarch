"""Binance spot daily candles (klines) from Binance's official public data archive, data.binance.vision.

Source: https://data.binance.vision/data/spot/monthly/klines/<SYMBOL>/1d/<SYMBOL>-1d-YYYY-MM.zip, one file per
symbol and month, each with a published SHA-256 `.CHECKSUM`. The bucket listing (S3, ap-northeast-1) also
holds symbols Binance has since delisted, so the universe can be built point in time. Same provenance rules
as the NSE loaders: raw zip kept byte for byte, checksum verified (a mismatch fails closed), one manifest per
symbol, missing months never filled.

Bars are UTC calendar days (open 00:00 UTC = 05:30 IST). Prices are in the quote asset (USDT), as traded;
crypto has no corporate actions to adjust. From 2025-01-01 Binance writes spot timestamps in microseconds;
both units are read.

CLI:  python -m trading_research.data.binance --list            # USDT pairs in the archive
      python -m trading_research.data.binance --load --end 2026-09
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import bhavcopy

DATASET = "binance_spot_1d"
ARCHIVE = "https://data.binance.vision"
LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
PREFIX = "data/spot/monthly/klines/"
DAILY_PREFIX = "data/spot/daily/klines/"
KLINE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
                 "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
QUOTE = "USDT"
# Bases that are not a crypto asset with its own price risk: stablecoins, fiat, gold tokens, wrapped or
# staked copies of BTC/ETH/BNB (they duplicate the original).
EXCLUDED_BASES = {
    "USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD", "USDS", "USDSB", "SUSD", "UST", "USTC", "USDE",
    "USD1", "BFUSD", "XUSD", "RLUSD", "AEUR", "EUR", "EURI", "GBP", "AUD", "BRL", "TRY", "RUB", "UAH", "NGN",
    "BIDR", "IDRT", "BVND", "ZAR", "JPY", "MXN", "ARS", "COP", "PLN", "RON", "CZK", "PAXG", "XAUT", "WBTC",
    "WBETH", "BETH", "BNSOL", "STETH",
}
LEVERAGED = re.compile(r"(UP|DOWN|BULL|BEAR)$")
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def _q(text: str) -> str:
    """Percent-encode a key for a URL (some pair names are not ASCII)."""
    return urllib.parse.quote(text, safe="/")


def http_fetch(url: str) -> bytes | None:
    return bhavcopy.http_fetch(url, retries=4, timeout=60.0)


def list_keys(prefix: str, delimiter: str | None = "/", fetch=http_fetch, start_after: str = "") -> list[str]:
    """Every common prefix (with a delimiter) or key (without) under `prefix` that sorts after `start_after`,
    following S3 pagination."""
    out, marker = [], start_after
    while True:
        url = f"{LISTING}?prefix={_q(prefix)}&marker={_q(marker)}" + (f"&delimiter={delimiter}" if delimiter else "")
        raw = fetch(url)
        if raw is None:
            raise bhavcopy.BhavcopyError(f"listing failed: {url}")
        root = ET.fromstring(raw)
        tag = "s3:CommonPrefixes/s3:Prefix" if delimiter else "s3:Contents/s3:Key"
        page = [e.text for e in root.findall(tag, NS)]
        out.extend(page)
        if root.findtext("s3:IsTruncated", default="false", namespaces=NS) != "true" or not page:
            return out
        marker = root.findtext("s3:NextMarker", default="", namespaces=NS) or page[-1]


def is_research_pair(symbol: str, quote: str = QUOTE) -> bool:
    if not symbol.endswith(quote) or symbol == quote:
        return False
    base = symbol[: -len(quote)]
    return base not in EXCLUDED_BASES and not LEVERAGED.search(base)


def list_symbols(fetch=http_fetch, quote: str = QUOTE) -> list[str]:
    prefixes = list_keys(PREFIX, "/", fetch)
    symbols = [p[len(PREFIX):].rstrip("/") for p in prefixes]
    return sorted(s for s in symbols if is_research_pair(s, quote))


def parse_klines(raw_zip: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise bhavcopy.BhavcopyError(f"expected one csv in the zip, found {names}")
        text = z.read(names[0])
    df = pd.read_csv(io.BytesIO(text), header=None)
    if not str(df.iloc[0, 0]).strip().lstrip("-").isdigit():   # some files carry a header row
        df = df.iloc[1:]
    df = df.iloc[:, : len(KLINE_COLUMNS)]
    df.columns = KLINE_COLUMNS[: df.shape[1]]
    ts = pd.to_numeric(df["open_time"])
    unit = pd.Series("ms", index=df.index).where(ts < 10**14, "us")
    df["date"] = [pd.Timestamp(int(t), unit=u).normalize() for t, u in zip(ts, unit)]
    for col in ("open", "high", "low", "close", "volume", "quote_volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
    return df[["date", "open", "high", "low", "close", "volume", "quote_volume", "trades"]].reset_index(drop=True)


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Drop rows that are not usable candles (never repaired); return kept rows and the exclusions."""
    bad = (df[["open", "high", "low", "close"]].isna().any(axis=1) | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
           | (df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))
           | df["volume"].isna() | (df["volume"] < 0))
    dup = df["date"].duplicated(keep=False)
    excluded = [{"date": str(d.date()), "reason": "duplicate date" if u else "invalid candle"}
                for d, u in zip(df.loc[bad | dup, "date"], dup[bad | dup])]
    return df[~(bad | dup)].reset_index(drop=True), excluded


def paths(root: Path, symbol: str) -> dict[str, Path]:
    return {"raw": root / "raw" / DATASET / symbol, "bars": root / "processed" / DATASET / f"{symbol}.parquet",
            "manifest": root / "manifests" / DATASET / f"{symbol}.json"}


def _fetch_month(key: str, raw_dir: Path, fetch) -> tuple[str, bytes | None, str]:
    name = key.rsplit("/", 1)[-1]
    target = raw_dir / name
    if target.exists():
        data = target.read_bytes()
    else:
        data = fetch(f"{ARCHIVE}/{_q(key)}")
        if data is None:
            return name, None, "not_found"
    checksum = fetch(f"{ARCHIVE}/{_q(key)}.CHECKSUM")
    if checksum is None:
        return name, None, "checksum missing"
    expected = checksum.decode().split()[0].strip().lower()
    if hashlib.sha256(data).hexdigest() != expected:
        return name, None, "checksum mismatch"
    if not target.exists():
        raw_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return name, data, "ok"


def load_symbol(symbol: str, end_month: str, root: Path = REPO_ROOT / "data", fetch=http_fetch,
                daily_through: str | None = None) -> dict:
    """Download (or re-verify) every monthly 1d file up to `end_month` (YYYY-MM), then, if `daily_through`
    (YYYY-MM-DD) is given, the daily 1d files after that month up to that day; write bars + manifest."""
    p = paths(root, symbol)
    keys = [k for k in list_keys(f"{PREFIX}{symbol}/1d/", None, fetch) if k.endswith(".zip")]
    keys = sorted(k for k in keys if k[-11:-4] <= end_month)
    if daily_through:
        daily = f"{DAILY_PREFIX}{symbol}/1d/"
        after = f"{daily}{symbol}-1d-{end_month}-32"            # sorts after every day of end_month
        keys += sorted(k for k in list_keys(daily, None, fetch, after)
                       if k.endswith(".zip") and k[-14:-4] <= daily_through)
    frames, months, problems = [], [], []
    for key in keys:
        name, data, status = _fetch_month(key, p["raw"], fetch)
        if status != "ok":
            problems.append({"file": name, "status": status})
            continue
        frames.append(parse_klines(data))
        months.append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
    bars = pd.concat(frames, ignore_index=True).sort_values("date") if frames else pd.DataFrame()
    excluded = []
    if len(bars):
        bars, excluded = validate(bars)
        bars.insert(0, "symbol", symbol)
        p["bars"].parent.mkdir(parents=True, exist_ok=True)
        bars.to_parquet(p["bars"], index=False)
    calendar = pd.date_range(bars["date"].min(), bars["date"].max(), freq="D") if len(bars) else []
    missing = sorted(set(calendar) - set(bars["date"])) if len(bars) else []
    manifest = {
        "dataset": DATASET, "provider": "Binance public data archive", "source": f"{ARCHIVE}/{PREFIX}{symbol}/1d/",
        "instrument": symbol, "exchange": "Binance spot", "timeframe": "1d (UTC day, open 00:00 UTC)",
        "first_bar": str(bars["date"].min().date()) if len(bars) else None,
        "last_bar": str(bars["date"].max().date()) if len(bars) else None, "end_month_requested": end_month, "daily_through_requested": daily_through,
        "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "price_adjustment": "none (no corporate actions; prices as traded in USDT)", "rows": int(len(bars)),
        "missing_days": [str(d.date()) for d in missing], "excluded": excluded, "file_problems": problems,
        "files": months,
        "status": "ok" if len(bars) and not problems and not missing and not excluded else ("partial" if len(bars) else "DATA INSUFFICIENT"),
        "licence": "Binance public market data; research use. Not an endorsement of trading on Binance.",
        "known_limitations": ["one exchange only (Binance spot, USDT quote); prices differ from Indian INR exchanges",
                              "symbols delisted before the archive began are absent"],
    }
    p["manifest"].parent.mkdir(parents=True, exist_ok=True)
    p["manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_bars(symbol: str, root: Path = REPO_ROOT / "data") -> pd.DataFrame:
    return pd.read_parquet(paths(root, symbol)["bars"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--end", default="2026-09", help="last month to load, YYYY-MM")
    parser.add_argument("--daily-through", help="then daily files after --end up to this day, YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    symbols = args.symbols or list_symbols()
    if args.list:
        print("\n".join(symbols))
        print(f"{len(symbols)} {QUOTE} pairs", flush=True)
        return 0
    if args.load:
        def one(s):
            try:
                m = load_symbol(s, args.end, daily_through=args.daily_through)
                return s, m["status"], m["rows"]
            except Exception as exc:  # reported, never silently skipped
                return s, f"error: {exc}", 0
        with ThreadPoolExecutor(args.workers) as pool:
            for s, status, rows in pool.map(one, symbols):
                print(s, status, rows, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
