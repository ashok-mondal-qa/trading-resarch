"""EXP-0052: multibagger base rates on NSE (research only, descriptive; no trading rule, no orders).

Question: of every NSE stock listed at the start of a year, what share became a 5x / 10x over the next 3 or 5
years, and do simple, observable-at-the-time screens (price level, liquidity, trend, volatility, distance from the
52-week high) raise that share? Everything is computed from NSE CM bhavcopies.

Returns are split/bonus adjusted by chaining NSE's own adjusted previous close: r_t = close_t / prev_close_t
(NSE restates prev_close on the ex-date). Dividends are excluded. A stock that stops trading before the window
ends is "gone" and keeps its last ratio (a delisting buy-out and a collapse look the same here; both are
reported). Single-day moves above 3x or below 1/3 are flagged as possible data errors and the stock-window is
dropped from the counts (reported).

Dev cohorts: starts 2006..2014. Check cohorts: starts 2015..2021 (5y) / 2015..2023 (3y). All of these years were
already read by earlier experiments, so this is not an out-of-sample test of anything; it measures how often
multibaggers happen and whether a screen's lift repeats across eras.

CLI: python -m trading_research.backtesting.multibagger_base_rates --days data/mb/nse_days --out reports/backtests
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.data import symbols

SERIES_PRIORITY = {"EQ": 0, "BE": 1, "BZ": 2, "SM": 3, "ST": 4}
DEV_STARTS = list(range(2006, 2015))
CHECK_STARTS = list(range(2015, 2024))
SUSPECT_JUMP = 3.0


def build_panel(day_dir: Path, changes: pd.DataFrame) -> pd.DataFrame:
    frames = [pd.read_parquet(p) for p in sorted(day_dir.glob("*.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["series"].isin(SERIES_PRIORITY)]
    isin = df["isin"].fillna("")
    etf_like = isin.str.startswith("INF") | df["symbol"].str.contains(r"BEES$|ETF|IETF|GOLD$", regex=True)
    df = df[~etf_like].copy()
    for _, ch in changes.sort_values("effective_date").iterrows():
        m = (df["symbol"] == ch["old_symbol"]) & (df["date"] < ch["effective_date"])
        df.loc[m, "symbol"] = ch["new_symbol"]
    df["prio"] = df["series"].map(SERIES_PRIORITY)
    df = df.sort_values(["symbol", "date", "prio"]).drop_duplicates(["symbol", "date"], keep="first")
    df = df[(df["close"] > 0) & (df["prev_close"] > 0)]
    df["r"] = df["close"] / df["prev_close"]
    df["suspect"] = (df["r"] > SUSPECT_JUMP) | (df["r"] < 1 / SUSPECT_JUMP)
    df["logr"] = np.log(df["r"])
    df["cum"] = df.groupby("symbol")["logr"].cumsum()
    return df[["date", "symbol", "series", "isin", "close", "traded_value", "r", "logr", "cum", "suspect"]]


def first_session_on_or_after(dates: pd.DatetimeIndex, ts: pd.Timestamp) -> pd.Timestamp | None:
    i = dates.searchsorted(ts)
    return dates[i] if i < len(dates) else None


def cohort(panel: pd.DataFrame, dates: pd.DatetimeIndex, year: int, horizon: int) -> pd.DataFrame | None:
    start = first_session_on_or_after(dates, pd.Timestamp(year, 1, 1))
    end = first_session_on_or_after(dates, pd.Timestamp(year + horizon, 1, 1))
    if start is None or end is None or end > dates[-1]:
        return None
    i0 = dates.get_loc(start)
    look0 = dates[max(0, i0 - 252)]
    look21 = dates[max(0, i0 - 21)]
    look63 = dates[max(0, i0 - 63)]
    hist = panel[(panel["date"] >= look0) & (panel["date"] <= start)]
    at = hist[hist["date"] == start].set_index("symbol")
    g = hist.groupby("symbol")
    feat = pd.DataFrame({
        "price": at["close"],
        "cum0": at["cum"],
        "series": at["series"],
    }).dropna(subset=["price"])
    recent = hist[hist["date"] > look63].groupby("symbol")
    feat["days63"] = recent.size()
    feat["liq"] = recent["traded_value"].median()
    feat["cum_252"] = g["cum"].first()
    feat["first_date"] = g["date"].first()
    feat["cum_21"] = hist[hist["date"] <= look21].groupby("symbol")["cum"].last()
    feat["max_cum"] = g["cum"].max()
    feat["vol"] = g["logr"].std() * np.sqrt(252)
    feat["suspect_pre"] = g["suspect"].any()
    feat = feat[(feat["days63"] >= 40)]
    full_year = feat["first_date"] <= look0 + pd.Timedelta(days=7)
    feat["mom12_1"] = np.where(full_year, np.exp(feat["cum_21"] - feat["cum_252"]) - 1, np.nan)
    feat["off_high"] = np.exp(feat["cum0"] - feat["max_cum"]) - 1

    fut = panel[(panel["date"] > start) & (panel["date"] <= end) & panel["symbol"].isin(feat.index)]
    gf = fut.groupby("symbol")
    feat["last_date"] = gf["date"].max()
    feat["cum_end"] = gf["cum"].last()
    feat["cum_peak"] = gf["cum"].max()
    feat["suspect_post"] = gf["suspect"].any()
    feat["ratio"] = np.exp(feat["cum_end"] - feat["cum0"])
    feat["peak"] = np.exp(feat["cum_peak"] - feat["cum0"])
    feat["gone"] = feat["last_date"].isna() | (feat["last_date"] < end - pd.Timedelta(days=45))
    feat["ratio"] = feat["ratio"].fillna(1.0)   # never traded again after start: treat as unknown flat, flagged gone
    feat["peak"] = feat["peak"].fillna(1.0)
    feat["suspect"] = feat["suspect_pre"].fillna(False) | feat["suspect_post"].fillna(False)
    feat["liq_q"] = pd.qcut(feat["liq"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    feat["mom_q"] = pd.qcut(feat["mom12_1"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(float)
    feat["vol_q"] = pd.qcut(feat["vol"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    feat["start_year"], feat["horizon"] = year, horizon
    return feat.reset_index().rename(columns={"index": "symbol"})


SCREENS = {
    "all stocks": lambda f: f.index == f.index,
    "penny (< Rs 10)": lambda f: f["price"] < 10,
    "price Rs 10-50": lambda f: (f["price"] >= 10) & (f["price"] < 50),
    "price > Rs 500": lambda f: f["price"] >= 500,
    "least liquid 20%": lambda f: f["liq_q"] == 1,
    "most liquid 20%": lambda f: f["liq_q"] == 5,
    "liquidity 2nd-4th 20%": lambda f: f["liq_q"].between(2, 4),
    "top 20% 12-1 momentum": lambda f: f["mom_q"] == 5,
    "bottom 20% 12-1 momentum": lambda f: f["mom_q"] == 1,
    "within 10% of 52w high": lambda f: f["off_high"] >= -0.10,
    "> 60% below 52w high": lambda f: f["off_high"] <= -0.60,
    "lowest-vol 20%": lambda f: f["vol_q"] == 1,
    "highest-vol 20%": lambda f: f["vol_q"] == 5,
    "small+trend: liq q2-3, top-40% mom, within 25% of high": lambda f: f["liq_q"].between(2, 3) & (f["mom_q"] >= 4) & (f["off_high"] >= -0.25),
    "small+trend+calm: above, vol below median": lambda f: f["liq_q"].between(2, 3) & (f["mom_q"] >= 4) & (f["off_high"] >= -0.25) & (f["vol_q"] <= 3),
    "penny + falling (< Rs 10, bottom-40% mom)": lambda f: (f["price"] < 10) & (f["mom_q"] <= 2),
}


def summarise(rows: pd.DataFrame) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    r = rows["ratio"]
    return {
        "n": int(n),
        "pct_10x": round(100 * (r >= 10).mean(), 2),
        "pct_5x": round(100 * (r >= 5).mean(), 2),
        "pct_3x": round(100 * (r >= 3).mean(), 2),
        "pct_peak_10x": round(100 * (rows["peak"] >= 10).mean(), 2),
        "pct_lost_half": round(100 * (r <= 0.5).mean(), 2),
        "pct_gone": round(100 * rows["gone"].mean(), 2),
        "median_x": round(float(r.median()), 3),
        "mean_x": round(float(r.mean()), 3),
        "top1pct_share_of_gains": round(float(_top_share(r)), 3),
    }


def _top_share(r: pd.Series) -> float:
    gains = (r - 1).clip(lower=0).sort_values(ascending=False)
    k = max(1, int(np.ceil(0.01 * len(r))))
    tot = gains.sum()
    return gains.iloc[:k].sum() / tot if tot > 0 else 0.0


def run(day_dir: Path, out_dir: Path) -> dict:
    cache = day_dir.parent / "nse_panel.parquet"
    if cache.exists():
        panel = pd.read_parquet(cache)
    else:
        panel = build_panel(day_dir, symbols.load_symbol_changes())
        panel.to_parquet(cache, index=False)
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    allc = []
    for h in (3, 5):
        for y in DEV_STARTS + CHECK_STARTS:
            c = cohort(panel, dates, y, h)
            if c is not None:
                allc.append(c)
    data = pd.concat(allc, ignore_index=True)
    suspect = data[data["suspect"]]
    clean = data[~data["suspect"]]
    result = {"sessions": [str(dates[0].date()), str(dates[-1].date()), len(dates)],
              "stock_windows": int(len(data)), "dropped_suspect": int(len(suspect)), "screens": {}}
    for h in (3, 5):
        for name, fn in SCREENS.items():
            for era, years in (("dev", DEV_STARTS), ("check", CHECK_STARTS)):
                sub = clean[(clean["horizon"] == h) & clean["start_year"].isin(years)]
                result["screens"][f"{h}y | {era} | {name}"] = summarise(sub[np.asarray(fn(sub))])
    per_year = {}
    for (h, y), sub in clean.groupby(["horizon", "start_year"]):
        per_year[f"{h}y {y}"] = summarise(sub)
    result["per_cohort"] = per_year
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "EXP-0052-multibagger-base-rates.json").write_text(json.dumps(result, indent=1))
    clean.to_parquet(day_dir.parent / "nse_cohorts.parquet", index=False)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=Path, default=Path("data/mb/nse_days"))
    ap.add_argument("--out", type=Path, default=Path("reports/backtests"))
    a = ap.parse_args(argv)
    res = run(a.days, a.out)
    print(json.dumps({k: v for k, v in res.items() if k != "per_cohort"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------- today's research watchlist (hypotheses only)

MCAP_URL = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{d:%d%m%y}.zip"


def load_mcap(day: pd.Timestamp) -> pd.DataFrame:
    """Market cap per symbol from NSE's PR archive (mcapDDMMYYYY.csv). Raises if missing (no made-up data)."""
    import io
    import zipfile
    from trading_research.data import bhavcopy
    raw = bhavcopy.http_fetch(MCAP_URL.format(d=day))
    if raw is None:
        raise bhavcopy.BhavcopyError(f"no PR archive for {day.date()}")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = next(n for n in zf.namelist() if n.lower().startswith("mcap"))
        m = pd.read_csv(zf.open(name), dtype=str)
    m.columns = [c.strip() for c in m.columns]
    out = pd.DataFrame({"symbol": m["Symbol"].str.strip(), "series": m["Series"].str.strip(),
                        "name": m["Security Name"].str.strip(), "category": m["Category"].str.strip(),
                        "mcap_cr": pd.to_numeric(m["Market Cap(Rs.)"].str.strip(), errors="coerce") / 1e7})
    return out[out["series"] == "EQ"].drop(columns="series")


def snapshot(panel: pd.DataFrame) -> pd.DataFrame:
    """Features as of the last session in the panel, same definitions as cohort(), no outcome columns."""
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    start = dates[-1]
    i0 = len(dates) - 1
    look0, look21, look63 = dates[i0 - 252], dates[i0 - 21], dates[i0 - 63]
    hist = panel[(panel["date"] >= look0) & (panel["date"] <= start)]
    at = hist[hist["date"] == start].set_index("symbol")
    g = hist.groupby("symbol")
    f = pd.DataFrame({"price": at["close"], "cum0": at["cum"], "series": at["series"]})
    recent = hist[hist["date"] > look63].groupby("symbol")
    f["days63"] = recent.size()
    f["liq_cr"] = recent["traded_value"].median() / 1e7
    f["cum_252"] = g["cum"].first()
    f["first_date"] = g["date"].first()
    f["cum_21"] = hist[hist["date"] <= look21].groupby("symbol")["cum"].last()
    f["max_cum"] = g["cum"].max()
    f["vol"] = g["logr"].std() * np.sqrt(252)
    f["suspect"] = g["suspect"].any()
    f = f[f["days63"] >= 40]
    full = f["first_date"] <= look0 + pd.Timedelta(days=7)
    f["mom12_1"] = np.where(full, np.exp(f["cum_21"] - f["cum_252"]) - 1, np.nan)
    f["off_high"] = np.exp(f["cum0"] - f["max_cum"]) - 1
    f["liq_q"] = pd.qcut(f["liq_cr"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    f["mom_q"] = pd.qcut(f["mom12_1"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(float)
    f["vol_q"] = pd.qcut(f["vol"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    f["as_of"] = start
    return f.reset_index().rename(columns={"index": "symbol"})
