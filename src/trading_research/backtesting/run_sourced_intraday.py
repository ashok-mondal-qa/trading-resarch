"""Run EXP-0068..0070 (spec docs/strategy-specifications/sourced-intraday-ideas.md v0.1). Research only; nothing
here orders. Reuses the EXP-0061..0066 data, charges, sizing and metrics.

    python -m trading_research.backtesting.run_sourced_intraday [--workers 6]
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import run_intraday_families as base
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.data.minute_vendor import out_dir
from trading_research.strategies import sourced_intraday as si

TOP_N_DIAG = 20


# ------------------------------------------------------------------ trades


def index_momentum(name: str, root: Path) -> pd.DataFrame:
    bars = pd.read_parquet(root / "indices" / f"{name}.parquet")
    days = pd.read_parquet(root / "indices" / f"{name}_days.parquet").set_index("date").sort_index()
    days = days[days["close"].notna()]
    prev_close = days["close"].shift(1)
    rows = []
    for d, day in bars.groupby(bars.index.normalize()):
        r = si.momentum_day(day, float(prev_close.get(d, np.nan)))
        if r is not None:
            rows.append(r)
    t = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    t["big"] = si.big_move_mask(t["r1"])
    t["inst"], t["scale"], t["liq"], t["rvol"] = name, base.ETF_SCALE, 1.0, np.nan
    return t


def _stock_job(args) -> list[dict]:
    sym, root = args
    bars = pd.read_parquet(root / "stocks" / f"{sym}.parquet")
    days = pd.read_parquet(root / "stocks" / f"{sym}_days.parquet").set_index("date").sort_index()
    if bars.empty:
        return []
    ok = days["status"] == "ok"
    liq = days["traded_value"].shift(1).rolling(20, min_periods=15).median()
    eligible = ok & (liq >= base.MIN_LIQ_INR) & (days["close"].shift(1) >= base.MIN_PRICE)
    groups = dict(tuple(bars.groupby(bars.index.normalize())))
    f5 = {d: si.first5(g) for d, g in groups.items()}
    vol = pd.Series({d: (v["volume"] if v else np.nan) for d, v in f5.items()}).sort_index()
    rv = si.rvol_series(vol)
    out = []
    for d, g in groups.items():
        if not eligible.get(d, False) or f5[d] is None or not (rv.get(d, np.nan) >= si.RVOL_MIN):
            continue
        tr = si.orb5_trade(g, f5[d])
        if tr is not None:
            tr.update(inst=sym, scale=float(days.at[d, "factor"]), liq=float(liq[d]), rvol=float(rv[d]))
            out.append(tr)
    return out


def top_rvol(t: pd.DataFrame, n: int) -> pd.DataFrame:
    t = t.sort_values(["date", "rvol", "liq"], ascending=[True, False, False])
    return t.groupby("date", group_keys=False).head(n)


# ------------------------------------------------------------------ evaluation


def walk_forward(by_year: dict) -> dict:
    yrs = {y: s.get("mean_net_r") for y, s in by_year.items() if s.get("trades", 0) > 0}
    pos = sum(1 for v in yrs.values() if v is not None and v > 0)
    return {"years": len(yrs), "positive_years": pos, "share_positive": round(pos / len(yrs), 3) if yrs else None}


def verdict(res: dict) -> dict:
    v = base.verdict(res)
    wf = res["walk_forward"]
    v["checks"]["walk-forward >= 2/3 of years > 0"] = bool(wf["share_positive"] and wf["share_positive"] >= 2 / 3)
    v["status"] = "FORWARD PAPER CANDIDATE" if all(v["checks"].values()) else "REJECTED"
    return v


def evaluate(one: pd.DataFrame, universe: str, extra: dict | None = None) -> dict:
    slip = base.SLIP[universe]
    splits = base.SPLITS[universe]
    a = base.rupees(one, slip, None)
    res = {"A": {s: base.stats(base.in_split(a, universe, s), ci=True) for s in splits}}
    stress = base.rupees(one.loc[a.index], slip, None, charge_mult=2.0, slip_mult=2.0, qty=a["qty"])
    res["A_stress"] = {s: base.stats(base.in_split(stress, universe, s)) for s in splits}
    b = base.rupees(one, slip, base.CAPITAL_INR)
    res["B_15k"] = {s: base.stats(base.in_split(b, universe, s)) for s in splits}
    res["slippage_sensitivity_A_mean_net_r"] = {}
    for sg in base.SLIP_GRID:
        x = base.rupees(one, slip if sg is None else sg, None)
        res["slippage_sensitivity_A_mean_net_r"]["base" if sg is None else f"{sg:.2%}"] = {
            s: base.stats(base.in_split(x, universe, s)).get("mean_net_r") for s in ("dev", "validation", "holdout")}
    res["by_year_A"] = {str(y): base.stats(g) for y, g in a.groupby(pd.to_datetime(a["date"]).dt.year)}
    res["walk_forward"] = walk_forward(res["by_year_A"])
    if extra:
        res.update(extra)
    res.update(verdict(res))
    return res, a


def gross_bps(t: pd.DataFrame, col: str, universe: str) -> dict:
    """Mean signed gross return in basis points per split (no costs), for diagnostics."""
    out = {}
    for s in ("dev", "validation", "holdout"):
        x = base.in_split(t, universe, s)
        v = (x[col] * x["side"]).dropna()
        out[s] = {"n": int(len(v)), "mean_bps": round(float(v.mean() * 1e4), 2) if len(v) else None,
                  "hit_rate": round(float((v > 0).mean()), 3) if len(v) else None}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    root = out_dir()
    result = {"generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
              "spec_version": si.SPEC_VERSION, "risk_inr": base.RISK_INR, "capital_inr_scenario_b": base.CAPITAL_INR,
              "slippage_base": base.SLIP}

    for name in ("NIFTY", "BANKNIFTY"):
        t = index_momentum(name, root)
        traded = t[t["side"] != 0].copy()
        traded["trade_ret"] = traded["exit"] / traded["entry"] - 1
        diag = {"sessions_with_signal": int(len(t)), "corr_r1_paper_window": round(float(
                    t[["r1", "paper_window_ret"]].dropna().corr().iloc[0, 1]), 4),
                "paper_window_gross": gross_bps(traded, "paper_window_ret", "indices"),
                "trade_window_gross": gross_bps(traded, "trade_ret", "indices")}
        for exp, sub in (("EXP-0068", traded), ("EXP-0069", traded[traded["big"]])):
            res, a_t = evaluate(sub, "indices", {"diagnostics": diag} if exp == "EXP-0068" else None)
            key = exp if name == "NIFTY" else f"{exp}-BANKNIFTY-diagnostic"
            result[key] = res
            a_t.to_csv(REPORT_DIR / f"{key}-trades.csv", index=False)

    syms = sorted(p.stem for p in (root / "stocks").glob("*.parquet") if not p.stem.endswith("_days"))
    with ProcessPoolExecutor(a.workers) as ex:
        parts = list(ex.map(_stock_job, [(s, root) for s in syms]))
    st = pd.DataFrame([r for p in parts for r in p])
    one = top_rvol(st, 1)
    top = top_rvol(st, TOP_N_DIAG)
    top_a = base.rupees(top, base.SLIP["stocks"], None)
    extra = {"stocks_in_play_setups": int(len(st)),
             "top20_all_signals_A": {s: base.stats(base.in_split(top_a, "stocks", s)) for s in
                                     ("dev", "validation", "holdout")}}
    res, a_t = evaluate(one, "stocks", extra)
    result["EXP-0070"] = res
    a_t.to_csv(REPORT_DIR / "EXP-0070-trades.csv", index=False)

    (REPORT_DIR / "EXP-0068-0070.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    for k, r in result.items():
        if isinstance(r, dict) and "A" in r:
            A = r["A"]
            print(k, r["status"], {s: (A[s]["trades"], A[s].get("mean_net_r"), A[s].get("profit_factor"))
                                   for s in ("dev", "validation", "holdout")}, r["walk_forward"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
