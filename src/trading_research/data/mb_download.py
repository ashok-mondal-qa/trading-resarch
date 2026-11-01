"""Fast raw downloads for the multibagger base-rate study (EXP-0052/0053). Research only; data stays in
git-ignored data/mb/.

  python -m trading_research.data.mb_download nse [START END]   # NSE CM bhavcopy, slim per-day parquet
  python -m trading_research.data.mb_download crypto            # Binance USDT pairs: Jan/Jul + first/last month
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import binance as bn
from trading_research.data import bhavcopy as b

ROOT = REPO_ROOT / "data" / "mb"


def nse(start: date = date(2004, 1, 1), end: date | None = None, workers: int = 10) -> dict:
    out = ROOT / "nse_days"
    out.mkdir(parents=True, exist_ok=True)
    end = end or date.today()
    days = [start + timedelta(d) for d in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() < 5 and not (out / f"{d}.parquet").exists() and not (out / f"{d}.none").exists()]

    def one(d):
        for fmt, url in b.candidate_urls(d):
            raw = b.http_fetch(url, retries=3, timeout=40)
            if raw:
                df = b.parse_bhavcopy(raw, fmt, optional=("ISIN", "TOTALTRADES"))
                df[["date", "symbol", "series", "isin", "close", "prev_close", "volume", "traded_value", "high", "low"]] \
                    .to_parquet(out / f"{d}.parquet", index=False)
                return "ok"
        if d < date.today() - timedelta(days=3):
            (out / f"{d}.none").touch()      # holiday / no file; only marked once safely in the past
        return "none"

    stats: dict = {}
    with ThreadPoolExecutor(workers) as ex:
        for s in ex.map(one, days):
            stats[s] = stats.get(s, 0) + 1
    return stats


def crypto(workers: int = 12) -> dict:
    out = ROOT / "crypto"
    out.mkdir(parents=True, exist_ok=True)

    def one(s):
        if (out / f"{s}.parquet").exists():
            return "skip"
        keys = [k for k in bn.list_keys(f"{bn.PREFIX}{s}/1d/", None) if k.endswith(".zip")]
        months = sorted(k[-11:-4] for k in keys)
        if not months:
            return "empty"
        want = {m for m in months if m.endswith("-01") or m.endswith("-07")} | {months[0], months[-1]}
        frames = []
        for m in sorted(want):
            raw = bn.http_fetch(bn.ARCHIVE + bn._q(f"/{bn.PREFIX}{s}/1d/{s}-1d-{m}.zip"))
            if raw:
                d = bn.parse_klines(raw)
                d["symbol"] = s
                frames.append(d)
        pd.concat(frames).to_parquet(out / f"{s}.parquet", index=False)
        (out / f"{s}.months.json").write_text(json.dumps(months))
        return "ok"

    stats: dict = {}
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, bn.list_symbols()):
            stats[r] = stats.get(r, 0) + 1
    return stats


if __name__ == "__main__":
    t0 = time.time()
    if sys.argv[1] == "nse":
        args = [date.fromisoformat(x) for x in sys.argv[2:4]]
        print(nse(*args))
    else:
        print(crypto())
    print(f"{time.time() - t0:.0f}s")
