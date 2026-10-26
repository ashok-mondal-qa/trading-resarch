"""Replication test EXP-0047..0049 (spec docs/strategy-specifications/factor-portfolios-pre2011.md): the frozen
Phase 18 factor rules on NSE data from 2006-07 to 2011-06, which no earlier experiment has read.
Research only: nothing here orders or alerts.

    python -m trading_research.backtesting.run_factors_pre2011 --symbols OUT   # EQ symbols to adjust
    python -m trading_research.backtesting.run_factors_pre2011 --tracking      # NIFTYBEES vs NIFTY, 2012-2014
    python -m trading_research.backtesting.run_factors_pre2011                 # all three, once

Data lives in the separate store data/pre2011 (legacy bhavcopy without ISINs, adjusted with the usual
checks). The benchmark is the NIFTYBEES ETF because NSE's index files start in 2012.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import run_factors as rf
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.backtesting.run_swing_ideas import _manifest, superseded_tickers
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import bhavcopy, indices
from trading_research.strategies import factors as fa

ROOT = REPO_ROOT / "data" / "pre2011"
DATA_START, DATA_END = date(2005, 7, 1), date(2011, 6, 30)
SPLITS = {
    "window": ("2006-07-01", "2011-06-30"),
    "first_half": ("2006-07-01", "2008-12-31"),
    "second_half": ("2009-01-01", "2011-06-30"),
}
EXPERIMENTS = {"lowvol": "EXP-0047", "momentum": "EXP-0048", "mom_lowvol": "EXP-0049"}
BENCHMARK = "NIFTYBEES"
ETF_PATTERN = re.compile(r"BEES|ETF|GOLD|NIFTY|SENSEX|LIQUID|SHARIAH")
ETF_SYMBOLS = {"M50", "QNIFTY"}
FIRST_ISIN_DAY = date(2011, 7, 1)          # first main-store bhavcopy with ISINs
TRACKING = ("2012-02-21", "2014-12-31")    # NIFTYBEES and the NIFTY 50 index both exist (main store)


def sessions(root: Path = ROOT) -> pd.DatetimeIndex:
    store = bhavcopy.Store(root=root)
    days = [d for d in bhavcopy.weekdays(DATA_START, DATA_END)
            if (m := store.read_manifest(d)) and m["status"] == "ok"]
    return pd.DatetimeIndex(days)


def etf_symbols(symbols: list[str], main_root: Path = REPO_ROOT / "data") -> set[str]:
    """ETFs and fund units: an INF ISIN on the first post-2011 bhavcopy, or a fund-like name."""
    out = {s for s in symbols if s in ETF_SYMBOLS or ETF_PATTERN.search(s)}
    path = bhavcopy.Store(root=main_root).bars_path(FIRST_ISIN_DAY)
    if path.exists():
        b = pd.read_parquet(path)
        out |= set(b.loc[b["isin"].str.startswith("INF"), "symbol"]) & set(symbols)
    return out


def list_symbols(root: Path = ROOT, min_bars: int = 240) -> list[str]:
    """EQ symbols with at least `min_bars` bars in the store (others can never enter the universe), plus the
    benchmark."""
    bars = bhavcopy.read_bars(DATA_START, DATA_END, bhavcopy.Store(root=root))
    counts = bars.groupby("symbol").size()
    return sorted(set(counts[counts >= min_bars].index) | {BENCHMARK})


def load(root: Path = ROOT, main_root: Path = REPO_ROOT / "data"):
    paths = sorted((root / "processed" / "adjusted").glob("*.parquet"))
    names = [q.stem for q in paths]
    superseded, etfs = superseded_tickers(root, names), etf_symbols(names, main_root)
    cal = sessions(root)
    close, open_, value, seg, bench = {}, {}, {}, {}, None
    for path in paths:
        if path.stem in superseded or (path.stem in etfs and path.stem != BENCHMARK):
            continue
        adj = pd.read_parquet(path)
        adj = adj[(adj["date"] >= pd.Timestamp(DATA_START)) & (adj["date"] <= pd.Timestamp(DATA_END))].copy()
        if adj.empty:
            continue
        adj["segment"] = rf.error_segments(adj["date"], _manifest(root, path.stem), DATA_END)
        adj = adj.set_index("date").sort_index()
        if path.stem == BENCHMARK:
            bench = adj[["adj_open", "adj_close"]].rename(columns={"adj_open": "open", "adj_close": "close"})
            continue
        if len(adj) < 250:
            continue
        close[path.stem], open_[path.stem], value[path.stem] = adj["adj_close"], adj["adj_open"], adj["traded_value"]
        seg[path.stem] = adj["segment"]
    if bench is None:
        raise SystemExit(f"DATA INSUFFICIENT: no usable {BENCHMARK} series")
    frame = lambda d: pd.DataFrame(d).reindex(cal).sort_index()   # noqa: E731
    return frame(close), frame(open_), frame(value), bench.reindex(cal), sorted(etfs), frame(seg)


def verdict(results: dict) -> dict:
    w = results["2x"]["window"]
    checks = {
        "window 2x: Sharpe above NIFTYBEES": w["sharpe_monthly"] > w["nifty_sharpe_monthly"],
        "window 2x: after-tax CAGR above NIFTYBEES": w["strategy_after_tax"]["cagr"] > w["nifty_after_tax"]["cagr"],
    }
    for split in ("first_half", "second_half"):
        s = results["2x"][split]
        checks[f"{split} 2x: Sharpe not below NIFTYBEES"] = s["sharpe_monthly"] >= s["nifty_sharpe_monthly"]
    checks["window 2x: drawdown at most 10 points worse than NIFTYBEES"] = (
        w["max_drawdown"] >= w["nifty_max_drawdown"] - rf.MAX_DD_GAP)
    return {"checks": checks, "status": "REPLICATED" if all(checks.values()) else "NOT REPLICATED"}


def run(strategy: str, close, open_, value, bench, costs: dict, segments: pd.DataFrame | None = None) -> dict:
    out = {"experiment": EXPERIMENTS[strategy], "frozen_rules": rf.EXPERIMENTS[strategy], "strategy": strategy,
           "spec_version": fa.SPEC_VERSION, "params": fa.Params().as_dict(), "benchmark": BENCHMARK,
           "note": "keys named nifty* hold the NIFTYBEES benchmark",
           "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    for mult, label in ((1.0, "1x"), (2.0, "2x")):
        out[label] = {}
        for split, (start, end) in SPLITS.items():
            eq, lots = rf.simulate(strategy, close, open_, value, start, end, costs, mult, segments=segments)
            beq, blots = rf.nifty_curve(bench.dropna(), start, end, costs, mult)   # first session it traded
            out[label][split] = rf.split_report(eq, lots, beq.reindex(eq.index).ffill(), blots,
                                                ci=(label == "1x" and split == "window"))
            if label == "1x" and split == "window":
                eq.to_csv(REPORT_DIR / f"{EXPERIMENTS[strategy]}-window-equity.csv", header=["equity"])
    out["verdict"] = verdict(out)
    return out


def tracking(main_root: Path = REPO_ROOT / "data") -> dict:
    """NIFTYBEES close vs the NIFTY 50 index close, 2012-02-21..2014-12-31 (main store, raw prices; no NIFTYBEES
    split in this window)."""
    start, end = (date.fromisoformat(d) for d in TRACKING)
    bars = bhavcopy.read_bars(start, end, bhavcopy.Store(root=main_root))
    etf = bars[bars["symbol"] == BENCHMARK].set_index("date")["close"]
    idx = indices.read_index("Nifty 50", start, end, main_root)["close"]
    idx.index = pd.to_datetime(idx.index)
    both = pd.concat([etf, idx[~idx.index.duplicated()]], axis=1, keys=["etf", "index"]).dropna()
    r = both.pct_change().dropna()
    years = (both.index[-1] - both.index[0]).days / 365.25
    cagr = (both.iloc[-1] / both.iloc[0]) ** (1 / years) - 1
    return {"window": [str(both.index[0].date()), str(both.index[-1].date())], "days": int(len(r)),
            "daily_return_correlation": float(r["etf"].corr(r["index"])),
            "tracking_error_annual": float((r["etf"] - r["index"]).std() * np.sqrt(252)),
            "cagr_etf_price": float(cagr["etf"]), "cagr_index": float(cagr["index"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", metavar="OUT")
    parser.add_argument("--tracking", action="store_true")
    parser.add_argument("--strategy", choices=fa.STRATEGIES)
    args = parser.parse_args(argv)
    if args.symbols:
        symbols = list_symbols()
        Path(args.symbols).write_text("\n".join(symbols) + "\n")
        print(f"{len(symbols)} symbols -> {args.symbols}")
        return 0
    if args.tracking:
        result = tracking()
        (REPORT_DIR / "niftybees-tracking-2012-2014.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    close, open_, value, bench, etfs, segments = load()
    costs = load_settings()["costs"]
    print(f"stocks {close.shape[1]}, sessions {close.index.min().date()}..{close.index.max().date()}, "
          f"ETFs excluded {len(etfs)}", flush=True)
    for strategy in ([args.strategy] if args.strategy else fa.STRATEGIES):
        result = run(strategy, close, open_, value, bench, costs, segments)
        result["etfs_excluded"] = etfs
        (REPORT_DIR / f"{EXPERIMENTS[strategy]}-pre2011-{strategy}.json").write_text(
            json.dumps(result, indent=2, default=str) + "\n")
        print(strategy, result["verdict"]["status"], json.dumps(result["verdict"]["checks"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
