"""EXP-0082: trailing-stop and partial exits vs fixed targets on the EXP-0081 scan-replay entries.

Spec: docs/strategy-specifications/trailing-exits.md. Research only; nothing here orders. Entries come from
`run_orb_scan_replay.replay_day` (the live v0.2 scan rule replayed on 1-minute bars); only the exit changes.

CLI:  python -m trading_research.backtesting.run_trailing --vendor-dir <NSE_Stocks_Data> --official-root <root>
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import run_orb_scan_replay as rep
from trading_research.backtesting.metrics import cluster_bootstrap_ci
from trading_research.config import REPO_ROOT
from trading_research.data import symbols
from trading_research.live import intraday_scan as scan
from trading_research.strategies import trailing_exits as tx

EXPERIMENT = "EXP-0082"
SLIP = 0.05 / 100
SLIP_GRID = (0.0, 0.05 / 100, 0.10 / 100)
SPLITS = rep.SPLITS
MFE_LEVELS = (1.0, 2.0, 3.0, 5.0)


# ------------------------------------------------------------------ charges per order


def groww_leg(value: float, buy: bool) -> float:
    """Groww intraday schedule as used for EXP-0061..0077 (unverified placeholder)."""
    brok = min(20.0, 0.001 * value)
    if brok < 5.0:
        brok = min(5.0, 0.025 * value)
    exch, sebi = 0.0000297 * value, 0.000001 * value
    gst = 0.18 * (brok + exch + sebi)
    return brok + exch + sebi + gst + (0.00003 * value if buy else 0.00025 * value)


def placeholder_leg(value: float, buy: bool, p: scan.Params = scan.Params()) -> float:
    """The EXP-0080/0081 schedule (`intraday_scan.round_trip_charges`) for one order."""
    brok = min(p.brokerage_pct / 100 * value, p.brokerage_cap_inr)
    fees = (p.exchange_pct + p.sebi_pct) / 100 * value
    tax = p.stamp_buy_pct / 100 * value if buy else p.stt_sell_pct / 100 * value
    return (brok + fees) * (1 + p.gst_pct / 100) + tax


def money(q: int, fill: float, legs: list[tuple[float, float, str, int]], leg_fn=groww_leg, slip: float = SLIP,
          mult: float = 1.0) -> tuple[float, float, float]:
    """(gross Rs, charges Rs, net Rs) for `q` shares bought at `fill` and sold in `legs` (fractions 0.5/0.5 or 1)."""
    shares = [q] if len(legs) == 1 else [q // 2, q - q // 2]
    gross = sum(s * (px - fill) for s, (_, px, _, _) in zip(shares, legs))
    charges = leg_fn(q * fill, True) + sum(leg_fn(s * px, False) for s, (_, px, _, _) in zip(shares, legs) if s)
    slippage = slip * (q * fill + sum(s * px for s, (_, px, _, _) in zip(shares, legs)))
    return gross, mult * charges, gross - mult * (charges + slippage)


# ------------------------------------------------------------------ per stock


def stock_job(args: tuple) -> tuple[str, list[dict]]:
    csv, current, links, official = args
    bars = rep.read_vendor(Path(csv))
    off = official.set_index(["symbol", "date"])
    hist_by_name = {n: g.reset_index(drop=True) for n, g in official.groupby("symbol")}
    ok = []                                   # (day, group, factor, name, official row): same gate as EXP-0081
    for day, g in bars.groupby("date"):
        if len(g) < rep.MIN_BARS:
            continue
        name = rep.name_on(day, current, links)
        if (name, day) not in off.index:
            continue
        t = off.loc[(name, day)]
        f = rep.factor(float(g["high"].max()), float(g["low"].min()), float(t["high"]), float(t["low"]))
        if f is not None:
            ok.append((day, g, f, name, t))
    if not ok:
        return current, []
    five = tx.five_minute_indicators(pd.concat([g for _, g, *_ in ok]))
    rows = []
    for day, g, f, name, t in ok:
        hist = []
        for n in {name, current} | {lk["old_symbol"] for lk in links}:
            hd = hist_by_name.get(n)
            if hd is not None:
                hist.append(hd[hd["date"] < day])
        if not hist:
            continue
        hd = pd.concat(hist).drop_duplicates("date").sort_values("date").tail(20)
        hbars = [{"date": str(r.date.date()), "open": r.open, "high": r.high, "low": r.low, "close": r.close}
                 for r in hd.itertuples()]
        row = rep.replay_day(g, f, current, {"date": day, "prev_close": float(t["prev_close"])}, hbars)
        if row is None:
            continue
        keep = {k: row[k] for k in ("date", "symbol", "value_cr", "entry", "stop", "risk", "qty", "charges_ok",
                                    "factor", "outcome")}
        if row["outcome"] == "triggered" and row["qty"] > 0:
            keep.update(exits_for(g, f, row, five.loc[day]))
        rows.append(keep)
    return current, rows


def exits_for(g: pd.DataFrame, f: float, row: dict, five_day: pd.DataFrame) -> dict:
    after = g[g["minute"] >= rep.SCAN_MIN]
    m = after["minute"].to_numpy()
    o, h, lo = (after[k].to_numpy() * f for k in ("open", "high", "low"))
    i = int(np.flatnonzero(m == row["entry_min"])[0])
    fill, entry, stop, q = row["fill"], row["entry"], row["stop"], int(row["qty"])
    intrabar = fill != float(o[i])
    fd = {int(e): (r.low * f, r.close * f, r.ema9 * f, r.atr14 * f) for e, r in five_day.iterrows()}
    out = {"fill": fill, "entry_min": row["entry_min"], "intrabar": intrabar,
           "mfe_r": tx.max_favourable_r(m, h, lo, i, entry, stop, intrabar),
           "rep_2R_exit": row["2R_exit"]}
    for rule in tx.EXITS:
        legs = tx.walk(m, o, h, lo, i, fill, entry, stop, rule, fd, intrabar, can_partial=q >= 2)
        gross, ch, net = money(q, fill, legs)
        out[f"{rule.name}|gross"] = gross
        out[f"{rule.name}|charges"] = ch
        out[f"{rule.name}|net"] = net
        out[f"{rule.name}|net2x"] = money(q, fill, legs, slip=2 * SLIP, mult=2.0)[2]
        for s in SLIP_GRID:
            out[f"{rule.name}|net_slip{s * 100:.2f}"] = money(q, fill, legs, slip=s)[2]
        out[f"{rule.name}|net_placeholder"] = money(q, fill, legs, leg_fn=placeholder_leg)[2]
        out[f"{rule.name}|reason"] = legs[-1][2]
        out[f"{rule.name}|orders"] = 1 + len(legs)
        out[f"{rule.name}|exit_min"] = legs[-1][3]
        out[f"{rule.name}|exit_px"] = legs[-1][1]
    return out


# ------------------------------------------------------------------ statistics


def stats(t: pd.DataFrame, name: str, ci: bool = False) -> dict:
    if t.empty:
        return {"trades": 0}
    net = t[f"{name}|net"].to_numpy()
    risk = (t["risk"] * t["qty"]).to_numpy()
    eq = np.concatenate([[0.0], np.cumsum(net)])
    streak = run = 0
    for v in net:
        run = run + 1 if v < 0 else 0
        streak = max(streak, run)
    wins, losses = net[net > 0], net[net < 0]
    out = {"trades": int(len(t)), "win_rate": round(float((net > 0).mean()), 3),
           "avg_win_inr": round(float(wins.mean()), 1) if len(wins) else None,
           "avg_loss_inr": round(float(losses.mean()), 1) if len(losses) else None,
           "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) else None,
           "mean_gross_inr": round(float(t[f"{name}|gross"].mean()), 1),
           "mean_net_inr": round(float(net.mean()), 1),
           "mean_net_inr_2x": round(float(t[f"{name}|net2x"].mean()), 1),
           "mean_net_r": round(float((net / risk).mean()), 3),
           "total_net_inr": round(float(net.sum()), 0),
           "max_drawdown_inr": round(float((np.maximum.accumulate(eq) - eq).max()), 0),
           "longest_losing_streak": int(streak),
           "mean_charges_inr": round(float(t[f"{name}|charges"].mean()), 1),
           "slippage_sensitivity": {f"{s * 100:.2f}%": round(float(t[f"{name}|net_slip{s * 100:.2f}"].mean()), 1)
                                    for s in SLIP_GRID},
           "mean_net_inr_placeholder_costs": round(float(t[f"{name}|net_placeholder"].mean()), 1),
           "exit_reasons": {k: int(v) for k, v in t[f"{name}|reason"].value_counts().items()}}
    if ci:
        lo, hi = cluster_bootstrap_ci(net, months(t), seed=82)
        out["ci95_mean_net_inr_by_month"] = [round(lo, 1), round(hi, 1)]
    return out


def months(t: pd.DataFrame) -> np.ndarray:
    return pd.to_datetime(t["date"]).dt.to_period("M").astype(str).to_numpy()


def mfe_profile(t: pd.DataFrame) -> dict:
    return {f">={k:g}R": round(float((t["mfe_r"] >= k).mean()), 3) for k in MFE_LEVELS} | \
        {"median_r": round(float(t["mfe_r"].median()), 2)}


def paired(t: pd.DataFrame, a: str, b: str = tx.BASELINE, ci: bool = False) -> dict:
    d = (t[f"{a}|net"] - t[f"{b}|net"]).to_numpy()
    out = {"mean_diff_inr": round(float(d.mean()), 1) if len(d) else None,
           "share_better": round(float((d > 0).mean()), 3) if len(d) else None,
           "share_worse": round(float((d < 0).mean()), 3) if len(d) else None}
    if ci:
        lo, hi = cluster_bootstrap_ci(d, months(t), seed=82)
        out["ci95_by_month"] = [round(lo, 1), round(hi, 1)]
    return out


def years(t: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(t["date"]).dt.year


def walk_forward(t: pd.DataFrame, names=tuple(e.name for e in tx.EXITS)) -> dict:
    y = years(t)
    out, nets = {}, []
    for test in (2018, 2019, 2020):
        past, now = t[y < test], t[y == test]
        best = max(names, key=lambda n: past[f"{n}|net"].mean())
        out[str(test)] = {"chosen_on_earlier_years": best, "trades": int(len(now)),
                          "mean_net_inr": round(float(now[f"{best}|net"].mean()), 1),
                          "total_net_inr": round(float(now[f"{best}|net"].sum()), 0),
                          "vs_2R_mean_diff_inr": round(float((now[f"{best}|net"] - now[f"{tx.BASELINE}|net"]).mean()), 1)}
        nets.append(now[f"{best}|net"].to_numpy())
    allnet = np.concatenate(nets)
    out["combined"] = {"trades": int(len(allnet)), "mean_net_inr": round(float(allnet.mean()), 1),
                       "total_net_inr": round(float(allnet.sum()), 0)}
    return out


def evaluate(t: pd.DataFrame) -> dict:
    names = [e.name for e in tx.EXITS]
    res = {"splits": {}, "pooled": {}, "mfe_profile": {}, "vs_2R": {}}
    for s, yrs in SPLITS.items():
        sub = rep.in_split(t, yrs)
        res["splits"][s] = {n: stats(sub, n) for n in names}
        res["mfe_profile"][s] = mfe_profile(sub)
        res["vs_2R"][s] = {n: paired(sub, n) for n in names if n != tx.BASELINE}
    res["pooled"] = {n: stats(t, n, ci=True) for n in names}
    res["mfe_profile"]["pooled"] = mfe_profile(t)
    res["vs_2R"]["pooled"] = {n: paired(t, n, ci=True) for n in names if n != tx.BASELINE}
    res["walk_forward"] = walk_forward(t)
    dev = rep.in_split(t, SPLITS["dev 2017-2018"])
    sel = max(tx.TRAILING, key=lambda n: dev[f"{n}|net"].mean())
    overall = max(names, key=lambda n: dev[f"{n}|net"].mean())

    def beats_2r(n: str) -> bool:
        if n == tx.BASELINE:
            return False
        split_ok = all(res["vs_2R"][s][n]["mean_diff_inr"] > 0 for s in SPLITS)
        return split_ok and res["vs_2R"]["pooled"][n]["ci95_by_month"][0] > 0

    def positive(n: str) -> bool:
        return all(res["splits"][s][n]["mean_net_inr_2x"] > 0 for s in SPLITS) and \
            res["pooled"][n]["ci95_mean_net_inr_by_month"][0] > 0 and \
            all(res["walk_forward"][str(y)]["mean_net_inr"] > 0 for y in (2018, 2019, 2020))

    res["decision"] = {
        "selected_trailing_exit_dev": sel, "beats_2R": beats_2r(sel),
        "overall_dev_best_exit": overall, "overall_best_beats_2R": beats_2r(overall),
        "rule_positive_with_selected": positive(sel),
        "status": "REJECTED" if not positive(sel) else "POSITIVE (descriptive only; forward data needed)",
        "live_rule_change": "none" if not beats_2r(sel) else "candidate for a registered v0.3 with forward data"}
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor-dir", required=True, type=Path)
    ap.add_argument("--official-root", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "reports" / "backtests" / "EXP-0082-trailing-exits.json")
    a = ap.parse_args(argv)
    changes = symbols.load_symbol_changes(a.official_root)
    jobs, names = [], set()
    for csv in sorted(a.vendor_dir.glob("*__EQ__NSE__NSE__MINUTE.csv")):
        vendor = csv.name.split("__")[0]
        current = rep.VENDOR_TO_NSE.get(vendor, vendor)
        links = [lk for lk in symbols.predecessors(current, changes)
                 if lk["effective_date"] > pd.Timestamp("2016-10-01")]
        names |= {current} | {lk["old_symbol"] for lk in links}
        jobs.append((str(csv), current, links))
    official = rep.load_official(a.official_root, names)
    rows = []
    with ProcessPoolExecutor(a.workers) as ex:
        args = [(csv, cur, links, official[official["symbol"].isin({cur} | {lk["old_symbol"] for lk in links})])
                for csv, cur, links in jobs]
        for _, r in ex.map(stock_job, args):
            rows += r
    cands = pd.DataFrame(rows)
    picks = rep.pick_one_per_day(cands)
    trades = picks[picks["outcome"] == "triggered"].sort_values("date").reset_index(drop=True)
    every = cands[(cands["outcome"] == "triggered") & cands["charges_ok"] & (cands["qty"] > 0)]
    every = every.sort_values(["date", "value_cr"], ascending=[True, False]).reset_index(drop=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(a.out.with_name(a.out.stem + "-trades.csv"), index=False)
    res = {"experiment": EXPERIMENT, "spec": "docs/strategy-specifications/trailing-exits.md",
           "entries": "EXP-0081 replay of the v0.2 scan (run_orb_scan_replay.replay_day)",
           "costs": "Groww intraday placeholder schedule + 0.05% slippage per fill; 2x = both doubled",
           "funnel": {"picked_days": int(len(picks)), "triggered_trades": int(len(trades)),
                      "robustness_set_trades": int(len(every))},
           "exp0081_cross_check": {
               "F2_exit_price_equal_share": round(float(np.isclose(trades["F2 2R|exit_px"],
                                                                   trades["rep_2R_exit"]).mean()), 3),
               "F2_mean_net_inr_exp0081_costs": round(float(trades["F2 2R|net_placeholder"].mean()), 1)},
           "picks": evaluate(trades), "robustness_every_idea": evaluate(every)}
    a.out.write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
    d = res["picks"]["decision"]
    print(json.dumps(d, indent=2))
    for n in (e.name for e in tx.EXITS):
        print(f"{n:28s}", {s: res["picks"]["splits"][s][n]["mean_net_inr"] for s in SPLITS},
              res["picks"]["pooled"][n]["mean_net_inr"], res["picks"]["pooled"][n]["ci95_mean_net_inr_by_month"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
