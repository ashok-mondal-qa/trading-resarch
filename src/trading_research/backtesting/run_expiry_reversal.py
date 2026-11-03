"""Run EXP-0054 (base rule) and EXP-0055 (variant grid) of spec docs/strategy-specifications/nifty-expiry-reversal.md.
Research only; nothing here orders or alerts.

    python -m trading_research.backtesting.run_expiry_reversal --fo-root data/fo_session

Step 1 simulates all 32 variants on dev + validation expiry days only. The variant is selected on dev. Step 2
then reads the holdout once, for the base rule and the selected variant only.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import metrics
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.config import REPO_ROOT
from trading_research.data import fo_bhavcopy, indices, nifty_intraday
from trading_research.strategies import expiry_reversal as er

SPLITS = {"dev": ("2019-02-01", "2022-12-31"), "dev_a": ("2019-02-01", "2020-12-31"),
          "dev_b": ("2021-01-01", "2022-12-31"), "validation": ("2023-01-01", "2024-12-31"),
          "holdout": ("2025-01-01", "2026-10-30")}
MIN_DEV_TRADES = 60
ETF_NOTIONAL = 15000.0
RISK_LIMIT_INR = 150.0


def split_of(d: pd.Timestamp) -> str | None:
    for s in ("dev", "validation", "holdout"):
        if pd.Timestamp(SPLITS[s][0]) <= d <= pd.Timestamp(SPLITS[s][1]):
            return s
    return None


def expiry_calendar(fo_root: Path) -> tuple[pd.DataFrame, dict]:
    """NIFTY option expiry dates on which a contract with that expiry traded (spec), plus lot size per date."""
    fo = fo_bhavcopy.read(date(2019, 1, 1), date(2026, 10, 30), root=fo_root, symbols=("NIFTY",))
    sessions = set(fo["date"].unique())
    opt = fo[fo["instrument"] == "OPT"]
    # A contract must trade ON its expiry date and never after: long-dated contracts can carry a stale date
    # (e.g. Thursday 2025-09-25 after the move to Tuesday, or a date later moved for a holiday).
    on_day = set(opt.loc[opt["date"] == opt["expiry"], "expiry"].unique())
    after = set(opt.loc[opt["date"] > opt["expiry"], "expiry"].unique())
    exp = sorted(e for e in on_day - after if e in sessions)
    fut = fo[fo["instrument"] == "FUT"].sort_values(["date", "expiry"]).groupby("date").first()
    lot = fut["lot_size"].where(fut["lot_size"].notna(),
                                (fut["value_lakh"] * 1e5 / (fut["contracts"] * fut["close"]) / 25).round() * 25)
    cal = pd.DataFrame({"date": pd.to_datetime(exp)})
    cal["weekday"] = cal["date"].dt.day_name()
    cal["lot"] = cal["date"].map(lot)
    return cal, {"fo_sessions": len(sessions), "first_session": str(min(sessions).date()),
                 "last_session": str(max(sessions).date())}


def gate1(bars: pd.DataFrame, days: list[pd.Timestamp], official: pd.DataFrame) -> dict[pd.Timestamp, str]:
    by_day = {d: g for d, g in bars.groupby(bars.index.normalize())}
    out = {}
    for d in days:
        g = by_day.get(d)
        if g is None:
            out[d] = "no intraday bars"
        elif d not in official.index:
            out[d] = "no official NSE row"
        else:
            out[d] = nifty_intraday.day_check(g, official.at[d, "high"], official.at[d, "low"])
    return out


def trades_for(bars: pd.DataFrame, days: list[pd.Timestamp], p: er.Params, lots: dict, sim=None,
               ctx: dict | None = None) -> pd.DataFrame:
    """`sim(day_bars, ctx_for_day)` replaces the base rule when given (used by run_expiry_ideas)."""
    by_day = {d: g for d, g in bars.groupby(bars.index.normalize()) if d in set(days)}
    rows = []
    for d in days:
        t = er.simulate(by_day[d], p) if sim is None else sim(by_day[d], (ctx or {}).get(d, {}))
        if not t or t.get("side") == "skip":
            continue
        lot = lots.get(d) or 75.0
        t.update(date=d, lot=lot, split=split_of(d), year=d.year, weekday=d.day_name())
        for mult, k in ((1.0, "1x"), (2.0, "2x")):
            cost = er.futures_cost_points(t["entry"], t["exit"], t["side"], lot, mult=mult)
            t[f"net_pts_{k}"] = t["gross_pts"] - cost
            t[f"r_{k}"] = t[f"net_pts_{k}"] / t["risk_pts"]
            gross_pct = t["gross_pts"] / t["entry"] * 100
            t[f"etf_inr_{k}"] = ETF_NOTIONAL * gross_pct / 100 - er.etf_cost_inr(ETF_NOTIONAL, gross_pct, mult)
        rows.append(t)
    return pd.DataFrame(rows)


def summary(t: pd.DataFrame, ci: bool = False) -> dict:
    if t.empty:
        return {"trades": 0}
    out = {"trades": int(len(t)), "gross_win_rate": float((t["gross_pts"] > 0).mean()),
           "reached_other_side_rate": float(t["reached_opposite"].mean()),
           "gross_mean_r": float((t["gross_pts"] / t["risk_pts"]).mean()), "gross_mean_pts": float(t["gross_pts"].mean()),
           "median_risk_pts": float(t["risk_pts"].median()),
           "median_risk_inr_per_lot": float((t["risk_pts"] * t["lot"]).median()),
           "exit_reasons": t["reason"].value_counts().to_dict(),
           "shorts": int((t["side"] == "short").sum()), "longs": int((t["side"] == "long").sum())}
    for k in ("1x", "2x"):
        r, pts = t[f"r_{k}"].to_numpy(float), t[f"net_pts_{k}"].to_numpy(float)
        inr = pts * t["lot"].to_numpy(float)
        cum = np.concatenate([[0.0], np.cumsum(inr)])
        cum_r = np.concatenate([[0.0], np.cumsum(r)])
        g, lo = pts[pts > 0].sum(), -pts[pts < 0].sum()
        out[k] = {"win_rate": float((pts > 0).mean()), "mean_r": float(r.mean()), "mean_pts": float(pts.mean()),
                  "mean_inr_per_lot": float(inr.mean()), "total_inr_per_lot": float(inr.sum()),
                  "profit_factor": float(g / lo) if lo > 0 else None,
                  "max_drawdown_inr_per_lot": float((cum - np.maximum.accumulate(cum)).min()),
                  "max_drawdown_r": float((cum_r - np.maximum.accumulate(cum_r)).min()),
                  "etf15k_mean_inr": float(t[f"etf_inr_{k}"].mean()), "etf15k_total_inr": float(t[f"etf_inr_{k}"].sum()),
                  "etf15k_win_rate": float((t[f"etf_inr_{k}"] > 0).mean())}
        if ci:
            out[k]["ci95_mean_r"] = metrics.cluster_bootstrap_ci(r, t["date"].dt.to_period("M").astype(str).to_numpy())
    return out


def in_split(t: pd.DataFrame, s: str) -> pd.DataFrame:
    if t.empty:
        return t
    a, b = pd.Timestamp(SPLITS[s][0]), pd.Timestamp(SPLITS[s][1])
    return t[(t["date"] >= a) & (t["date"] <= b)]


def dev_checks(t: pd.DataFrame) -> dict:
    dev = summary(in_split(t, "dev"), ci=True)
    if dev["trades"] == 0:
        return {"pass": False, "checks": {}}
    c = {f"dev >= {MIN_DEV_TRADES} trades": dev["trades"] >= MIN_DEV_TRADES,
         "dev 1x mean R > 0, 95% interval above 0": dev["1x"]["ci95_mean_r"][0] > 0,
         "dev 2x mean R > 0": dev["2x"]["mean_r"] > 0}
    for h in ("dev_a", "dev_b"):
        s = summary(in_split(t, h))
        c[f"{h} 1x mean R > 0"] = s["trades"] > 0 and s["1x"]["mean_r"] > 0
    return {"pass": all(c.values()), "checks": c, "dev_2x_mean_r": dev["2x"]["mean_r"]}


def by_group(t: pd.DataFrame, col: str) -> dict:
    return {str(k): {"trades": int(len(g)), "win_rate_1x": float((g["net_pts_1x"] > 0).mean()),
                     "mean_r_1x": float(g["r_1x"].mean()), "mean_r_2x": float(g["r_2x"].mean()),
                     "inr_per_lot_1x": float((g["net_pts_1x"] * g["lot"]).sum()),
                     "reached_other_side": float(g["reached_opposite"].mean())} for k, g in t.groupby(col)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fo-root", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--read-holdout", action="store_true", help="step 2: read the holdout once (base + selected)")
    a = ap.parse_args(argv)
    bars = nifty_intraday.load()
    cal, cal_info = expiry_calendar(a.fo_root)
    official = indices.read_index("Nifty 50", date(2019, 1, 1), date(2026, 10, 30))
    official.index = pd.to_datetime(official.index)
    cal = cal[cal["date"] >= pd.Timestamp(SPLITS["dev"][0])]
    status = gate1(bars, list(cal["date"]), official)
    cal["gate1"] = cal["date"].map(status)
    ok = cal[cal["gate1"] == "ok"]
    lots = dict(zip(ok["date"], ok["lot"]))
    open_days = [d for d in ok["date"] if split_of(d) in ("dev", "validation")]
    out = {"generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
           "spec_version": er.SPEC_VERSION, "splits": SPLITS, "calendar": cal_info,
           "expiry_days": {s: int(sum(split_of(d) == s for d in cal["date"])) for s in ("dev", "validation", "holdout")},
           "expiry_weekdays": {f"{y}": cal[cal["date"].dt.year == y]["weekday"].value_counts().to_dict()
                               for y in sorted(cal["date"].dt.year.unique())},
           "gate1_excluded": {str(r.date.date()): r.gate1 for r in cal.itertuples() if r.gate1 != "ok"}}

    # Step 1: grid on dev + validation only.
    grid = {}
    all_trades = {}
    for p in er.grid():
        t = trades_for(bars, open_days, p, lots)
        all_trades[p.name] = t
        grid[p.name] = {"dev_checks": dev_checks(t), "dev": summary(in_split(t, "dev")),
                        "validation": summary(in_split(t, "validation"))}
    passers = {k: v for k, v in grid.items() if v["dev_checks"]["pass"]}
    selected = max(passers, key=lambda k: passers[k]["dev_checks"]["dev_2x_mean_r"]) if passers else None
    out["grid"] = grid
    out["selected_variant"] = selected
    out["dev_passers"] = sorted(passers)

    base = all_trades[er.BASE.name]
    out["base"] = {s: summary(in_split(base, s), ci=True) for s in ("dev", "dev_a", "dev_b", "validation")}
    out["base_by_year"] = by_group(base, "year")
    out["base_by_weekday"] = by_group(base, "weekday")

    # Control: base rule on non-expiry dev sessions.
    exp_set = set(cal["date"])
    sess = [d for d in official.index if pd.Timestamp(SPLITS["dev"][0]) <= d <= pd.Timestamp(SPLITS["dev"][1])
            and d not in exp_set]
    c_status = gate1(bars, sess, official)
    c_days = [d for d in sess if c_status[d] == "ok"]
    ctrl = trades_for(bars, c_days, er.BASE, {})
    out["control_non_expiry_dev"] = {"sessions": len(c_days), **summary(ctrl, ci=True)}

    # Second source: base rule on sandeepkapri bars for the same days (to 2024-03-27).
    cross = nifty_intraday.load(cross=True)
    x_days = [d for d in open_days if d <= pd.Timestamp("2024-03-26")]
    x_status = gate1(cross, x_days, official)
    x_ok = [d for d in x_days if x_status[d] == "ok"]
    xt = trades_for(cross, x_ok, er.BASE, lots)
    pt = base[base["date"].isin(x_ok)]
    out["second_source_base"] = {"days": len(x_ok), "this_source": summary(pt), "second_source": summary(xt)}

    tag = "step1"
    if a.read_holdout:
        tag = "step2"
        h_days = [d for d in ok["date"] if split_of(d) == "holdout"]
        out["holdout"] = {}
        for name, p in (("base", er.BASE), ("selected", next((q for q in er.grid() if q.name == selected), None))):
            if p is None:
                out["holdout"][name] = "no variant passed dev; not read"
                continue
            ht = trades_for(bars, h_days, p, lots)
            out["holdout"][name] = {"variant": p.name, **summary(ht, ci=True), "by_year": by_group(ht, "year"),
                                    "by_weekday": by_group(ht, "weekday")}
            if name == "base":
                base = pd.concat([base, ht], ignore_index=True)
        out["base_by_year"] = by_group(base, "year")
        out["base_by_weekday"] = by_group(base, "weekday")
        out["base_all"] = summary(base, ci=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"EXP-0054-0055-{tag}.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    base.to_csv(REPORT_DIR / f"EXP-0054-base-trades-{tag}.csv", index=False)
    print(json.dumps({k: out[k] for k in ("expiry_days", "selected_variant", "dev_passers", "base")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
