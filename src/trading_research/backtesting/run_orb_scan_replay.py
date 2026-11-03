"""EXP-0081: historical replay of the v0.2 opening-range scan rule, comparing exit targets.

Spec: docs/strategy-specifications/intraday-orb-scan.md, section "Historical replay of the v0.2 rule".
Research only; nothing here orders. The screen and levels reuse `live.intraday_scan` (quote_screen, plan,
money_plan, round_trip_charges), so the replay applies the same rule as the morning scan.

Data: unofficial 1-minute bars (GitHub ShabbirHasan1/NSE-Data, split adjusted) scaled day by day to the official
NSE CM bhavcopy: the vendor's day high and low must give the same factor within 0.10%, else the day is skipped.

CLI:  python -m trading_research.backtesting.run_orb_scan_replay --vendor-dir <NSE_Stocks_Data> --official-root <root>
      [--out reports/backtests/EXP-0081-orb-scan-replay.json]
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import bhavcopy, symbols
from trading_research.live import intraday_scan as scan

EXPERIMENT = "EXP-0081"
TARGETS = (1.0, 1.5, 2.0, 3.0, None)       # None = no target, hold to 15:10
SCAN_MIN = 9 * 60 + 35                      # decision at 09:35 from bars 09:15..09:34
OPEN_MIN = 9 * 60 + 15
EXIT_MIN = 15 * 60 + 10
FACTOR_TOL = 0.10 / 100
MIN_BARS = 360
CAPITAL, MAX_RISK_INR, CHARGES_EST = 15000.0, 300.0, 40.0
VENDOR_TO_NSE = {"BAJAJ_AUTO": "BAJAJ-AUTO", "M_M": "M&M", "L_TFH": "L&TFH", "M_MFIN": "M&MFIN",
                 "NAM_INDIA": "NAM-INDIA"}
SPLITS = {"dev 2017-2018": (2017, 2018), "validation 2019": (2019, 2019), "2020 (already seen)": (2020, 2020)}


def tkey(m: float | None) -> str:
    return "no target" if m is None else f"{m:g}R"


# ------------------------------------------------------------------ data


def read_vendor(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv)
    ts = pd.to_datetime(df["timestamp"].str.slice(0, 19))  # values are IST wall time
    df = df.assign(ts=ts, date=ts.dt.normalize(), minute=ts.dt.hour * 60 + ts.dt.minute)
    df = df[(df["minute"] >= OPEN_MIN) & (df["minute"] <= 15 * 60 + 29)]
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[(df["high"] >= df["low"]) & (df["low"] > 0)].drop_duplicates("ts").sort_values("ts")


def factor(vh: float, vl: float, oh: float, ol: float) -> float | None:
    if not (vh > 0 and vl > 0 and oh > 0 and ol > 0):
        return None
    fh, fl = oh / vh, ol / vl
    return (fh + fl) / 2 if abs(fh / fl - 1) <= FACTOR_TOL else None


def name_on(day: pd.Timestamp, current: str, links: list[dict]) -> str:
    """NSE ticker in force on `day`: links are newest first (old_symbol used before effective_date)."""
    name = current
    for link in links:
        if day < link["effective_date"]:
            name = link["old_symbol"]
    return name


def load_official(root: Path, names: set[str]) -> pd.DataFrame:
    files = sorted((root / "processed" / bhavcopy.DATASET).glob("*/*.parquet"))
    frames = []
    for f in files:
        d = pd.read_parquet(f, columns=["date", "symbol", "series", "open", "high", "low", "close", "prev_close"])
        frames.append(d[(d["series"] == "EQ") & d["symbol"].isin(names)])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out.drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)


# ------------------------------------------------------------------ one day


def exit_walk(m: np.ndarray, o: np.ndarray, h: np.ndarray, lo: np.ndarray, i: int, entry: float, stop: float,
              target: float | None, intrabar: bool) -> tuple[float, str, int]:
    """Stop before target in a bar; a bar opening through the stop fills at its open; on an intrabar entry the
    entry bar can stop out but not reach the target; otherwise the 15:10 bar's open."""
    for j in range(i, len(m)):
        if m[j] >= EXIT_MIN:
            return float(o[j]), "time", int(m[j])
        if lo[j] <= stop:
            px = stop if (j == i and intrabar) else min(stop, float(o[j]))
            return px, "stop", int(m[j])
        if target is not None and not (j == i and intrabar) and h[j] >= target:
            return target, "target", int(m[j])
    return float(o[-1]), "time_last_bar", int(m[-1])


def replay_day(bars: pd.DataFrame, f: float, symbol: str, today: dict, hist: list[dict],
               p: scan.Params = scan.Params()) -> dict | None:
    """Scan at 09:35, then (if it passes) the buy-stop and each target's exit. Prices are real (vendor x f)."""
    m = bars["minute"].to_numpy()
    o, h, lo, c = (bars[k].to_numpy() * f for k in ("open", "high", "low", "close"))
    pre = m < SCAN_MIN
    if pre.sum() < 15 or m[0] != OPEN_MIN:
        return None
    value_cr = float((bars["close"] * bars["volume"])[pre].sum()) / 1e7   # split adjustment cancels out
    ltp = float(c[pre][-1])
    q = {"symbol": symbol, "series": "EQ", "lastTradedPrice": ltp, "openPrice": float(o[0]),
         "highPrice": float(h[pre].max()), "lowPrice": float(lo[pre].min()), "preClosePrice": today["prev_close"],
         "perChange": (ltp / today["prev_close"] - 1) * 100 if today["prev_close"] else 0.0, "value": value_cr}
    if not scan.quote_screen([q], p):
        return None
    idea, why = scan.plan(q, hist, p)
    if idea is None:
        return None
    money = scan.money_plan(idea, CAPITAL, 100.0, charges_inr=CHARGES_EST, p=p, max_risk_inr=MAX_RISK_INR)
    row = {"date": str(today["date"].date()), "symbol": symbol, "value_cr": value_cr, "entry": idea["entry"],
           "stop": idea["stop"], "risk": idea["entry"] - idea["stop"], "qty": money["qty"],
           "charges_ok": money["charges_ok"], "factor": f}
    after = ~pre
    m2, o2, h2, l2 = m[after], o[after], h[after], lo[after]
    entry, stop = idea["entry"], idea["stop"]
    fill_i = None
    for j in range(len(m2)):
        if m2[j] >= EXIT_MIN:
            break
        if l2[j] <= stop and h2[j] < entry:
            row["outcome"] = "invalidated before entry"
            return row
        if h2[j] >= entry:   # a bar that also reaches the stop fills and then stops out (against the idea)
            fill_i = j
            break
    if fill_i is None:
        row["outcome"] = "not triggered"
        return row
    fill = max(entry, float(o2[fill_i]))
    intrabar = fill != float(o2[fill_i])
    row.update(outcome="triggered", fill=fill, entry_min=int(m2[fill_i]))
    risk = entry - stop
    for t in TARGETS:
        tgt = None if t is None else scan._round_up(entry + t * risk, p.tick)
        px, why, xm = exit_walk(m2, o2, h2, l2, fill_i, fill, stop, tgt, intrabar)
        row[f"{tkey(t)}_exit"], row[f"{tkey(t)}_reason"], row[f"{tkey(t)}_exit_min"] = px, why, xm
    return row


# ------------------------------------------------------------------ per stock


def stock_job(args: tuple) -> tuple[str, list[dict], dict]:
    csv, current, links, official = args
    bars = read_vendor(Path(csv))
    off = official.set_index(["symbol", "date"])
    hist_by_name = {n: g.reset_index(drop=True) for n, g in official.groupby("symbol")}
    rows, counts = [], {"vendor_days": 0, "ok_days": 0}
    for day, g in bars.groupby("date"):
        counts["vendor_days"] += 1
        if len(g) < MIN_BARS:
            continue
        name = name_on(day, current, links)
        if (name, day) not in off.index:
            continue
        t = off.loc[(name, day)]
        f = factor(float(g["high"].max()), float(g["low"].min()), float(t["high"]), float(t["low"]))
        if f is None:
            continue
        counts["ok_days"] += 1
        hist = []
        for n in {name_on(day, current, links), current} | {lk["old_symbol"] for lk in links}:
            hd = hist_by_name.get(n)
            if hd is not None:
                hist.append(hd[hd["date"] < day])
        if not hist:
            continue
        hd = pd.concat(hist).drop_duplicates("date").sort_values("date").tail(20)
        hbars = [{"date": str(r.date.date()), "open": r.open, "high": r.high, "low": r.low, "close": r.close}
                 for r in hd.itertuples()]
        today = {"date": day, "prev_close": float(t["prev_close"])}
        r = replay_day(g, f, current, today, hbars)
        if r is not None:
            rows.append(r)
    return current, rows, counts


# ------------------------------------------------------------------ money and stats


def net_inr(row: dict, t: float | None, cost_mult: float = 1.0, p: scan.Params = scan.Params()) -> float:
    q, fill, px = row["qty"], row["fill"], row[f"{tkey(t)}_exit"]
    charges = scan.round_trip_charges(fill, px, q, p)
    slip = p.slippage_pct_per_side / 100 * (fill + px) * q
    return (px - fill) * q - cost_mult * (charges + slip)


def pick_one_per_day(cands: pd.DataFrame) -> pd.DataFrame:
    """The scan's lead: the most traded passing idea whose charges check passes (order unknown otherwise)."""
    ok = cands[cands["charges_ok"] & (cands["qty"] > 0)]
    return ok.sort_values(["date", "value_cr"], ascending=[True, False]).groupby("date", as_index=False).head(1)


def bootstrap_ci(x: np.ndarray, n: int = 5000, seed: int = 81) -> tuple[float, float]:
    if len(x) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def stats(trades: pd.DataFrame, t: float | None, ci: bool = False) -> dict:
    if trades.empty:
        return {"trades": 0}
    net1 = np.array([net_inr(r, t) for r in trades.to_dict("records")])
    net2 = np.array([net_inr(r, t, 2.0) for r in trades.to_dict("records")])
    gross = np.array([(r[f"{tkey(t)}_exit"] - r["fill"]) * r["qty"] for r in trades.to_dict("records")])
    risk_inr = (trades["risk"] * trades["qty"]).to_numpy()
    eq = np.cumsum(net1)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max())
    wins, losses = net1[net1 > 0].sum(), -net1[net1 < 0].sum()
    reasons = trades[f"{tkey(t)}_reason"].value_counts().to_dict()
    streak = run = 0
    for v in net1:
        run = run + 1 if v < 0 else 0
        streak = max(streak, run)
    out = {"trades": int(len(trades)), "win_rate_net": round(float((net1 > 0).mean()), 3),
           "target_hit_rate": round(reasons.get("target", 0) / len(trades), 3),
           "mean_gross_inr": round(float(gross.mean()), 1), "mean_net_inr": round(float(net1.mean()), 1),
           "mean_net_inr_2x": round(float(net2.mean()), 1), "total_net_inr": round(float(net1.sum()), 0),
           "mean_net_r": round(float((net1 / risk_inr).mean()), 3),
           "profit_factor": round(float(wins / losses), 2) if losses else None,
           "max_drawdown_inr": round(dd, 0), "longest_losing_streak": int(streak),
           "exit_reasons": {k: int(v) for k, v in reasons.items()}}
    if ci:
        out["ci95_mean_net_inr"] = [round(v, 1) for v in bootstrap_ci(net1)]
    return out


def in_split(trades: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    y = pd.to_datetime(trades["date"]).dt.year
    return trades[(y >= years[0]) & (y <= years[1])]


def evaluate(trades: pd.DataFrame) -> dict:
    res = {"splits": {}, "pooled": {}}
    for name, yrs in SPLITS.items():
        sub = in_split(trades, yrs)
        res["splits"][name] = {tkey(t): stats(sub, t) for t in TARGETS}
    res["pooled"] = {tkey(t): stats(trades, t, ci=True) for t in TARGETS}
    dev = res["splits"]["dev 2017-2018"]
    best = max(TARGETS, key=lambda t: dev[tkey(t)].get("mean_net_inr", -1e9))
    consistent = all(
        res["splits"][s][tkey(best)].get("mean_net_inr", -1e9)
        >= max(res["splits"][s][tkey(t)].get("mean_net_inr", -1e9) for t in TARGETS) - 5
        for s in ("validation 2019", "2020 (already seen)"))
    positive = all(res["splits"][s][tkey(best)].get("mean_net_inr_2x", -1) > 0 for s in SPLITS) and \
        res["pooled"][tkey(best)]["ci95_mean_net_inr"][0] > 0
    res["decision"] = {"preferred_target_dev": tkey(best), "consistent_2019_2020": consistent,
                       "rule_positive": positive, "status": "POSITIVE (descriptive only)" if positive else "REJECTED"}
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor-dir", required=True, type=Path)
    ap.add_argument("--official-root", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "reports" / "backtests" / "EXP-0081-orb-scan-replay.json")
    a = ap.parse_args(argv)
    changes = symbols.load_symbol_changes(a.official_root)
    jobs, names = [], set()
    for csv in sorted(a.vendor_dir.glob("*__EQ__NSE__NSE__MINUTE.csv")):
        vendor = csv.name.split("__")[0]
        current = VENDOR_TO_NSE.get(vendor, vendor)
        links = [lk for lk in symbols.predecessors(current, changes)
                 if lk["effective_date"] > pd.Timestamp("2016-10-01")]
        names |= {current} | {lk["old_symbol"] for lk in links}
        jobs.append((str(csv), current, links))
    official = load_official(a.official_root, names)
    rows, coverage = [], {}
    with ProcessPoolExecutor(a.workers) as ex:
        args = [(csv, cur, links, official[official["symbol"].isin({cur} | {lk["old_symbol"] for lk in links})])
                for csv, cur, links in jobs]
        for cur, r, cnt in ex.map(stock_job, args):
            rows += r
            coverage[cur] = cnt
    cands = pd.DataFrame(rows)
    picks = pick_one_per_day(cands)
    trades = picks[picks["outcome"] == "triggered"]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(a.out.with_name(a.out.stem + "-trades.csv"), index=False)
    days = sum(1 for _ in pd.to_datetime(cands["date"]).dt.normalize().unique()) if len(cands) else 0
    res = {"experiment": EXPERIMENT, "spec": "docs/strategy-specifications/intraday-orb-scan.md (replay section)",
           "data": {"vendor": "https://github.com/ShabbirHasan1/NSE-Data (unofficial, GPL-3.0)",
                    "official": "NSE CM bhavcopy (nsearchives.nseindia.com)",
                    "stocks": len(coverage), "vendor_stock_days": sum(c["vendor_days"] for c in coverage.values()),
                    "checked_stock_days": sum(c["ok_days"] for c in coverage.values())},
           "funnel": {"days_with_a_passing_stock": days, "picked_days": int(len(picks)),
                      "picks_by_outcome": picks["outcome"].value_counts().to_dict(),
                      "triggered_trades": int(len(trades)),
                      "mean_qty": round(float(trades["qty"].mean()), 1) if len(trades) else None,
                      "mean_risk_inr": round(float((trades["risk"] * trades["qty"]).mean()), 1) if len(trades) else None},
           **evaluate(trades)}
    a.out.write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(res["decision"], indent=2))
    for t in TARGETS:
        print(tkey(t), {s: res["splits"][s][tkey(t)].get("mean_net_inr") for s in SPLITS},
              res["pooled"][tkey(t)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
