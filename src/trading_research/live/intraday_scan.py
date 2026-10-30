"""Morning opening-range scan on live NSE quotes (EXP-0052, forward paper test only).

Spec: docs/strategy-specifications/intraday-orb-scan.md. Runs once at about 09:35 IST. It reads the
NSE `cm-market` MCP (quotes 1-3 minutes behind real time) and the `nse-bhavcopy` MCP (daily history), and
writes at most two WATCHLIST ideas: buy above the opening-range high, stop below the opening-range low,
target 1.5R, exit by 15:10 IST. It never places orders. `score` grades a past day's ideas from that day's
EOD bar, resolving every ambiguity against the idea.

    python -m trading_research.live.intraday_scan scan --out-dir <dir> [--capital 17600]
    python -m trading_research.live.intraday_scan score --day 2026-11-02 --out-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import math
import string
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from trading_research.data import nse_mcp
from trading_research.data.nse_mcp import BHAVCOPY_URL, CM_MARKET_URL, McpError, Transport, http_transport

IST = timezone(timedelta(hours=5, minutes=30))
EXPERIMENT = "EXP-0052"
VERSION = "0.1"


@dataclass(frozen=True)
class Params:
    min_value_cr: float = 10.0          # traded value so far today, Rs crore
    min_price: float = 100.0
    min_change_pct: float = 0.5
    max_change_pct: float = 4.0
    max_gap_pct: float = 2.5
    max_below_high_pct: float = 0.6     # LTP within this % of the day high
    min_risk_atr: float = 0.15          # entry - stop, in ATR14 units
    max_risk_atr: float = 0.5
    target_r: float = 1.5
    tick: float = 0.05
    entry_buffer_pct: float = 0.05      # buy-stop this % above the opening-range high
    max_ideas: int = 2                  # config/settings.yaml max_new_candidates_per_day
    max_quote_age_min: float = 15.0
    risk_pct: float = 0.5               # of capital, config/settings.yaml max_risk_per_position_pct
    # Intraday (MIS) cash charges, unverified placeholders; see the spec.
    brokerage_pct: float = 0.03
    brokerage_cap_inr: float = 20.0
    stt_sell_pct: float = 0.025
    exchange_pct: float = 0.00297
    sebi_pct: float = 0.0001
    stamp_buy_pct: float = 0.003
    gst_pct: float = 18.0
    slippage_pct_per_side: float = 0.05


def _round_up(x: float, tick: float) -> float:
    return round(math.ceil(round(x / tick, 6)) * tick, 2)


def _round_down(x: float, tick: float) -> float:
    return round(math.floor(round(x / tick, 6)) * tick, 2)


def is_fund(symbol: str) -> bool:
    return "BEES" in symbol or "ETF" in symbol


def fetch_quotes(transport: Transport = http_transport) -> list[dict]:
    """Every NSE CM equity quote. The tool returns at most 500 per prefix, so full prefixes are split."""
    seen: dict[str, dict] = {}
    queue = list(string.ascii_uppercase + string.digits)
    while queue:
        prefix = queue.pop(0)
        reply = json.loads(nse_mcp.call_tool(CM_MARKET_URL, "cm_get_equity_stocks",
                                             {"limit": 500, "symbolFilter": prefix}, transport))
        if "error" in reply:
            raise McpError(f"cm_get_equity_stocks {prefix}: {reply['error']}")
        if reply.get("returned", 0) >= 500:
            queue += [prefix + c for c in string.ascii_uppercase + string.digits + "-&"]
            continue
        for s in reply.get("stocks", []):
            seen[s["symbol"]] = s
    return list(seen.values())


def fetch_daily(symbol: str, end: date, transport: Transport = http_transport, attempts: int = 6,
                pause_s: float = 1.0) -> list[dict]:
    """Daily bars up to `end` (unadjusted), oldest first. Tool errors are retried, never read as no data."""
    last = ""
    for attempt in range(attempts):
        reply = json.loads(nse_mcp.call_tool(BHAVCOPY_URL, "get_stock_history",
                                             {"symbol": symbol, "months": 2, "endDate": end.isoformat()}, transport))
        if "error" not in reply:
            return sorted(reply.get("data", []), key=lambda b: b["date"])
        last = reply["error"]
        if attempt + 1 < attempts and pause_s:
            time.sleep(pause_s)
    raise McpError(f"get_stock_history {symbol} {end}: {last}")


def atr14(bars: list[dict]) -> float | None:
    if len(bars) < 15:
        return None
    tr = [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"]))
          for p, b in zip(bars[:-1], bars[1:])]
    return sum(tr[-14:]) / 14


def breadth(quotes: list[dict], min_value_cr: float) -> dict:
    eq = [q for q in quotes if q.get("series") == "EQ" and q.get("volume", 0) > 0]
    liquid = [q for q in eq if q.get("value", 0) >= min_value_cr]
    return {"traded": len(eq), "advancing": sum(q["perChange"] > 0 for q in eq),
            "liquid": len(liquid), "liquid_advancing": sum(q["perChange"] > 0 for q in liquid)}


def quote_screen(quotes: list[dict], p: Params = Params()) -> list[dict]:
    """Quote-only filters, most traded first."""
    out = []
    for q in quotes:
        if q.get("series") != "EQ" or is_fund(q["symbol"]):
            continue
        ltp, o, h, pc = q["lastTradedPrice"], q["openPrice"], q["highPrice"], q["preClosePrice"]
        if not (ltp and o and h and pc) or q.get("value", 0) < p.min_value_cr or ltp < p.min_price:
            continue
        if not p.min_change_pct <= q["perChange"] <= p.max_change_pct:
            continue
        if (o / pc - 1) * 100 >= p.max_gap_pct or ltp < o or (h / ltp - 1) * 100 > p.max_below_high_pct:
            continue
        out.append(q)
    return sorted(out, key=lambda q: -q["value"])


def plan(q: dict, bars: list[dict], p: Params = Params()) -> tuple[dict | None, str]:
    """Levels for one screened quote, or (None, reason). `bars` must end at the previous session."""
    if not bars:
        return None, "no daily history"
    prev = bars[-1]
    if abs(prev["close"] - q["preClosePrice"]) > 0.011:
        return None, f"history close {prev['close']} != live previous close {q['preClosePrice']}"
    atr = atr14(bars)
    if atr is None or atr <= 0:
        return None, "fewer than 15 daily bars"
    if q["lastTradedPrice"] <= prev["high"]:
        return None, "not above the previous day's high"
    entry = _round_up(q["highPrice"] * (1 + p.entry_buffer_pct / 100), p.tick)
    stop = _round_down(q["lowPrice"] - p.tick, p.tick)
    risk = entry - stop
    if not p.min_risk_atr * atr <= risk <= p.max_risk_atr * atr:
        return None, f"opening range risk {risk / atr:.2f} ATR outside {p.min_risk_atr}-{p.max_risk_atr}"
    target = _round_up(entry + p.target_r * risk, p.tick)
    return {"symbol": q["symbol"], "ltp": q["lastTradedPrice"], "or_high": q["highPrice"],
            "or_low": q["lowPrice"], "prev_close": q["preClosePrice"], "prev_high": prev["high"],
            "prev_date": prev["date"], "atr14": round(atr, 2), "value_cr": round(q["value"], 1),
            "change_pct": q["perChange"], "entry": entry, "stop": stop, "target": target,
            "risk_per_share": round(risk, 2), "quote_time": q.get("latestTimestamp")}, "ok"


def quantity(entry: float, stop: float, capital: float, p: Params = Params()) -> int:
    """Shares for `risk_pct` of capital, never more than the cash covers (no leverage)."""
    by_risk = math.floor(capital * p.risk_pct / 100 / (entry - stop))
    return max(0, min(by_risk, math.floor(capital / entry)))


def quote_age_ok(quotes: list[dict], now: datetime, p: Params = Params()) -> tuple[bool, str]:
    stamps = [q.get("latestTimestamp") for q in quotes if q.get("latestTimestamp")]
    if not stamps:
        return False, "no quote timestamps"
    newest = datetime.strptime(max(stamps), "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
    age = (now - newest).total_seconds() / 60
    if newest.date() != now.astimezone(IST).date() or age > p.max_quote_age_min:
        return False, f"newest quote {newest:%Y-%m-%d %H:%M} IST is stale (market closed or feed down)"
    return True, f"newest quote {newest:%H:%M:%S} IST"


def scan(now: datetime, transport: Transport = http_transport, p: Params = Params(),
         capital: float | None = None) -> dict:
    quotes = fetch_quotes(transport)
    fresh, why = quote_age_ok(quotes, now, p)
    result = {"experiment": EXPERIMENT, "version": VERSION, "run_at": now.astimezone(IST).isoformat(),
              "data": why, "sources": [f"{CM_MARKET_URL} cm_get_equity_stocks", f"{BHAVCOPY_URL} get_stock_history"],
              "ideas": [], "rejected": []}
    if not fresh:
        result["status"] = "DATA INSUFFICIENT"
        return result
    result["breadth"] = breadth(quotes, p.min_value_cr)
    prev_day = now.astimezone(IST).date() - timedelta(days=1)
    for q in quote_screen(quotes, p):
        if len(result["ideas"]) >= p.max_ideas:
            break
        try:
            idea, reason = plan(q, fetch_daily(q["symbol"], prev_day, transport), p)
        except McpError as exc:
            idea, reason = None, f"DATA INSUFFICIENT: {exc}"
        if idea is None:
            result["rejected"].append({"symbol": q["symbol"], "reason": reason})
            continue
        if capital:
            idea["qty"] = quantity(idea["entry"], idea["stop"], capital, p)
            idea["capital"] = capital
        result["ideas"].append(idea)
    result["status"] = "WATCHLIST" if result["ideas"] else "NO TRADE"
    return result


def cost_r(entry: float, exit_: float, risk: float, p: Params = Params()) -> float:
    """Round-trip charges plus slippage for one share, in R."""
    turnover = entry + exit_
    brokerage = min(p.brokerage_pct / 100 * entry, p.brokerage_cap_inr) + \
        min(p.brokerage_pct / 100 * exit_, p.brokerage_cap_inr)
    fees = (p.exchange_pct + p.sebi_pct) / 100 * turnover
    rupees = (brokerage + fees) * (1 + p.gst_pct / 100) + p.stt_sell_pct / 100 * exit_ + \
        p.stamp_buy_pct / 100 * entry + p.slippage_pct_per_side / 100 * turnover
    return rupees / risk


def grade(idea: dict, bar: dict, p: Params = Params(), cost_mult: float = 1.0) -> dict:
    """Outcome from the day's EOD bar. Stop beats target when both were touched; close stands in for 15:10."""
    entry, stop, target = idea["entry"], idea["stop"], idea["target"]
    risk = entry - stop
    if bar["high"] < entry:
        return {"symbol": idea["symbol"], "outcome": "not triggered", "r": 0.0}
    if bar["low"] <= stop:
        outcome, exit_ = "stop", stop
    elif bar["high"] >= target:
        outcome, exit_ = "target", target
    else:
        outcome, exit_ = "time exit (close)", bar["close"]
    gross = (exit_ - entry) / risk
    return {"symbol": idea["symbol"], "outcome": outcome, "exit": exit_, "gross_r": round(gross, 3),
            "r": round(gross - cost_mult * cost_r(entry, exit_, risk, p), 3)}


def score(day: date, ideas: dict, transport: Transport = http_transport) -> dict:
    graded = []
    for idea in ideas.get("ideas", []):
        try:
            bars = [b for b in fetch_daily(idea["symbol"], day, transport) if b["date"] == day.isoformat()]
        except McpError as exc:
            graded.append({"symbol": idea["symbol"], "outcome": f"DATA INSUFFICIENT: {exc}"})
            continue
        if not bars:
            graded.append({"symbol": idea["symbol"], "outcome": "DATA INSUFFICIENT: no EOD bar yet"})
            continue
        g = grade(idea, bars[0])
        g["r_2x_costs"] = grade(idea, bars[0], cost_mult=2.0)["r"]
        g["bar"] = {k: bars[0][k] for k in ("open", "high", "low", "close")}
        graded.append(g)
    return {"experiment": EXPERIMENT, "day": day.isoformat(), "graded": graded}


def render(result: dict) -> str:
    lines = [f"# Opening-range scan {result['run_at'][:10]} ({EXPERIMENT} v{VERSION}, paper only)", "",
             f"**Status: {result['status']}.** Untested forward experiment; not a recommendation.", "",
             f"- Data: {result['data']}. Sources: {'; '.join(result['sources'])}."]
    if "breadth" in result:
        b = result["breadth"]
        lines.append(f"- Breadth (calculated): {b['advancing']}/{b['traded']} traded EQ stocks up; "
                     f"{b['liquid_advancing']}/{b['liquid']} liquid ones up.")
    if result["ideas"]:
        lines += ["", "| Stock | LTP | Opening range | Buy above | Stop | Target 1.5R | Risk/share | Qty |",
                  "|---|---|---|---|---|---|---|---|"]
        for i in result["ideas"]:
            lines.append(f"| {i['symbol']} | {i['ltp']} | {i['or_low']}-{i['or_high']} | {i['entry']} | {i['stop']} | "
                         f"{i['target']} | {i['risk_per_share']} | {i.get('qty', '-')} |")
        lines += ["", "Exit by 15:10 IST if neither level is hit. No entry if the price never trades above the buy level."]
    if result["rejected"]:
        lines += ["", "Screened out after history check: " +
                  "; ".join(f"{r['symbol']} ({r['reason']})" for r in result["rejected"])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--out-dir", type=Path, required=True)
    s.add_argument("--capital", type=float)
    g = sub.add_parser("score")
    g.add_argument("--day", type=date.fromisoformat, required=True)
    g.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.cmd == "scan":
        now = datetime.now(timezone.utc)
        result = scan(now, capital=a.capital)
        stem = a.out_dir / now.astimezone(IST).date().isoformat()
        stem.with_suffix(".json").write_text(json.dumps(result, indent=2))
        stem.with_suffix(".md").write_text(render(result))
        print(render(result))
    else:
        ideas = json.loads((a.out_dir / f"{a.day.isoformat()}.json").read_text())
        out = score(a.day, ideas)
        (a.out_dir / f"{a.day.isoformat()}.score.json").write_text(json.dumps(out, indent=2))
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
