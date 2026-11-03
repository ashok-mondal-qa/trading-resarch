"""Run EXP-0071/0072 (spec docs/strategy-specifications/nifty-orb30.md v0.1): 30-minute NIFTY ORB grid, selection
on dev, validation, test, walk-forward, instrument feasibility at Rs 300 risk, and the 2026-only volume variants.
Research only; nothing here orders.

    python -m trading_research.backtesting.run_orb30 --src <clone of technovusin/nifty50-historical-data> \
        --official-root data/s30 [--commit 7f94ced]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.backtesting.run_intraday_families import RISK_INR, CAPITAL_INR, rupees, stats
from trading_research.data import indices
from trading_research.data.nifty_intraday import clean, day_check
from trading_research.strategies import orb30 as orb

SLIP = 0.03 / 100
SLIP_GRID = (0.0, 0.03 / 100, 0.05 / 100, 0.10 / 100)
ETF_SCALE = 0.01
LOT_NOW, LOT_MIN = 65, 25
OPTION_DELTA = 0.5
START, END = "2020-01-01", "2026-10-30"
SPLITS = {"dev": ("2020-01-01", "2022-12-31"), "dev_a": ("2020-01-01", "2021-06-30"),
          "dev_b": ("2021-07-01", "2022-12-31"), "validation": ("2023-01-01", "2024-12-31"),
          "test": ("2025-01-01", END)}
WF_TRAIN_MONTHS, WF_TEST_MONTHS = 24, 6
WF_FIRST_TEST = "2022-01-01"
WF_MIN_TRAIN_TRADES = 60
MAX_DD_R = 15.0


# ------------------------------------------------------------------ data


def read_vendor(src: Path) -> tuple[pd.DataFrame, list[dict]]:
    """technovusin 1-min CSVs with Volume kept where present (2026 files only)."""
    frames, hashes = [], []
    for f in sorted((src / "1min").glob("*/*.csv")):
        raw = f.read_bytes()
        hashes.append({"file": str(f.relative_to(src)), "sha256": hashlib.sha256(raw).hexdigest()})
        df = pd.read_csv(f)
        frames.append(pd.DataFrame({"ts": pd.to_datetime(df["Timestamp"]), "open": df["Open"], "high": df["High"],
                                    "low": df["Low"], "close": df["Close"],
                                    "volume": df["Volume"] if "Volume" in df else np.nan}))
    bars = pd.concat(frames, ignore_index=True)
    vol = bars.set_index("ts")["volume"]
    vol = vol[~vol.index.duplicated(keep=False)]
    out = clean(bars.drop(columns="volume"))
    out["volume"] = vol.reindex(out.index)
    return out, hashes


def gate(bars: pd.DataFrame, official: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    key = bars.index.normalize()
    status, keep = {}, []
    for d, day in bars.groupby(key):
        if d in official.index:
            st = day_check(day[["open", "high", "low", "close"]], official.at[d, "high"], official.at[d, "low"],
                           min_bars=360)
        else:
            st = "no official bar"
        status[d] = st
        if st == "ok":
            keep.append(d)
    return bars[key.isin(keep)], pd.Series(status)


def slot_baselines(bars: pd.DataFrame) -> dict:
    """date -> Series(5-min bar end -> mean volume of that slot over the previous 20 sessions), 2026 volume only."""
    vb = bars[bars["volume"].notna()]
    if vb.empty:
        return {}
    mins = vb.index.hour * 60 + vb.index.minute
    end = orb.OPEN_MIN + ((mins - orb.OPEN_MIN) // 5 + 1) * 5
    piv = vb.assign(end=end.values, date=vb.index.normalize()).pivot_table(index="date", columns="end",
                                                                           values="volume", aggfunc="sum")
    base = piv.shift(1).rolling(20, min_periods=20).mean()
    return {d: base.loc[d].dropna() for d in base.index if base.loc[d].notna().any()}


def build_days(bars: pd.DataFrame, ctx: pd.DataFrame) -> list[orb.OrbDay]:
    bases = slot_baselines(bars)
    out = []
    for d, day in bars.groupby(bars.index.normalize()):
        od = orb.build_day(day, ctx.loc[d] if d in ctx.index else None, bases.get(d))
        if od is not None:
            out.append(od)
    return out


# ------------------------------------------------------------------ evaluation helpers


def run_cfg(days: list[orb.OrbDay], cfg: tuple) -> pd.DataFrame:
    rows = [t for d in days if (t := orb.trade(d, *cfg)) is not None]
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    return t.assign(scale=ETF_SCALE, inst="NIFTY")


def money(t: pd.DataFrame, slip: float = SLIP, cap: float | None = None, **kw) -> pd.DataFrame:
    if t.empty:
        return t
    m = rupees(t, slip, cap, **kw)
    m["fut_lot_risk_now"] = m["stop_pts"] * LOT_NOW
    m["fut_lot_risk_min"] = m["stop_pts"] * LOT_MIN
    m["opt_atm_lot_risk"] = m["stop_pts"] * OPTION_DELTA * LOT_NOW
    return m


def window(t: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    if t.empty:
        return t
    d = pd.to_datetime(t["date"])
    return t[(d >= a) & (d <= b)]


def split(t: pd.DataFrame, s: str) -> pd.DataFrame:
    return window(t, *SPLITS[s])


def mean_r(t: pd.DataFrame) -> float:
    return float(t["net_r"].mean()) if len(t) else float("nan")


def max_dd_r(t: pd.DataFrame) -> float:
    """Max drawdown of cumulative net R (trade order)."""
    if t.empty:
        return 0.0
    eq = t.sort_values("date")["net_r"].cumsum()
    return float((eq - eq.cummax().clip(lower=0)).min())


def wf_windows() -> list[tuple[str, str, str, str]]:
    out = []
    start = pd.Timestamp(WF_FIRST_TEST)
    while start <= pd.Timestamp(END):
        tr_a = start - pd.DateOffset(months=WF_TRAIN_MONTHS)
        te_b = min(start + pd.DateOffset(months=WF_TEST_MONTHS) - pd.Timedelta(days=1), pd.Timestamp(END))
        out.append((tr_a.date().isoformat(), (start - pd.Timedelta(days=1)).date().isoformat(),
                    start.date().isoformat(), te_b.date().isoformat()))
        start += pd.DateOffset(months=WF_TEST_MONTHS)
    return out


def walk_forward(base: dict) -> dict:
    """base: cfg -> scenario-A trades. Selects the best eligible config on each training window."""
    eligible = orb.configs(eligible_only=True)
    parts, rows = [], []
    for tr_a, tr_b, te_a, te_b in wf_windows():
        best, best_r = None, -np.inf
        for cfg in eligible:
            tr = window(base[cfg], tr_a, tr_b)
            if len(tr) >= WF_MIN_TRAIN_TRADES and mean_r(tr) > best_r:
                best, best_r = cfg, mean_r(tr)
        te = window(base[best], te_a, te_b) if best else pd.DataFrame()
        rows.append({"train": f"{tr_a}..{tr_b}", "test": f"{te_a}..{te_b}",
                     "selected": orb.cfg_name(best) if best else None, "train_mean_net_r": round(best_r, 3),
                     "test_trades": int(len(te)), "test_mean_net_r": round(mean_r(te), 3) if len(te) else None,
                     "test_pnl_inr": round(float(te["pnl"].sum()), 0) if len(te) else 0})
        if len(te):
            parts.append(te.assign(wf_cfg=orb.cfg_name(best)))
    oos = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    s = stats(oos, ci=True) if len(oos) else {"trades": 0}
    s["max_drawdown_r"] = round(max_dd_r(oos), 2)
    s["windows_positive"] = int(sum(1 for r in rows if (r["test_mean_net_r"] or -1) > 0))
    s["windows"] = len(rows)
    return {"windows": rows, "oos": s, "_trades": oos}


def diagnostics(a: pd.DataFrame, dev_edges: np.ndarray | None = None) -> dict:
    out = {"long": stats(a[a["side"] > 0]), "short": stats(a[a["side"] < 0])}
    reg = np.where(a["adx14"] >= 25, "trending_adx>=25", np.where(a["adx14"] < 20, "sideways_adx<20", "neutral"))
    out["regime_prev_adx14"] = {k: stats(g) for k, g in a.groupby(reg)}
    out["day_type_expost_LOOKAHEAD"] = {("trend_day" if k else "non_trend_day"): stats(g)
                                        for k, g in a.groupby(a["trend_day_expost"])}
    if dev_edges is None:
        dev_edges = np.nanquantile(split(a, "dev")["or_width_atr"], [0.25, 0.5, 0.75])
    q = np.digitize(a["or_width_atr"], dev_edges)
    out["or_width_atr_quartile"] = {f"Q{k + 1}": stats(g) for k, g in a.groupby(q)}
    out["or_width_atr_dev_edges"] = [round(float(x), 3) for x in dev_edges]
    return out


def feasibility(a: pd.DataFrame) -> dict:
    if a.empty:
        return {}
    return {"median_stop_pts": round(float(a["stop_pts"].median()), 1),
            "futures_lot65_median_risk_inr": round(float(a["fut_lot_risk_now"].median()), 0),
            "futures_lot65_share_within_300": round(float((a["fut_lot_risk_now"] <= RISK_INR).mean()), 3),
            "futures_lot25_share_within_300": round(float((a["fut_lot_risk_min"] <= RISK_INR).mean()), 3),
            "atm_option_lot65_median_risk_inr": round(float(a["opt_atm_lot_risk"].median()), 0),
            "atm_option_share_within_300": round(float((a["opt_atm_lot_risk"] <= RISK_INR).mean()), 3),
            "niftybees_median_notional_inr": round(float(a["notional"].median()), 0),
            "niftybees_median_qty": int(a["qty"].median())}


def evaluate_cfg(trades: pd.DataFrame, full: bool = False) -> dict:
    a = money(trades)
    res = {s: stats(split(a, s), ci=s in ("dev", "validation", "test")) for s in SPLITS}
    if not full:
        return res
    st = money(trades.loc[a.index], charge_mult=2.0, slip_mult=2.0, qty=a["qty"])
    res = {"A": res, "A_stress": {s: stats(split(st, s)) for s in SPLITS}}
    b = money(trades, cap=CAPITAL_INR)
    res["B_15k"] = {s: stats(split(b, s)) for s in ("dev", "validation", "test")}
    res["slippage_sensitivity_mean_net_r"] = {
        f"{sg:.2%}": {s: stats(split(money(trades, slip=sg), s)).get("mean_net_r")
                      for s in ("dev", "validation", "test")} for sg in SLIP_GRID}
    res["by_year"] = {str(y): stats(g) for y, g in a.groupby(pd.to_datetime(a["date"]).dt.year)}
    res["diagnostics"] = diagnostics(a)
    res["feasibility"] = feasibility(a)
    return res


def futures_lot_diagnostic(trades: pd.DataFrame, slip: float = 0.01 / 100) -> dict:
    """POST-HOC (not pre-registered, not used for the verdict): the same trades on ONE NIFTY futures lot (65),
    ignoring the Rs 300 rule, to show whether the gross edge survives costs at full-lot size. Groww F&O schedule
    as found by web search 2026-11-03 (unverified): Rs 20/order, STT 0.02% sell, NSE 0.00173%, SEBI 0.0001%,
    stamp 0.002% buy, GST 18% on brokerage + exchange + SEBI; spread + slippage 0.01% per side; spot stands in for
    the futures price (basis ignored)."""
    if trades.empty:
        return {}
    q = LOT_NOW
    e, x, side = trades["entry"].to_numpy(), trades["exit"].to_numpy(), trades["side"].to_numpy()
    buy, sell = np.where(side > 0, e, x) * q, np.where(side > 0, x, e) * q
    exch = (buy + sell) * (0.0000173 + 0.000001)
    charges = 40 + exch + 0.18 * (40 + exch) + 0.0002 * sell + 0.00002 * buy
    slip_inr = slip * (e + x) * q
    risk_inr = trades["stop_pts"].to_numpy() * q
    net = (trades["gross_r"].to_numpy() * risk_inr - charges - slip_inr) / risk_inr
    out = {"label": "POST-HOC diagnostic, one 65-unit futures lot, breaks the Rs 300 rule",
           "median_risk_per_trade_inr": round(float(np.median(risk_inr)), 0),
           "mean_cost_r": round(float(np.mean((charges + slip_inr) / risk_inr)), 3)}
    d = pd.to_datetime(trades["date"])
    for s, (a, b) in SPLITS.items():
        m = ((d >= a) & (d <= b)).to_numpy()
        out[s] = {"trades": int(m.sum()), "mean_net_r": round(float(net[m].mean()), 3) if m.any() else None,
                  "mean_gross_r": round(float(trades["gross_r"].to_numpy()[m].mean()), 3) if m.any() else None}
    return out


def acceptance(sel: dict, wf: dict, feas: dict) -> dict:
    A, S = sel["A"], sel["A_stress"]
    g = lambda d, k="mean_net_r": d.get(k, -1) if d.get(k) is not None else -1  # noqa: E731
    fits = feas.get("futures_lot65_share_within_300", 0) > 0.5 or feas.get("niftybees_median_qty", 0) > 0
    c = {"dev >= 100 trades": A["dev"]["trades"] >= 100,
         "dev mean net R > 0": g(A["dev"]) > 0,
         "dev CI above 0": A["dev"].get("mean_net_r_ci95", [-1])[0] > 0,
         "dev PF >= 1.15": (A["dev"].get("profit_factor") or 0) >= 1.15,
         "dev halves > 0": g(A["dev_a"]) > 0 and g(A["dev_b"]) > 0,
         "dev stress > 0": g(S["dev"]) > 0,
         "validation > 0": g(A["validation"]) > 0,
         "validation stress > 0": g(S["validation"]) > 0,
         "test > 0": g(A["test"]) > 0,
         "walk-forward OOS > 0": g(wf["oos"]) > 0,
         "walk-forward CI above 0": wf["oos"].get("mean_net_r_ci95", [-1])[0] > 0,
         "walk-forward >= 6/10 windows positive": wf["oos"]["windows_positive"] >= 6,
         "walk-forward max DD <= 15R": wf["oos"]["max_drawdown_r"] >= -MAX_DD_R,
         "instrument fits Rs300 (NIFTYBEES)": bool(fits)}
    return {"checks": c, "status": "PAPER CANDIDATE" if all(c.values()) else "REJECTED"}


def volume_diagnostic(days: list[orb.OrbDay]) -> dict:
    """EXP-0072: V0/V1/V2(true VWAP via V3 logic)/V3 on 2026 days that have a 20-session volume baseline."""
    vdays = [d for d in days if d.date.year == 2026 and d.vwap == d.vwap and d.rvol == d.rvol]
    first = min((d.date for d in vdays), default=None)
    pool = [d for d in days if first is not None and d.date >= first]
    out = {"first_day": str(first.date()) if first is not None else None, "sessions": len(pool),
           "signal_days_with_volume": len(vdays)}
    for v in ("V0", "V1", "V3"):
        for st in orb.STOPS:
            for tg in (2.0, 3.0):
                t = run_cfg(pool, (v, st, tg, "both"))
                out[f"{v}|{st}|{tg:g}R|both"] = stats(money(t)) if len(t) else {"trades": 0}
    return out


# ------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--official-root", required=True, type=Path)
    ap.add_argument("--commit", default="unknown")
    a = ap.parse_args(argv)
    bars, hashes = read_vendor(a.src)
    bars = bars[(bars.index >= START) & (bars.index < pd.Timestamp(END) + pd.Timedelta(days=1))]
    official = indices.read_index("Nifty 50", date(2019, 6, 1), date.fromisoformat(END), a.official_root)
    official = official[~official.index.duplicated()]
    official.index = pd.to_datetime(official.index)
    ok_bars, status = gate(bars, official)
    ctx = orb.daily_context(official)
    days = build_days(ok_bars, ctx)

    base = {cfg: run_cfg(days, cfg) for cfg in orb.configs()}
    base_a = {cfg: money(t) for cfg, t in base.items()}
    table = []
    for cfg, t in base.items():
        r = evaluate_cfg(t)
        row = {"config": orb.cfg_name(cfg), "eligible": cfg[2] >= 2.0}
        for s in ("dev", "dev_a", "dev_b", "validation", "test"):
            row[f"{s}_trades"] = r[s]["trades"]
            row[f"{s}_mean_net_r"] = r[s].get("mean_net_r")
            row[f"{s}_gross_r"] = r[s].get("mean_gross_r")
            row[f"{s}_pf"] = r[s].get("profit_factor")
            row[f"{s}_win"] = r[s].get("win_rate")
        row["dev_ci95"] = r["dev"].get("mean_net_r_ci95")
        table.append(row)
    table = pd.DataFrame(table)
    table.to_csv(REPORT_DIR / "EXP-0071-grid.csv", index=False)

    elig = table[table["eligible"] & (table["dev_trades"] >= 100)].sort_values("dev_mean_net_r", ascending=False)
    sel_name = elig.iloc[0]["config"]
    sel_cfg = next(c for c in orb.configs() if orb.cfg_name(c) == sel_name)
    std_cfg = ("V0", "range", 2.0, "both")
    sel = evaluate_cfg(base[sel_cfg], full=True)
    std = evaluate_cfg(base[std_cfg], full=True)
    wf = walk_forward(base_a)
    wf_trades = wf.pop("_trades")
    verdict = acceptance(sel, wf, sel["feasibility"])
    money(base[sel_cfg]).to_csv(REPORT_DIR / "EXP-0071-selected-trades.csv", index=False)
    if len(wf_trades):
        wf_trades.to_csv(REPORT_DIR / "EXP-0071-walkforward-trades.csv", index=False)

    vc = status.value_counts()
    result = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "spec_version": orb.SPEC_VERSION, "risk_inr": RISK_INR, "slippage_per_side": SLIP,
        "data": {"vendor": "technovusin/nifty50-historical-data (UNOFFICIAL)", "commit": a.commit,
                 "files": len(hashes), "files_sha256": hashlib.sha256(json.dumps(hashes).encode()).hexdigest(),
                 "vendor_days": int(len(status)), "days_passed_gate": int(vc.get("ok", 0)),
                 "gate_fail_reasons": status[status != "ok"].str.split(" ").str[0].value_counts().to_dict(),
                 "days_with_opening_range": len(days), "breakout_days": int(sum(d.side != 0 for d in days))},
        "selection": {"rule": "highest dev mean net R among eligible (target >= 2R) configs with >= 100 dev trades",
                      "selected": sel_name, "top5_dev": elig.head(5)[["config", "dev_trades", "dev_mean_net_r",
                                                                       "validation_mean_net_r",
                                                                       "test_mean_net_r"]].to_dict("records"),
                      "eligible_configs_with_dev_mean_net_r_gt_0": int((elig["dev_mean_net_r"] > 0).sum()),
                      "eligible_configs": int(len(elig))},
        "selected": sel, "standard_orb_V0_range_2R_both": std, "walk_forward": wf, "verdict_EXP_0071": verdict,
        "EXP_0072_volume_2026": volume_diagnostic(days),
        "posthoc_futures_lot": {orb.cfg_name(c): futures_lot_diagnostic(base[c]) for c in
                                (sel_cfg, std_cfg, ("V0", "range", 3.0, "short"), ("V0", "range", 2.0, "short"))},
    }
    (REPORT_DIR / "EXP-0071-0072.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps({"selected": sel_name, "verdict": verdict, "wf_oos": wf["oos"],
                      "sel_A": {s: (sel["A"][s]["trades"], sel["A"][s].get("mean_net_r")) for s in SPLITS},
                      "data": result["data"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
