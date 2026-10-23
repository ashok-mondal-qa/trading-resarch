"""Run the Phase 8 experiments (spec docs/strategy-specifications/pa-smc.md) on one pre-registered split.

    python -m trading_research.backtesting.run_phase8 --split train
    python -m trading_research.backtesting.run_phase8 --split validation
    python -m trading_research.backtesting.run_phase8 --robustness          # train only
    python -m trading_research.backtesting.run_phase8 --split holdout --strategy <name> --confirm-holdout

Same splits, universe, regime gate, costs, engine and ranking (highest 63-day RS first, at most 2 a day)
as the baseline runner. Writes reports/backtests/<EXP>-<split>.json and -trades.csv per strategy. The
holdout is one evaluation in total across all strategies (see run_baseline.run_split).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.backtesting import engine, metrics
from trading_research.backtesting.run_baseline import DATA_START, REPORT_DIR, SPLITS, breakdowns, select
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import bhavcopy, indices, quality
from trading_research.indicators import core, regime
from trading_research.strategies import pa_smc

EXPERIMENTS = {"pa_pullback": "EXP-0007", "smc_sweep": "EXP-0008"}
ROBUSTNESS = {
    "pa_pullback": {"ema_n": (10, 30), "swing_k": (2, 5)},
    "smc_sweep": {"body_atr": (1.25, 2.0), "sweep_window": (3, 10)},
}


def load_universe(root: Path, data_end: date, nifty: pd.Series, params: dict[str, pa_smc.Params], calendar):
    """Engine frames and candidate rows per strategy, from bars up to data_end only."""
    frames = {s: {} for s in params}
    rows = {s: [] for s in params}
    loaded = skipped = 0
    for path in sorted((root / "processed" / "adjusted").glob("*.parquet")):
        symbol = path.stem
        manifest_path = root / "manifests" / "adjusted" / f"{symbol}.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if manifest.get("status") == "DATA INSUFFICIENT":
            skipped += 1
            continue
        adj = pd.read_parquet(path)
        adj = adj[adj["date"] <= pd.Timestamp(data_end)]
        if adj.empty:
            continue
        bars = core.ohlcv(adj, usable_only=True)
        if len(bars) < 200:
            skipped += 1
            continue
        loaded += 1
        usable = adj[adj["usable"]].set_index("date").sort_index()
        bars["raw_close"] = usable["close"].to_numpy()
        gate1 = quality.gate1_series(bars.index, bars["volume"], calendar)
        for strategy, p in params.items():
            f = pa_smc.stock_features(bars, nifty, strategy, p)
            frames[strategy][symbol] = pd.DataFrame({
                "open": bars["open"], "high": bars["high"], "low": bars["low"], "close": bars["close"],
                "adj_factor": usable["adj_factor"].to_numpy(), "stop": f["stop"],
                "exit_signal": f["exit_signal"], "median_traded_value": f["median_traded_value"]})
            for d, r in f[f["signal"] & gate1].iterrows():
                rows[strategy].append((d, symbol, True, r["rs"]))
            for d, r in f[f["ablation"] & gate1].iterrows():
                rows[strategy].append((d, symbol, None, r["rs"]))
    feats = {s: pd.DataFrame(r, columns=["date", "symbol", "signal", "rs"]) for s, r in rows.items()}
    return frames, feats, loaded, skipped


def _context(split: str, root: Path):
    start, end = SPLITS[split]
    data_end = date.fromisoformat(end)  # never load bars after the split
    store = bhavcopy.Store(root=root)
    calendar = quality.sessions(store, DATA_START, data_end)
    nifty = indices.read_index("Nifty 50", DATA_START, data_end, root)["close"]
    split_calendar = [d for d in calendar if pd.Timestamp(start) <= pd.Timestamp(d) <= pd.Timestamp(end)]
    return start, end, data_end, calendar, nifty, regime.regime(nifty), split_calendar


def _run(frames, feats, reg, start, end, split_calendar, settings, p, ablation, mult):
    cands, n_signals = select(feats, reg["trend"], start, end, p, ablation)
    equity0 = float(settings["virtual_portfolio"]["starting_equity_inr"])
    res = engine.run(frames, cands, split_calendar, settings, equity0, p.max_holding_sessions, mult)
    summary = metrics.summarize(res.trades, res.equity, equity0)
    summary.update({"signals_after_regime_gate": n_signals,
                    "candidates_taken": int(sum(len(v) for v in cands.values())),
                    "entries_skipped": res.skipped["reason"].value_counts().to_dict() if len(res.skipped) else {}})
    return res, summary


def run_split(split: str, strategies=pa_smc.STRATEGIES, confirm_holdout: bool = False,
              root: Path = REPO_ROOT / "data") -> dict:
    if split == "holdout":
        if not confirm_holdout or len(strategies) != 1:
            raise SystemExit("holdout is sealed: pass one --strategy and --confirm-holdout (once, ever)")
        done = sorted(REPORT_DIR.glob("EXP-*-holdout.json"))
        if done:
            raise SystemExit(f"holdout already evaluated: {done[0]}")
    settings = load_settings()
    start, end, data_end, calendar, nifty, reg, split_calendar = _context(split, root)
    params = {s: pa_smc.Params() for s in strategies}
    frames, feats, loaded, skipped = load_universe(root, data_end, nifty, params, calendar)
    bench = nifty[(nifty.index >= pd.Timestamp(start)) & (nifty.index <= pd.Timestamp(end))]
    reports = {}
    for strategy in strategies:
        exp, p = EXPERIMENTS[strategy], params[strategy]
        report = {
            "experiment": exp, "strategy": strategy, "spec_version": pa_smc.SPEC_VERSION, "split": split,
            "range": [start, end], "params": p.as_dict(),
            "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "universe_symbols_loaded": loaded, "universe_symbols_skipped": skipped,
            "costs_verified": bool(settings["costs"]["verified"]),
            "regime_days": reg["trend"].reindex(pd.to_datetime(split_calendar)).value_counts().to_dict(),
            "benchmark_nifty50_return": float(bench.iloc[-1] / bench.iloc[0] - 1) if len(bench) > 1 else None,
            "runs": {},
        }
        for name, ablation, mult in (("strategy_1x", False, 1.0), ("strategy_2x_costs", False, 2.0),
                                     ("ablation_1x", True, 1.0), ("ablation_2x_costs", True, 2.0)):
            res, summary = _run(frames[strategy], feats[strategy], reg, start, end, split_calendar, settings,
                                p, ablation, mult)
            if name == "strategy_1x" and len(res.trades):
                t = res.trades.copy()
                t["vol_regime"] = reg["volatility"].reindex(t["signal_date"]).to_numpy()
                t["median_traded_value"] = [frames[strategy][r.symbol].loc[r.signal_date, "median_traded_value"]
                                            for r in t.itertuples()]
                summary.update(breakdowns(t))
                t.to_csv(REPORT_DIR / f"{exp}-{split}-trades.csv", index=False)
            report["runs"][name] = summary
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"{exp}-{split}.json").write_text(json.dumps(report, indent=2, default=str) + "\n",
                                                        encoding="utf-8")
        reports[strategy] = report
    return reports


def robustness(root: Path = REPO_ROOT / "data") -> dict:
    """Pre-registered neighbouring values on train only; reported, never used to choose."""
    settings = load_settings()
    start, end, data_end, calendar, nifty, reg, split_calendar = _context("train", root)
    out = {}
    for strategy, grid in ROBUSTNESS.items():
        variants = {}
        for name, values in grid.items():
            for value in values:
                p = replace(pa_smc.Params(), **{name: value})
                frames, feats, _, _ = load_universe(root, data_end, nifty, {strategy: p}, calendar)
                row = {}
                for label, mult in (("1x", 1.0), ("2x_costs", 2.0)):
                    _, s = _run(frames[strategy], feats[strategy], reg, start, end, split_calendar, settings,
                                p, False, mult)
                    row[label] = {k: s.get(k) for k in ("trades", "net_return", "expectancy_r",
                                                        "expectancy_r_ci95", "profit_factor", "max_drawdown")}
                variants[f"{name}={value}"] = row
        out[strategy] = {"experiment": EXPERIMENTS[strategy], "split": "train", "variants": variants,
                         "note": "robustness only; not used to choose values",
                         "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
        (REPORT_DIR / f"{EXPERIMENTS[strategy]}-train-robustness.json").write_text(
            json.dumps(out[strategy], indent=2, default=str) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=list(SPLITS))
    parser.add_argument("--strategy", choices=list(pa_smc.STRATEGIES))
    parser.add_argument("--confirm-holdout", action="store_true")
    parser.add_argument("--robustness", action="store_true")
    args = parser.parse_args(argv)
    if args.robustness:
        robustness()
        return 0
    if not args.split:
        parser.error("--split is required")
    strategies = (args.strategy,) if args.strategy else pa_smc.STRATEGIES
    reports = run_split(args.split, strategies, args.confirm_holdout)
    for strategy, report in reports.items():
        runs = {k: {m: v.get(m) for m in ("trades", "net_return", "expectancy_r", "expectancy_r_ci95",
                                          "profit_factor")} for k, v in report["runs"].items()}
        print(strategy, json.dumps(runs, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
