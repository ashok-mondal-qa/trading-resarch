"""Run EXP-0073..0077 (spec docs/strategy-specifications/influencer-intraday.md v0.1): popular Indian influencer
intraday setups on liquid NSE stocks (2017-2020) and NIFTY / BANK NIFTY (2017-2026), one trade a day, Rs 300 risk,
Groww intraday charges, every split, rolling 6-month windows. Research only; nothing here orders.

    python -m trading_research.backtesting.run_influencer [--workers 6]
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.backtesting.run_intraday_families import (CAPITAL_INR, ETF_SCALE, MIN_LIQ_INR, MIN_PRICE,
                                                                RISK_INR, SLIP, SLIP_GRID, SPLITS, in_split, rupees,
                                                                select_one_per_day, stats)
from trading_research.data.minute_vendor import out_dir
from trading_research.strategies import influencer as inf

EXPS = {"ema5": "EXP-0073", "st_flip": "EXP-0074", "st_2r": "EXP-0075", "ohol": "EXP-0076", "cpr": "EXP-0077"}
WINDOW_MONTHS = 6
MIN_WINDOWS_POSITIVE = 0.6


# ------------------------------------------------------------------ signal generation


def _trades_for(days: list[inf.IDay], inst: str, scale, liq, eligible=None) -> list[dict]:
    out = []
    for d in days:
        if eligible is not None and not eligible.get(d.date, False):
            continue
        for rule in EXPS:
            for variant, check in (("main", True), ("raw", False)):
                sig = inf.first_signal(d, rule, check_width=check)
                if sig is None:
                    continue
                tr = inf.simulate(d, sig)
                tr.update(inst=inst, variant=variant,
                          scale=float(scale(d.date)) if callable(scale) else scale,
                          liq=float(liq(d.date)) if callable(liq) else liq)
                out.append(tr)
    return out


def _stock_job(args) -> list[dict]:
    sym, root = args
    bars = pd.read_parquet(root / "stocks" / f"{sym}.parquet")
    days = pd.read_parquet(root / "stocks" / f"{sym}_days.parquet").set_index("date").sort_index()
    if bars.empty:
        return []
    ok = days["status"] == "ok"
    prev_ok = ok.shift(1, fill_value=False)
    # vendor-scale daily bars of the gate-passing sessions (CPR of a session needs the previous session passing)
    daily = bars.groupby(bars.index.normalize()).agg(high=("high", "max"), low=("low", "min"),
                                                     close=("close", "last"))
    idays = inf.build_days(bars, daily)
    for d in idays:
        if not prev_ok.get(d.date, False):
            d.cpr = {}
    liq = days["traded_value"].shift(1).rolling(20, min_periods=15).median()
    eligible = ok & (liq >= MIN_LIQ_INR) & (days["close"].shift(1) >= MIN_PRICE)
    return _trades_for(idays, sym, lambda d: days.at[d, "factor"], lambda d: liq[d], eligible.to_dict())


def _index_trades(name: str, root: Path) -> list[dict]:
    bars = pd.read_parquet(root / "indices" / f"{name}.parquet")
    days = pd.read_parquet(root / "indices" / f"{name}_days.parquet").set_index("date").sort_index()
    days = days[days["close"].notna()]
    idays = inf.build_days(bars, days[["high", "low", "close"]])
    return _trades_for(idays, name, ETF_SCALE, 1.0 if name == "NIFTY" else 0.0)


# ------------------------------------------------------------------ evaluation


def windows(universe: str) -> list[tuple[str, str]]:
    a, b = pd.Timestamp(SPLITS[universe]["dev"][0]), pd.Timestamp(SPLITS[universe]["holdout"][1])
    start = pd.Timestamp(a.year, 1 if a.month <= 6 else 7, 1)
    out = []
    while start <= b:
        end = start + pd.DateOffset(months=WINDOW_MONTHS) - pd.Timedelta(days=1)
        out.append((str(start.date()), str(min(end, b).date())))
        start = start + pd.DateOffset(months=WINDOW_MONTHS)
    return out


def rolling(a: pd.DataFrame, universe: str) -> dict:
    d = pd.to_datetime(a["date"])
    rows = []
    for s, e in windows(universe):
        w = a[(d >= s) & (d <= e)]
        rows.append({"window": f"{s}..{e}", "trades": int(len(w)),
                     "mean_net_r": round(float(w["net_r"].mean()), 3) if len(w) else None})
    used = [r for r in rows if r["trades"] >= 10]
    pos = sum(1 for r in used if r["mean_net_r"] > 0)
    return {"windows": rows, "windows_used": len(used), "windows_positive": pos,
            "share_positive": round(pos / len(used), 3) if used else None}


def verdict(res: dict) -> dict:
    A, S = res["A"], res["A_stress"]
    g = lambda x: x.get("mean_net_r", -1) if x.get("trades", 0) else -1  # noqa: E731
    c = {
        "dev >= 100 trades": A["dev"].get("trades", 0) >= 100,
        "dev mean net R > 0": g(A["dev"]) > 0,
        "dev CI above 0": A["dev"].get("mean_net_r_ci95", [-1])[0] > 0,
        "dev PF >= 1.15": (A["dev"].get("profit_factor") or 0) >= 1.15,
        "dev halves > 0": g(A["dev_a"]) > 0 and g(A["dev_b"]) > 0,
        "dev stress > 0": g(S["dev"]) > 0,
        "validation > 0": g(A["validation"]) > 0,
        "validation stress > 0": g(S["validation"]) > 0,
        "holdout > 0": g(A["holdout"]) > 0,
        ">= 60% of 6-month windows positive": (res["rolling_6m"]["share_positive"] or 0) >= MIN_WINDOWS_POSITIVE,
    }
    return {"checks": c, "status": "PAPER CANDIDATE" if all(c.values()) else "REJECTED"}


def evaluate(trades: pd.DataFrame, universe: str) -> dict:
    slip = SLIP[universe]
    out = {}
    for rule, exp in EXPS.items():
        t_rule = trades[trades["rule"] == rule]
        t_all = t_rule[t_rule["variant"] == "main"]
        res = {"rule": rule, "signals_all_instruments": int(len(t_all))}
        if t_all.empty:
            res.update(status="NO SIGNALS")
            out[exp] = res
            continue
        one = select_one_per_day(t_all)
        a = rupees(one, slip, None)
        res["A"] = {s: stats(in_split(a, universe, s), ci=True) for s in SPLITS[universe]}
        stress = rupees(one.loc[a.index], slip, None, charge_mult=2.0, slip_mult=2.0, qty=a["qty"])
        res["A_stress"] = {s: stats(in_split(stress, universe, s)) for s in SPLITS[universe]}
        b = rupees(one, slip, CAPITAL_INR)
        res["B_15k"] = {s: stats(in_split(b, universe, s)) for s in SPLITS[universe]}
        res["B_15k"]["skipped_qty0"] = int(len(one) - len(b))
        res["slippage_sensitivity_A_mean_net_r"] = {}
        for sg in SLIP_GRID:
            x = rupees(one, slip if sg is None else sg, None)
            res["slippage_sensitivity_A_mean_net_r"]["base" if sg is None else f"{sg:.2%}"] = {
                s: stats(in_split(x, universe, s)).get("mean_net_r") for s in ("dev", "validation", "holdout")}
        res["rolling_6m"] = rolling(a, universe)
        raw = select_one_per_day(t_rule[t_rule["variant"] == "raw"])
        res["raw_signals_no_width_check"] = {
            s: {"trades": int(len(x)), "mean_gross_r": round(float(x["gross_r"].mean()), 3) if len(x) else None,
                "median_stop_pct": round(float((abs(x["entry"] - x["stop"]) / x["entry"]).median() * 100), 3)
                if len(x) else None}
            for s in ("dev", "validation", "holdout") for x in [in_split(raw, universe, s)]}
        res["exit_reasons_A"] = a["reason"].value_counts().to_dict()
        if universe == "indices":
            res["futures_min_lot_risk_inr_median"] = round(float(a["min_lot_risk_pts_inr"].median()), 0)
            res["futures_share_within_300"] = round(float((a["min_lot_risk_pts_inr"] <= RISK_INR).mean()), 3)
            res["by_instrument_A"] = {i: stats(g) for i, g in rupees(t_all, slip, None).groupby("inst")}
        res["by_year_A"] = {str(y): stats(g) for y, g in a.groupby(pd.to_datetime(a["date"]).dt.year)}
        res.update(verdict(res))
        out[exp] = res
        a.assign(universe=universe).to_csv(REPORT_DIR / f"{exp}-{universe}-trades.csv", index=False)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    root = out_dir()
    syms = sorted(p.stem for p in (root / "stocks").glob("*.parquet") if not p.stem.endswith("_days"))
    with ProcessPoolExecutor(a.workers) as ex:
        parts = list(ex.map(_stock_job, [(s, root) for s in syms]))
    stock_t = pd.DataFrame([r for p in parts for r in p])
    idx_t = pd.DataFrame(_index_trades("NIFTY", root) + _index_trades("BANKNIFTY", root))
    result = {"generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
              "spec_version": inf.SPEC_VERSION, "risk_inr": RISK_INR, "capital_inr_scenario_b": CAPITAL_INR,
              "slippage_base": SLIP, "stocks": evaluate(stock_t, "stocks"), "indices": evaluate(idx_t, "indices")}
    (REPORT_DIR / "EXP-0073-0077.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    for u in ("stocks", "indices"):
        for exp, r in result[u].items():
            if "A" not in r:
                print(u, exp, r["rule"], r["status"])
                continue
            A = r["A"]
            print(u, exp, r["rule"], r["status"],
                  {s: (A[s]["trades"], A[s].get("mean_net_r"), A[s].get("mean_gross_r"), A[s].get("profit_factor"))
                   for s in ("dev", "validation", "holdout")},
                  "windows+", r["rolling_6m"]["windows_positive"], "/", r["rolling_6m"]["windows_used"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
