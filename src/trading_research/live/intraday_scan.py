"""Morning opening-range scan on live NSE quotes (EXP-0053 = v0.2, forward test; never places orders).

Spec: docs/strategy-specifications/intraday-orb-scan.md. Runs once at about 09:35 IST. It reads the
NSE `cm-market` MCP (quotes 1-3 minutes behind real time) and the `nse-bhavcopy` MCP (daily history), and
picks at most ONE lead idea a day (others that pass are listed as WATCH): buy above the opening-range
high, stop below the opening-range low, target 2R, exit by 15:10 IST. NSE cash only. `score` grades a past day's ideas from that day's
EOD bar, resolving every ambiguity against the idea.

    python -m trading_research.live.intraday_scan scan --out-dir <dir> [--capital 15000 --risk-pct 1]
    python -m trading_research.live.intraday_scan status --out-dir <dir>      # live WATCH/APPROACHING/...
    python -m trading_research.live.intraday_scan score --day 2026-11-02 --out-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import math
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from trading_research.data import nse_mcp
from trading_research.data.nse_mcp import BHAVCOPY_URL, CM_MARKET_URL, McpError, Transport, http_transport

IST = timezone(timedelta(hours=5, minutes=30))
EXPERIMENT = "EXP-0053"        # v0.1 (1.5R target, 2 ideas) was EXP-0052
VERSION = "0.2"


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
    target_r: float = 2.0
    tick: float = 0.05
    entry_buffer_pct: float = 0.05      # buy-stop this % above the opening-range high
    max_ideas: int = 1                  # owner's brief: at most one opportunity a day
    approaching_pct: float = 0.25       # LTP within this % below the buy level
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


def _call_with_retries(url: str, name: str, args: dict, transport: Transport, rounds: int = 5,
                       pause_s: float = 2.0) -> str:
    """call_tool, retried in rounds: the load balancer can lose sessions several times in a row."""
    for attempt in range(rounds):
        try:
            return nse_mcp.call_tool(url, name, args, transport)
        except (McpError, OSError):        # OSError covers timeouts and dropped connections
            if attempt + 1 == rounds:
                raise
            time.sleep(pause_s)
    raise AssertionError("unreachable")


def fetch_quotes(transport: Transport = http_transport) -> list[dict]:
    """Every NSE CM equity quote. The tool returns at most 500 per prefix, so full prefixes are split."""
    seen: dict[str, dict] = {}
    queue = list(string.ascii_uppercase + string.digits)
    while queue:
        prefix = queue.pop(0)
        reply = json.loads(_call_with_retries(CM_MARKET_URL, "cm_get_equity_stocks",
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


def quantity(entry: float, stop: float, capital: float, p: Params = Params(), risk_pct: float | None = None) -> int:
    """Shares for `risk_pct` of capital, never more than the cash covers (no leverage)."""
    by_risk = math.floor(capital * (p.risk_pct if risk_pct is None else risk_pct) / 100 / (entry - stop))
    return max(0, min(by_risk, math.floor(capital / entry)))


def round_trip_charges(entry: float, exit_: float, qty: int, p: Params = Params()) -> float:
    """Rupee charges for one buy and one sell order of `qty` shares (brokerage capped per order)."""
    buy, sell = entry * qty, exit_ * qty
    brokerage = min(p.brokerage_pct / 100 * buy, p.brokerage_cap_inr) + min(p.brokerage_pct / 100 * sell,
                                                                            p.brokerage_cap_inr)
    fees = (p.exchange_pct + p.sebi_pct) / 100 * (buy + sell)
    return (brokerage + fees) * (1 + p.gst_pct / 100) + p.stt_sell_pct / 100 * sell + p.stamp_buy_pct / 100 * buy


def money_plan(idea: dict, capital: float, risk_pct: float, charges_inr: float | None = None,
               p: Params = Params(), min_reward_to_charges: float = 4.0, max_risk_inr: float | None = None) -> dict:
    """Size one idea for a real cash account and check that charges leave room for profit.

    The charges check passes only if the profit at target is at least `min_reward_to_charges` times the
    round-trip charges (the owner's own broker estimate when given, else the placeholder schedule)."""
    if max_risk_inr is not None:                 # a fixed rupee cap: risk never grows with profits
        risk_pct = min(risk_pct, max_risk_inr / capital * 100)
    qty = quantity(idea["entry"], idea["stop"], capital, p, risk_pct)
    charges = charges_inr if charges_inr is not None else round_trip_charges(idea["entry"], idea["target"], qty, p)
    reward = (idea["target"] - idea["entry"]) * qty
    return {"qty": qty, "capital": capital, "cash_needed": round(idea["entry"] * qty, 2),
            "risk_inr": round((idea["entry"] - idea["stop"]) * qty, 2), "reward_inr": round(reward, 2),
            "charges_inr": round(charges, 2),
            "charges_ok": qty > 0 and reward >= min_reward_to_charges * charges}


def level_status(idea: dict, q: dict, p: Params = Params()) -> str:
    """WATCH, APPROACHING, ACTIVATED (TARGET HIT) or INVALIDATED from the day's high/low so far.

    The scan's opening-range low sits above the stop, so a later low at or below the stop means the stop
    traded after the scan: INVALIDATED, whether or not the entry had triggered (the order is unknown)."""
    if q["lowPrice"] <= idea["stop"]:
        return "INVALIDATED"
    if q["highPrice"] >= idea["entry"]:
        return "ACTIVATED (TARGET HIT)" if q["highPrice"] >= idea["target"] else "ACTIVATED"
    if q["lastTradedPrice"] >= idea["entry"] * (1 - p.approaching_pct / 100):
        return "APPROACHING"
    return "WATCH"


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
         capital: float | None = None, risk_pct: float | None = None, charges_inr: float | None = None,
         list_all: bool = False, workers: int = 8, max_risk_inr: float | None = None) -> dict:
    """Ideas for the experiment record (at most `max_ideas`). With `list_all`, every other stock that passes
    the same rule goes to `also_passing` for the owner to pick from; only `ideas` are graded."""
    quotes = fetch_quotes(transport)
    fresh, why = quote_age_ok(quotes, now, p)
    result = {"experiment": EXPERIMENT, "version": VERSION, "run_at": now.astimezone(IST).isoformat(),
              "data": why, "sources": [f"{CM_MARKET_URL} cm_get_equity_stocks", f"{BHAVCOPY_URL} get_stock_history"],
              "ideas": [], "also_passing": [], "rejected": []}
    if not fresh:
        result["status"] = "DATA INSUFFICIENT"
        return result
    result["breadth"] = breadth(quotes, p.min_value_cr)
    prev_day = now.astimezone(IST).date() - timedelta(days=1)
    screened = quote_screen(quotes, p)

    def history(q):
        try:
            return fetch_daily(q["symbol"], prev_day, transport)
        except (McpError, OSError) as exc:
            return exc
    with ThreadPoolExecutor(max_workers=workers) as pool:       # history calls are slow; order is kept
        histories = list(pool.map(history, screened))
    passing = []
    for q, bars in zip(screened, histories):
        if isinstance(bars, Exception):
            idea, reason = None, f"DATA INSUFFICIENT: {bars}"
        else:
            idea, reason = plan(q, bars, p)
        if idea is None:
            result["rejected"].append({"symbol": q["symbol"], "reason": reason})
            continue
        if capital:
            idea.update(money_plan(idea, capital, p.risk_pct if risk_pct is None else risk_pct, charges_inr, p,
                                   max_risk_inr=max_risk_inr))
        idea["status"] = level_status(idea, q, p)
        passing.append(idea)
    # Lead = most traded passing idea; with a capital, the most traded one whose charges check passes.
    lead = [i for i in passing if i.get("charges_ok", True)][:p.max_ideas]
    result["ideas"] = lead
    result["also_passing"] = [i for i in passing if i not in lead] if list_all else []
    result["status"] = result["ideas"][0]["status"] if result["ideas"] else "NO TRADE"
    return result


def live_status(day_result: dict, transport: Transport = http_transport, p: Params = Params()) -> list[dict]:
    """Current WATCH/APPROACHING/ACTIVATED/INVALIDATED for every idea listed in a scan result."""
    out = []
    for idea in day_result["ideas"] + day_result.get("also_passing", []):
        try:
            q = json.loads(_call_with_retries(CM_MARKET_URL, "cm_get_stock_quote", {"symbol": idea["symbol"]},
                                              transport))["stock"]
        except (McpError, OSError, KeyError) as exc:
            out.append({"symbol": idea["symbol"], "status": f"DATA INSUFFICIENT: {exc}"})
            continue
        out.append({"symbol": idea["symbol"], "status": level_status(idea, q, p), "ltp": q["lastTradedPrice"],
                    "high": q["highPrice"], "low": q["lowPrice"], "quote_time": q.get("latestTimestamp"),
                    "entry": idea["entry"], "stop": idea["stop"], "target": idea["target"]})
    return out


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
    return {"experiment": ideas.get("experiment", EXPERIMENT), "day": day.isoformat(), "graded": graded}


def render(result: dict) -> str:
    lines = [f"# Opening-range scan {result['run_at'][:10]} ({result['experiment']} v{result['version']})", "",
             f"**Status: {result['status']}.** Untested forward experiment; not a recommendation.", "",
             f"- Data: {result['data']}. Sources: {'; '.join(result['sources'])}."]
    if "breadth" in result:
        b = result["breadth"]
        lines.append(f"- Breadth (calculated): {b['advancing']}/{b['traded']} traded EQ stocks up; "
                     f"{b['liquid_advancing']}/{b['liquid']} liquid ones up.")
    listed = result["ideas"] + result.get("also_passing", [])
    if result["ideas"]:
        i = result["ideas"][0]
        b = result.get("breadth", {})
        share = b.get("liquid_advancing", 0) / b["liquid"] if b.get("liquid") else 0
        regime = "broad advance" if share >= 0.6 else "broad decline" if share <= 0.4 else "mixed"
        money = (f"{i['qty']} shares (Rs {i['cash_needed']:,.0f})", f"Rs {i['risk_inr']:,.0f}",
                 f"Rs {i['charges_inr']:,.0f} round trip (estimate) + slippage") if "qty" in i else ("-", "-", "-")
        lines += ["", "## Today's pick", "",
                  f"- Date: {result['run_at'][:10]}",
                  f"- Market regime (calculated, breadth only; NIFTY trend and India VIX not read): {regime}",
                  f"- Market breadth (calculated): {b.get('liquid_advancing')}/{b.get('liquid')} liquid stocks up",
                  f"- Selected instrument: {i['symbol']} (NSE cash, intraday)",
                  "- Direction: long",
                  f"- Strategy: opening-range breakout, {result['experiment']} v{result['version']}",
                  f"- Entry: buy above {i['entry']}",
                  f"- Stop-loss: {i['stop']} (one tick under the opening-range low; never widened)",
                  f"- Target: {i['target']}",
                  f"- Risk/reward: 1:{(i['target'] - i['entry']) / (i['entry'] - i['stop']):.1f}",
                  f"- Quantity: {money[0]}",
                  f"- Maximum planned monetary risk: {money[1]}",
                  f"- Estimated costs: {money[2]}",
                  f"- Setup confirmation (calculated): above previous day high {i['prev_high']}; opening range "
                  f"{i['or_low']}-{i['or_high']} = {i['risk_per_share'] / i['atr14']:.2f} ATR14; "
                  f"Rs {i['value_cr']} cr traded so far",
                  "- Invalidation condition: price trades at or below the stop, or no entry by 15:10 IST",
                  "- Reason for selection: most traded stock passing every rule"
                  + (" and the charges check" if "qty" in i else ""),
                  f"- Data timestamp: {i.get('quote_time')} IST (NSE, 1-3 min delayed)",
                  f"- Strategy backtest reference: none. No intraday history exists here; {result['experiment']} "
                  "is a forward test, graded each next morning",
                  f"- Status: {i.get('status')}"]
    if result["ideas"]:
        if result.get("also_passing"):
            lines += ["", "Also passing (not today's pick; listed as WATCH only): "
                      + ", ".join(i["symbol"] for i in result["also_passing"]) + "."]
        lines += ["", "| Stock | Status | LTP | Opening range | Buy above | Stop | Target 2R | Risk/share | Qty |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for i in listed:
            lines.append(f"| {i['symbol']} | {i.get('status', '-')} | {i['ltp']} | {i['or_low']}-{i['or_high']} | "
                         f"{i['entry']} | {i['stop']} | {i['target']} | {i['risk_per_share']} | {i.get('qty', '-')} |")
        sized = [i for i in listed if "qty" in i]
        if sized:
            c = sized[0]["capital"]
            lines += ["", f"Money plan for Rs {c:,.0f} (one trade a day, no margin):", "",
                      "| Stock | Qty | Cash needed | Loss at stop | Profit at target | Charges (est.) | Charges check |",
                      "|---|---|---|---|---|---|---|"]
            for i in sized:
                lines.append(f"| {i['symbol']} | {i['qty']} | {i['cash_needed']:,.0f} | {i['risk_inr']:,.0f} | "
                             f"{i['reward_inr']:,.0f} | {i['charges_inr']:,.0f} | "
                             f"{'OK' if i['charges_ok'] else 'SKIP: charges too high'} |")
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
    s.add_argument("--risk-pct", type=float, help="percent of capital at risk per trade (default: settings 0.5)")
    s.add_argument("--charges-inr", type=float, help="your broker's round-trip charges per trade, if known")
    s.add_argument("--max-risk-inr", type=float, help="fixed rupee cap on risk per trade")
    s.add_argument("--list-all", action="store_true", help="also list every other stock that passes the rule")
    st = sub.add_parser("status")
    st.add_argument("--out-dir", type=Path, required=True)
    st.add_argument("--day", type=date.fromisoformat, default=None)
    g = sub.add_parser("score")
    g.add_argument("--day", type=date.fromisoformat, required=True)
    g.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.cmd == "scan":
        now = datetime.now(timezone.utc)
        result = scan(now, capital=a.capital, risk_pct=a.risk_pct, charges_inr=a.charges_inr,
                      list_all=a.list_all, max_risk_inr=a.max_risk_inr)
        stem = a.out_dir / now.astimezone(IST).date().isoformat()
        stem.with_suffix(".json").write_text(json.dumps(result, indent=2))
        stem.with_suffix(".md").write_text(render(result))
        print(render(result))
    elif a.cmd == "status":
        day = a.day or datetime.now(IST).date()
        out = live_status(json.loads((a.out_dir / f"{day.isoformat()}.json").read_text()))
        print(json.dumps(out, indent=2))
    else:
        ideas = json.loads((a.out_dir / f"{a.day.isoformat()}.json").read_text())
        out = score(a.day, ideas)
        (a.out_dir / f"{a.day.isoformat()}.score.json").write_text(json.dumps(out, indent=2))
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
