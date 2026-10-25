"""Run the NIFTY options experiments EXP-0029..0032 (spec docs/strategy-specifications/nifty-options.md).
Research only: derivatives are banned for paper and live trading, nothing here orders or alerts.

    python -m trading_research.backtesting.run_options          # all four, every split, 1x and 2x costs

Data are read only up to DATA_END; the 2025-01-01..2026-10-23 holdout has no path here.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import metrics
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.config import REPO_ROOT
from trading_research.data import fo_bhavcopy, indices
from trading_research.indicators import regime
from trading_research.strategies import options as op

DATA_START, DATA_END = date(2012, 1, 2), date(2024, 12, 31)
SPLITS = {
    "dev": ("2012-02-21", "2022-12-31"),
    "dev_a": ("2012-02-21", "2016-12-31"),
    "dev_b": ("2017-01-01", "2022-12-31"),
    "validation": ("2023-01-01", "2024-12-31"),
}
SIGN_SPLITS = ("dev_a", "dev_b", "validation")
HOLDOUT = ("2025-01-01", "2026-10-23")       # sealed: never loaded by this runner
EXPERIMENTS = {"iron_condor": "EXP-0029", "short_strangle": "EXP-0030", "covered_call": "EXP-0031",
               "long_call": "EXP-0032"}
FAMILY_SIZE = 4
ALPHA = 0.05 / FAMILY_SIZE
MIN_TRADES = 60
ILLUSTRATIVE_RISK = 0.05
FO_TAX = 0.312


def load(root: Path = REPO_ROOT / "data"):
    rows = fo_bhavcopy.read(DATA_START, DATA_END, root)
    nifty = indices.read_index("Nifty 50", DATA_START, DATA_END, root)
    nifty.index = pd.to_datetime(nifty.index)
    nifty = nifty[~nifty.index.duplicated()].sort_index()
    return op.Chain(rows[rows["symbol"] == "NIFTY"]), nifty


def in_split(trades: pd.DataFrame, split: str) -> pd.DataFrame:
    start, end = (pd.Timestamp(x) for x in SPLITS[split])
    if trades.empty:
        return trades
    return trades[(trades["entry_date"] >= start) & (trades["expiry"] <= end) & (trades["exit_date"] <= end)]


def fy(day: pd.Timestamp) -> int:
    return day.year if day.month >= 4 else day.year - 1


def fo_tax_curve(pnl: pd.Series, start: float = 1.0) -> dict:
    """Sequential equity from per-trade rupee P&L (indexed by exit date) with F&O business-income tax: 31.2% of
    each financial year's net profit after carried-forward losses, paid at the year's end."""
    equity, carry, yearly = start, 0.0, {}
    for year, group in pnl.groupby(pnl.index.map(fy)):
        net = group.sum() - carry
        tax = FO_TAX * max(net, 0.0)
        carry = max(-net, 0.0)
        equity += group.sum() - tax
        yearly[int(year)] = {"pnl": float(group.sum()), "tax": float(tax)}
    return {"end_equity": equity, "years": yearly}


def risk_curve(trades: pd.DataFrame) -> dict:
    """Illustrative: risk ILLUSTRATIVE_RISK of equity per trade (losses beyond R lose more)."""
    if trades.empty:
        return {}
    t = trades.sort_values("exit_date")
    equity, pnls, curve = 1.0, [], []
    for _, row in t.iterrows():
        gain = equity * ILLUSTRATIVE_RISK * row["r_multiple"]
        pnls.append(gain)
        equity = max(equity + gain, 0.0)
        curve.append(equity)
    curve = pd.Series(curve, index=t["exit_date"].to_numpy())
    years = (t["exit_date"].max() - t["entry_date"].min()).days / 365.25
    taxed = fo_tax_curve(pd.Series(pnls, index=t["exit_date"].to_numpy()))
    return {"end_equity": float(equity), "cagr": float(equity ** (1 / years) - 1) if equity > 0 and years > 0 else -1.0,
            "max_drawdown": metrics.max_drawdown(pd.concat([pd.Series([1.0]), curve.reset_index(drop=True)])),
            "end_equity_after_fo_tax_approx": float(taxed["end_equity"])}


def r_summary(trades: pd.DataFrame, ci: bool = False) -> dict:
    if trades.empty:
        return {"trades": 0}
    r = trades["r_multiple"].to_numpy(float)
    pnl = trades["pnl"]
    gains, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    top5 = pnl.sort_values(ascending=False).head(5).sum()
    out = {"trades": int(len(r)), "expectancy_r": float(r.mean()), "win_rate": float((r > 0).mean()),
           "profit_factor": float(gains / losses) if losses > 0 else None, "worst_r": float(r.min()),
           "best_r": float(r.max()), "worst_loss_pct_of_index": float((pnl / trades["spot"]).min() * 100),
           "mean_pnl_points": float(pnl.mean()), "top5_share_of_net_profit": float(top5 / pnl.sum()) if pnl.sum() > 0 else None,
           "losing_months": int((pnl.groupby(trades["exit_date"].dt.to_period("M")).sum() < 0).sum()),
           "exit_reasons": trades["reason"].value_counts().to_dict(), "illustrative_5pct_risk": risk_curve(trades)}
    if ci:
        out[f"ci_{1 - ALPHA:.4f}"] = metrics.bootstrap_ci(r, alpha=ALPHA)
    return out


def covered_call_cycles(chain: op.Chain, nifty: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Monthly returns from one monthly expiry close to the next: NIFTY alone vs NIFTY + the short call."""
    close = nifty["close"]
    expiries = [e for e in chain.monthly_expiries() if e in close.index]
    by_expiry = trades.set_index("expiry") if not trades.empty else pd.DataFrame()
    rows = []
    for prev, nxt in zip(expiries, expiries[1:]):
        start = close.index[close.index > prev]
        if not len(start):
            continue
        option = float(by_expiry.loc[nxt, "pnl"]) if nxt in by_expiry.index else 0.0
        rows.append({"entry_date": start[0], "expiry": nxt, "exit_date": nxt,
                     "hold": close[nxt] / close[prev] - 1, "covered_call": (close[nxt] - close[prev] + option) / close[prev],
                     "call_sold": nxt in by_expiry.index})
    return pd.DataFrame(rows)


def monthly_stats(returns: pd.Series) -> dict:
    if len(returns) < 2:
        return {"months": int(len(returns))}
    equity = (1 + returns).cumprod()
    years = len(returns) / 12
    return {"months": int(len(returns)), "sharpe": float(returns.mean() / returns.std() * np.sqrt(12)),
            "cagr": float(equity.iloc[-1] ** (1 / years) - 1),
            "max_drawdown": metrics.max_drawdown(pd.concat([pd.Series([1.0]), equity.reset_index(drop=True)])),
            "worst_month": float(returns.min())}


def verdict(strategy: str, results: dict) -> dict:
    if strategy == "covered_call":
        dev1, dev2 = results["1x"]["dev"], results["2x"]["dev"]
        checks = {
            "dev 1x: Sharpe above buy and hold": dev1["covered_call"]["sharpe"] > dev1["hold"]["sharpe"],
            "dev 2x: Sharpe above buy and hold": dev2["covered_call"]["sharpe"] > dev2["hold"]["sharpe"],
            "dev 1x: max drawdown not worse": dev1["covered_call"]["max_drawdown"] >= dev1["hold"]["max_drawdown"],
        }
        for split in SIGN_SPLITS:
            s = results["2x"][split]
            checks[f"{split} 2x: Sharpe not below buy and hold"] = s["covered_call"]["sharpe"] >= s["hold"]["sharpe"]
    else:
        dev1, dev2 = results["1x"]["dev"], results["2x"]["dev"]
        lo = (dev1.get(f"ci_{1 - ALPHA:.4f}") or (-1, -1))[0]
        checks = {
            f"dev >= {MIN_TRADES} trades": dev1.get("trades", 0) >= MIN_TRADES,
            "dev 2x: expectancy > 0": (dev2.get("expectancy_r") or -1) > 0,
            "dev 2x: profit factor >= 1.1": (dev2.get("profit_factor") or 0) >= 1.1,
            f"dev 1x: {1 - ALPHA:.2%} interval lower bound > 0": lo > 0,
        }
        for split in SIGN_SPLITS:
            checks[f"{split} 2x: expectancy > 0"] = (results["2x"][split].get("expectancy_r") or -1) > 0
    return {"checks": checks, "status": "HOLDOUT CANDIDATE" if all(checks.values()) else "REJECTED"}


def run(strategy: str, chain: op.Chain, nifty: pd.DataFrame) -> dict:
    sessions = list(nifty.index)
    trend = regime.regime(nifty["close"])["trend"]
    out = {"experiment": EXPERIMENTS[strategy], "strategy": strategy, "spec_version": op.SPEC_VERSION,
           "params": op.Params().as_dict(), "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    cycles_possible = None
    for mult, label in ((1.0, "1x"), (2.0, "2x")):
        if strategy == "long_call":
            trades = op.long_call_trades(chain, nifty, trend, sessions, mult=mult)
        else:
            trades = op.monthly_trades(strategy, chain, nifty["close"], sessions, mult=mult)
        out[label] = {}
        if strategy == "covered_call":
            cycles = covered_call_cycles(chain, nifty, trades)
            cycles_possible = len(cycles)
            for split in SPLITS:
                c = in_split(cycles, split)
                out[label][split] = {"hold": monthly_stats(c["hold"]), "covered_call": monthly_stats(c["covered_call"]),
                                     "months_with_call": int(c["call_sold"].sum()),
                                     "option_trades": r_summary(in_split(trades, split))}
        else:
            for split in SPLITS:
                out[label][split] = r_summary(in_split(trades, split), ci=(label == "1x" and split == "dev"))
        if label == "1x":
            trades.to_csv(REPORT_DIR / f"{EXPERIMENTS[strategy]}-trades.csv", index=False)
    if cycles_possible is not None:
        out["monthly_cycles"] = cycles_possible
    out["verdict"] = verdict(strategy, out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=op.STRATEGIES)
    args = parser.parse_args(argv)
    chain, nifty = load()
    print(f"NIFTY sessions {nifty.index.min().date()}..{nifty.index.max().date()} ({len(nifty)}); "
          f"option rows {len(chain.rows)}; monthly expiries {len(chain.monthly_expiries())}", flush=True)
    for strategy in ([args.strategy] if args.strategy else op.STRATEGIES):
        result = run(strategy, chain, nifty)
        path = REPORT_DIR / f"{EXPERIMENTS[strategy]}-{strategy}.json"
        path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
        print(strategy, result["verdict"]["status"], json.dumps(result["verdict"]["checks"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
