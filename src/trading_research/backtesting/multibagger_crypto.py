"""EXP-0053: crypto multibagger base rates on Binance USDT spot pairs (research only, descriptive).

For each cohort start (first UTC day of January 2018..2023) take every research USDT pair (no stablecoins,
leveraged tokens or wrapped copies) with a close that day, and measure the end-to-end multiple after 3 and 5
years (close on the first day of the end January). A pair whose last archived month is before the end month is
"gone" (delisted by Binance) and keeps its last archived close. Screens use only what was known at the start:
6-month trend (vs the July close), quote volume in the start month, and age since the pair's first month.

Source: data.binance.vision monthly 1d klines (only January and July files plus each pair's first and last month
are downloaded). USDT prices; INR, fees, tax and exchange risk are not included. Binance lists coins that are
already established, so this is not the universe of all coins (most small coins never reach Binance).

CLI: python -m trading_research.backtesting.multibagger_crypto --dir data/mb/crypto --out reports/backtests
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

STARTS = list(range(2018, 2024))
# Token redenominations found as single-day price jumps in the full daily archive of every pair with an
# end-to-end multiple above 15x or below 0.02x (one-off check of every month of those 34 pairs, 2026-11-01). Factor = one-day price multiple at the swap,
# rounded to the nominal swap ratio (the observed one-day jump was 1295x, 107x, 0.0008x, 0.0012x, 0.009x).
REDENOMINATIONS = {
    "COCOSUSDT": ("2021-01-23", 1000.0), "DREPUSDT": ("2021-04-02", 100.0), "QUICKUSDT": ("2023-07-21", 0.001),
    "SUNUSDT": ("2021-06-18", 0.001), "BNXUSDT": ("2023-02-22", 0.01),
}
# LUNAUSDT collapsed in May 2022 (one-day move to 0.0003x) and the ticker was reused for a new token from
# 2022-05-31; holders of the original coin are counted as a total loss for windows ending after that date.
LUNA_REUSE = pd.Timestamp("2022-05-31")


def load(dir_: Path) -> tuple[pd.DataFrame, dict]:
    frames, months = [], {}
    for p in sorted(dir_.glob("*.parquet")):
        frames.append(pd.read_parquet(p))
        months[p.stem] = json.loads((dir_ / f"{p.stem}.months.json").read_text())
    return pd.concat(frames, ignore_index=True), months


def cohort(bars: pd.DataFrame, months: dict, year: int, horizon: int) -> pd.DataFrame | None:
    t0, t1 = pd.Timestamp(year, 1, 1), pd.Timestamp(year + horizon, 1, 1)
    if t1 > pd.Timestamp("2026-10-01"):
        return None
    jul = pd.Timestamp(year - 1, 7, 1)
    at0 = bars[bars["date"] == t0].set_index("symbol")
    at1 = bars[bars["date"] == t1].set_index("symbol")["close"]
    atj = bars[bars["date"] == jul].set_index("symbol")["close"]
    jan_vol = bars[(bars["date"] >= t0) & (bars["date"] < t0 + pd.Timedelta(days=31))].groupby("symbol")["quote_volume"].sum()
    rows = []
    for s, r in at0.iterrows():
        m = months[s]
        end_m = f"{year + horizon}-01"
        gone = m[-1] < end_m
        if gone:
            last = bars[bars["symbol"] == s].sort_values("date").iloc[-1]
            end_close = last["close"]
        else:
            end_close = at1.get(s, np.nan)
        ratio = end_close / r["close"]
        end_date = t1 if not gone else pd.Timestamp(m[-1] + "-28")
        if s in REDENOMINATIONS and t0 < pd.Timestamp(REDENOMINATIONS[s][0]) <= end_date:
            ratio /= REDENOMINATIONS[s][1]
        if s == "LUNAUSDT" and t0 < LUNA_REUSE <= end_date:
            ratio, gone = 0.0, True
        rows.append({"symbol": s, "start_year": year, "horizon": horizon, "start_close": r["close"],
                     "ratio": ratio, "gone": gone, "mom6": r["close"] / atj.get(s, np.nan) - 1,
                     "jan_quote_vol": jan_vol.get(s, np.nan), "age_months": _age(m[0], year)})
    df = pd.DataFrame(rows).dropna(subset=["ratio"])
    df["vol_q"] = pd.qcut(df["jan_quote_vol"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    df["mom_q"] = pd.qcut(df["mom6"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(float) if df["mom6"].notna().sum() >= 10 else np.nan
    return df


def _age(first_month: str, year: int) -> int:
    y, mth = map(int, first_month.split("-"))
    return (year - y) * 12 + (1 - mth)


SCREENS = {
    "all pairs": lambda f: f.index == f.index,
    "BTCUSDT": lambda f: f["symbol"] == "BTCUSDT",
    "ETHUSDT": lambda f: f["symbol"] == "ETHUSDT",
    "lowest-volume 20%": lambda f: f["vol_q"] == 1,
    "highest-volume 20%": lambda f: f["vol_q"] == 5,
    "listed < 12 months": lambda f: f["age_months"] < 12,
    "listed >= 24 months": lambda f: f["age_months"] >= 24,
    "top 20% 6m trend": lambda f: f["mom_q"] == 5,
    "bottom 20% 6m trend": lambda f: f["mom_q"] == 1,
}


def summarise(rows: pd.DataFrame) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    r = rows["ratio"]
    return {"n": int(n), "pct_10x": round(100 * (r >= 10).mean(), 1), "pct_5x": round(100 * (r >= 5).mean(), 1),
            "pct_beat_btc": None, "pct_lost_80": round(100 * (r <= 0.2).mean(), 1),
            "pct_gone": round(100 * rows["gone"].mean(), 1), "median_x": round(float(r.median()), 3),
            "mean_x": round(float(r.mean()), 3)}


def run(dir_: Path, out: Path) -> dict:
    bars, months = load(dir_)
    data = pd.concat([c for h in (3, 5) for y in STARTS if (c := cohort(bars, months, y, h)) is not None])
    btc = data[data["symbol"] == "BTCUSDT"].set_index(["start_year", "horizon"])["ratio"]
    data["beat_btc"] = [r > btc.get((y, h), np.inf) for r, y, h in zip(data["ratio"], data["start_year"], data["horizon"])]
    res = {"screens": {}, "per_cohort": {}}
    for h in (3, 5):
        sub = data[data["horizon"] == h]
        for name, fn in SCREENS.items():
            s = sub[np.asarray(fn(sub))]
            d = summarise(s)
            d["pct_beat_btc"] = round(100 * s["beat_btc"].mean(), 1) if len(s) else None
            res["screens"][f"{h}y | {name}"] = d
        for y, s in sub.groupby("start_year"):
            d = summarise(s)
            d["pct_beat_btc"] = round(100 * s["beat_btc"].mean(), 1)
            d["btc_x"] = round(float(btc.get((y, h), np.nan)), 2)
            res["per_cohort"][f"{h}y {y}"] = d
    out.mkdir(parents=True, exist_ok=True)
    (out / "EXP-0053-crypto-multibagger-base-rates.json").write_text(json.dumps(res, indent=1))
    data.to_parquet(dir_.parent / "crypto_cohorts.parquet", index=False)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/mb/crypto"))
    ap.add_argument("--out", type=Path, default=Path("reports/backtests"))
    a = ap.parse_args(argv)
    print(json.dumps(run(a.dir, a.out), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
