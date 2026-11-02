"""Run EXP-0056..0060 (spec docs/strategy-specifications/nifty-expiry-ideas.md): five fixed expiry-day rules on
every split (no tuning, so each split is an out-of-sample test). Research only; nothing here orders.

    python -m trading_research.backtesting.run_expiry_ideas --fo-root data/fo_session
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.backtesting import run_expiry_reversal as rr
from trading_research.backtesting.run_baseline import REPORT_DIR
from trading_research.config import REPO_ROOT
from trading_research.data import indices, nifty_intraday
from trading_research.strategies import expiry_ideas as ei
from trading_research.strategies import expiry_reversal as er


def verdict(t: pd.DataFrame) -> dict:
    c = rr.dev_checks(t)["checks"] if len(t) else {}
    for s, k in (("validation", "2x"), ("holdout", "1x"), ("holdout", "2x")):
        sm = rr.summary(rr.in_split(t, s))
        c[f"{s} {k} mean R > 0"] = sm["trades"] > 0 and sm[k]["mean_r"] > 0
    return {"checks": c, "status": "PAPER CANDIDATE" if c and all(c.values()) else "REJECTED"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fo-root", type=Path, default=REPO_ROOT / "data")
    a = ap.parse_args(argv)
    bars = nifty_intraday.load()
    cal, _ = rr.expiry_calendar(a.fo_root)
    official = indices.read_index("Nifty 50", date(2018, 12, 1), date(2026, 10, 30))
    official.index = pd.to_datetime(official.index)
    cal = cal[cal["date"] >= pd.Timestamp(rr.SPLITS["dev"][0])]
    status = rr.gate1(bars, list(cal["date"]), official)
    ok = cal[cal["date"].map(status) == "ok"]
    days = list(ok["date"])
    lots = dict(zip(ok["date"], ok["lot"]))
    prev_close = official["close"].shift(1)
    ctx = {d: {"prev_close": prev_close.get(d)} for d in days}
    out = {"generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
           "spec_version": ei.SPEC_VERSION, "expiry_days_used": len(days), "rules": {}}
    for exp, (name, fn) in ei.RULES.items():
        t = rr.trades_for(bars, days, er.BASE, lots, sim=fn, ctx=ctx)
        res = {"rule": name, **verdict(t)}
        for s in ("dev", "dev_a", "dev_b", "validation", "holdout"):
            res[s] = rr.summary(rr.in_split(t, s), ci=True)
        res["all"] = rr.summary(t, ci=True)
        if len(t):
            res["by_year"] = rr.by_group(t, "year")
            res["by_weekday"] = rr.by_group(t, "weekday")
            t.to_csv(REPORT_DIR / f"{exp}-{name}-trades.csv", index=False)
        out["rules"][exp] = res
    (REPORT_DIR / "EXP-0056-0060.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    for exp, r in out["rules"].items():
        al = r["all"]
        print(exp, r["rule"], r["status"], al.get("trades"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
