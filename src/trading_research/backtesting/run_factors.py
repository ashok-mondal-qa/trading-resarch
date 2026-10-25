"""Run the factor-portfolio experiments EXP-0039..0041 (spec docs/strategy-specifications/factor-portfolios.md).
Research and paper only: nothing here orders or alerts.

    python -m trading_research.backtesting.run_factors        # all three, every split, 1x and 2x costs
    python -m trading_research.backtesting.run_factors --forward --as-of 2026-11-30   # EXP-0042/0043 (paper)

Each split is simulated on its own from ₹10 lakh. Signals at a month's last close; trades at the next session's
open; sells first, then buys sized at min(cash / new names, equity / holdings); positions drift between
rebalances; idle cash earns nothing. Stocks are read only up to DATA_END; the 2026 holdout has no path here.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import compare_markets as cm
from trading_research.backtesting import costs as cost_model
from trading_research.backtesting import metrics
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.backtesting.run_swing_ideas import _manifest, superseded_tickers, usable_as_of
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import indices
from trading_research.strategies import factors as fa

DATA_START, DATA_END = date(2011, 7, 1), date(2025, 12, 31)
SPLITS = {
    "dev": ("2013-01-01", "2022-12-31"),
    "dev_a": ("2013-01-01", "2017-12-31"),
    "dev_b": ("2018-01-01", "2022-12-31"),
    "validation": ("2023-01-01", "2025-12-31"),
}
SIGN_SPLITS = ("dev_a", "dev_b", "validation")
HOLDOUT = ("2026-01-01", "2026-10-22")       # sealed: never loaded by this runner
EXPERIMENTS = {"lowvol": "EXP-0039", "momentum": "EXP-0040", "mom_lowvol": "EXP-0041"}
ALPHA = 0.05 / len(EXPERIMENTS)
START_EQUITY = 1_000_000.0
SLIPPAGE_PCT = 0.10                          # per side at 1x, of the open price
STALE_DAYS = 5                               # a holding with no bar for this many sessions is sold at its last close
MAX_DD_GAP = 0.10                            # validation drawdown may be at most 10 points worse than NIFTY's
# Forward paper tracking of the two near misses (forward-tracking.md v0.2): frozen EXP-0039 / EXP-0041 rules,
# first portfolio from the close of 2026-10-30, trades from the next open. Decide after FORWARD_MONTHS.
FORWARD = {"lowvol": "EXP-0042", "mom_lowvol": "EXP-0043"}
FORWARD_START = "2026-11-02"
FORWARD_MONTHS = 24
FORWARD_DIR = REPO_ROOT / "reports" / "forward"


def load(root: Path = REPO_ROOT / "data", end: date = DATA_END):
    paths = sorted((root / "processed" / "adjusted").glob("*.parquet"))
    superseded = superseded_tickers(root, [q.stem for q in paths])
    close, open_, value = {}, {}, {}
    for path in paths:
        if path.stem in superseded:
            continue
        adj = pd.read_parquet(path)
        adj = adj[(adj["date"] >= pd.Timestamp(DATA_START)) & (adj["date"] <= pd.Timestamp(end))].copy()
        if adj.empty or str(adj["isin"].iloc[-1]).startswith("INF"):
            continue
        adj["usable"] = usable_as_of(adj, _manifest(root, path.stem), end)
        adj = adj[adj["usable"]].set_index("date").sort_index()
        if len(adj) < 250:
            continue
        close[path.stem], open_[path.stem], value[path.stem] = adj["adj_close"], adj["adj_open"], adj["traded_value"]
    nifty = indices.read_index("Nifty 50", DATA_START, end, root)
    nifty.index = pd.to_datetime(nifty.index)
    nifty = nifty[~nifty.index.duplicated()].sort_index()
    cal = nifty.index
    frame = lambda d: pd.DataFrame(d).reindex(cal).sort_index()   # noqa: E731
    return frame(close), frame(open_), frame(value), nifty


def _cost(side: str, value: float, costs: dict, mult: float) -> float:
    if value <= 0:
        return 0.0
    c = cost_model.leg_costs(side, value, 1, costs).total
    return (c + value * SLIPPAGE_PCT / 100) * mult


def simulate(strategy: str, close: pd.DataFrame, open_: pd.DataFrame, value: pd.DataFrame, start: str, end: str,
             costs: dict, mult: float = 1.0, p: fa.Params = fa.Params()):
    """Daily equity (₹) and closed lots (entry_date, exit_date, pnl) for one split."""
    cal = close.index[(close.index >= pd.Timestamp(start)) & (close.index <= pd.Timestamp(end))]
    rebal = set(fa.month_ends(close.index[close.index <= pd.Timestamp(end)]))
    cash, pos, lots, equity = START_EQUITY, {}, [], {}
    last_px = close.ffill(limit=STALE_DAYS)
    prev = close.index[close.index.get_loc(cal[0]) - 1]      # first portfolio from the last close before the split
    pending = fa.targets(strategy, close, value, prev, p)
    for day in cal:
        if pending is not None:
            px = open_.loc[day]
            for s in [s for s in pos if s not in pending]:
                q, basis, d0 = pos[s]
                price = px.get(s)
                if not np.isfinite(price):
                    continue                                   # no open today: retry at the next rebalance
                proceeds = q * price
                c = _cost("sell", proceeds, costs, mult)
                cash += proceeds - c
                lots.append({"symbol": s, "entry_date": d0, "exit_date": day, "pnl": proceeds - c - basis})
                del pos[s]
            mark = sum(q * last_px.at[day, s] if np.isfinite(last_px.at[day, s]) else 0 for s, (q, _, _) in pos.items())
            eq = cash + mark
            new = [s for s in pending if s not in pos and np.isfinite(px.get(s, np.nan))]
            if new:
                size = min(cash / len(new), eq / p.holdings)
                for s in new:
                    gross = size / (1 + (cost_model.leg_costs("buy", 1e6, 1, costs).total / 1e6 + SLIPPAGE_PCT / 100) * mult)
                    c = _cost("buy", gross, costs, mult)
                    if gross <= 0 or gross + c > cash + 1e-6:
                        continue
                    cash -= gross + c
                    pos[s] = (gross / px[s], gross + c, day)
            pending = None
        # holdings that stopped trading are sold at their last close
        for s in list(pos):
            if not np.isfinite(last_px.at[day, s]):
                q, basis, d0 = pos.pop(s)
                lastc = close[s].loc[:day].dropna()
                proceeds = q * float(lastc.iloc[-1])
                c = _cost("sell", proceeds, costs, mult)
                cash += proceeds - c
                lots.append({"symbol": s, "entry_date": d0, "exit_date": day, "pnl": proceeds - c - basis})
        equity[day] = cash + sum(q * last_px.at[day, s] for s, (q, _, _) in pos.items())
        if day in rebal and day != cal[-1]:
            pending = fa.targets(strategy, close, value, day, p)
    # liquidate at the last close for tax
    last = cal[-1]
    for s, (q, basis, d0) in pos.items():
        proceeds = q * last_px.at[last, s]
        lots.append({"symbol": s, "entry_date": d0, "exit_date": last,
                     "pnl": proceeds - _cost("sell", proceeds, costs, mult) - basis})
    return pd.Series(equity), pd.DataFrame(lots)


def nifty_curve(nifty: pd.DataFrame, start: str, end: str, costs: dict, mult: float = 1.0):
    """NIFTY 50 price index bought at the first open with the same costs, held, sold for tax at the end."""
    n = nifty[(nifty.index >= pd.Timestamp(start)) & (nifty.index <= pd.Timestamp(end))]
    gross = START_EQUITY / (1 + (cost_model.leg_costs("buy", 1e6, 1, costs).total / 1e6 + SLIPPAGE_PCT / 100) * mult)
    units = gross / n["open"].iloc[0]
    equity = START_EQUITY - gross + units * n["close"]
    proceeds = units * n["close"].iloc[-1]
    lots = pd.DataFrame([{"entry_date": n.index[0], "exit_date": n.index[-1],
                          "pnl": proceeds - _cost("sell", proceeds, costs, mult) - START_EQUITY}])
    return equity, lots


def monthly(equity: pd.Series) -> pd.Series:
    return equity.resample("ME").last().pct_change().dropna()


def sharpe(r: pd.Series | np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(12)) if len(r) > 2 and r.std(ddof=1) > 0 else float("nan")


def sharpe_diff_ci(a: pd.Series, b: pd.Series, alpha: float = ALPHA, block: int = 12, n: int = 5000,
                   seed: int = 0) -> tuple[float, float]:
    """Moving-block bootstrap (12-month blocks) of Sharpe(a) - Sharpe(b) on paired monthly returns."""
    x = pd.concat([a, b], axis=1).dropna().to_numpy()
    m = len(x)
    if m < 2 * block:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    starts = np.arange(m - block + 1)
    k = int(np.ceil(m / block))
    diffs = np.empty(n)
    for i in range(n):
        idx = (rng.choice(starts, k)[:, None] + np.arange(block)).ravel()[:m]
        s = x[idx]
        diffs[i] = sharpe(s[:, 0]) - sharpe(s[:, 1])
    return float(np.quantile(diffs, alpha / 2)), float(np.quantile(diffs, 1 - alpha / 2))


def split_report(equity: pd.Series, lots: pd.DataFrame, bench: pd.Series, bench_lots: pd.DataFrame,
                 ci: bool = False) -> dict:
    taxes, btaxes = cm.equity_tax(lots, equity.index[-1]), cm.equity_tax(bench_lots, bench.index[-1])
    ms, mb = monthly(equity), monthly(bench)
    out = {"strategy": cm.stats(equity, 252), "strategy_after_tax": cm.stats(cm.apply_taxes(equity, taxes), 252),
           "nifty": cm.stats(bench, 252), "nifty_after_tax": cm.stats(cm.apply_taxes(bench, btaxes), 252),
           "sharpe_monthly": sharpe(ms), "nifty_sharpe_monthly": sharpe(mb),
           "max_drawdown": metrics.max_drawdown(equity), "nifty_max_drawdown": metrics.max_drawdown(bench),
           "lots_closed": int(len(lots)), "tax_paid_inr": float(taxes.sum())}
    if ci:
        out[f"sharpe_diff_ci_{1 - ALPHA:.4f}"] = sharpe_diff_ci(ms, mb)
    return out


def verdict(results: dict) -> dict:
    d1, d2 = results["1x"]["dev"], results["2x"]["dev"]
    lo = (d1.get(f"sharpe_diff_ci_{1 - ALPHA:.4f}") or (-1, -1))[0]
    checks = {
        "dev 2x: Sharpe above NIFTY": d2["sharpe_monthly"] > d2["nifty_sharpe_monthly"],
        "dev 2x: after-tax CAGR above NIFTY": d2["strategy_after_tax"]["cagr"] > d2["nifty_after_tax"]["cagr"],
        f"dev 1x: {1 - ALPHA:.2%} interval of the Sharpe difference above 0": lo > 0,
    }
    for split in SIGN_SPLITS:
        s = results["2x"][split]
        checks[f"{split} 2x: Sharpe not below NIFTY"] = s["sharpe_monthly"] >= s["nifty_sharpe_monthly"]
    v = results["2x"]["validation"]
    checks["validation 2x: drawdown at most 10 points worse than NIFTY"] = v["max_drawdown"] >= v["nifty_max_drawdown"] - MAX_DD_GAP
    return {"checks": checks, "status": "HOLDOUT CANDIDATE" if all(checks.values()) else "REJECTED"}


def run(strategy: str, close, open_, value, nifty, costs: dict) -> dict:
    out = {"experiment": EXPERIMENTS[strategy], "strategy": strategy, "spec_version": fa.SPEC_VERSION,
           "params": fa.Params().as_dict(), "slippage_pct_per_side": SLIPPAGE_PCT,
           "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    for mult, label in ((1.0, "1x"), (2.0, "2x")):
        out[label] = {}
        for split, (start, end) in SPLITS.items():
            eq, lots = simulate(strategy, close, open_, value, start, end, costs, mult)
            beq, blots = nifty_curve(nifty, start, end, costs, mult)
            out[label][split] = split_report(eq, lots, beq.reindex(eq.index).ffill(), blots,
                                             ci=(label == "1x" and split == "dev"))
            if label == "1x" and split == "dev":
                eq.to_csv(REPORT_DIR / f"{EXPERIMENTS[strategy]}-dev-equity.csv", header=["equity"])
    out["verdict"] = verdict(out)
    return out


def forward_decision(report: dict, months: float) -> str:
    """Pre-registered: tracking until FORWARD_MONTHS; then PASSED only if at 1x and 2x costs CAGR and Sharpe are
    not below NIFTY's and the drawdown is at most 10 points worse."""
    if months < FORWARD_MONTHS:
        return "tracking"
    ok = all(r["strategy"]["cagr"] >= r["nifty"]["cagr"] and r["sharpe_monthly"] >= r["nifty_sharpe_monthly"]
             and r["max_drawdown"] >= r["nifty_max_drawdown"] - MAX_DD_GAP for r in (report["1x"], report["2x"]))
    return "PASSED (candidate for paper-trading review)" if ok else "REJECTED"


def forward(strategy: str, as_of: date, root: Path = REPO_ROOT / "data") -> dict:
    if pd.Timestamp(as_of) < pd.Timestamp(FORWARD_START):
        raise SystemExit(f"as_of must be on or after {FORWARD_START}")
    exp = FORWARD[strategy]
    close, open_, value, nifty = load(root, end=as_of)
    costs = load_settings()["costs"]
    sessions = close.index[close.index >= pd.Timestamp(FORWARD_START)]
    report = {"experiment": exp, "frozen_rules": EXPERIMENTS[strategy], "strategy": strategy,
              "forward_start": FORWARD_START, "as_of": str(as_of), "last_bar": str(close.index.max().date())}
    if close.index.max() < pd.Timestamp(as_of) - pd.Timedelta(days=4):
        report["status"] = "DATA INSUFFICIENT"
    elif len(sessions) < 2:
        report["status"] = "no forward sessions yet"
    else:
        for mult, label in ((1.0, "1x"), (2.0, "2x")):
            eq, lots = simulate(strategy, close, open_, value, FORWARD_START, str(as_of), costs, mult)
            beq, blots = nifty_curve(nifty, FORWARD_START, str(as_of), costs, mult)
            report[label] = split_report(eq, lots, beq.reindex(eq.index).ffill(), blots) if len(eq) >= 20 else {
                "net_return": float(eq.iloc[-1] / START_EQUITY - 1),
                "nifty_net_return": float(beq.iloc[-1] / START_EQUITY - 1), "sessions": int(len(eq))}
            if label == "1x":
                FORWARD_DIR.mkdir(parents=True, exist_ok=True)
                eq.to_csv(FORWARD_DIR / f"{exp}-equity.csv", header=["equity"])
                last = close.index.max()
                report["targets_from_close_of"] = str(last.date())   # trade at the next open if this ends a month
                report["targets"] = fa.targets(strategy, close, value, last)
        months = (pd.Timestamp(as_of) - pd.Timestamp(FORWARD_START)).days / 30.4375
        report["months"] = round(months, 2)
        report["status"] = forward_decision(report, months) if "strategy" in report.get("1x", {}) else "tracking"
    report["generated_at_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    FORWARD_DIR.mkdir(parents=True, exist_ok=True)
    (FORWARD_DIR / f"{exp}-{as_of}.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=fa.STRATEGIES)
    parser.add_argument("--forward", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args(argv)
    if args.forward:
        for strategy in FORWARD:
            r = forward(strategy, args.as_of)
            print(r["experiment"], r["status"], {k: r.get("1x", {}).get(k) for k in ("net_return", "nifty_net_return")})
        return 0
    close, open_, value, nifty = load()
    costs = load_settings()["costs"]
    print(f"stocks {close.shape[1]}, sessions {close.index.min().date()}..{close.index.max().date()}", flush=True)
    for strategy in ([args.strategy] if args.strategy else fa.STRATEGIES):
        result = run(strategy, close, open_, value, nifty, costs)
        (REPORT_DIR / f"{EXPERIMENTS[strategy]}-{strategy}.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(strategy, result["verdict"]["status"], json.dumps(result["verdict"]["checks"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
