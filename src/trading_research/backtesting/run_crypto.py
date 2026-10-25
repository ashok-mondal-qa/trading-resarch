"""Run the crypto experiments EXP-0021..0026 (spec docs/strategy-specifications/crypto-comparison.md) on one split.

    python -m trading_research.backtesting.run_crypto --split dev        # 2018-04-01..2023-12-31, decides
    python -m trading_research.backtesting.run_crypto --split dev_a      # and dev_b / validation
    python -m trading_research.backtesting.run_crypto --verdict

The six NSE rule sets (five from Phase 13 plus weekly 12-1 momentum) on Binance spot USDT pairs, with the same
engine, caps and measurements. Regime and relative strength use BTCUSDT; costs are Binance's fee plus GST and
slippage. The 2025-01-01..2026-09-30 holdout has no path here.
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
from trading_research.backtesting.run_swing_ideas import ci_key, standalone, standalone_summary
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import binance, quality
from trading_research.indicators import core, regime
from trading_research.strategies import social
from trading_research.strategies import swing_ideas as si
from trading_research.strategies import swing_ideas2 as s2

SPLITS = {
    "dev": ("2018-04-01", "2023-12-31"),
    "dev_a": ("2018-04-01", "2020-12-31"),
    "dev_b": ("2021-01-01", "2023-12-31"),
    "validation": ("2024-01-01", "2024-12-31"),
}
# Descriptive only (spec "Market comparison"): the window both markets share; portfolio runs, no verdict.
DESCRIPTIVE_SPLITS = {"common": ("2018-04-01", "2024-12-31")}
HOLDOUT = ("2025-01-01", "2026-09-30")       # sealed: never loaded by this runner
SIGN_SPLITS = ("dev_a", "dev_b", "validation")
STRATEGIES = social.STRATEGIES + ("momentum_weekly",)
EXPERIMENTS = {"minervini": "EXP-0021", "supertrend": "EXP-0022", "ma44": "EXP-0023", "turtle55": "EXP-0024",
               "golden_cross": "EXP-0025", "momentum_weekly": "EXP-0026"}
BENCHMARK = "BTCUSDT"
FAMILY_SIZE = 6
ALPHA = 0.05 / FAMILY_SIZE
MIN_PORTFOLIO_TRADES = 30
MIN_STANDALONE_TRADES = 300
MIN_QUOTE_VOLUME = 5e6           # USDT, 20-day median
MIN_SEGMENT_BARS = 200
DELIST_NO_SIGNAL_BARS = 7
START_EQUITY = 1e9               # USDT units; results are scale-free (R and percent)
# Binance spot base fee 0.10% per side (secondary sources, unverified) with 18% GST on the fee; no STT/stamp.
CRYPTO_COSTS = {"verified": False, "source_note": "Binance spot base fee 0.10% + 18% GST; unverified",
                "brokerage_pct": 0.10, "brokerage_cap_inr": 0.0, "stt_pct_buy": 0.0, "stt_pct_sell": 0.0,
                "exchange_txn_pct": 0.0, "sebi_fee_pct": 0.0, "stamp_duty_pct_buy": 0.0, "gst_pct": 18.0,
                "dp_charge_inr_per_sell": 0.0}
SOCIAL_PARAMS = social.Params(min_price=0.0, min_median_traded_value=MIN_QUOTE_VOLUME)
MOMENTUM_PARAMS = s2.Params(base=si.Params(min_price=0.0, min_median_traded_value=MIN_QUOTE_VOLUME))


def crypto_settings() -> dict:
    s = load_settings()
    return {**s, "costs": CRYPTO_COSTS,
            "virtual_portfolio": {**s["virtual_portfolio"], "starting_equity_inr": START_EQUITY, "currency": "USDT"}}


def max_holding(strategy: str) -> int:
    return MOMENTUM_PARAMS.max_holding(strategy) if strategy == "momentum_weekly" else SOCIAL_PARAMS.max_holding(strategy)


def segments(bars: pd.DataFrame, symbol: str, data_end: pd.Timestamp) -> list[tuple[str, pd.DataFrame, bool]]:
    """Split a pair's daily bars at every missing UTC day. Returns (instrument, bars, delisted) per piece of at
    least MIN_SEGMENT_BARS; a piece ending before `data_end` counts as delisted. Later pieces of a reused
    ticker are named SYMBOL~YYYY-MM-DD (their first day) and never join earlier ones."""
    b = bars[bars["date"] <= data_end].sort_values("date").reset_index(drop=True)
    if b.empty:
        return []
    piece = (b["date"].diff() != pd.Timedelta(days=1)).cumsum()
    groups = [g for _, g in b.groupby(piece)]
    out = []
    for i, g in enumerate(groups):
        if len(g) < MIN_SEGMENT_BARS:
            continue
        name = symbol if i == 0 else f"{symbol}~{g['date'].iloc[0]:%Y-%m-%d}"
        frame = pd.DataFrame({
            "open": g["open"].to_numpy(), "high": g["high"].to_numpy(), "low": g["low"].to_numpy(),
            "close": g["close"].to_numpy(), "volume": g["volume"].to_numpy(dtype=float),
            "traded_value": g["quote_volume"].to_numpy(dtype=float)},
            index=pd.DatetimeIndex(g["date"], name="date"))
        frame["raw_close"] = frame["close"]
        out.append((name, frame, bool(g["date"].iloc[-1] < data_end)))
    return out


def apply_delisting(f: pd.DataFrame) -> pd.DataFrame:
    """No new signals in a delisted piece's last bars; exit at the open of its last bar."""
    f = f.copy()
    f.loc[f.index[-DELIST_NO_SIGNAL_BARS:], "signal"] = False
    f.loc[f.index[-2], "exit_signal"] = True
    return f


def _features(bars, btc, strategy):
    if strategy == "momentum_weekly":
        f = s2.stock_features(bars, btc, strategy, MOMENTUM_PARAMS)
        f["target"] = np.nan
        return f
    return social.stock_features(bars, btc, strategy, SOCIAL_PARAMS)


def load_universe(root: Path, data_end: date, strategies=STRATEGIES):
    end = pd.Timestamp(data_end)
    btc_bars = binance.read_bars(BENCHMARK, root)
    btc = btc_bars[btc_bars["date"] <= end].set_index("date")["close"]
    calendar = list(pd.date_range(btc.index.min(), end, freq="D"))
    feats = {s: {} for s in strategies}
    delisted, counts = set(), {"pairs": 0, "instruments": 0, "delisted_pieces": 0, "short_pieces_or_empty": 0}
    for path in sorted((root / "processed" / binance.DATASET).glob("*.parquet")):
        counts["pairs"] += 1
        pieces = segments(pd.read_parquet(path), path.stem, end)
        if not pieces:
            counts["short_pieces_or_empty"] += 1
        for name, bars, gone in pieces:
            counts["instruments"] += 1
            if gone:
                counts["delisted_pieces"] += 1
                delisted.add(name)
            gate1 = quality.gate1_series(bars.index, bars["volume"], calendar)
            for strategy in strategies:
                f = _features(bars, btc, strategy)
                f["gate1"] = gate1
                f["adj_factor"] = 1.0
                for col in ("open", "high", "low"):
                    f[col] = bars[col]
                feats[strategy][name] = f
    if "minervini" in strategies:
        fm = feats["minervini"]
        score = pd.DataFrame({s: f["rs_score"] for s, f in fm.items()})
        rankable = pd.DataFrame({s: f["rs_score"].notna() & f["liquid"] & f["gate1"] for s, f in fm.items()})
        pct = core.cross_sectional_rank(score.where(rankable.reindex_like(score).fillna(False).astype(bool)))
        for s in fm:
            fm[s] = social.apply_rs_rank(fm[s], pct[s], SOCIAL_PARAMS)
    if "momentum_weekly" in strategies:
        fm = feats["momentum_weekly"]
        mom = pd.DataFrame({s: f["mom"] for s, f in fm.items()})
        rankable = pd.DataFrame({s: f["inputs_complete"] & f["liquid"] & f["gate1"] for s, f in fm.items()})
        pct = si.momentum_rank(mom, rankable.reindex_like(mom).fillna(False).astype(bool))
        starts = s2.week_starts(calendar)
        for s in fm:
            fm[s] = si.apply_momentum(fm[s], pct[s], starts, MOMENTUM_PARAMS.base)
    frames = {s: {} for s in strategies}
    signals = {}
    for strategy in strategies:
        rows = []
        for name, f in feats[strategy].items():
            if name in delisted:
                f = apply_delisting(f)
            frames[strategy][name] = f[["open", "high", "low", "close", "adj_factor", "stop", "target",
                                        "exit_signal", "median_traded_value"]].copy()
            hits = f[f["signal"].fillna(False).astype(bool) & f["gate1"]]
            rows.extend((d, name, True, r["rank_key"]) for d, r in hits.iterrows())
        signals[strategy] = pd.DataFrame(rows, columns=["date", "symbol", "signal", "rs"])
    return frames, signals, counts, btc, calendar


def annual_stats(equity: pd.Series, periods: int = 365) -> dict:
    """CAGR, volatility, Sharpe (risk-free 0) and max drawdown of a daily equity curve."""
    if len(equity) < 20:
        return {}
    rets = equity.pct_change().dropna()
    years = len(equity) / periods
    vol = float(rets.std() * np.sqrt(periods))
    return {"cagr": float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1), "ann_vol": vol,
            "sharpe_rf0": float(rets.mean() * periods / vol) if vol > 0 else None,
            "max_drawdown": metrics.max_drawdown(equity), "years": float(years)}


def all_trades_expectancy(t: pd.DataFrame) -> float | None:
    """Mean R over every trade, those still open at the split end marked to market (spec rule 3)."""
    return float(t["r_multiple"].mean()) if len(t) else None


def run_split(split: str, strategies=STRATEGIES, root: Path = REPO_ROOT / "data") -> dict:
    ranges = {**SPLITS, **DESCRIPTIVE_SPLITS}
    if split not in ranges:
        raise SystemExit(f"unknown split {split!r}; the {HOLDOUT[0]}..{HOLDOUT[1]} holdout is sealed")
    start, end = ranges[split]
    portfolio_only = split in DESCRIPTIVE_SPLITS
    settings = crypto_settings()
    frames, signals, counts, btc, calendar = load_universe(root, date.fromisoformat(end), strategies)
    reg = regime.regime(btc)
    split_calendar = [d for d in calendar if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    bench = btc[(btc.index >= pd.Timestamp(start)) & (btc.index <= pd.Timestamp(end))]
    reports = {}
    for strategy in strategies:
        exp, hold = EXPERIMENTS[strategy], max_holding(strategy)
        report = {
            "experiment": exp, "strategy": strategy, "spec_version": "0.1", "split": split, "range": [start, end],
            "market": "Binance spot USDT pairs", "max_holding_bars": hold,
            "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "universe": counts, "costs": CRYPTO_COSTS,
            "regime_days": reg["trend"].reindex(pd.DatetimeIndex(split_calendar)).value_counts().to_dict(),
            "benchmark_btc_return": float(bench.iloc[-1] / bench.iloc[0] - 1) if len(bench) > 1 else None,
            "benchmark_btc": annual_stats(bench), "runs": {},
        }
        p = MOMENTUM_PARAMS if strategy == "momentum_weekly" else SOCIAL_PARAMS
        for mult, label in ((1.0, "1x"), (2.0, "2x_costs")):
            cands, n_signals = select(signals[strategy], reg["trend"], start, end, p, False)
            res = engine.run(frames[strategy], cands, split_calendar, settings, START_EQUITY, hold, mult)
            summary = metrics.summarize(res.trades, res.equity, START_EQUITY)
            summary.update(annual_stats(res.equity))
            summary.update({"signals_after_regime_gate": n_signals,
                            "entries_skipped": res.skipped["reason"].value_counts().to_dict()
                            if len(res.skipped) else {}})
            report["runs"][f"portfolio_{label}"] = summary
            if portfolio_only:
                if label == "1x":
                    REPORT_DIR.mkdir(parents=True, exist_ok=True)
                    res.trades.to_csv(REPORT_DIR / f"{exp}-{split}-trades.csv", index=False)
                    res.equity.to_csv(REPORT_DIR / f"{exp}-{split}-equity.csv")
                continue
            alone = standalone(frames[strategy], signals[strategy], reg["trend"], split_calendar, settings, hold, mult)
            report["runs"][f"standalone_{label}"] = {**standalone_summary(alone, ALPHA),
                                                     "expectancy_r_all_incl_open": all_trades_expectancy(alone)}
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
    for split in SIGN_SPLITS:
        if split in reports:
            run = reports[split]["runs"]["standalone_2x_costs"]
            checks[f"{split} standalone 2x: expectancy > 0 (closed and incl. open)"] = (
                (run.get("expectancy_r") or -1) > 0 and (run.get("expectancy_r_all_incl_open") or -1) > 0)
    passed = all(checks.values()) and set(SIGN_SPLITS) <= set(reports)
    return {"checks": checks, "passed": passed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=list(SPLITS) + list(DESCRIPTIVE_SPLITS))
    parser.add_argument("--strategy", choices=list(STRATEGIES))
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
    strategies = (args.strategy,) if args.strategy else STRATEGIES
    for strategy, report in run_split(args.split, strategies).items():
        runs = {k: {m: v.get(m) for m in ("trades", "expectancy_r", "profit_factor")} for k, v in report["runs"].items()}
        print(strategy, json.dumps(runs, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
