"""Run the Phase 13 experiments (spec docs/strategy-specifications/social-strategies.md) on one split.

    python -m trading_research.backtesting.run_social --split dev          # 2013-01-01..2025-12-31, decides
    python -m trading_research.backtesting.run_social --split early        # and presample/train/validation
    python -m trading_research.backtesting.run_social --verdict

Same engine (now with optional profit targets), costs, portfolio and standalone measurements as Phases
11-12. No holdout path. Every split here has been used before, so the pass rule corrects for every strategy
definition ever tested on these dates (FAMILY_SIZE).
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
from trading_research.backtesting.run_swing_ideas import (
    _manifest, ci_key, standalone, standalone_summary, superseded_tickers, usable_as_of)
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import bhavcopy, indices, quality
from trading_research.indicators import core, regime
from trading_research.strategies import social

SPLITS = {
    "dev": ("2013-01-01", "2025-12-31"),
    "early": ("2013-01-01", "2015-12-31"),
    "presample": ("2016-01-01", "2022-08-12"),
    "train": ("2022-08-15", "2024-12-31"),
    "validation": ("2025-01-01", "2025-12-31"),
}
DATA_START = date(2011, 7, 1)
EXPERIMENTS = {"minervini": "EXP-0016", "supertrend": "EXP-0017", "ma44": "EXP-0018", "turtle55": "EXP-0019",
               "golden_cross": "EXP-0020"}
# Strategy definitions evaluated on 2013..2025 so far: baseline v0.1/v0.2, pa_pullback + ablation,
# smc_sweep + ablation (= displacement), st_reversal, momentum monthly, momentum weekly, gap_drift (11 in the
# Phase 12 report), plus the 5 here.
FAMILY_SIZE = 16
ALPHA = 0.05 / FAMILY_SIZE
MIN_PORTFOLIO_TRADES = 30
MIN_STANDALONE_TRADES = 300


def load_universe(root: Path, data_end: date, nifty: pd.Series, calendar: list, p: social.Params = social.Params(),
                  strategies=social.STRATEGIES):
    paths = sorted((root / "processed" / "adjusted").glob("*.parquet"))
    superseded = superseded_tickers(root, [q.stem for q in paths])
    feats = {s: {} for s in strategies}
    counts = {"loaded": 0, "insufficient": 0, "short": 0, "etf": 0, "superseded": 0}
    for path in paths:
        symbol = path.stem
        if symbol in superseded:
            counts["superseded"] += 1
            continue
        adj = pd.read_parquet(path)
        adj = adj[adj["date"] <= pd.Timestamp(data_end)].copy()
        if adj.empty:
            continue
        adj["usable"] = usable_as_of(adj, _manifest(root, symbol), data_end)
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
            f = social.stock_features(bars, nifty, strategy, p)
            f["gate1"] = gate1
            f["adj_factor"] = usable["adj_factor"].to_numpy()
            for col in ("open", "high", "low"):
                f[col] = bars[col]
            feats[strategy][symbol] = f
    if "minervini" in strategies:
        fm = feats["minervini"]
        score = pd.DataFrame({s: f["rs_score"] for s, f in fm.items()})
        rankable = pd.DataFrame({s: f["rs_score"].notna() & f["liquid"] & f["gate1"] for s, f in fm.items()})
        pct = core.cross_sectional_rank(score.where(rankable.reindex_like(score).fillna(False).astype(bool)))
        for s in fm:
            fm[s] = social.apply_rs_rank(fm[s], pct[s], p)
    frames = {s: {} for s in strategies}
    signals = {}
    for strategy in strategies:
        rows = []
        for symbol, f in feats[strategy].items():
            frames[strategy][symbol] = f[["open", "high", "low", "close", "adj_factor", "stop", "target",
                                          "exit_signal", "median_traded_value"]].copy()
            hits = f[f["signal"] & f["gate1"]]
            rows.extend((d, symbol, True, r["rank_key"]) for d, r in hits.iterrows())
        signals[strategy] = pd.DataFrame(rows, columns=["date", "symbol", "signal", "rs"])
    return frames, signals, counts


def equity_stats(equity: pd.Series) -> dict:
    """Annualised return, volatility and Sharpe (risk-free 0) of the portfolio's daily equity curve."""
    if len(equity) < 20:
        return {}
    rets = equity.pct_change().dropna()
    years = len(equity) / 252
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    vol = float(rets.std() * np.sqrt(252))
    return {"cagr": float(cagr), "ann_vol": vol, "sharpe_rf0": float(rets.mean() * 252 / vol) if vol > 0 else None,
            "years": float(years)}


def _context(split: str, root: Path):
    start, end = SPLITS[split]
    data_end = date.fromisoformat(end)  # never load bars after the split
    calendar = quality.sessions(bhavcopy.Store(root=root), DATA_START, data_end)
    nifty = indices.read_index("Nifty 50", DATA_START, data_end, root)["close"]
    split_calendar = [d for d in calendar if pd.Timestamp(start) <= pd.Timestamp(d) <= pd.Timestamp(end)]
    return start, end, data_end, calendar, nifty, regime.regime(nifty), split_calendar


def run_split(split: str, strategies=social.STRATEGIES, root: Path = REPO_ROOT / "data") -> dict:
    if split not in SPLITS:
        raise SystemExit(f"unknown split {split!r}; the 2026 holdout is not available from this runner")
    settings = load_settings()
    p = social.Params()
    start, end, data_end, calendar, nifty, reg, split_calendar = _context(split, root)
    frames, signals, counts = load_universe(root, data_end, nifty, calendar, p, strategies)
    bench = nifty[(nifty.index >= pd.Timestamp(start)) & (nifty.index <= pd.Timestamp(end))]
    equity0 = float(settings["virtual_portfolio"]["starting_equity_inr"])
    reports = {}
    for strategy in strategies:
        exp, hold = EXPERIMENTS[strategy], p.max_holding(strategy)
        report = {
            "experiment": exp, "strategy": strategy, "spec_version": social.SPEC_VERSION, "split": split,
            "range": [start, end], "params": p.as_dict(), "max_holding_sessions": hold,
            "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "universe": counts, "costs_verified": bool(settings["costs"]["verified"]),
            "regime_days": reg["trend"].reindex(pd.to_datetime(split_calendar)).value_counts().to_dict(),
            "benchmark_nifty50_return": float(bench.iloc[-1] / bench.iloc[0] - 1) if len(bench) > 1 else None,
            "benchmark_nifty50": equity_stats(bench), "runs": {},
        }
        for mult, label in ((1.0, "1x"), (2.0, "2x_costs")):
            cands, n_signals = select(signals[strategy], reg["trend"], start, end, p, False)
            res = engine.run(frames[strategy], cands, split_calendar, settings, equity0, hold, mult)
            summary = metrics.summarize(res.trades, res.equity, equity0)
            summary.update(equity_stats(res.equity))
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
                res.equity.to_csv(REPORT_DIR / f"{exp}-{split}-equity.csv")
        (REPORT_DIR / f"{exp}-{split}.json").write_text(json.dumps(report, indent=2, default=str) + "\n",
                                                        encoding="utf-8")
        reports[strategy] = report
    return reports


def verdict(reports: dict[str, dict]) -> dict:
    dev = reports["dev"]["runs"]
    checks = {
        "dev portfolio >= 30 trades": dev["portfolio_2x_costs"].get("trades", 0) >= MIN_PORTFOLIO_TRADES,
        "dev portfolio 2x: expectancy > 0": (dev["portfolio_2x_costs"].get("expectancy_r") or -1) > 0,
        "dev portfolio 2x: profit factor >= 1.1": (dev["portfolio_2x_costs"].get("profit_factor") or 0) >= 1.1,
        "dev standalone >= 300 trades": dev["standalone_1x"].get("trades", 0) >= MIN_STANDALONE_TRADES,
        f"dev standalone 1x: Bonferroni ({FAMILY_SIZE}) interval lower bound > 0":
            (dev["standalone_1x"].get(ci_key(ALPHA)) or (-1, -1))[0] > 0,
        "dev standalone 2x: expectancy > 0": (dev["standalone_2x_costs"].get("expectancy_r") or -1) > 0,
    }
    for split in ("early", "presample", "train", "validation"):
        if split in reports:
            checks[f"{split} standalone 2x: expectancy > 0"] = (
                reports[split]["runs"]["standalone_2x_costs"].get("expectancy_r") or -1) > 0
    passed = all(checks.values()) and {"early", "presample", "train", "validation"} <= set(reports)
    return {"checks": checks, "passed": passed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=list(SPLITS))
    parser.add_argument("--strategy", choices=list(social.STRATEGIES))
    parser.add_argument("--verdict", action="store_true")
    args = parser.parse_args(argv)
    if args.verdict:
        out = {}
        for strategy, exp in EXPERIMENTS.items():
            reports = {s: json.loads((REPORT_DIR / f"{exp}-{s}.json").read_text())
                       for s in SPLITS if (REPORT_DIR / f"{exp}-{s}.json").exists()}
            out[strategy] = verdict(reports) if "dev" in reports else {"missing": "dev"}
        print(json.dumps(out, indent=2))
        return 0
    if not args.split:
        parser.error("--split is required")
    strategies = (args.strategy,) if args.strategy else social.STRATEGIES
    for strategy, report in run_split(args.split, strategies).items():
        runs = {k: {m: v.get(m) for m in ("trades", "expectancy_r", "profit_factor")}
                for k, v in report["runs"].items()}
        print(strategy, json.dumps(runs, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
