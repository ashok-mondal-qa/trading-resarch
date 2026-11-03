"""Unofficial 1-minute bars for NSE stocks and indices, checked day by day against official NSE daily files
(spec docs/strategy-specifications/intraday-three-families.md).

Sources (all UNOFFICIAL, hashed into a manifest, never repaired):
  * stocks: GitHub `ShabbirHasan1/NSE-Data` (GPL-3.0), "NSE Minute Data/NSE_Stocks_Data/<SYM>__EQ__NSE__NSE__MINUTE.csv",
    2017-01..2020-12, split/bonus adjusted by the vendor, with volume;
  * NIFTY 50: `technovusin/nifty50-historical-data` via `nifty_intraday` (PR #22); the Shabbir NIFTY 50 file is used
    for the 2017-2020 stock-universe market filter;
  * NIFTY BANK: `sandeepkapri/BankNifty-Data` (MIT) bank-nifty-1m-data.csv.

Stock gate 1: scale factors official_high / vendor_high and official_low / vendor_low (NSE CM bhavcopy, EQ) must
agree within 0.10%; the day's real prices are the vendor's times that factor. Vendor names are mapped to the NSE
symbol in force on the date through NSE symbolchange.csv; the factor check confirms the match.

CLI:  python -m trading_research.data.minute_vendor --shabbir <clone> --banknifty <clone> --official-root data/s17
"""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import bhavcopy, indices, symbols
from trading_research.data.nifty_intraday import clean, day_check

DATASET = "intraday_minute_vendor"
SHABBIR = "https://github.com/ShabbirHasan1/NSE-Data"
BANKNIFTY_SRC = "https://github.com/sandeepkapri/BankNifty-Data"
VENDOR_TO_NSE = {"BAJAJ_AUTO": "BAJAJ-AUTO", "M_M": "M&M", "L_TFH": "L&TFH", "M_MFIN": "M&MFIN",
                 "NAM_INDIA": "NAM-INDIA"}
FACTOR_TOL = 0.10 / 100
MIN_BARS = 360


def out_dir(root: Path = REPO_ROOT / "data") -> Path:
    return root / "processed" / DATASET


def nse_symbol(vendor: str) -> str:
    return VENDOR_TO_NSE.get(vendor, vendor)


def read_shabbir(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv)
    ts = pd.to_datetime(df["timestamp"].str.slice(0, 19))  # "+05:30" stripped: values are IST wall time
    bars = clean(pd.DataFrame({"ts": ts, "open": df["open"], "high": df["high"], "low": df["low"],
                               "close": df["close"], "volume": df["volume"]}))
    return bars.between_time("09:15", "15:29")


def read_banknifty(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv)
    ts = pd.to_datetime(df["Date"] + " " + df["Time"], format="%d-%m-%Y %H:%M:%S")
    return clean(pd.DataFrame({"ts": ts, "open": df["Open"], "high": df["High"], "low": df["Low"],
                               "close": df["Close"]})).between_time("09:15", "15:29")


def stock_factor_check(vend_high: float, vend_low: float, off_high: float, off_low: float) -> tuple[str, float]:
    """('ok', factor) when both extremes scale to the official ones by the same factor, else (reason, nan)."""
    if not (off_high > 0 and off_low > 0 and vend_high > 0 and vend_low > 0):
        return "no official bar", np.nan
    fh, fl = off_high / vend_high, off_low / vend_low
    if abs(fh / fl - 1) > FACTOR_TOL:
        return f"high/low factors differ ({fh:.4f} vs {fl:.4f})", np.nan
    return "ok", (fh + fl) / 2


def candidates(sym: str, changes: pd.DataFrame) -> list[tuple[str, pd.Timestamp | None]]:
    """[(symbol, valid_before)]: the current symbol and its predecessors with the date they stopped being used."""
    out = [(sym, None)]
    for link in symbols.predecessors(sym, changes):
        out.append((link["old_symbol"], link["effective_date"]))
    return out


def prepare_stock(args: tuple) -> dict:
    csv, official_path, changes_path, dest = args
    vendor = csv.name.split("__")[0]
    sym = nse_symbol(vendor)
    official = pd.read_parquet(official_path)
    changes = pd.read_parquet(changes_path)
    names = [c[0] for c in candidates(sym, changes)]
    off = official[official["symbol"].isin(names)].copy()
    # one official row per date: the name in force (current symbol preferred when both exist)
    off["rank"] = off["symbol"].map({n: i for i, n in enumerate(names)})
    off = off.sort_values(["date", "rank"]).drop_duplicates("date").set_index("date")
    bars = read_shabbir(csv)
    raw_sha = hashlib.sha256(csv.read_bytes()).hexdigest()
    day_key = bars.index.normalize()
    rows = []
    for d, day in bars.groupby(day_key):
        rec = {"date": d, "bars": len(day), "vend_high": day["high"].max(), "vend_low": day["low"].min()}
        if len(day) < MIN_BARS:
            rec.update(status=f"only {len(day)} bars", factor=np.nan)
        elif d not in off.index:
            rec.update(status="no official bar", factor=np.nan)
        else:
            o = off.loc[d]
            st, f = stock_factor_check(rec["vend_high"], rec["vend_low"], o["high"], o["low"])
            rec.update(status=st, factor=f)
        rows.append(rec)
    vd = pd.DataFrame(rows).set_index("date")
    days = off[["symbol", "open", "high", "low", "close", "traded_value"]].join(vd, how="left")
    days["status"] = days["status"].fillna("no vendor bars")
    ok_days = set(days.index[days["status"] == "ok"])
    keep = bars[day_key.isin(ok_days)]
    dest.mkdir(parents=True, exist_ok=True)
    keep.to_parquet(dest / f"{sym}.parquet")
    days.reset_index().to_parquet(dest / f"{sym}_days.parquet", index=False)
    return {"vendor_file": csv.name, "symbol": sym, "sha256": raw_sha, "vendor_days": int(len(vd)),
            "ok_days": int(len(ok_days)), "first": str(bars.index.min()), "last": str(bars.index.max()),
            "fail_reasons": vd["status"].where(vd["status"] != "ok").dropna().str.split("(").str[0]
            .value_counts().to_dict()}


def prepare_index(bars: pd.DataFrame, official: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keeps index days passing `nifty_intraday.day_check`; returns (bars, days table)."""
    key = bars.index.normalize()
    rows, ok = [], set()
    for d, day in bars.groupby(key):
        if d in official.index:
            o = official.loc[d]
            st = day_check(day, o["high"], o["low"], min_bars=MIN_BARS)
        else:
            st = "no official bar"
        rows.append({"date": d, "status": st})
        if st == "ok":
            ok.add(d)
    vd = pd.DataFrame(rows).set_index("date")
    days = official[["open", "high", "low", "close"]].join(vd, how="left")
    days["status"] = days["status"].fillna("no vendor bars")
    return bars[key.isin(ok)], days


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shabbir", required=True, type=Path)
    ap.add_argument("--shabbir-commit", default="unknown")
    ap.add_argument("--banknifty", required=True, type=Path)
    ap.add_argument("--banknifty-commit", default="unknown")
    ap.add_argument("--official-root", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    dest = out_dir()
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / "_tmp"
    tmp.mkdir(exist_ok=True)
    store = bhavcopy.Store(a.official_root)
    official = bhavcopy.read_bars(date(2016, 11, 1), date(2020, 12, 31), store)
    official[["date", "symbol", "open", "high", "low", "close", "traded_value"]].to_parquet(tmp / "official.parquet")
    symbols.load_symbol_changes(a.official_root).to_parquet(tmp / "changes.parquet")
    files = sorted((a.shabbir / "NSE Minute Data" / "NSE_Stocks_Data").glob("*__EQ__NSE__NSE__MINUTE.csv"))
    jobs = [(f, tmp / "official.parquet", tmp / "changes.parquet", dest / "stocks") for f in files]
    with ProcessPoolExecutor(a.workers) as ex:
        stocks = list(ex.map(prepare_stock, jobs))

    def official_index(name: str) -> pd.DataFrame:
        return indices.read_index(name, date(2016, 11, 1), date(2026, 10, 31), a.official_root)

    idx_meta = {}
    nifty_off, bank_off = official_index("Nifty 50"), official_index("Nifty Bank")
    from trading_research.data import nifty_intraday
    sources = {
        "NIFTY": (nifty_intraday.load(), nifty_off, nifty_intraday.SOURCE),
        "BANKNIFTY": (read_banknifty(a.banknifty / "bank-nifty-1m-data.csv"), bank_off, BANKNIFTY_SRC),
        "NIFTY_S": (read_shabbir(a.shabbir / "NSE Minute Data" / "NSE_Index_Data" /
                                 "NIFTY_50__EQ__INDICES__NSE__MINUTE.csv"), nifty_off, SHABBIR),
    }
    (dest / "indices").mkdir(exist_ok=True)
    for name, (bars, off, src) in sources.items():
        bars = bars[bars.index >= "2017-01-01"]
        kept, days = prepare_index(bars, off)
        kept.to_parquet(dest / "indices" / f"{name}.parquet")
        days.reset_index().to_parquet(dest / "indices" / f"{name}_days.parquet", index=False)
        idx_meta[name] = {"source_url": src, "vendor_days": int((days["status"] != "no vendor bars").sum()),
                          "ok_days": int((days["status"] == "ok").sum()), "first": str(kept.index.min()),
                          "last": str(kept.index.max())}
    manifest = {
        "dataset": DATASET, "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "provider": "UNOFFICIAL GitHub vendors; each used day checked against NSE official daily files",
        "stocks_source": {"url": SHABBIR, "commit": a.shabbir_commit, "licence": "GPL-3.0",
                          "price_adjustment": "vendor split/bonus adjusted; real prices = vendor x daily factor"},
        "banknifty_source": {"url": BANKNIFTY_SRC, "commit": a.banknifty_commit, "licence": "MIT"},
        "gate1": {"stocks": f"high/low factors agree within {FACTOR_TOL:.2%}, >= {MIN_BARS} bars",
                  "indices": "nifty_intraday.day_check (0.05% vs NSE ind_close_all), >= 360 bars"},
        "stocks": stocks, "indices": idx_meta,
        "known_limitations": ["vendor chose the stock list in 2021 (survivorship), list stops at TATACHEM",
                              "minute bars unofficial; no order book", "index files have no volume"],
    }
    mpath = REPO_ROOT / "data" / "manifests" / DATASET / "manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    ok = sum(s["ok_days"] for s in stocks)
    vd = sum(s["vendor_days"] for s in stocks)
    print(json.dumps({"stocks": len(stocks), "stock_days_ok": ok, "stock_days_vendor": vd, "indices": idx_meta},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
