"""Backtest metrics (quant-backtesting skill). Calculated values, not probabilities."""

from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    return float((equity / equity.cummax() - 1).min())


def bootstrap_ci(values: np.ndarray, n: int = 5000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(n, len(values)), replace=True).mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def cluster_bootstrap_ci(values: np.ndarray, clusters: np.ndarray, n: int = 5000, alpha: float = 0.05,
                         seed: int = 0) -> tuple[float, float]:
    """Bootstrap CI of the mean, resampling whole clusters (e.g. entry months) with replacement, so trades
    that share a market move are not counted as independent evidence."""
    values, clusters = np.asarray(values, dtype=float), np.asarray(clusters)
    labels = np.unique(clusters)
    if len(labels) < 2:
        return (float("nan"), float("nan"))
    sums = np.array([values[clusters == c].sum() for c in labels])
    counts = np.array([(clusters == c).sum() for c in labels])
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(labels), size=(n, len(labels)))
    means = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def summarize(trades: pd.DataFrame, equity: pd.Series, start_equity: float) -> dict:
    closed = trades[trades["reason"] != "open at end (marked)"] if len(trades) else trades
    out = {"trades": int(len(closed)), "open_at_end": int(len(trades) - len(closed))}
    if equity.empty:
        return out
    out["net_return"] = float(equity.iloc[-1] / start_equity - 1)
    out["max_drawdown"] = max_drawdown(equity)
    if len(closed) == 0:
        return out
    pnl, r = closed["pnl"].to_numpy(), closed["r_multiple"].to_numpy()
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    out.update({
        "win_rate": float((pnl > 0).mean()),
        "expectancy_inr": float(pnl.mean()),
        "expectancy_r": float(r.mean()),
        "expectancy_r_ci95": bootstrap_ci(r),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "avg_win_inr": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_inr": float(losses.mean()) if len(losses) else 0.0,
        "avg_sessions": float(closed["sessions"].mean()),
        "total_costs_inr": float(closed["costs"].sum()),
        "worst_r": float(r.min()),
        "exit_reasons": closed["reason"].value_counts().to_dict(),
        "inconclusive_lt_30_trades": bool(len(closed) < 30),
    })
    return out
