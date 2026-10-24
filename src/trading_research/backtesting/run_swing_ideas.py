"""Run the Phase 11 experiments (spec docs/strategy-specifications/swing-ideas.md) on one split.

    python -m trading_research.backtesting.run_swing_ideas --list-symbols data/universe-2015-2026.txt
    python -m trading_research.backtesting.run_swing_ideas --split presample
    python -m trading_research.backtesting.run_swing_ideas --split train
    python -m trading_research.backtesting.run_swing_ideas --split validation
    python -m trading_research.backtesting.run_swing_ideas --verdict

Splits: `presample` (2016-01-01..2022-08-12) is data no earlier experiment has evaluated; train and
validation are the earlier splits. There is no holdout path here: the sealed 2026 holdout stays unused
(spec: it needs a pass on every rule below and the project owner's go-ahead).

Two evaluations per strategy and split, each at 1x and 2x costs:
  * portfolio: the strategy as it would be traded (engine, 0.5% / 2% caps, at most 2 a day);
  * standalone: every signal after the regime gate, each simulated alone by the same engine with a fresh
    portfolio, skipping signals in a symbol while its previous standalone trade is open. This measures
    the signal without the cap deciding which trades exist. Intervals resample whole entry months.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import engine, metrics
from trading_research.backtesting.run_baseline import REPORT_DIR, select
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import bhavcopy, indices, quality
from trading_research.indicators import core, regime
from trading_research.strategies import swing_ideas as si

SPLITS = {
    "presample": ("2016-01-01", "2022-08-12"),
    "train": ("2022-08-15", "2024-12-31"),
    "validation": ("2025-01-01", "2025-12-31"),
}
DATA_START, DATA_END = date(2015, 1, 1), date(2026, 10, 22)  # DATA_END only bounds the adjuster's pre-filter
EXPERIMENTS = {"displacement": "EXP-0011", "st_reversal": "EXP-0012", "momentum_12_1": "EXP-0013"}
FAMILY_SIZE = len(EXPERIMENTS)
ALPHA = 0.05 / FAMILY_SIZE        # two-sided interval at 1 - 0.05/3 (Bonferroni over the three strategies)
MIN_PORTFOLIO_TRADES = 30
MIN_STANDALONE_TRADES = 100


# ---------------------------------------------------------------- universe


def list_liquid_symbols(start: date, end: date, root: Path = REPO_ROOT / "data",
                        min_value: float = 5e7, min_price: float = 50.0, n: int = 20) -> list[str]:
    """EQ symbols whose raw 20-day median traded value >= ₹5 crore and raw close >= ₹50 on at least one
    day in [start, end]. Only these can ever pass the liquidity rule, so only these are adjusted."""
    bars = bhavcopy.read_bars(start, end, bhavcopy.Store(root=root), series=("EQ",))
    bars = bars.sort_values(["symbol", "date"])
    med = bars.groupby("symbol")["traded_value"].transform(lambda s: s.rolling(n, min_periods=n).median())
    ok = (med >= min_value) & (bars["close"] >= min_price)
    return sorted(bars.loc[ok, "symbol"].unique())


def _manifest(root: Path, symbol: str) -> dict:
    path = root / "manifests" / "adjusted" / f"{symbol}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def superseded_tickers(root: Path, symbols: list[str]) -> set[str]:
    """Old tickers whose history is already joined into a newer ticker (confirmed rename). Loading both
    would count the same company twice."""
    out = set()
    for symbol in symbols:
        for link in _manifest(root, symbol).get("symbol_links", []):
            if link.get("status") == "confirmed":
                out.add(link["old_symbol"])
    return out


def load_universe(root: Path, data_end: date, nifty: pd.Series, calendar: list, p: si.Params = si.Params(),
                  strategies=si.STRATEGIES):
    """Engine frames and signal rows per strategy, from bars up to data_end only."""
    paths = sorted((root / "processed" / "adjusted").glob("*.parquet"))
    superseded = superseded_tickers(root, [q.stem for q in paths])
    frames = {s: {} for s in strategies}
    feats = {s: {} for s in strategies}
    counts = {"loaded": 0, "insufficient": 0, "short": 0, "etf": 0, "superseded": 0}
    for path in paths:
        symbol = path.stem
        if symbol in superseded:
            counts["superseded"] += 1
            continue
        if _manifest(root, symbol).get("status") == "DATA INSUFFICIENT":
            counts["insufficient"] += 1
            continue
        adj = pd.read_parquet(path)
        adj = adj[adj["date"] <= pd.Timestamp(data_end)]
        if adj.empty:
            continue
        if str(adj["isin"].iloc[-1]).startswith("INF"):  # ETFs and other funds in the EQ series
            counts["etf"] += 1
            continue
        bars = core.ohlcv(adj, usable_only=True)
        if len(bars) < 200:
            counts["short"] += 1
            continue
        counts["loaded"] += 1
        usable = adj[adj["usable"]].set_index("date").sort_index()
        bars["raw_close"] = usable["close"].to_numpy()
        gate1 = quality.gate1_series(bars.index, bars["volume"], calendar)
        for strategy in strategies:
            f = si.stock_features(bars, nifty, strategy, p)
            f["gate1"] = gate1
            f["adj_factor"] = usable["adj_factor"].to_numpy()
            for col in ("open", "high", "low"):
                f[col] = bars[col]
            feats[strategy][symbol] = f
    if "momentum_12_1" in strategies:
        fm = feats["momentum_12_1"]
        mom = pd.DataFrame({s: f["mom"] for s, f in fm.items()})
        rankable = pd.DataFrame({s: f["inputs_complete"] & f["liquid"] & f["gate1"] for s, f in fm.items()})
        pct = si.momentum_rank(mom, rankable.reindex_like(mom).fillna(False).astype(bool))
        starts = si.month_starts(calendar)
        for s in fm:
            fm[s] = si.apply_momentum(fm[s], pct[s], starts, p)
    rows = {s: [] for s in strategies}
    for strategy in strategies:
        for symbol, f in feats[strategy].items():
            frames[strategy][symbol] = f[["open", "high", "low", "close", "adj_factor", "stop", "exit_signal",
                                          "median_traded_value"]].copy()
            hits = f[f["signal"].fillna(False).astype(bool) & f["gate1"]]
            rows[strategy].extend((d, symbol, True, r["rank_key"]) for d, r in hits.iterrows())
    signals = {s: pd.DataFrame(r, columns=["date", "symbol", "signal", "rs"]) for s, r in rows.items()}
    return frames, signals, counts


# ---------------------------------------------------------------- evaluation


def standalone(frames: dict, signals: pd.DataFrame, regime_trend: pd.Series, split_calendar: list, settings: dict,
               max_holding: int, mult: float) -> pd.DataFrame:
    """Each signal (regime 'up', inside the split) traded alone; none while the symbol's last one is open."""
    sub = signals[regime_trend.reindex(signals["date"]).to_numpy() == "up"]
    cal = pd.DatetimeIndex(pd.to_datetime(split_calendar))
    sub = sub[(sub["date"] >= cal[0]) & (sub["date"] <= cal[-1])].sort_values(["symbol", "date"])
    equity0 = float(settings["virtual_portfolio"]["starting_equity_inr"])
    out = []
    for symbol, g in sub.groupby("symbol"):
        free_from = pd.Timestamp.min
        for d in g["date"]:
            if d < free_from:
                continue
            i = cal.searchsorted(d)
            window = list(cal[i:i + max_holding + 40])  # long enough for the time stop plus gaps
            res = engine.run({symbol: frames[symbol]}, {d: [symbol]}, window, settings, equity0, max_holding, mult)
            if len(res.trades) == 0:
                continue  # skipped (opened at/below the stop, or no bar)
            t = res.trades.iloc[0].to_dict()
            out.append(t)
            free_from = t["exit_date"] if t["reason"] != "open at end (marked)" else pd.Timestamp.max
    return pd.DataFrame(out)


def standalone_summary(t: pd.DataFrame) -> dict:
    if len(t) == 0:
        return {"trades": 0}
    closed = t[t["reason"] != "open at end (marked)"]
    r = closed["r_multiple"].to_numpy()
    months = pd.to_datetime(closed["entry_date"]).dt.to_period("M").astype(str).to_numpy()
    years = pd.to_datetime(closed["entry_date"]).dt.year
    pnl = closed["pnl"].to_numpy()
    return {
        "trades": int(len(closed)), "open_at_end": int(len(t) - len(closed)),
        "expectancy_r": float(r.mean()) if len(r) else None,
        "median_r": float(np.median(r)) if len(r) else None,
        "win_rate": float((pnl > 0).mean()) if len(r) else None,
        "profit_factor": float(pnl[pnl > 0].sum() / -pnl[pnl <= 0].sum()) if (pnl <= 0).any() else None,
        "expectancy_r_ci95_month_clustered": metrics.cluster_bootstrap_ci(r, months),
        f"expectancy_r_ci{100 * (1 - ALPHA):.1f}_month_clustered": metrics.cluster_bootstrap_ci(r, months,
                                                                                                alpha=ALPHA),
        "entry_months": int(len(set(months))),
        "avg_sessions": float(closed["sessions"].mean()) if len(r) else None,
        "worst_r": float(r.min()) if len(r) else None,
        "by_year": {str(y): {"trades": int(len(g)), "expectancy_r": float(g["r_multiple"].mean())}
                    for y, g in closed.groupby(years)},
        "exit_reasons": closed["reason"].value_counts().to_dict(),
    }


def _context(split: str, root: Path):
    start, end = SPLITS[split]
    data_end = date.fromisoformat(end)  # never load bars after the split
    calendar = quality.sessions(bhavcopy.Store(root=root), DATA_START, data_end)
    nifty = indices.read_index("Nifty 50", DATA_START, data_end, root)["close"]
    split_calendar = [d for d in calendar if pd.Timestamp(start) <= pd.Timestamp(d) <= pd.Timestamp(end)]
    return start, end, data_end, calendar, nifty, regime.regime(nifty), split_calendar


def run_split(split: str, strategies=si.STRATEGIES, root: Path = REPO_ROOT / "data") -> dict:
    if split not in SPLITS:
        raise SystemExit(f"unknown split {split!r}; the 2026 holdout is not available from this runner")
    settings = load_settings()
    p = si.Params()
    start, end, data_end, calendar, nifty, reg, split_calendar = _context(split, root)
    frames, signals, counts = load_universe(root, data_end, nifty, calendar, p, strategies)
    bench = nifty[(nifty.index >= pd.Timestamp(start)) & (nifty.index <= pd.Timestamp(end))]
    equity0 = float(settings["virtual_portfolio"]["starting_equity_inr"])
    reports = {}
    for strategy in strategies:
        exp, hold = EXPERIMENTS[strategy], p.max_holding(strategy)
        report = {
            "experiment": exp, "strategy": strategy, "spec_version": si.SPEC_VERSION, "split": split,
            "range": [start, end], "params": p.as_dict(), "max_holding_sessions": hold,
            "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "universe": counts, "costs_verified": bool(settings["costs"]["verified"]),
            "regime_days": reg["trend"].reindex(pd.to_datetime(split_calendar)).value_counts().to_dict(),
            "benchmark_nifty50_return": float(bench.iloc[-1] / bench.iloc[0] - 1) if len(bench) > 1 else None,
            "runs": {},
        }
        for mult, label in ((1.0, "1x"), (2.0, "2x_costs")):
            cands, n_signals = select(signals[strategy], reg["trend"], start, end, p, False)
            res = engine.run(frames[strategy], cands, split_calendar, settings, equity0, hold, mult)
            summary = metrics.summarize(res.trades, res.equity, equity0)
            summary.update({"signals_after_regime_gate": n_signals,
                            "entries_skipped": res.skipped["reason"].value_counts().to_dict()
                            if len(res.skipped) else {}})
            report["runs"][f"portfolio_{label}"] = summary
            alone = standalone(frames[strategy], signals[strategy], reg["trend"], split_calendar, settings,
                               hold, mult)
            report["runs"][f"standalone_{label}"] = standalone_summary(alone)
            if label == "1x":
                REPORT_DIR.mkdir(parents=True, exist_ok=True)
                res.trades.to_csv(REPORT_DIR / f"{exp}-{split}-trades.csv", index=False)
                alone.to_csv(REPORT_DIR / f"{exp}-{split}-standalone-trades.csv", index=False)
        (REPORT_DIR / f"{exp}-{split}.json").write_text(json.dumps(report, indent=2, default=str) + "\n",
                                                        encoding="utf-8")
        reports[strategy] = report
    return reports


# ---------------------------------------------------------------- pre-registered decision


def verdict(reports: dict[str, dict]) -> dict:
    """Rules from the spec, applied mechanically. `reports[split]` is one strategy's report per split."""
    pre = reports["presample"]["runs"]
    lo_key = f"expectancy_r_ci{100 * (1 - ALPHA):.1f}_month_clustered"
    checks = {
        "presample portfolio >= 30 trades": pre["portfolio_2x_costs"].get("trades", 0) >= MIN_PORTFOLIO_TRADES,
        "presample portfolio 2x: expectancy > 0":
            (pre["portfolio_2x_costs"].get("expectancy_r") or -1) > 0,
        "presample portfolio 2x: profit factor >= 1.1":
            (pre["portfolio_2x_costs"].get("profit_factor") or 0) >= 1.1,
        "presample standalone >= 100 trades": pre["standalone_1x"].get("trades", 0) >= MIN_STANDALONE_TRADES,
        "presample standalone 1x: Bonferroni interval lower bound > 0":
            (pre["standalone_1x"].get(lo_key) or (-1, -1))[0] > 0,
        "presample standalone 2x: expectancy > 0": (pre["standalone_2x_costs"].get("expectancy_r") or -1) > 0,
    }
    for split in ("train", "validation"):
        if split in reports:
            checks[f"{split} standalone 2x: expectancy > 0"] = (
                reports[split]["runs"]["standalone_2x_costs"].get("expectancy_r") or -1) > 0
    passed = all(checks.values()) and {"train", "validation"} <= set(reports)
    return {"checks": checks, "passed_presample_rules": passed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=list(SPLITS))
    parser.add_argument("--strategy", choices=list(si.STRATEGIES))
    parser.add_argument("--list-symbols", metavar="OUT")
    parser.add_argument("--verdict", action="store_true")
    args = parser.parse_args(argv)
    if args.list_symbols:
        symbols = list_liquid_symbols(DATA_START, DATA_END)
        Path(args.list_symbols).write_text("\n".join(symbols) + "\n")
        print(f"{len(symbols)} symbols -> {args.list_symbols}")
        return 0
    if args.verdict:
        out = {}
        for strategy, exp in EXPERIMENTS.items():
            reports = {s: json.loads((REPORT_DIR / f"{exp}-{s}.json").read_text())
                       for s in SPLITS if (REPORT_DIR / f"{exp}-{s}.json").exists()}
            out[strategy] = verdict(reports) if "presample" in reports else {"missing": "presample"}
        print(json.dumps(out, indent=2))
        return 0
    if not args.split:
        parser.error("--split is required")
    strategies = (args.strategy,) if args.strategy else si.STRATEGIES
    for strategy, report in run_split(args.split, strategies).items():
        runs = {k: {m: v.get(m) for m in ("trades", "expectancy_r", "profit_factor")}
                for k, v in report["runs"].items()}
        print(strategy, json.dumps(runs, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
