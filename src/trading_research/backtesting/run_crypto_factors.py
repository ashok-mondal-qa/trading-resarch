"""Run the crypto factor-portfolio experiments EXP-0044..0046 (spec
docs/strategy-specifications/crypto-factor-portfolios.md). Research and paper only: nothing here orders or alerts.

    python -m trading_research.backtesting.run_crypto_factors        # all three, every split, 1x and 2x costs

The Phase 18 rules (`factors.py`, simulated by `run_factors.simulate`) on Binance USDT coins: top 50 by 63-day
median quote volume (at least 5M USDT), hold 10, monthly, against BTCUSDT bought and held. Bars are read only
up to DATA_END; the crypto holdout has no path here.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import compare_markets as cm
from trading_research.backtesting import metrics
from trading_research.backtesting import run_crypto as rc
from trading_research.backtesting import run_factors as rf
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.config import REPO_ROOT
from trading_research.data import binance
from trading_research.strategies import factors as fa

DATA_END = date(2024, 12, 31)
SPLITS = {
    "dev": ("2020-07-01", "2023-12-31"),
    "dev_a": ("2020-07-01", "2021-12-31"),
    "dev_b": ("2022-01-01", "2023-12-31"),
    "validation": ("2024-01-01", "2024-12-31"),
}
HOLDOUT = rc.HOLDOUT                         # 2025-01-01..2026-09-30, sealed: never loaded by this runner
EXPERIMENTS = {"lowvol": "EXP-0044", "momentum": "EXP-0045", "mom_lowvol": "EXP-0046"}
ALPHA = 0.05 / len(EXPERIMENTS)
EXCLUDED = {"BKRWUSDT"}                      # KRW-pegged stablecoin missing from binance.EXCLUDED_BASES
PARAMS = fa.Params(universe_size=50, holdings=10, min_median_value=rc.MIN_QUOTE_VOLUME, value_on_t=True)
COSTS = rc.CRYPTO_COSTS                      # 0.10% fee + 18% GST; run_factors adds 0.10% slippage per side


def load(root: Path = REPO_ROOT / "data", end: date = DATA_END):
    """Close, open and quote-volume frames on every UTC day, plus BTCUSDT open/close. Pairs are split into
    instruments at missing days (Phase 14); a delisted piece has no traded value in its last 7 bars, so it
    leaves the universe."""
    end = pd.Timestamp(end)
    btc = binance.read_bars(rc.BENCHMARK, root)
    btc = btc[btc["date"] <= end].set_index("date")[["open", "close"]]
    cal = pd.date_range(btc.index.min(), end, freq="D")
    close, open_, value = {}, {}, {}
    for path in sorted((root / "processed" / binance.DATASET).glob("*.parquet")):
        if path.stem in EXCLUDED:
            continue
        for name, bars, gone in rc.segments(pd.read_parquet(path), path.stem, end):
            v = bars["traded_value"].copy()
            if gone:
                v.iloc[-rc.DELIST_NO_SIGNAL_BARS:] = np.nan
            close[name], open_[name], value[name] = bars["close"], bars["open"], v
    frame = lambda d: pd.DataFrame(d).reindex(cal)   # noqa: E731
    return frame(close), frame(open_), frame(value), btc.reindex(cal)


def split_report(equity: pd.Series, lots: pd.DataFrame, bench: pd.Series, bench_lots: pd.DataFrame,
                 ci: bool = False) -> dict:
    taxes, btaxes = cm.crypto_tax(lots), cm.crypto_tax(bench_lots)
    ms, mb = rf.monthly(equity), rf.monthly(bench)
    out = {"strategy": cm.stats(equity, 365), "strategy_after_tax": cm.stats(cm.apply_taxes(equity, taxes), 365),
           "btc": cm.stats(bench, 365), "btc_after_tax": cm.stats(cm.apply_taxes(bench, btaxes), 365),
           "sharpe_monthly": rf.sharpe(ms), "btc_sharpe_monthly": rf.sharpe(mb),
           "max_drawdown": metrics.max_drawdown(equity), "btc_max_drawdown": metrics.max_drawdown(bench),
           "lots_closed": int(len(lots)), "tax_paid_usdt": float(taxes.sum())}
    if ci:
        out[f"sharpe_diff_ci_{1 - ALPHA:.4f}"] = rf.sharpe_diff_ci(ms, mb, alpha=ALPHA)
    return out


def verdict(results: dict) -> dict:
    d1, d2 = results["1x"]["dev"], results["2x"]["dev"]
    lo = (d1.get(f"sharpe_diff_ci_{1 - ALPHA:.4f}") or (-1, -1))[0]
    checks = {
        "dev 2x: Sharpe above BTC": d2["sharpe_monthly"] > d2["btc_sharpe_monthly"],
        "dev 2x: after-tax CAGR above BTC": d2["strategy_after_tax"]["cagr"] > d2["btc_after_tax"]["cagr"],
        f"dev 1x: {1 - ALPHA:.2%} interval of the Sharpe difference above 0": lo > 0,
    }
    for split in rf.SIGN_SPLITS:
        s = results["2x"][split]
        checks[f"{split} 2x: Sharpe not below BTC"] = s["sharpe_monthly"] >= s["btc_sharpe_monthly"]
    v = results["2x"]["validation"]
    checks["validation 2x: drawdown at most 10 points worse than BTC"] = v["max_drawdown"] >= v["btc_max_drawdown"] - rf.MAX_DD_GAP
    return {"checks": checks, "status": "HOLDOUT CANDIDATE" if all(checks.values()) else "REJECTED"}


def run(strategy: str, close, open_, value, btc) -> dict:
    out = {"experiment": EXPERIMENTS[strategy], "strategy": strategy, "spec_version": fa.SPEC_VERSION,
           "params": PARAMS.as_dict(), "slippage_pct_per_side": rf.SLIPPAGE_PCT, "excluded": sorted(EXCLUDED),
           "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    for mult, label in ((1.0, "1x"), (2.0, "2x")):
        out[label] = {}
        for split, (start, end) in SPLITS.items():
            eq, lots = rf.simulate(strategy, close, open_, value, start, end, COSTS, mult, PARAMS)
            beq, blots = rf.nifty_curve(btc, start, end, COSTS, mult)
            out[label][split] = split_report(eq, lots, beq.reindex(eq.index).ffill(), blots,
                                             ci=(label == "1x" and split == "dev"))
            if label == "1x" and split == "dev":
                eq.to_csv(REPORT_DIR / f"{EXPERIMENTS[strategy]}-dev-equity.csv", header=["equity"])
                lots.to_csv(REPORT_DIR / f"{EXPERIMENTS[strategy]}-dev-lots.csv", index=False)
    out["verdict"] = verdict(out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=fa.STRATEGIES)
    args = parser.parse_args(argv)
    close, open_, value, btc = load()
    print(f"instruments {close.shape[1]}, days {close.index.min().date()}..{close.index.max().date()}", flush=True)
    for strategy in ([args.strategy] if args.strategy else fa.STRATEGIES):
        result = run(strategy, close, open_, value, btc)
        (REPORT_DIR / f"{EXPERIMENTS[strategy]}-crypto-{strategy}.json").write_text(
            json.dumps(result, indent=2, default=str) + "\n")
        print(strategy, result["verdict"]["status"], json.dumps(result["verdict"]["checks"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
