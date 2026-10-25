"""Run the crypto intraday experiments EXP-0033..0036 (spec docs/strategy-specifications/crypto-intraday.md).
Research only: long only, spot, nothing here orders or alerts.

    python -m trading_research.backtesting.run_intraday            # all four, every split, 1x and 2x costs

Bars are read strictly before DATA_END; the 2025-01-01..2026-09-30 holdout has no path here.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import metrics
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.config import REPO_ROOT
from trading_research.data import binance_intraday as bi
from trading_research.strategies import intraday as it

SYMBOLS = ("BTCUSDT", "ETHUSDT")
DATA_START, DATA_END = "2018-01-01", "2025-01-01"          # end exclusive
SPLITS = {
    "dev": ("2018-01-01", "2022-12-31"),
    "dev_a": ("2018-01-01", "2020-12-31"),
    "dev_b": ("2021-01-01", "2022-12-31"),
    "validation": ("2023-01-01", "2024-12-31"),
}
SIGN_SPLITS = ("dev_a", "dev_b", "validation")
HOLDOUT = ("2025-01-01", "2026-09-30")                      # sealed: not downloaded, never read
EXPERIMENTS = {"orb": "EXP-0033", "ema_cross": "EXP-0034", "bb_rsi": "EXP-0035", "supertrend": "EXP-0036",
               "ema_scalp": "EXP-0037", "ema_scalp_minstop": "EXP-0038"}
# Bonferroni families: the four pre-registered in v0.1, then the two 9/15 EMA scalp variants added in v0.2.
FAMILY_SIZE = {"orb": 4, "ema_cross": 4, "bb_rsi": 4, "supertrend": 4, "ema_scalp": 2, "ema_scalp_minstop": 2}
ALPHA = 0.05 / 4


def alpha(strategy: str) -> float:
    return 0.05 / FAMILY_SIZE[strategy]
MIN_TRADES = 200
RISK = 0.005
MAX_POSITION = 0.5


def load(root: Path = REPO_ROOT / "data") -> dict[str, pd.DataFrame]:
    out = {}
    for s in SYMBOLS:
        b = bi.read_bars(s, root, end=DATA_END)
        out[s] = b[b.index >= pd.Timestamp(DATA_START)]
    return out


def in_split(trades: pd.DataFrame, split: str) -> pd.DataFrame:
    if trades.empty:
        return trades
    start, end = pd.Timestamp(SPLITS[split][0]), pd.Timestamp(SPLITS[split][1]) + pd.Timedelta(days=1)
    return trades[(trades["entry_time"] >= start) & (trades["entry_time"] < end)]


def equity_curve(trades: pd.DataFrame) -> dict:
    """Illustrative: risk min(0.5%, 50% x stop distance) of equity per trade, compounded in exit order."""
    if trades.empty:
        return {}
    t = trades.sort_values("exit_time")
    frac = np.minimum(RISK, MAX_POSITION * t["risk_pct"].to_numpy() / 100)
    growth = 1 + frac * t["r_multiple"].to_numpy()
    growth_tax = 1 + frac * t["r_after_tax"].to_numpy()
    eq, eq_tax = np.cumprod(growth), np.cumprod(growth_tax)
    years = (t["exit_time"].max() - t["entry_time"].min()).days / 365.25
    return {"end_equity": float(eq[-1]), "cagr": float(eq[-1] ** (1 / years) - 1),
            "max_drawdown": metrics.max_drawdown(pd.Series(np.concatenate([[1.0], eq]))),
            "end_equity_after_tax": float(eq_tax[-1]), "cagr_after_tax": float(eq_tax[-1] ** (1 / years) - 1)}


def summary(trades: pd.DataFrame, ci: bool = False, a: float = ALPHA) -> dict:
    if trades.empty:
        return {"trades": 0}
    r = trades["r_multiple"].to_numpy(float)
    pnl = trades["pnl_pct"]
    gains, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    top5 = pnl.sort_values(ascending=False).head(5).sum()
    hold = (trades["exit_time"] - trades["entry_time"]).dt.total_seconds() / 3600
    months = trades["entry_time"].dt.to_period("M")
    out = {"trades": int(len(r)), "expectancy_r": float(r.mean()), "expectancy_r_after_tax": float(trades["r_after_tax"].mean()),
           "win_rate": float((r > 0).mean()), "profit_factor": float(gains / losses) if losses > 0 else None,
           "mean_pnl_pct": float(pnl.mean()), "sum_pnl_pct": float(pnl.sum()), "worst_r": float(r.min()),
           "best_r": float(r.max()), "worst_pnl_pct": float(pnl.min()),
           "top5_share_of_net_profit": float(top5 / pnl.sum()) if pnl.sum() > 0 else None,
           "mean_hold_hours": float(hold.mean()), "trades_per_month": float(len(r) / months.nunique()),
           "median_stop_pct": float(trades["risk_pct"].median()), "exit_reasons": trades["reason"].value_counts().to_dict(),
           "by_symbol": {s: {"trades": int(len(g)), "expectancy_r": float(g["r_multiple"].mean())}
                         for s, g in trades.groupby("symbol")},
           "illustrative_0p5pct_risk": equity_curve(trades)}
    if ci:
        out[f"ci_{1 - a:.4f}"] = metrics.cluster_bootstrap_ci(r, months.astype(str).to_numpy(), alpha=a)
    return out


def buy_and_hold(bars: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for s, b in bars.items():
        out[s] = {}
        for split, (start, end) in SPLITS.items():
            c = b["close"][(b.index >= pd.Timestamp(start)) & (b.index < pd.Timestamp(end) + pd.Timedelta(days=1))]
            years = (c.index[-1] - c.index[0]).days / 365.25
            daily = c.resample("1D").last().dropna()
            out[s][split] = {"return": float(c.iloc[-1] / c.iloc[0] - 1), "cagr": float((c.iloc[-1] / c.iloc[0]) ** (1 / years) - 1),
                             "max_drawdown": metrics.max_drawdown(daily)}
    return out


def verdict(results: dict, a: float = ALPHA) -> dict:
    dev1, dev2 = results["1x"]["dev"], results["2x"]["dev"]
    lo = (dev1.get(f"ci_{1 - a:.4f}") or (-1, -1))[0]
    checks = {
        f"dev >= {MIN_TRADES} trades": dev1.get("trades", 0) >= MIN_TRADES,
        "dev 2x: expectancy > 0": (dev2.get("expectancy_r") or -1) > 0,
        "dev 2x: profit factor >= 1.1": (dev2.get("profit_factor") or 0) >= 1.1,
        f"dev 1x: {1 - a:.2%} interval lower bound > 0": lo > 0,
        "dev 1x: after-tax expectancy > 0": (dev1.get("expectancy_r_after_tax") or -1) > 0,
    }
    for split in SIGN_SPLITS:
        checks[f"{split} 2x: expectancy > 0"] = (results["2x"][split].get("expectancy_r") or -1) > 0
    return {"checks": checks, "status": "HOLDOUT CANDIDATE" if all(checks.values()) else "REJECTED"}


def run(strategy: str, bars: dict[str, pd.DataFrame], p: it.Params = it.Params()) -> tuple[dict, pd.DataFrame]:
    tf = it.STRATEGIES[strategy]
    out = {"experiment": EXPERIMENTS[strategy], "strategy": strategy, "timeframe": tf, "spec_version": it.SPEC_VERSION,
           "params": p.as_dict(), "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    first = None
    for mult, label in ((1.0, "1x"), (2.0, "2x")):
        frames = []
        for s, b5 in bars.items():
            tfb = b5 if tf == "5min" else bi.resample(b5, tf)
            sig = it.signals(strategy, b5, tfb, p)
            frames.append(it.simulate(strategy, b5, sig, tf, p, mult, s))
        trades = pd.concat(frames, ignore_index=True)
        out[label] = {split: summary(in_split(trades, split), ci=(label == "1x" and split == "dev"), a=alpha(strategy))
                      for split in SPLITS}
        if first is None:
            first = trades
    out["verdict"] = verdict(out, alpha(strategy))
    return out, first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=list(it.STRATEGIES))
    args = parser.parse_args(argv)
    bars = load()
    for s, b in bars.items():
        print(s, b.index.min(), b.index.max(), len(b), flush=True)
    (REPORT_DIR / "intraday-buy-and-hold.json").write_text(json.dumps(buy_and_hold(bars), indent=2) + "\n")
    for strategy in ([args.strategy] if args.strategy else list(it.STRATEGIES)):
        result, trades = run(strategy, bars)
        exp = EXPERIMENTS[strategy]
        (REPORT_DIR / f"{exp}-{strategy}.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
        trades.to_csv(REPORT_DIR / f"{exp}-trades.csv", index=False)
        print(strategy, result["verdict"]["status"], json.dumps(result["verdict"]["checks"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
