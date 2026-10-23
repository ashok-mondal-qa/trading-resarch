"""Daily after-close report (daily-report skill), paper trading only.

    python -m trading_research.reporting.daily                      # latest completed session
    python -m trading_research.reporting.daily --date 2026-10-22    # a given session
    python -m trading_research.reporting.daily --no-fetch           # use only data already on disk

Steps: load the bhavcopy and NIFTY files the window needs (idempotent); check freshness; screen every
registered strategy through gates 1-9 (signal-gates skill); journal every signal or rejection; let the paper
broker process the session for any open paper orders/positions; write `reports/YYYY-MM-DD.md` and
validate it. Nothing here sends an order anywhere: the paper broker only writes journal records.

Split/bonus adjustment in daily mode: corporate actions are fetched only for symbols that need them (a
raw open/previous-close move of 20% or more in the window, a setup on the report date, or an open paper
position). Other symbols are screened on raw prices. A small bonus (raw move under 20%) can therefore hide
a setup, but cannot create one: every setup is re-checked on adjusted prices before it gets a status.
"""

from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from trading_research.backtesting.costs import round_trip_cost
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import adjust, bhavcopy, corporate_actions, indices, quality
from trading_research.data import symbols as symbol_changes
from trading_research.indicators import core, regime
from trading_research.paper_trading.guard import get_broker
from trading_research.paper_trading.journal import Journal
from trading_research.risk.sizing import SizingRejected, size_long_position
from trading_research.strategies import baseline_trend_breakout as baseline
from trading_research.strategies import pa_smc

STOCK_WINDOW_DAYS = 490   # ~330 sessions: SMA200, 63-day RS and the 260-session gate-1 window
INDEX_WINDOW_DAYS = 1250  # ~840 sessions: SMA200 regime plus the 756-session volatility percentile
GAP_FOR_ACTIONS = 0.20
STATUSES = ("TRADE CANDIDATE", "WATCHLIST", "REJECTED", "NO TRADE", "DATA INSUFFICIENT")
SECTIONS = [
    "1. Report date and data timestamp", "2. Market regime and benchmark", "3. Data quality",
    "4. Candidates screened", "5. Shortlist", "6. Candidate details", "7. Gate results",
    "8. Auditor and risk-manager objections", "9. Final status", "10. Open virtual positions",
    "11. Source evidence", "12. Limitations",
]
BANNED_PHRASES = ["guaranteed", "sure shot", "sure-shot", "high probability", "can't lose", "cannot lose",
                  "risk-free", "risk free", "certain to", "will definitely", "100% accurate"]


@dataclass
class StrategyDef:
    name: str
    experiment: str
    version: str
    features: Callable[[pd.DataFrame, pd.Series], pd.DataFrame]


def _baseline_features(bars, nifty):
    f = baseline.stock_features(bars, nifty)
    f["higher_tf"], f["context_rule"] = f["trend_ok"], "close > SMA200 and SMA50 > SMA200"
    f["setup_ok"] = f["breakout"] & f["rs_ok"] & f["liquid"] & f["stop_ok"]
    f["confirm_ok"] = f["volume_ok"]
    f["candidate"] = f["inputs_complete"] & (f["signal"] | f["watchlist"])
    return f


def _pa_smc(strategy):
    def features(bars, nifty):
        f = pa_smc.stock_features(bars, nifty, strategy)
        f["higher_tf"], f["context_rule"] = f["context"], "close > SMA200"
        f["setup_ok"] = f["event"] & f["filter"] & f["stop_ok"] & f["liquid"]
        f["confirm_ok"] = True  # these specs have no separate confirmation gate
        f["candidate"] = f["inputs_complete"] & f["signal"]
        return f
    return features


STRATEGIES = [
    StrategyDef("baseline_trend_breakout", "EXP-0006", baseline.SPEC_VERSION, _baseline_features),
    StrategyDef("pa_pullback", "EXP-0007", pa_smc.SPEC_VERSION, _pa_smc("pa_pullback")),
    StrategyDef("smc_sweep", "EXP-0008", pa_smc.SPEC_VERSION, _pa_smc("smc_sweep")),
]


def registry_status(experiment: str, path: Path = REPO_ROOT / "experiments" / "registry.csv") -> str:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["experiment_id"] == experiment]
    return rows[-1]["status"] if rows else "unregistered"


# ---------------------------------------------------------------------------------------------- data
def ensure_data(day: date, root: Path, workers: int = 8) -> dict:
    """Fetch the bhavcopy and index files the window needs (existing ones are skipped)."""
    store = bhavcopy.Store(root=root)
    stock_days = list(bhavcopy.weekdays(day - timedelta(days=STOCK_WINDOW_DAYS), day))
    index_days = list(bhavcopy.weekdays(day - timedelta(days=INDEX_WINDOW_DAYS), day))
    errors = []

    def one(fn, d):
        try:
            fn(d)
        except Exception as exc:  # recorded; a missing day then shows up in the data checks
            errors.append(f"{d}: {exc}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda d: one(lambda x: bhavcopy.load_day(x, store), d), stock_days))
        list(pool.map(lambda d: one(lambda x: indices.load_day(x, root), d), index_days))
    if not symbol_changes.raw_path(root).exists():
        symbol_changes.refresh_symbol_changes(root)
    return {"stock_days": len(stock_days), "index_days": len(index_days), "errors": errors}


def _no_actions(symbol: str) -> dict:
    return {"symbol": symbol, "source": "not fetched (no raw move >= 20% in window and no setup)",
            "retrieved_at_utc": None, "actions": []}


def _needs_actions(raw: pd.DataFrame) -> bool:
    r = raw.sort_values("date")
    move = (r["open"] / r["close"].shift(1) - 1).abs()
    return bool((move >= GAP_FOR_ACTIONS).any())


@dataclass
class Universe:
    bars: dict = field(default_factory=dict)        # symbol -> adjusted OHLCV (+ raw_close)
    manifests: dict = field(default_factory=dict)   # symbol -> adjustment manifest
    features: dict = field(default_factory=dict)    # (strategy, symbol) -> features frame
    gate1: dict = field(default_factory=dict)       # symbol -> gate-1 series
    screened: int = 0
    actions_fetched: list = field(default_factory=list)
    actions_failed: list = field(default_factory=list)


def build_universe(day: date, root: Path, nifty: pd.Series, calendar: list, held: set[str],
                   fetch_actions: Callable = corporate_actions.load_actions, workers: int = 6) -> Universe:
    start = day - timedelta(days=STOCK_WINDOW_DAYS)
    store = bhavcopy.Store(root=root)
    raw = bhavcopy.read_bars(start, day, store, series=("EQ",))
    changes = symbol_changes.load_symbol_changes(root)
    u = Universe()
    if raw.empty:
        return u
    ts = pd.Timestamp(day)
    today = raw[raw["date"] == ts]
    by_symbol = {s: g for s, g in raw.groupby("symbol")}
    # cheap pre-filter, identical to the strategies' own liquidity rule on raw values
    liquid = []
    for s in today["symbol"]:
        g = by_symbol[s]
        if g["close"].iloc[-1] >= 50 and g["traded_value"].tail(20).median() >= 5e7:
            liquid.append(s)
    liquid = sorted(set(liquid) | (held & set(by_symbol)))
    u.screened = len(liquid)

    def history(symbol):
        related = [symbol] + [l["old_symbol"] for l in symbol_changes.predecessors(symbol, changes)]
        subset = pd.concat([by_symbol[t] for t in related if t in by_symbol])
        return symbol_changes.join_history(symbol, subset, changes, calendar_start=raw["date"].min())

    def evaluate(symbol, record, hist):
        result = adjust.build_adjusted(symbol, hist.bars, record, hist.links)
        u.manifests[symbol] = result.manifest
        adj = result.bars
        if result.manifest["status"] == "DATA INSUFFICIENT" or not adj["usable"].any():
            return False
        bars = core.ohlcv(adj, usable_only=True)
        if len(bars) < 200 or bars.index[-1] != ts:
            return False
        bars["raw_close"] = adj[adj["usable"]]["close"].to_numpy()
        u.bars[symbol] = bars
        u.gate1[symbol] = quality.gate1_series(bars.index, bars["volume"], calendar)
        hit = False
        for sd in STRATEGIES:
            f = sd.features(bars, nifty)
            u.features[(sd.name, symbol)] = f
            hit |= bool(f["candidate"].iloc[-1]) or bool(f["event"].iloc[-1] if "event" in f else False)
        return hit

    histories, recheck = {}, []
    for symbol in liquid:
        histories[symbol] = history(symbol)
        hit = evaluate(symbol, _no_actions(symbol), histories[symbol])
        if hit or symbol in held or _needs_actions(histories[symbol].bars):
            recheck.append(symbol)

    def load(symbol):
        tickers = [symbol] + [l["old_symbol"] for l in histories[symbol].links if l["status"] == "confirmed"]
        try:
            return symbol, adjust.merge_action_records([fetch_actions(t, start, day, root) for t in tickers]), None
        except Exception as exc:
            return symbol, None, str(exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        loaded = list(pool.map(load, recheck))
    for symbol, record, error in loaded:
        for key in [k for k in u.features if k[1] == symbol]:
            del u.features[key]
        u.bars.pop(symbol, None)
        if error:
            u.actions_failed.append(symbol)
            u.manifests[symbol] = {"symbol": symbol, "status": "DATA INSUFFICIENT",
                                   "issues": [{"kind": "corporate actions unavailable", "detail": error}]}
            continue
        u.actions_fetched.append(symbol)
        evaluate(symbol, record, histories[symbol])
    return u


# --------------------------------------------------------------------------------------------- gates
def gap_risk(bars: pd.DataFrame) -> float:
    """5th percentile of open/previous-close - 1 over the window (an adverse overnight gap)."""
    gaps = (bars["open"] / bars["close"].shift(1) - 1).dropna()
    return float(np.percentile(gaps, 5)) if len(gaps) >= 20 else float("nan")


def evaluate_candidates(day: date, u: Universe, reg: pd.DataFrame, broker, settings: dict) -> list[dict]:
    ts = pd.Timestamp(day)
    trend = reg["trend"].get(ts, "unknown")
    equity, cash, open_risk = broker.equity(), broker.cash(), broker.open_planned_risk()
    risk_cfg = settings["risk"]
    out = []
    for sd in STRATEGIES:
        strategy_status = registry_status(sd.experiment)
        for (name, symbol), f in u.features.items():
            if name != sd.name or ts not in f.index or not bool(f.loc[ts, "candidate"]):
                continue
            r, bars = f.loc[ts], u.bars[symbol]
            g = {}
            g1 = bool(u.gate1[symbol].get(ts, False)) and bool(r["inputs_complete"])
            g[1] = (g1, "gate-1 bar checks over 260 sessions; inputs present" if g1 else
                    "gate-1 bar checks failed or an input is missing")
            g[2] = (trend == "up", f"NIFTY 50 trend = {trend}")
            g[3] = (bool(r["higher_tf"]), r["context_rule"])
            g[4] = (bool(r["setup_ok"]), "every entry condition of the spec at the close")
            g[5] = (bool(r["confirm_ok"]), "confirmation as specified")
            stop, close = float(r["stop"]), float(r["close"])
            plan, risk_note = None, ""
            full = equity * float(risk_cfg["max_risk_per_position_pct"]) / 100
            cap = equity * float(risk_cfg["max_aggregate_open_risk_pct"]) / 100
            if cap - open_risk < full:
                risk_note = "aggregate cap: no room for a full 0.5% position"
            else:
                try:
                    plan = size_long_position(equity, cash, close, stop, open_risk, settings)
                    risk_note = (f"{plan.quantity} shares at ~₹{close:,.2f}, stop ₹{stop:,.2f}, planned risk "
                                 f"₹{plan.planned_risk_inr:,.0f} ({plan.planned_risk_pct:.2f}%)")
                except SizingRejected as exc:
                    risk_note = f"sizer: {exc}"
            g[6] = (plan is not None, risk_note)
            g[7] = (False, "liquidity floor met; **event screen not available** (results dates, filings "
                           "not checked), so this gate cannot pass")
            g[8] = (strategy_status.upper() == "ACCEPTED",
                    f"strategy {sd.experiment} status in registry: {strategy_status}")
            status = "TRADE CANDIDATE"
            for gate in range(1, 9):
                ok, _ = g[gate]
                if ok:
                    continue
                status = {1: "DATA INSUFFICIENT", 5: "WATCHLIST", 7: "DATA INSUFFICIENT"}.get(gate, "REJECTED")
                failed = gate
                break
            else:
                failed = None
            gap = gap_risk(bars)
            out.append({
                "strategy": sd.name, "experiment": sd.experiment, "version": sd.version, "symbol": symbol,
                "signal_date": day.isoformat(), "close": close, "stop": stop, "rs": float(r["rs"]),
                "gates": {k: {"pass": v[0], "evidence": v[1]} for k, v in g.items()},
                "status": status, "failed_gate": failed,
                "quantity": plan.quantity if plan else None,
                "planned_risk_inr": plan.planned_risk_inr if plan else None,
                "est_round_trip_costs_inr": (round_trip_cost(close, stop, plan.quantity, settings["costs"])
                                             if plan else None),
                "gap_p5": gap,
                "gap_loss_inr": (plan.quantity * close * -gap if plan and not np.isnan(gap) else None),
                "adjustment": u.manifests.get(symbol, {}).get("status"),
            })
    # gate 9: at most 2 TRADE CANDIDATES a day, highest RS first; the rest WATCHLIST
    tc = sorted([c for c in out if c["status"] == "TRADE CANDIDATE"], key=lambda c: -c["rs"])
    for i, c in enumerate(tc):
        c["gates"][9] = {"pass": i < settings["risk"]["max_new_candidates_per_day"],
                         "evidence": f"rank {i + 1} by 63-day RS"}
        if i >= settings["risk"]["max_new_candidates_per_day"]:
            c["status"], c["failed_gate"] = "WATCHLIST", 9
    return out


# -------------------------------------------------------------------------------------------- report
def _fmt(x, spec=",.2f"):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else format(x, spec)


def render(ctx: dict) -> str:
    c, L = ctx, []
    add = L.append
    add(f"# Daily paper-trading report — {c['day']}")
    add("")
    add("Paper trading only, not investment advice. Every number below is calculated from the files listed in "
        "section 11; nothing is typed by hand.")
    add(f"\n## {SECTIONS[0]}")
    add(f"- Report date: {c['day']} (generated {c['generated_at_utc']} UTC)")
    add(f"- Last bar: {c['last_bar']} (NSE CM bhavcopy, close 15:30 IST); bhavcopy retrieved "
        f"{c['bhav_retrieved']} UTC")
    add(f"\n## {SECTIONS[1]}")
    add(f"- NIFTY 50 close {_fmt(c['nifty_close'])}; trend **{c['trend']}** (close vs SMA200 "
        f"{_fmt(c['sma200'])}, SMA50 20-day slope {_fmt(c['slope'], '+.2f')}); volatility {c['volatility']} "
        f"(percentile {_fmt(c['vol_pct'], '.0%')})")
    add("- Label: calculated indicator, not a forecast.")
    add(f"\n## {SECTIONS[2]}")
    for name, (ok, note) in c["quality"].items():
        add(f"- {name}: {'pass' if ok else 'FAIL'} — {note}")
    add(f"\n## {SECTIONS[3]}")
    add(f"- {c['screened']} liquid EQ symbols screened (₹50 raw price floor, 20-day median traded value ≥ "
        f"₹5 crore); corporate actions fetched for {c['actions_fetched']}, unavailable for "
        f"{c['actions_failed']}")
    add(f"- Strategies: " + "; ".join(f"{s.name} v{s.version} ({s.experiment}: {registry_status(s.experiment)})"
                                     for s in STRATEGIES))
    add(f"- Setups found at today's close: {len(c['candidates'])}")
    tc = [x for x in c["candidates"] if x["status"] == "TRADE CANDIDATE"]
    add(f"\n## {SECTIONS[4]}")
    if tc:
        for x in tc:
            add(f"- **{x['symbol']}** ({x['strategy']})")
    else:
        add("- None. No setup passed every gate.")
    add(f"\n## {SECTIONS[5]}")
    if not c["candidates"]:
        add("- No setups today.")
    for x in c["candidates"]:
        add(f"- **{x['symbol']}** (NSE, daily) — {x['strategy']} v{x['version']}: status **{x['status']}**"
            + (f" (first failed gate {x['failed_gate']})" if x["failed_gate"] else ""))
        add(f"  - Evidence: close ₹{_fmt(x['close'])}, 63-day RS {_fmt(x['rs'], '+.1%')} (calculated)")
        add(f"  - Entry condition: next session open above the stop; invalidation/stop ₹{_fmt(x['stop'])}; "
            "target: none (exits by rule: close below 10-session low, or 40 sessions)")
        add(f"  - Size: {_fmt(x['quantity'], 'd') if x['quantity'] else 'n/a'} shares; planned risk "
            f"₹{_fmt(x['planned_risk_inr'], ',.0f')}; reward-to-risk: no fixed target; est. costs "
            f"₹{_fmt(x['est_round_trip_costs_inr'], ',.0f')} (rates unverified)")
        add(f"  - Gap risk: 5th-percentile overnight gap {_fmt(x['gap_p5'], '+.1%')}; loss if it happens at this "
            f"size ₹{_fmt(x['gap_loss_inr'], ',.0f')}. Event risks: not screened.")
    add(f"\n## {SECTIONS[6]}")
    if c["candidates"]:
        add("| Symbol | Strategy | " + " | ".join(f"G{i}" for i in range(1, 10)) + " | Status |")
        add("| --- | --- | " + " | ".join("---" for _ in range(9)) + " | --- |")
        for x in c["candidates"]:
            cells = [("pass" if x["gates"][i]["pass"] else "FAIL") if i in x["gates"] else "—"
                     for i in range(1, 10)]
            add(f"| {x['symbol']} | {x['strategy']} | " + " | ".join(cells) + f" | {x['status']} |")
        add("")
        add("Gate evidence: 7 = event screen not available; 8 = strategy status in experiments/registry.csv.")
    else:
        add("- No setups, so no gates were run.")
    add(f"\n## {SECTIONS[7]}")
    add("- Auditor: no strategy has passed out-of-sample validation (EXP-0006/0007/0008 all REJECTED), so any "
        "setup above is a research record, not a trade. The event screen is missing.")
    add(f"- Risk manager: open planned risk ₹{c['open_risk']:,.0f} of the ₹{c['cap']:,.0f} cap (2%); gaps can "
        "lose more than planned risk.")
    add(f"\n## {SECTIONS[8]}")
    add(f"**{c['final_status']}** — {c['final_reason']}")
    add(f"\n## {SECTIONS[9]}")
    if c["positions"]:
        for p in c["positions"]:
            add(f"- {p.symbol} ({p.strategy}): {p.qty:g} shares from {p.entry_date} at ₹{p.entry:,.2f}, stop "
                f"₹{p.stop:,.2f}, planned risk ₹{p.planned_risk:,.0f}")
    else:
        add("- None.")
    add(f"- Virtual equity ₹{c['equity']:,.0f}; aggregate open planned risk ₹{c['open_risk']:,.0f} "
        f"vs cap ₹{c['cap']:,.0f}")
    if c["broker_events"]:
        add("- Paper broker today: " + "; ".join(c["broker_events"]))
    add(f"\n## {SECTIONS[10]}")
    for s in c["sources"]:
        add(f"- {s}")
    add(f"\n## {SECTIONS[11]}")
    add(f"- Cost rates verified: {'yes' if c['costs_verified'] else 'no (placeholders in config/settings.yaml)'}")
    add("- Survivorship: universe is every EQ symbol in the day's bhavcopy (point-in-time).")
    add("- Event screen (results dates, filings) not implemented; circuit-locked days not detected.")
    add("- Small splits/bonuses (raw move under 20%) are screened on raw prices and can hide a setup.")
    add("- ETFs trade in the EQ series and are not excluded by the current strategy specs.")
    add("- Paper trading only, not investment advice. No order is sent anywhere.")
    return "\n".join(L) + "\n"


def validate_report(text: str) -> list[str]:
    problems = [f"missing section: {s}" for s in SECTIONS if f"## {s}" not in text]
    lower = text.lower()
    problems += [f"banned phrase: {p}" for p in BANNED_PHRASES if p in lower]
    if not any(f"**{s}**" in text for s in STATUSES):
        problems.append("no final status")
    return problems


# ------------------------------------------------------------------------------------------------ run
def latest_session(store: bhavcopy.Store, before: date) -> date | None:
    day = before
    for _ in range(15):
        m = store.read_manifest(day) if day.weekday() < 5 else None
        if m and m["status"] == "ok":
            return day
        day -= timedelta(days=1)
    return None


def run(day: date | None = None, root: Path = REPO_ROOT / "data", fetch: bool = True,
        now_utc: datetime | None = None, journal: Journal | None = None,
        report_dir: Path = REPO_ROOT / "reports") -> dict:
    now = now_utc or datetime.now(timezone.utc)
    settings = load_settings()
    store = bhavcopy.Store(root=root)
    target = day or now.astimezone(quality.IST).date()
    fetch_info = ensure_data(target, root) if fetch else {"errors": []}
    fresh = quality.check_freshness(store, now_utc=now) if day is None else quality.QualityResult(
        "ok" if (store.read_manifest(target) or {}).get("status") == "ok" else "DATA INSUFFICIENT",
        [] if (store.read_manifest(target) or {}).get("status") == "ok" else [f"{target} not loaded"])
    if day is None:
        target = latest_session(store, target) or target
    broker = get_broker()
    if journal is not None:
        broker.journal = journal  # tests and dry runs use their own journal
    held = {p.symbol for p in broker.open_positions()} | {o["data"]["symbol"] for o in broker.pending_orders()}

    nifty_full = indices.read_index("Nifty 50", target - timedelta(days=INDEX_WINDOW_DAYS), target, root)
    nifty = nifty_full["close"] if len(nifty_full) else pd.Series(dtype=float)
    reg = regime.regime(nifty) if len(nifty) else pd.DataFrame(columns=["trend", "volatility"])
    ts = pd.Timestamp(target)
    quality_rows = {
        "freshness": (fresh.status == "ok", "; ".join(fresh.reasons) or f"latest session {target}"),
        "NIFTY 50 file": (ts in nifty.index, f"index close for {target}" if ts in nifty.index else "missing"),
        "fetch errors": (not fetch_info["errors"], f"{len(fetch_info['errors'])} files failed to load"),
    }
    data_ok = all(ok for ok, _ in quality_rows.values()) and reg["trend"].get(ts, "unknown") != "unknown"
    calendar = quality.sessions(store, target - timedelta(days=STOCK_WINDOW_DAYS), target)
    candidates, u = [], Universe()
    broker_events = []
    if data_ok:
        u = build_universe(target, root, nifty, calendar, held)
        # paper broker: exits decided at the previous close, then today's open for pending orders
        prev = [d for d in calendar if d < target]
        exits_due = {}
        for p in broker.open_positions():
            f = u.features.get((p.strategy, p.symbol))
            if f is not None and prev and pd.Timestamp(prev[-1]) in f.index and bool(
                    f.loc[pd.Timestamp(prev[-1]), "exit_signal"]):
                exits_due[p.symbol] = "exit signal"
            elif len([d for d in calendar if d.isoformat() >= p.entry_date and d < target]) >= 40:
                exits_due[p.symbol] = "time stop"
        raw_today = bhavcopy.read_bars(target, target, store, series=("EQ",)).set_index("symbol")
        bars = {s: raw_today.loc[s, ["open", "high", "low", "close"]].to_dict()
                for s in held if s in raw_today.index}
        factors = {}
        for s in held:
            m = u.manifests.get(s, {})
            for e in m.get("price_events_applied", []):
                if e["ex_date"] == target.isoformat():
                    factors[s] = e["factor"]
        for rec in broker.process_session(target.isoformat(), bars, exits_due, factors):
            broker_events.append(f"{rec['type']} {rec['data'].get('symbol')} "
                                 f"{rec['data'].get('reason') or rec['data'].get('action') or ''}".strip())
        candidates = evaluate_candidates(target, u, reg, broker, settings)

    # journal: one record per setup per strategy and day (re-runs do not duplicate)
    j = broker.journal
    seen = {(r["strategy"], r["data"].get("symbol"), r["data"].get("signal_date"))
            for r in j.records() if r["type"] in ("signal", "rejection")}
    for c in candidates:
        key = (c["strategy"], c["symbol"], c["signal_date"])
        if key in seen:
            continue
        kind = "signal" if c["status"] in ("TRADE CANDIDATE", "WATCHLIST") else "rejection"
        rec = j.append(kind, c["strategy"], c["version"], {**c, "data_timestamp": f"{target}T15:30:00+05:30",
                                                           "gates": {str(k): v for k, v in c["gates"].items()}})
        if c["status"] == "TRADE CANDIDATE":
            broker.submit(rec["id"])

    tc = [c for c in candidates if c["status"] == "TRADE CANDIDATE"]
    if not data_ok:
        final, reason = "DATA INSUFFICIENT", "market data or NIFTY 50 regime not available for the session"
    elif tc:
        final, reason = "TRADE CANDIDATE", f"{len(tc)} setup(s) passed gates 1–9 (paper order for next open)"
    else:
        final, reason = "NO TRADE", "no setup passed every gate; zero trades is an acceptable outcome"
    equity = broker.equity()
    m = store.read_manifest(target) or {}
    sources = [f"Bhavcopy {m.get('source_url')} (sha256 {str(m.get('raw_sha256'))[:12]}…), manifest "
               f"data/manifests/{bhavcopy.DATASET}/{target:%Y}/{target}.json",
               f"NIFTY 50 {indices.url_for(target)}, manifest under data/manifests/{indices.DATASET}/",
               "Strategy specs: docs/strategy-specifications/; registry: experiments/registry.csv",
               f"Journal: journal/ (hash chain {'valid' if not j.verify() else 'BROKEN'})"]
    r = reg.loc[ts] if ts in reg.index else {}
    ctx = {
        "day": target.isoformat(), "generated_at_utc": now.replace(microsecond=0).isoformat(),
        "last_bar": target.isoformat() if m.get("status") == "ok" else "not loaded",
        "bhav_retrieved": m.get("retrieved_at_utc"), "nifty_close": float(nifty.get(ts, np.nan)),
        "trend": r.get("trend", "unknown"), "sma200": r.get("sma200"), "slope": r.get("sma50_slope20"),
        "volatility": r.get("volatility", "unknown"), "vol_pct": r.get("vol_percentile"),
        "quality": quality_rows, "screened": u.screened, "actions_fetched": len(u.actions_fetched),
        "actions_failed": len(u.actions_failed), "candidates": candidates,
        "final_status": final, "final_reason": reason, "positions": broker.open_positions(),
        "equity": equity, "open_risk": broker.open_planned_risk(),
        "cap": equity * float(settings["risk"]["max_aggregate_open_risk_pct"]) / 100,
        "broker_events": broker_events, "sources": sources, "costs_verified": settings["costs"]["verified"],
    }
    text = render(ctx)
    problems = validate_report(text)
    if problems:
        raise ValueError(f"report failed validation: {problems}")
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{target}.md"
    path.write_text(text, encoding="utf-8")
    summary = {"date": target.isoformat(), "final_status": final, "reason": reason, "report": str(path),
               "setups": [{"symbol": c["symbol"], "strategy": c["strategy"], "status": c["status"]}
                          for c in candidates]}
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily paper-trading report (paper only)")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.date, fetch=not args.no_fetch), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
