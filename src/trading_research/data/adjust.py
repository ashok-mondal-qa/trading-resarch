"""Split/bonus price adjustment for one symbol, with checks against the raw prices.

Method (price-only, backward): every bar before an ex-date is multiplied by that event's factor
(bonus 1:1 -> 0.5); volume is divided by it. Several events on one ex-date multiply (e.g. bonus 4:1 plus
split 2:1 -> 0.2 * 0.5 = 0.1). Ordinary dividends are NOT adjusted. Raw prices are kept beside the
adjusted ones because simulated fills use raw prices (docs/data-sources.md).

Checks (errors make the earlier part of the series unusable, never "fixed" by guessing):
  * factor vs prices: open on the ex-date / previous close must be within 25% of the factor;
  * unexplained jump: an adjusted close-to-close move above 35% with no event on that date;
  * price-changing events the source gives no usable factor for (demerger, rights, ...).
The series is usable from `valid_from` (the first bar after the last error). No usable bars ->
status DATA INSUFFICIENT.

CLI:  python -m trading_research.data.adjust --symbols RELIANCE,HDFCBANK --start 2021-10-25 --end 2026-10-22
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import bhavcopy, corporate_actions, symbols as symbol_changes

ADJUSTER_VERSION = "0.1.0"
FACTOR_TOLERANCE = 0.25
JUMP_THRESHOLD = 0.35
PRICES = ["open", "high", "low", "close"]


def price_events(actions: pd.DataFrame) -> pd.DataFrame:
    """Combine actions with a factor other than 1 into one factor per ex-date."""
    usable = actions[(actions["factor"] > 0) & (actions["factor"] != 1.0)]
    combined = usable.groupby("ex_date").agg(
        factor=("factor", "prod"), purposes=("purpose", lambda p: " + ".join(p))).reset_index()
    return combined.sort_values("ex_date").reset_index(drop=True)


def adjust_prices(bars: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Add adj_factor, adj_open/high/low/close and adj_volume to one symbol's raw bars."""
    out = bars.sort_values("date").reset_index(drop=True).copy()
    cumulative = pd.Series(1.0, index=out.index)
    for event in price_events(actions).itertuples():
        cumulative[out["date"] < event.ex_date] *= event.factor
    out["adj_factor"] = cumulative
    for col in PRICES:
        out[f"adj_{col}"] = out[col] * cumulative
    out["adj_volume"] = out["volume"].astype(float) / cumulative
    return out


def verify_adjustment(adjusted: pd.DataFrame, actions: pd.DataFrame) -> list[dict]:
    issues: list[dict] = []
    if adjusted.empty:
        return issues
    first, last = adjusted["date"].iloc[0], adjusted["date"].iloc[-1]
    events = price_events(actions)
    event_bar_dates = set()

    for event in events.itertuples():
        if not first < event.ex_date <= last:
            continue
        after = adjusted[adjusted["date"] >= event.ex_date]
        before = adjusted[adjusted["date"] < event.ex_date]
        ex_bar, prev_bar = after.iloc[0], before.iloc[-1]
        event_bar_dates.add(ex_bar["date"])
        ratio = ex_bar["open"] / prev_bar["close"]
        if abs(ratio / event.factor - 1) > FACTOR_TOLERANCE:
            issues.append({"date": ex_bar["date"].date().isoformat(), "severity": "error",
                           "kind": "factor inconsistent with prices",
                           "detail": f"{event.purposes}: factor {event.factor:g}, raw open/prev close {ratio:.4f}"})

    for action in actions.itertuples():
        text = action.purpose.lower()
        if action.factor == 1.0 and first < action.ex_date <= last and any(
                key in text for key in corporate_actions.UNADJUSTED_PRICE_EVENTS):
            issues.append({"date": action.ex_date.date().isoformat(), "severity": "error",
                           "kind": "price-changing event not adjusted",
                           "detail": f"{action.purpose} (source factor 1.0)"})
            after = adjusted[adjusted["date"] >= action.ex_date]
            if not after.empty:
                event_bar_dates.add(after["date"].iloc[0])

    returns = adjusted["adj_close"].pct_change()
    for idx in returns.index[returns.abs() > JUMP_THRESHOLD]:
        if adjusted.at[idx, "date"] in event_bar_dates:
            continue
        issues.append({"date": adjusted.at[idx, "date"].date().isoformat(), "severity": "error",
                       "kind": "unexplained jump",
                       "detail": f"adjusted close-to-close move {returns[idx]:+.1%} with no corporate action"})
    return sorted(issues, key=lambda i: i["date"])


@dataclass
class AdjustedSeries:
    bars: pd.DataFrame
    manifest: dict


def build_adjusted(symbol: str, bars: pd.DataFrame, record: dict,
                   symbol_links: list[dict] | None = None) -> AdjustedSeries:
    actions = corporate_actions.actions_frame(record)
    adjusted = adjust_prices(bars, actions)
    issues = verify_adjustment(adjusted, actions)
    errors = [i for i in issues if i["severity"] == "error"]
    valid_from = adjusted["date"].iloc[0] if not adjusted.empty else None
    if errors:
        last_error = pd.Timestamp(max(i["date"] for i in errors))
        later = adjusted[adjusted["date"] > last_error]
        valid_from = later["date"].iloc[0] if not later.empty else None
    if valid_from is None:
        status = "DATA INSUFFICIENT"
    else:
        status = "partial" if errors else "ok"
    adjusted["usable"] = adjusted["date"] >= valid_from if valid_from is not None else False
    events = price_events(actions)
    manifest = {
        "symbol": symbol,
        "adjuster_version": ADJUSTER_VERSION,
        "status": status,
        "method": "backward price-only adjustment for splits/bonuses; dividends not adjusted",
        "raw_source": f"{bhavcopy.DATASET} (series EQ), see data/manifests/{bhavcopy.DATASET}/",
        "actions_source": record.get("source"),
        "actions_retrieved_at_utc": record.get("retrieved_at_utc"),
        "first_bar": adjusted["date"].iloc[0].date().isoformat() if not adjusted.empty else None,
        "last_bar": adjusted["date"].iloc[-1].date().isoformat() if not adjusted.empty else None,
        "bars": int(len(adjusted)),
        "symbol_links": symbol_links or [],
        "valid_from": valid_from.date().isoformat() if valid_from is not None else None,
        "price_events_applied": [
            {"ex_date": e.ex_date.date().isoformat(), "factor": e.factor, "purpose": e.purposes}
            for e in events.itertuples()],
        "issues": issues,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    return AdjustedSeries(adjusted, manifest)


def merge_action_records(records: list[dict]) -> dict:
    """One action record across a company's tickers; the same ex-date + purpose counts once."""
    merged, seen = dict(records[0]), set()
    merged["actions"] = []
    for rec in records:
        for action in rec.get("actions", []):
            key = (action.get("exDate"), action.get("purpose"))
            if key not in seen:
                seen.add(key)
                merged["actions"].append(action)
    merged["symbols"] = [r.get("symbol") for r in records]
    return merged


def prefetch_actions(symbols: list[str], start: date, end: date, root: Path, workers: int) -> list[str]:
    """Fetch (and cache) corporate actions for many tickers in parallel. Returns tickers that failed."""
    from concurrent.futures import ThreadPoolExecutor

    def one(ticker: str) -> str | None:
        try:
            corporate_actions.load_actions(ticker, start, end, root)
            return None
        except Exception as exc:  # recorded and reported; the symbol is then adjusted from cache only
            return f"{ticker}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [r for r in pool.map(one, symbols) if r]


def run(symbols: list[str], start: date, end: date, root: Path = REPO_ROOT / "data",
        workers: int = 1) -> list[dict]:
    store = bhavcopy.Store(root=root)
    raw = bhavcopy.read_bars(start, end, store, series=("EQ",))
    if not symbol_changes.raw_path(root).exists():
        symbol_changes.refresh_symbol_changes(root)
    changes = symbol_changes.load_symbol_changes(root)
    if workers > 1:
        tickers = set(symbols)
        for symbol in symbols:
            tickers.update(l["old_symbol"] for l in symbol_changes.predecessors(symbol, changes))
        failed = prefetch_actions(sorted(tickers), start, end, root, workers)
        if failed:
            print(f"corporate actions failed for {len(failed)} tickers, e.g. {failed[:3]}")
    raw = raw.sort_values(["symbol", "date"])
    by_symbol = {s: g for s, g in raw.groupby("symbol")}
    manifests = []
    for symbol in symbols:
        related = [symbol] + [l["old_symbol"] for l in symbol_changes.predecessors(symbol, changes)]
        subset = pd.concat([by_symbol[t] for t in related if t in by_symbol] or [raw.iloc[:0]])
        history = symbol_changes.join_history(symbol, subset, changes, calendar_start=raw["date"].min())
        tickers = [symbol] + [l["old_symbol"] for l in history.links if l["status"] == "confirmed"]
        try:
            record = merge_action_records(
                [corporate_actions.load_actions(t, start, end, root) for t in tickers])
        except Exception as exc:
            manifests.append({"symbol": symbol, "status": "DATA INSUFFICIENT", "bars": 0,
                              "valid_from": None, "price_events_applied": [], "symbol_links": [],
                              "issues": [{"date": None, "severity": "error",
                                          "kind": "corporate actions unavailable", "detail": str(exc)}]})
            continue
        result = build_adjusted(symbol, history.bars, record, history.links)
        out = root / "processed" / "adjusted" / f"{symbol}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        result.bars.to_parquet(out, index=False)
        path = root / "manifests" / "adjusted" / f"{symbol}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.manifest, indent=2) + "\n", encoding="utf-8")
        manifests.append(result.manifest)
    return manifests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Split/bonus adjustment with price checks")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.symbols.startswith("@"):
        symbols = Path(args.symbols[1:]).read_text().split()
    else:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    results = run(symbols, args.start, args.end, workers=args.workers)
    if args.quiet:
        from collections import Counter
        print(Counter(m["status"] for m in results))
        return 0
    for m in results:
        print(f"{m['symbol']:<12} {m['status']:<17} bars={m['bars']:<5} valid_from={m['valid_from']} "
              f"events={len(m['price_events_applied'])} issues={len(m['issues'])}")
        for link in m["symbol_links"]:
            print(f"    rename {link['old_symbol']} -> {link['new_symbol']} {link['effective_date']}: "
                  f"{link['status']} {link.get('reason', '')}")
        for issue in m["issues"]:
            print(f"    {issue['date']} {issue['kind']}: {issue['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
