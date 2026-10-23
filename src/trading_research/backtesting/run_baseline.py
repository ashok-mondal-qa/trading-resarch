"""Run the baseline trend-breakout experiment (EXPERIMENT below) on one pre-registered split.

    python -m trading_research.backtesting.run_baseline --split train
    python -m trading_research.backtesting.run_baseline --split validation
    python -m trading_research.backtesting.run_baseline --split holdout --confirm-holdout   # once only

Writes reports/backtests/<EXPERIMENT>-<split>.json. The holdout refuses to run without --confirm-holdout and
refuses if any holdout report already exists (the spec allows one holdout evaluation, for any version).

EXP-0005 = spec v0.1 (train only; superseded after its run showed the cap-filling problem, see spec
changelog). EXP-0006 = spec v0.2.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import engine, metrics
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import bhavcopy, indices, quality
from trading_research.indicators import core, regime
from trading_research.strategies import baseline_trend_breakout as strat

SPLITS = {
    "train": ("2022-08-15", "2024-12-31"),
    "validation": ("2025-01-01", "2025-12-31"),
    "holdout": ("2026-01-01", "2026-10-22"),
}
DATA_START, DATA_END = date(2021, 10, 25), date(2026, 10, 22)
REPORT_DIR = REPO_ROOT / "reports" / "backtests"
EXPERIMENT = "EXP-0006"


def load_universe(root: Path, data_end: date, nifty: pd.Series, p: strat.Params, calendar: list):
    """Per-symbol engine frames and per-date feature rows, using only bars up to data_end."""
    frames, rows, skipped = {}, [], {}
    for path in sorted((root / "processed" / "adjusted").glob("*.parquet")):
        symbol = path.stem
        manifest_path = root / "manifests" / "adjusted" / f"{symbol}.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if manifest.get("status") == "DATA INSUFFICIENT":
            skipped[symbol] = "adjustment DATA INSUFFICIENT"
            continue
        adj = pd.read_parquet(path)
        adj = adj[adj["date"] <= pd.Timestamp(data_end)]
        if adj.empty:
            continue
        bars = core.ohlcv(adj, usable_only=True)
        if len(bars) < p.trend_slow:
            skipped[symbol] = "fewer usable bars than the slow MA"
            continue
        usable = adj[adj["usable"]].set_index("date").sort_index()
        bars["raw_close"] = usable["close"].to_numpy()
        f = strat.stock_features(bars, nifty, p)
        f["gate1"] = quality.gate1_series(bars.index, bars["volume"], calendar)
        frames[symbol] = pd.DataFrame({
            "open": bars["open"], "high": bars["high"], "low": bars["low"], "close": bars["close"],
            "adj_factor": usable["adj_factor"].to_numpy(), "stop": f["stop"], "exit_signal": f["exit_signal"],
            "median_traded_value": f["median_traded_value"],
        })
        hits = f[(f["signal"] | f["watchlist"]) & f["gate1"]]
        for d, r in hits.iterrows():
            rows.append((d, symbol, bool(r["signal"]), r["rs"]))
        # ablation: same entries without the volume and RS filters
        abl = f[f["inputs_complete"] & f["trend_ok"] & f["breakout"] & f["liquid"] & f["stop_ok"] & f["gate1"]]
        for d, r in abl.iterrows():
            rows.append((d, symbol, None, r["rs"]))
    feats = pd.DataFrame(rows, columns=["date", "symbol", "signal", "rs"])
    return frames, feats, skipped


def select(feats: pd.DataFrame, regime_trend: pd.Series, start, end, p: strat.Params, ablation: bool):
    sub = feats[feats["signal"].isna()] if ablation else feats[feats["signal"] == True]  # noqa: E712
    sub = sub[(sub["date"] >= pd.Timestamp(start)) & (sub["date"] <= pd.Timestamp(end))]
    sub = sub[regime_trend.reindex(sub["date"]).to_numpy() == "up"]
    sub = sub.sort_values(["date", "rs", "symbol"], ascending=[True, False, True])
    picked = sub.groupby("date").head(p.max_new_per_day)
    return {d: g["symbol"].tolist() for d, g in picked.groupby("date")}, int(len(sub))


def _bucket_stats(groups) -> dict:
    return {str(k): {"trades": int(len(g)), "expectancy_r": float(g["r_multiple"].mean()),
                     "sum_pnl_inr": float(g["pnl"].sum())} for k, g in groups}


def breakdowns(t: pd.DataFrame) -> dict:
    """Closed trades by volatility regime and by liquidity bucket (a size proxy: 20-day median traded
    value at the signal; NSE market caps are not in our data), plus how alike same-day entries were."""
    closed = t[t["reason"] != "open at end (marked)"]
    bins = [0, 2e8, 1e9, np.inf]
    labels = ["5-20 crore/day", "20-100 crore/day", ">100 crore/day"]
    liq = pd.cut(closed["median_traded_value"], bins=bins, labels=labels, right=False)
    pairs = closed.groupby("entry_date").filter(lambda g: len(g) == 2).sort_values(["entry_date", "symbol"])
    a, b = pairs["r_multiple"].to_numpy()[0::2], pairs["r_multiple"].to_numpy()[1::2]
    same_day = {"days_with_two_entries": int(len(a)),
                "both_lost": int(((a < 0) & (b < 0)).sum()), "both_won": int(((a > 0) & (b > 0)).sum()),
                "r_correlation": float(np.corrcoef(a, b)[0, 1]) if len(a) >= 10 else None}
    return {"by_volatility_regime": _bucket_stats(closed.groupby("vol_regime")),
            "by_liquidity_bucket": _bucket_stats(closed.groupby(liq, observed=True)),
            "same_day_entries": same_day}


def run_split(split: str, confirm_holdout: bool = False, root: Path = REPO_ROOT / "data") -> dict:
    start, end = SPLITS[split]
    out_path = REPORT_DIR / f"{EXPERIMENT}-{split}.json"
    if split == "holdout":
        if not confirm_holdout:
            raise SystemExit("holdout is sealed: pass --confirm-holdout to run it (once)")
        done = sorted(REPORT_DIR.glob("EXP-*-holdout.json"))
        if done:
            raise SystemExit(f"holdout already evaluated: {done[0]}")
    data_end = date.fromisoformat(end)  # never load bars after the split
    settings = load_settings()
    p = strat.Params()
    store = bhavcopy.Store(root=root)
    calendar = quality.sessions(store, DATA_START, data_end)
    nifty = indices.read_index("Nifty 50", DATA_START, data_end, root)["close"]
    reg = regime.regime(nifty)
    frames, feats, skipped = load_universe(root, data_end, nifty, p, calendar)
    split_calendar = [d for d in calendar if pd.Timestamp(start) <= pd.Timestamp(d) <= pd.Timestamp(end)]
    equity0 = float(settings["virtual_portfolio"]["starting_equity_inr"])

    report = {
        "experiment": EXPERIMENT, "strategy": "baseline-trend-breakout", "spec_version": strat.SPEC_VERSION,
        "split": split, "range": [start, end], "params": p.as_dict(),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "universe_symbols_loaded": len(frames), "universe_symbols_skipped": len(skipped),
        "costs_verified": bool(settings["costs"]["verified"]),
        "regime_days": reg["trend"].reindex(pd.to_datetime(split_calendar)).value_counts().to_dict(),
        "runs": {},
    }
    for name, ablation, mult in (("baseline_1x", False, 1.0), ("baseline_2x_costs", False, 2.0),
                                 ("ablation_no_volume_rs_1x", True, 1.0)):
        cands, n_signals = select(feats, reg["trend"], start, end, p, ablation)
        res = engine.run(frames, cands, split_calendar, settings, equity0, p.max_holding_sessions, mult)
        summary = metrics.summarize(res.trades, res.equity, equity0)
        summary.update({"signals_after_regime_gate": n_signals,
                        "candidates_taken": int(sum(len(v) for v in cands.values())),
                        "entries_skipped": res.skipped["reason"].value_counts().to_dict() if len(res.skipped) else {}})
        if name == "baseline_1x" and len(res.trades):
            t = res.trades.copy()
            t["vol_regime"] = reg["volatility"].reindex(t["signal_date"]).to_numpy()
            t["median_traded_value"] = [frames[r.symbol].loc[r.signal_date, "median_traded_value"]
                                        for r in t.itertuples()]
            summary.update(breakdowns(t))
            trades_path = REPORT_DIR / f"{EXPERIMENT}-{split}-trades.csv"
            trades_path.parent.mkdir(parents=True, exist_ok=True)
            t.to_csv(trades_path, index=False)
        report["runs"][name] = summary
    bench = nifty[(nifty.index >= pd.Timestamp(start)) & (nifty.index <= pd.Timestamp(end))]
    report["benchmark_nifty50_return"] = float(bench.iloc[-1] / bench.iloc[0] - 1) if len(bench) > 1 else None
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report


# pre-registered neighbouring values (spec "Splits"): a robustness check on train only, never used to pick
ROBUSTNESS = {"breakout_lookback": (15, 30), "stop_atr": (1.5, 2.5), "volume_ratio_min": (1.25, 2.0)}


def robustness(root: Path = REPO_ROOT / "data") -> dict:
    start, end = SPLITS["train"]
    data_end = date.fromisoformat(end)
    settings = load_settings()
    store = bhavcopy.Store(root=root)
    calendar = quality.sessions(store, DATA_START, data_end)
    nifty = indices.read_index("Nifty 50", DATA_START, data_end, root)["close"]
    reg = regime.regime(nifty)
    split_calendar = [d for d in calendar if pd.Timestamp(start) <= pd.Timestamp(d) <= pd.Timestamp(end)]
    equity0 = float(settings["virtual_portfolio"]["starting_equity_inr"])
    out = {"experiment": EXPERIMENT, "split": "train", "note": "robustness only; not used to choose values",
           "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "variants": {}}
    for name, values in ROBUSTNESS.items():
        for value in values:
            p = replace(strat.Params(), **{name: value})
            frames, feats, _ = load_universe(root, data_end, nifty, p, calendar)
            row = {}
            for label, mult in (("1x", 1.0), ("2x_costs", 2.0)):
                cands, _ = select(feats, reg["trend"], start, end, p, ablation=False)
                res = engine.run(frames, cands, split_calendar, settings, equity0, p.max_holding_sessions, mult)
                s = metrics.summarize(res.trades, res.equity, equity0)
                row[label] = {k: s.get(k) for k in ("trades", "net_return", "expectancy_r", "expectancy_r_ci95",
                                                    "profit_factor", "max_drawdown")}
            out["variants"][f"{name}={value}"] = row
    path = REPORT_DIR / f"{EXPERIMENT}-train-robustness.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=list(SPLITS))
    parser.add_argument("--confirm-holdout", action="store_true")
    parser.add_argument("--robustness", action="store_true", help="neighbouring values on train only")
    args = parser.parse_args(argv)
    if args.robustness:
        print(json.dumps(robustness(), indent=2, default=str))
        return 0
    if not args.split:
        parser.error("--split is required")
    report = run_split(args.split, args.confirm_holdout)
    print(json.dumps({k: v for k, v in report.items() if k != "params"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
