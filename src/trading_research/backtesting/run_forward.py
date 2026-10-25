"""Forward (out-of-sample) tracking of the two near misses, EXP-0027 / EXP-0028
(spec docs/strategy-specifications/forward-tracking.md). Paper only: nothing here orders, alerts or changes a
signal status.

    python -m trading_research.backtesting.run_forward --market crypto --as-of 2026-11-30
    python -m trading_research.backtesting.run_forward --market nse --as-of 2026-11-30

Rules are frozen as EXP-0021 (crypto Minervini) and EXP-0014 (NSE weekly momentum). Features use all bars up to
`as_of` (earlier bars only as indicator warm-up); trades start no earlier than FORWARD_START, and nothing
before it is ever reported.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.backtesting import engine, metrics
from trading_research.backtesting import run_crypto as rc
from trading_research.backtesting import run_swing_ideas2 as rs2
from trading_research.backtesting.run_baseline import select
from trading_research.backtesting.run_swing_ideas import ci_key, standalone, standalone_summary
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import bhavcopy, indices, quality
from trading_research.indicators import regime
from trading_research.strategies import swing_ideas2 as s2

FORWARD_START = "2026-10-26"
EXPERIMENTS = {"crypto": ("EXP-0027", "minervini", "EXP-0021"), "nse": ("EXP-0028", "momentum_weekly", "EXP-0014")}
ALPHA = 0.05 / 2
MIN_MONTHS = 12
MAX_MONTHS = 24
MIN_PORTFOLIO_TRADES = 30
MIN_STANDALONE_TRADES = 50
OUT_DIR = REPO_ROOT / "reports" / "forward"


def _crypto(as_of: date, root: Path):
    frames, signals, counts, btc, calendar = rc.load_universe(root, as_of, ("minervini",))
    settings = rc.crypto_settings()
    return (frames["minervini"], signals["minervini"], regime.regime(btc)["trend"], calendar, settings,
            rc.START_EQUITY, rc.max_holding("minervini"), rc.SOCIAL_PARAMS, counts,
            btc.index.max())


def _nse(as_of: date, root: Path):
    p = s2.Params()
    calendar = quality.sessions(bhavcopy.Store(root=root), rs2.DATA_START, as_of)
    nifty = indices.read_index("Nifty 50", rs2.DATA_START, as_of, root)["close"]
    frames, signals, counts = rs2.load_universe(root, as_of, nifty, calendar, p, ("momentum_weekly",))
    settings = load_settings()
    return (frames["momentum_weekly"], signals["momentum_weekly"], regime.regime(nifty)["trend"],
            [pd.Timestamp(d) for d in calendar], settings, float(settings["virtual_portfolio"]["starting_equity_inr"]),
            p.max_holding("momentum_weekly"), p, counts, nifty.index.max())


def months_between(start: str, end: date) -> float:
    return (pd.Timestamp(end) - pd.Timestamp(start)).days / 30.4375


def decide(runs: dict, months: float) -> str:
    """Pre-registered forward rule (spec). 'tracking' until enough time and trades; then PASSED / REJECTED."""
    p2, s1, s2_ = runs["portfolio_2x_costs"], runs["standalone_1x"], runs["standalone_2x_costs"]
    trades = p2.get("trades", 0) + p2.get("open_at_end", 0)
    if months < MIN_MONTHS or (trades < MIN_PORTFOLIO_TRADES and months < MAX_MONTHS):
        return "tracking"
    ok = (trades >= MIN_PORTFOLIO_TRADES
          and (p2.get("expectancy_r_all_incl_open") or -1) > 0 and (p2.get("profit_factor") or 0) >= 1.1
          and (s1.get("trades", 0) + s1.get("open_at_end", 0)) >= MIN_STANDALONE_TRADES
          and (s1.get(ci_key(ALPHA)) or (-1, -1))[0] > 0
          and (s2_.get("expectancy_r_all_incl_open") or -1) > 0)
    return "PASSED (candidate for paper trading review)" if ok else "REJECTED"


def run(market: str, as_of: date, root: Path = REPO_ROOT / "data") -> dict:
    if pd.Timestamp(as_of) < pd.Timestamp(FORWARD_START):
        raise SystemExit(f"as_of must be on or after {FORWARD_START}")
    exp, strategy, rules = EXPERIMENTS[market]
    (frames, signals, trend, calendar, settings, equity0, hold, p, counts,
     last_bar) = (_crypto if market == "crypto" else _nse)(as_of, root)
    # crypto trades every UTC day; NSE may close for a weekend plus a holiday
    tolerance = pd.Timedelta(days=0 if market == "crypto" else 4)
    if pd.Timestamp(last_bar) < pd.Timestamp(as_of) - tolerance:
        status = "DATA INSUFFICIENT"   # benchmark not loaded up to as_of
        report = {"experiment": exp, "as_of": str(as_of), "status": status, "last_bar": str(last_bar)}
    else:
        fwd = [d for d in calendar if pd.Timestamp(FORWARD_START) <= pd.Timestamp(d) <= pd.Timestamp(as_of)]
        runs = {}
        for mult, label in ((1.0, "1x"), (2.0, "2x_costs")):
            cands, n_signals = select(signals, trend, FORWARD_START, str(as_of), p, False)
            res = engine.run(frames, cands, fwd, settings, equity0, hold, mult)
            summary = metrics.summarize(res.trades, res.equity, equity0)
            summary["expectancy_r_all_incl_open"] = float(res.trades["r_multiple"].mean()) if len(res.trades) else None
            summary["signals_after_regime_gate"] = n_signals
            runs[f"portfolio_{label}"] = summary
            alone = standalone(frames, signals, trend, fwd, settings, hold, mult)
            runs[f"standalone_{label}"] = {**standalone_summary(alone, ALPHA),
                                           "expectancy_r_all_incl_open": float(alone["r_multiple"].mean()) if len(alone) else None}
            if label == "1x":
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                res.trades.to_csv(OUT_DIR / f"{exp}-trades.csv", index=False)
                res.equity.to_csv(OUT_DIR / f"{exp}-equity.csv")
        months = months_between(FORWARD_START, as_of)
        status = decide(runs, months)
        report = {"experiment": exp, "strategy": strategy, "frozen_rules": rules, "market": market,
                  "forward_start": FORWARD_START, "as_of": str(as_of), "months": round(months, 2),
                  "status": status, "universe": counts, "runs": runs}
    report["generated_at_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{exp}-{as_of}.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=list(EXPERIMENTS), required=True)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)
    r = run(args.market, args.as_of)
    p = r.get("runs", {}).get("portfolio_1x", {})
    print(r["experiment"], r["status"], {k: p.get(k) for k in ("trades", "open_at_end", "expectancy_r", "net_return")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
