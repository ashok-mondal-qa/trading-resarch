"""NIFTY monthly options (spec docs/strategy-specifications/nifty-options.md, v0.1). Research only.

All prices are per unit of the index (points). A trade's `pnl` is net of costs per unit; `risk` is its R unit.

* `iron_condor`: sell call >= S + D and put <= S - D, buy call >= S + 2D and put <= S - 2D, hold to expiry.
* `short_strangle`: sell call >= S + D and put <= S - D; exit at the next open after a close where the buy-back
  cost is >= 3 x the credit.
* `covered_call`: hold NIFTY, sell the monthly call >= 1.02 S, hold to expiry.
* `long_call`: NIFTY 20-session breakout in an `up` regime -> buy the ATM call of the first monthly expiry at
  least 15 sessions away; exit after a close below the 10-session low or with <= 5 sessions left.

S = NIFTY close and D = ATM straddle (call + put closes) on the signal day t; legs fill at t+1's open and settle
at intrinsic value against the NIFTY close on expiry day.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

SPEC_VERSION = "0.1"
STRATEGIES = ("iron_condor", "short_strangle", "covered_call", "long_call")


@dataclass(frozen=True)
class Params:
    brokerage_per_order: float = 20.0       # ₹ per order (per lot)
    stt_sell_pct: float = 0.1               # of premium, sells
    stt_exercise_pct: float = 0.125         # of intrinsic value, long options exercised at expiry
    txn_pct: float = 0.03503                # NSE options transaction charge, of premium
    sebi_fraction: float = 1e-6             # ₹10 per crore
    stamp_buy_pct: float = 0.003            # of premium, buys
    gst_pct: float = 18.0
    slip_points: float = 1.0
    slip_pct: float = 1.5
    strangle_stop_mult: float = 2.0         # loss >= 2 x credit
    cc_otm: float = 0.02
    lc_breakout: int = 20
    lc_exit_low: int = 10
    lc_min_sessions: int = 15
    lc_exit_sessions: int = 5

    def as_dict(self) -> dict:
        return asdict(self)


def slippage(price: float, p: Params, mult: float = 1.0) -> float:
    return max(p.slip_points, p.slip_pct / 100 * price) * mult


def leg_cost(price: float, side: str, lot: float, p: Params, mult: float = 1.0) -> float:
    """Charges per unit for one leg traded at `price` (excluding slippage)."""
    turnover = max(price, 0.0)
    brokerage = p.brokerage_per_order / lot
    txn = turnover * p.txn_pct / 100
    sebi = turnover * p.sebi_fraction
    gst = (brokerage + txn + sebi) * p.gst_pct / 100
    tax = turnover * (p.stt_sell_pct / 100 if side == "sell" else p.stamp_buy_pct / 100)
    return (brokerage + txn + sebi + gst + tax) * mult


def fill(price: float, side: str, lot: float, p: Params, mult: float) -> tuple[float, float]:
    """(fill price, charges) for a market order at `price`."""
    s = slippage(price, p, mult)
    px = price + s if side == "buy" else max(price - s, 0.05)
    return px, leg_cost(px, side, lot, p, mult)


class Chain:
    """NIFTY option rows indexed by (date, expiry, option_type, strike)."""

    def __init__(self, rows: pd.DataFrame):
        o = rows[(rows["symbol"] == "NIFTY") & (rows["instrument"] == "OPT")].copy()
        o["date"], o["expiry"] = pd.to_datetime(o["date"]), pd.to_datetime(o["expiry"])
        self.rows = o.set_index(["date", "expiry", "option_type", "strike"]).sort_index()
        f = rows[(rows["symbol"] == "NIFTY") & (rows["instrument"] == "FUT")].copy()
        f["date"], f["expiry"] = pd.to_datetime(f["date"]), pd.to_datetime(f["expiry"])
        self.futures = f

    def strikes(self, date, expiry, kind: str, traded_only: bool = True) -> pd.DataFrame:
        try:
            s = self.rows.loc[(date, expiry, kind)]
        except KeyError:
            return pd.DataFrame(columns=self.rows.columns)
        return s[s["traded"]] if traded_only else s

    def quote(self, date, expiry, kind: str, strike: float) -> pd.Series | None:
        try:
            return self.rows.loc[(date, expiry, kind, strike)]
        except KeyError:
            return None

    def monthly_expiries(self) -> list[pd.Timestamp]:
        """Last expiry per calendar month among contracts that traded on their expiry day. Contracts listed
        months ahead can carry the original date of an expiry later moved for a holiday (e.g. 2014-02-27, moved
        to 2014-02-26); such a date has no session and is not an expiry."""
        dates = set(self.rows.index.get_level_values("date").unique())
        exp = pd.Series(sorted(e for e in self.rows.index.get_level_values("expiry").unique() if e in dates))
        return sorted(exp.groupby(exp.dt.to_period("M")).max().tolist())

    def lot_size(self, date) -> float:
        """Lot from UDiFF, else inferred from the near-month future (notional turnover / contracts / price)."""
        day = self.futures[self.futures["date"] == date]
        if day.empty:
            return np.nan
        if day["lot_size"].notna().any():
            return float(day["lot_size"].dropna().iloc[0])
        near = day.sort_values("expiry").iloc[0]
        if not near["contracts"] or not near["close"]:
            return np.nan
        raw = near["value_lakh"] * 1e5 / (near["contracts"] * near["close"])
        return float(25 * round(raw / 25))


def first_at_or_above(strikes: pd.Index, level: float):
    s = strikes[strikes >= level]
    return float(s.min()) if len(s) else None


def last_at_or_below(strikes: pd.Index, level: float):
    s = strikes[strikes <= level]
    return float(s.max()) if len(s) else None


def atm_straddle(chain: Chain, t, expiry, spot: float):
    calls, puts = chain.strikes(t, expiry, "CE"), chain.strikes(t, expiry, "PE")
    both = calls.index.intersection(puts.index)
    if not len(both):
        return None, None
    k = float(both[np.argmin(np.abs(both.to_numpy() - spot))])
    return k, float(calls.loc[k, "close"] + puts.loc[k, "close"])


def intrinsic(kind: str, strike: float, settle: float) -> float:
    return max(settle - strike, 0.0) if kind == "CE" else max(strike - settle, 0.0)


def choose_legs(strategy: str, chain: Chain, t, expiry, spot: float, p: Params):
    """Legs (kind, strike, side) chosen from strikes listed at t and t's closes only, or None."""
    _, d = atm_straddle(chain, t, expiry, spot)
    if d is None:
        return None, None
    calls = chain.strikes(t, expiry, "CE", traded_only=False).index
    puts = chain.strikes(t, expiry, "PE", traded_only=False).index
    if strategy == "covered_call":
        k = first_at_or_above(calls, spot * (1 + p.cc_otm))
        return ([("CE", k, "sell")] if k is not None else None), d
    sc, sp = first_at_or_above(calls, spot + d), last_at_or_below(puts, spot - d)
    legs = [("CE", sc, "sell"), ("PE", sp, "sell")]
    if strategy == "iron_condor":
        legs += [("CE", first_at_or_above(calls, spot + 2 * d), "buy"), ("PE", last_at_or_below(puts, spot - 2 * d), "buy")]
    if any(k is None for _, k, _ in legs) or (strategy == "iron_condor" and (legs[2][1] <= legs[0][1] or legs[3][1] >= legs[1][1])):
        return None, d
    return legs, d


def exit_price(chain: Chain, day, fallback_day, expiry, kind: str, strike: float) -> float:
    """Open at `day` if the leg traded, else its settlement price at `day`, else at `fallback_day`."""
    q = chain.quote(day, expiry, kind, strike)
    if q is not None and q["traded"] and q["open"] > 0:
        return float(q["open"])
    if q is not None:
        return float(q["settle"])
    return float(chain.quote(fallback_day, expiry, kind, strike)["settle"])


def _mark(chain: Chain, date, expiry, legs) -> float | None:
    """Cost to close all legs at `date`'s settlement prices (positive = pay)."""
    total = 0.0
    for kind, k, side in legs:
        q = chain.quote(date, expiry, kind, k)
        if q is None:
            return None
        total += q["settle"] if side == "sell" else -q["settle"]
    return total


def run_cycle(strategy: str, chain: Chain, nifty_close: pd.Series, sessions: list, t, expiry, p: Params,
              mult: float = 1.0) -> dict | None:
    """One monthly trade from signal day t to `expiry` (iron_condor, short_strangle, covered_call)."""
    i = sessions.index(t)
    if i + 1 >= len(sessions) or sessions[i + 1] >= expiry:
        return None
    t1, spot = sessions[i + 1], float(nifty_close[t])
    legs, d = choose_legs(strategy, chain, t, expiry, spot, p)
    if legs is None:
        return None
    quotes = [chain.quote(t1, expiry, kind, k) for kind, k, _ in legs]
    if any(q is None or not q["traded"] or q["open"] <= 0 for q in quotes):
        return None                           # every leg must trade at t+1
    lot = chain.lot_size(t1)
    if not lot or np.isnan(lot):
        return None
    credit, costs, fills = 0.0, 0.0, []
    for (kind, k, side), q in zip(legs, quotes):
        px, c = fill(float(q["open"]), side, lot, p, mult)
        credit += px if side == "sell" else -px
        costs += c
        fills.append(px)
    exit_date, reason, payoff = expiry, "expiry", None
    if strategy == "short_strangle":
        later = [s for s in sessions if t1 <= s < expiry]
        for day in later:
            m = _mark(chain, day, expiry, legs)
            if m is not None and m - credit >= p.strangle_stop_mult * credit:
                nxt = sessions[sessions.index(day) + 1]
                exit_date, reason = nxt, "stop"
                payoff = 0.0
                for kind, k, side in legs:
                    price = exit_price(chain, nxt, day, expiry, kind, k)
                    px, c = fill(price, "buy" if side == "sell" else "sell", lot, p, mult)
                    payoff += px if side == "sell" else -px
                    costs += c
                break
    if payoff is None:                        # settle at expiry against the index close
        if expiry not in nifty_close.index:
            return None
        settle = float(nifty_close[expiry])
        payoff = 0.0
        for kind, k, side in legs:
            v = intrinsic(kind, k, settle)
            payoff += v if side == "sell" else -v
            if side == "buy" and v > 0:
                costs += v * p.stt_exercise_pct / 100 * mult
    pnl = credit - payoff - costs
    if strategy == "iron_condor":
        width = max(legs[2][1] - legs[0][1], legs[1][1] - legs[3][1])
        risk = width - credit
    elif strategy == "short_strangle":
        risk = p.strangle_stop_mult * credit
    else:
        risk = spot
    return {"strategy": strategy, "signal_date": t, "entry_date": t1, "exit_date": exit_date, "expiry": expiry,
            "spot": spot, "straddle": d, "legs": ";".join(f"{s} {k:g}{c}" for c, k, s in legs), "credit": credit,
            "payoff": payoff, "costs": costs, "pnl": pnl, "risk": risk, "r_multiple": pnl / risk if risk > 0 else np.nan,
            "reason": reason, "lot": lot}


def monthly_trades(strategy: str, chain: Chain, nifty_close: pd.Series, sessions: list, p: Params = Params(),
                   mult: float = 1.0) -> pd.DataFrame:
    expiries = [e for e in chain.monthly_expiries() if e in set(sessions)]
    out = []
    for prev, nxt in zip(expiries, expiries[1:]):
        after = [s for s in sessions if s > prev]
        if not after:
            continue
        r = run_cycle(strategy, chain, nifty_close, sessions, after[0], nxt, p, mult)
        if r:
            out.append(r)
    return pd.DataFrame(out)


def long_call_trades(chain: Chain, nifty: pd.DataFrame, trend: pd.Series, sessions: list, p: Params = Params(),
                     mult: float = 1.0) -> pd.DataFrame:
    """`nifty`: index bars (high, low, close) indexed by date; `trend`: regime trend per date."""
    hi = nifty["high"].shift(1).rolling(p.lc_breakout, min_periods=p.lc_breakout).max()
    lo = nifty["low"].shift(1).rolling(p.lc_exit_low, min_periods=p.lc_exit_low).min()
    expiries = chain.monthly_expiries()
    pos = {s: i for i, s in enumerate(sessions)}
    out, open_ = [], None
    for i, t in enumerate(sessions[:-1]):
        t1 = sessions[i + 1]
        if open_ is not None:
            left = pos[open_["expiry"]] - i
            if nifty.loc[t, "close"] < lo.get(t, np.nan) or left <= p.lc_exit_sessions:
                price = exit_price(chain, t1, t, open_["expiry"], "CE", open_["strike"])
                px, c = fill(price, "sell", open_["lot"], p, mult)
                pnl = px - open_["entry_px"] - open_["costs"] - c
                risk = open_["entry_px"] + open_["costs"]
                out.append({"strategy": "long_call", "signal_date": open_["signal_date"], "entry_date": open_["entry_date"],
                            "exit_date": t1, "expiry": open_["expiry"], "spot": open_["spot"],
                            "legs": f"buy {open_['strike']:g}CE", "credit": -open_["entry_px"], "payoff": -px,
                            "costs": open_["costs"] + c, "pnl": pnl, "risk": risk, "r_multiple": pnl / risk,
                            "reason": "exit low" if left > p.lc_exit_sessions else "near expiry", "lot": open_["lot"]})
                open_ = None
            continue
        if not (trend.get(t) == "up" and nifty.loc[t, "close"] > hi.get(t, np.nan)):
            continue
        exp = next((e for e in expiries if e in pos and pos[e] - i >= p.lc_min_sessions), None)
        if exp is None:
            continue
        calls = chain.strikes(t, exp, "CE", traded_only=False).index
        if not len(calls):
            continue
        spot = float(nifty.loc[t, "close"])
        k = float(calls[np.argmin(np.abs(calls.to_numpy() - spot))])
        lot = chain.lot_size(t1)
        q = chain.quote(t1, exp, "CE", k)
        if not lot or np.isnan(lot) or q is None or not q["traded"] or q["open"] <= 0:
            continue
        px, c = fill(float(q["open"]), "buy", lot, p, mult)
        open_ = {"signal_date": t, "entry_date": t1, "expiry": exp, "strike": k, "entry_px": px, "costs": c,
                 "lot": lot, "spot": spot}
    return pd.DataFrame(out)
