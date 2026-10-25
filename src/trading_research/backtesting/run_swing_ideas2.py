"""Run the Phase 12 experiments (spec docs/strategy-specifications/swing-ideas-2.md) on one split.

    python -m trading_research.backtesting.run_swing_ideas2 --split early      # decisive, never evaluated
    python -m trading_research.backtesting.run_swing_ideas2 --split presample  # sign checks only
    python -m trading_research.backtesting.run_swing_ideas2 --split train
    python -m trading_research.backtesting.run_swing_ideas2 --split validation
    python -m trading_research.backtesting.run_swing_ideas2 --verdict

Same engine, costs, portfolio and standalone measurements as `run_swing_ideas`. No holdout path.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.backtesting import engine, metrics
from trading_research.backtesting.run_baseline import REPORT_DIR, select
from trading_research.backtesting.run_swing_ideas import (
    _manifest, ci_key, standalone, standalone_summary, superseded_tickers, usable_as_of)
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import bhavcopy, indices, quality
from trading_research.indicators import core, regime
from trading_research.strategies import swing_ideas as si
from trading_research.strategies import swing_ideas2 as s2

SPLITS = {
    "early": ("2013-01-01", "2015-12-31"),
    "presample": ("2016-01-01", "2022-08-12"),
    "train": ("2022-08-15", "2024-12-31"),
    "validation": ("2025-01-01", "2025-12-31"),
}
DATA_START = date(2011, 7, 1)    # first legacy bhavcopy files with ISINs; NSE index files start Feb 2012
EXPERIMENTS = {"momentum_weekly": "EXP-0014", "gap_drift": "EXP-0015"}
ALPHA = 0.05 / len(EXPERIMENTS)   # Bonferroni over the two strategies evaluated on the early split
MIN_PORTFOLIO_TRADES = 30
MIN_STANDALONE_TRADES = 100


def load_universe(root: Path, data_end: date, nifty: pd.Series, calendar: list, p: s2.Params = s2.Params(),
                  strategies=s2.STRATEGIES):
    paths = sorted((root / "processed" / "adjusted").glob("*.parquet"))
    superseded = superseded_tickers(root, [q.stem for q in paths])
    feats = {s: {} for s in strategies}
    counts = {"loaded": 0, "insufficient": 0, "short": 0, "etf": 0, "superseded": 0}
    for path in paths:
        symbol = path.stem
        if symbol in superseded:
            counts["superseded"] += 1
            continue
        manifest = _manifest(root, symbol)
        adj = pd.read_parquet(path)
        adj = adj[adj["date"] <= pd.Timestamp(data_end)].copy()
        if adj.empty:
            continue
        adj["usable"] = usable_as_of(adj, manifest, data_end)
        if not adj["usable"].any():
            counts["insufficient"] += 1
            continue
        if str(adj["isin"].iloc[-1]).startswith("INF"):
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
            f = s2.stock_features(bars, nifty, strategy, p)
            f["gate1"] = gate1
            f["adj_factor"] = usable["adj_factor"].to_numpy()
            for col in ("open", "high", "low"):
                f[col] = bars[col]
            feats[strategy][symbol] = f
    if "momentum_weekly" in strategies:
        fm = feats["momentum_weekly"]
        mom = pd.DataFrame({s: f["mom"] for s, f in fm.items()})
        rankable = pd.DataFrame({s: f["inputs_complete"] & f["liquid"] & f["gate1"] for s, f in fm.items()})
        pct = si.momentum_rank(mom, rankable.reindex_like(mom).fillna(False).astype(bool))
        starts = s2.week_starts(calendar)
        for s in fm:
            fm[s] = si.apply_momentum(fm[s], pct[s], starts, p.base)
    frames = {s: {} for s in strategies}
    signals = {}
    for strategy in strategies:
        rows = []
        for symbol, f in feats[strategy].items():
            frames[strategy][symbol] = f[["open", "high", "low", "close", "adj_factor", "stop", "exit_signal",
                                          "median_traded_value"]].copy()
            hits = f[f["signal"].fillna(False).astype(bool) & f["gate1"]]
            rows.extend((d, symbol, True, r["rank_key"]) for d, r in hits.iterrows())
        signals[strategy] = pd.DataFrame(rows, columns=["date", "symbol", "signal", "rs"])
    return frames, signals, counts


def _context(split: str, root: Path):
    start, end = SPLITS[split]
    data_end = date.fromisoformat(end)  # never load bars after the split
    calendar = quality.sessions(bhavcopy.Store(root=root), DATA_START, data_end)
    nifty = indices.read_index("Nifty 50", DATA_START, data_end, root)["close"]
    split_calendar = [d for d in calendar if pd.Timestamp(start) <= pd.Timestamp(d) <= pd.Timestamp(end)]
    return start, end, data_end, calendar, nifty, regime.regime(nifty), split_calendar


def run_split(split: str, strategies=s2.STRATEGIES, root: Path = REPO_ROOT / "data") -> dict:
    if split not in SPLITS:
        raise SystemExit(f"unknown split {split!r}; the 2026 holdout is not available from this runner")
    settings = load_settings()
    p = s2.Params()
    start, end, data_end, calendar, nifty, reg, split_calendar = _context(split, root)
    frames, signals, counts = load_universe(root, data_end, nifty, calendar, p, strategies)
    bench = nifty[(nifty.index >= pd.Timestamp(start)) & (nifty.index <= pd.Timestamp(end))]
    equity0 = float(settings["virtual_portfolio"]["starting_equity_inr"])
    reports = {}
    for strategy in strategies:
        exp, hold = EXPERIMENTS[strategy], p.max_holding(strategy)
        report = {
            "experiment": exp, "strategy": strategy, "spec_version": s2.SPEC_VERSION, "split": split,
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
            report["runs"][f"standalone_{label}"] = standalone_summary(alone, ALPHA)
            if label == "1x":
                REPORT_DIR.mkdir(parents=True, exist_ok=True)
                res.trades.to_csv(REPORT_DIR / f"{exp}-{split}-trades.csv", index=False)
                alone.to_csv(REPORT_DIR / f"{exp}-{split}-standalone-trades.csv", index=False)
        (REPORT_DIR / f"{exp}-{split}.json").write_text(json.dumps(report, indent=2, default=str) + "\n",
                                                        encoding="utf-8")
        reports[strategy] = report
    return reports


def verdict(reports: dict[str, dict]) -> dict:
    """Rules from the spec, applied mechanically. `reports[split]` is one strategy's report per split."""
    early = reports["early"]["runs"]
    checks = {
        "early portfolio >= 30 trades": early["portfolio_2x_costs"].get("trades", 0) >= MIN_PORTFOLIO_TRADES,
        "early portfolio 2x: expectancy > 0": (early["portfolio_2x_costs"].get("expectancy_r") or -1) > 0,
        "early portfolio 2x: profit factor >= 1.1": (early["portfolio_2x_costs"].get("profit_factor") or 0) >= 1.1,
        "early standalone >= 100 trades": early["standalone_1x"].get("trades", 0) >= MIN_STANDALONE_TRADES,
        "early standalone 1x: Bonferroni interval lower bound > 0":
            (early["standalone_1x"].get(ci_key(ALPHA)) or (-1, -1))[0] > 0,
        "early standalone 2x: expectancy > 0": (early["standalone_2x_costs"].get("expectancy_r") or -1) > 0,
    }
    for split in ("presample", "train", "validation"):
        if split in reports:
            checks[f"{split} standalone 2x: expectancy > 0"] = (
                reports[split]["runs"]["standalone_2x_costs"].get("expectancy_r") or -1) > 0
    passed = all(checks.values()) and {"presample", "train", "validation"} <= set(reports)
    return {"checks": checks, "passed": passed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=list(SPLITS))
    parser.add_argument("--strategy", choices=list(s2.STRATEGIES))
    parser.add_argument("--verdict", action="store_true")
    args = parser.parse_args(argv)
    if args.verdict:
        out = {}
        for strategy, exp in EXPERIMENTS.items():
            reports = {s: json.loads((REPORT_DIR / f"{exp}-{s}.json").read_text())
                       for s in SPLITS if (REPORT_DIR / f"{exp}-{s}.json").exists()}
            out[strategy] = verdict(reports) if "early" in reports else {"missing": "early"}
        print(json.dumps(out, indent=2))
        return 0
    if not args.split:
        parser.error("--split is required")
    strategies = (args.strategy,) if args.strategy else s2.STRATEGIES
    for strategy, report in run_split(args.split, strategies).items():
        runs = {k: {m: v.get(m) for m in ("trades", "expectancy_r", "profit_factor")}
                for k, v in report["runs"].items()}
        print(strategy, json.dumps(runs, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
