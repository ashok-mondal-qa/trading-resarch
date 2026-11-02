"""Run EXP-0061..0066 (spec docs/strategy-specifications/intraday-three-families.md v0.1): three intraday families,
base and filtered, on liquid NSE stocks (2017-2020) and NIFTY / BANK NIFTY (2017-2026), every split reported.
Research only; nothing here orders.

    python -m trading_research.backtesting.run_intraday_families [--workers 6]
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting.metrics import cluster_bootstrap_ci
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.data.minute_vendor import out_dir
from trading_research.strategies import intraday_families as fam

RISK_INR = 300.0
CAPITAL_INR = 15_000.0
SLIP = {"stocks": 0.02 / 100, "indices": 0.03 / 100}
SLIP_GRID = [0.0, None, 0.05 / 100, 0.10 / 100]  # None = base
MIN_LIQ_INR = 50e7  # Rs 50 crore median traded value
MIN_PRICE = 50.0
ETF_SCALE = 0.01    # NIFTYBEES / BANKBEES ~ index / 100
MIN_LOT = {"NIFTY": 25, "BANKNIFTY": 15}  # smallest lot either index has had; any larger lot risks more
EXPS = {("orb", False): "EXP-0061", ("brt", False): "EXP-0062", ("ema", False): "EXP-0063",
        ("orb", True): "EXP-0064", ("brt", True): "EXP-0065", ("ema", True): "EXP-0066"}
SPLITS = {
    "stocks": {"dev": ("2017-01-01", "2018-12-31"), "dev_a": ("2017-01-01", "2017-12-31"),
               "dev_b": ("2018-01-01", "2018-12-31"), "validation": ("2019-01-01", "2019-12-31"),
               "holdout": ("2020-01-01", "2020-12-31")},
    "indices": {"dev": ("2017-04-01", "2021-12-31"), "dev_a": ("2017-04-01", "2019-06-30"),
                "dev_b": ("2019-07-01", "2021-12-31"), "validation": ("2022-01-01", "2023-12-31"),
                "holdout": ("2024-01-01", "2026-10-31")},
}


# ------------------------------------------------------------------ charges (Groww intraday schedule, unverified)


def leg_charges(value: float, buy: bool) -> float:
    brok = min(20.0, 0.001 * value)
    if brok < 5.0:
        brok = min(5.0, 0.025 * value)
    exch, sebi = 0.0000297 * value, 0.000001 * value
    gst = 0.18 * (brok + exch + sebi)
    tax = 0.00003 * value if buy else 0.00025 * value  # stamp on buy, STT on sell
    return brok + exch + sebi + gst + tax


def round_trip(q: int, entry: float, exit_: float, side: int) -> float:
    buy_px, sell_px = (entry, exit_) if side > 0 else (exit_, entry)
    return leg_charges(q * buy_px, True) + leg_charges(q * sell_px, False)


def size(entry: float, stop: float, side: int, slip: float, cap: float | None) -> int:
    rps = abs(entry - stop) + slip * (entry + stop)
    if rps <= 0:
        return 0
    q = int(RISK_INR // rps)
    if cap is not None:
        q = min(q, int(cap // (entry * (1 + slip))))
    while q > 0 and q * rps + round_trip(q, entry, stop, side) > RISK_INR:
        q -= 1
    return q


def rupees(t: pd.DataFrame, slip: float, cap: float | None, charge_mult: float = 1.0, slip_mult: float = 1.0,
           qty: pd.Series | None = None) -> pd.DataFrame:
    """Adds qty, net P&L (Rs), charges, planned risk and net R. Prices are converted with t['scale']."""
    out = t.copy()
    s_eff = slip * slip_mult
    rows = []
    for idx, r in out.iterrows():
        f, side = r["scale"], int(r["side"])
        e, st, x = r["entry"] * f, r["stop"] * f, r["exit"] * f
        q = int(qty.loc[idx]) if qty is not None else size(e, st, side, slip, cap)
        ef, xf = e * (1 + s_eff * side), x * (1 - s_eff * side)
        ch = round_trip(q, ef, xf, side) * charge_mult if q else 0.0
        pnl = q * (xf - ef) * side - ch
        planned = q * (abs(e - st) + slip * (e + st)) + (round_trip(q, e, st, side) if q else 0.0)
        rows.append((q, q * e, ch, pnl, planned, pnl / planned if planned > 0 else np.nan,
                     abs(r["entry"] - r["stop"]) * MIN_LOT.get(r["inst"], 0)))
    cols = ["qty", "notional", "charges", "pnl", "planned_risk", "net_r", "min_lot_risk_pts_inr"]
    out[cols] = pd.DataFrame(rows, index=out.index, columns=cols)
    return out[out["qty"] > 0]


# ------------------------------------------------------------------ per-instrument signal generation


def _stock_job(args) -> list[dict]:
    sym, root, mkt = args
    bars = pd.read_parquet(root / "stocks" / f"{sym}.parquet")
    days = pd.read_parquet(root / "stocks" / f"{sym}_days.parquet").set_index("date").sort_index()
    if bars.empty:
        return []
    key = bars.index.normalize()
    daily = bars.groupby(key).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    ok = days["status"] == "ok"
    prev_ok = ok.shift(1, fill_value=False)
    info = pd.DataFrame(index=days.index)
    info["prev_high"] = daily["high"].reindex(days.index).shift(1).where(prev_ok)
    info["prev_low"] = daily["low"].reindex(days.index).shift(1).where(prev_ok)
    info["prev_close"] = daily["close"].reindex(days.index).shift(1).where(prev_ok)
    info["sma20"] = daily["close"].rolling(20, min_periods=15).mean().shift(1).reindex(days.index).ffill(limit=1)
    info["sma20"] = info["sma20"].where(prev_ok)
    liq = days["traded_value"].shift(1).rolling(20, min_periods=15).median()
    eligible = ok & (liq >= MIN_LIQ_INR) & (days["close"].shift(1) >= MIN_PRICE)
    out = []
    for d in fam.build_days(bars, info, mkt):
        if not eligible.get(d.date, False):
            continue
        for (rule, filt) in EXPS:
            sig = fam.first_signal(d, rule, filt, use_rvol=True)
            if sig is not None:
                tr = fam.simulate(d, sig)
                tr.update(inst=sym, filtered=filt, scale=float(days.at[d.date, "factor"]), liq=float(liq[d.date]))
                out.append(tr)
    return out


def _index_trades(name: str, root: Path, mkt: dict) -> list[dict]:
    bars = pd.read_parquet(root / "indices" / f"{name}.parquet")
    days = pd.read_parquet(root / "indices" / f"{name}_days.parquet").set_index("date").sort_index()
    days = days[days["close"].notna()]
    info = pd.DataFrame(index=days.index)
    info["prev_high"] = days["high"].shift(1)
    info["prev_low"] = days["low"].shift(1)
    info["prev_close"] = days["close"].shift(1)
    info["sma20"] = days["close"].rolling(20, min_periods=15).mean().shift(1)
    out = []
    for d in fam.build_days(bars, info, mkt):
        for (rule, filt) in EXPS:
            sig = fam.first_signal(d, rule, filt, use_rvol=False)
            if sig is not None:
                tr = fam.simulate(d, sig)
                tr.update(inst=name, filtered=filt, scale=ETF_SCALE, liq=1.0 if name == "NIFTY" else 0.0)
                out.append(tr)
    return out


def select_one_per_day(t: pd.DataFrame) -> pd.DataFrame:
    """Earliest entry; ties by higher trigger RVOL, then higher liquidity (NIFTY before BANK NIFTY)."""
    t = t.assign(_rv=t["rvol"].fillna(-1.0))
    t = t.sort_values(["date", "entry_min", "_rv", "liq"], ascending=[True, True, False, False])
    return t.drop_duplicates("date").drop(columns="_rv")


# ------------------------------------------------------------------ metrics


def stats(t: pd.DataFrame, ci: bool = False) -> dict:
    n = len(t)
    if n == 0:
        return {"trades": 0}
    pnl = t["pnl"].to_numpy()
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    daily = t.groupby("date")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    dd = float((eq - eq.cummax().clip(lower=0)).min())
    streak = best = 0
    for p in pnl:
        streak = streak + 1 if p <= 0 else 0
        best = max(best, streak)
    out = {"trades": n, "win_rate": round(float((pnl > 0).mean()), 3),
           "avg_win_inr": round(float(wins.mean()), 1) if len(wins) else None,
           "avg_loss_inr": round(float(losses.mean()), 1) if len(losses) else None,
           "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.sum() < 0 else None,
           "expectancy_inr": round(float(pnl.mean()), 1), "mean_net_r": round(float(t["net_r"].mean()), 3),
           "mean_gross_r": round(float(t["gross_r"].mean()), 3), "total_pnl_inr": round(float(pnl.sum()), 0),
           "max_drawdown_inr": round(dd, 0), "max_losing_streak": int(best),
           "total_charges_inr": round(float(t["charges"].sum()), 0),
           "avg_charges_inr": round(float(t["charges"].mean()), 1),
           "median_notional_inr": round(float(t["notional"].median()), 0),
           "target_rate": round(float((t["reason"] == "target").mean()), 3),
           "stop_rate": round(float((t["reason"] == "stop").mean()), 3),
           "long_share": round(float((t["side"] > 0).mean()), 3)}
    if ci and n >= 10:
        months = pd.to_datetime(t["date"]).dt.to_period("M").astype(str).to_numpy()
        lo, hi = cluster_bootstrap_ci(t["net_r"].to_numpy(), months)
        out["mean_net_r_ci95"] = [round(lo, 3), round(hi, 3)]
    return out


def in_split(t: pd.DataFrame, universe: str, s: str) -> pd.DataFrame:
    a, b = SPLITS[universe][s]
    d = pd.to_datetime(t["date"])
    return t[(d >= a) & (d <= b)]


def verdict(res: dict) -> dict:
    dv, va, ho = res["A"]["dev"], res["A"]["validation"], res["A"]["holdout"]
    c = {
        "dev >= 100 trades": dv["trades"] >= 100,
        "dev mean net R > 0": dv.get("mean_net_r", -1) > 0,
        "dev CI above 0": dv.get("mean_net_r_ci95", [-1])[0] > 0,
        "dev PF >= 1.15": (dv.get("profit_factor") or 0) >= 1.15,
        "dev halves > 0": res["A"]["dev_a"].get("mean_net_r", -1) > 0 and res["A"]["dev_b"].get("mean_net_r", -1) > 0,
        "dev stress > 0": res["A_stress"]["dev"].get("mean_net_r", -1) > 0,
        "validation > 0": va.get("mean_net_r", -1) > 0,
        "validation stress > 0": res["A_stress"]["validation"].get("mean_net_r", -1) > 0,
        "holdout > 0": ho.get("mean_net_r", -1) > 0,
    }
    return {"checks": c, "status": "PAPER CANDIDATE" if all(c.values()) else "REJECTED"}


def evaluate(trades: pd.DataFrame, universe: str) -> dict:
    slip = SLIP[universe]
    out = {}
    for (rule, filt), exp in EXPS.items():
        t_all = trades[(trades["rule"] == rule) & (trades["filtered"] == filt)]
        one = select_one_per_day(t_all)
        a = rupees(one, slip, None)
        res = {"rule": rule, "filtered": filt, "signals_all_instruments": int(len(t_all))}
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
        all_a = rupees(t_all, slip, None)
        res["all_signals_A"] = {s: stats(in_split(all_a, universe, s)) for s in ("dev", "validation", "holdout")}
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
    nifty_s = pd.read_parquet(root / "indices" / "NIFTY_S.parquet")
    nifty = pd.read_parquet(root / "indices" / "NIFTY.parquet")
    mkt_s, mkt_n = fam.market_direction(nifty_s), fam.market_direction(nifty)
    syms = sorted(p.stem for p in (root / "stocks").glob("*.parquet") if not p.stem.endswith("_days"))
    with ProcessPoolExecutor(a.workers) as ex:
        parts = list(ex.map(_stock_job, [(s, root, mkt_s) for s in syms]))
    stock_t = pd.DataFrame([r for p in parts for r in p])
    idx_t = pd.DataFrame(_index_trades("NIFTY", root, mkt_n) + _index_trades("BANKNIFTY", root, mkt_n))
    result = {"generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
              "spec_version": fam.SPEC_VERSION, "risk_inr": RISK_INR, "capital_inr_scenario_b": CAPITAL_INR,
              "slippage_base": SLIP, "stocks": evaluate(stock_t, "stocks"), "indices": evaluate(idx_t, "indices")}
    (REPORT_DIR / "EXP-0061-0066.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    for u in ("stocks", "indices"):
        for exp, r in result[u].items():
            A = r["A"]
            print(u, exp, r["rule"], "filt" if r["filtered"] else "base", r["status"],
                  {s: (A[s]["trades"], A[s].get("mean_net_r"), A[s].get("profit_factor")) for s in
                   ("dev", "validation", "holdout")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
