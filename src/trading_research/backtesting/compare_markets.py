"""Indian equities vs crypto over the common window (spec docs/strategy-specifications/crypto-comparison.md,
"Market comparison"). Descriptive only: nothing here passes or fails a strategy.

    python -m trading_research.backtesting.compare_markets

For each market: buy and hold, 200-day trend timing of the index (NIFTY 50 / BTCUSDT), an equal-weight basket of
the 10 most liquid coins, and each strategy's capped portfolio; before and after Indian tax (assumed rates, see
the spec). Fully invested yardsticks have no stop and do not meet the paper risk policy.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from trading_research.backtesting import engine
from trading_research.backtesting import run_crypto as rc
from trading_research.backtesting import run_social as rs
from trading_research.backtesting import run_swing_ideas2 as rs2
from trading_research.backtesting.costs import leg_costs
from trading_research.backtesting.run_baseline import REPORT_DIR, select
from trading_research.config import REPO_ROOT, load_settings
from trading_research.data import binance, indices
from trading_research.indicators import core
from trading_research.strategies import swing_ideas2 as s2

WINDOW = ("2018-04-01", "2024-12-31")
CRYPTO_TAX = 0.312               # 30% + 4% cess on each profitable transfer, no loss set-off (assumption)
EQUITY_STCG = 0.208              # 20% + 4% cess (s.111A, from 23 Jul 2024; applied throughout)
EQUITY_LTCG = 0.13               # 12.5% + 4% cess above the yearly exemption (s.112A)
LTCG_EXEMPTION_INR = 125_000
EQUITY_START_INR = 1_000_000
SLIP = 0.001                     # 10 bps per side, both markets
BASKET_SIZE = 10


# ---------------------------------------------------------------- stats

def stats(equity: pd.Series, periods: int) -> dict:
    s = rc.annual_stats(equity, periods)
    yearly = equity.groupby(equity.index.year).last() / equity.groupby(equity.index.year).first() - 1
    s["calendar_years"] = {str(y): float(v) for y, v in yearly.items()}
    s["worst_year"] = float(yearly.min())
    s["positive_years"] = f"{int((yearly > 0).sum())}/{len(yearly)}"
    return s


def apply_taxes(equity: pd.Series, taxes: pd.Series) -> pd.Series:
    """After-tax curve: each tax payment scales all later equity by (1 - tax / equity that day), i.e. sizes
    follow equity, as in every strategy here."""
    factor = pd.Series(1.0, index=equity.index)
    for d, tax in taxes[taxes > 0].items():
        d = equity.index[equity.index.searchsorted(d)] if d not in equity.index else d
        factor.loc[d:] *= max(0.0, 1 - tax / equity.loc[d])
    return equity * factor


def crypto_tax(trades: pd.DataFrame) -> pd.Series:
    """31.2% of every profitable sale, paid on the exit date; losses never offset."""
    gains = trades["pnl"].clip(lower=0) * CRYPTO_TAX
    return gains.groupby(pd.to_datetime(trades["exit_date"])).sum()


def _fy_end(d: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(d.year + (d.month > 3), 3, 31)


def equity_tax(trades: pd.DataFrame, last_day: pd.Timestamp) -> pd.Series:
    """Indian listed-equity capital-gains tax per financial year (Apr-Mar): short term (held under 365 days)
    20.8% and long term 13% above ₹1.25 lakh, with losses set off and carried forward (short-term losses
    against either, long-term only against long-term). Paid at the year's end (or the window's last day)."""
    t = trades.copy()
    t["exit_date"], t["entry_date"] = pd.to_datetime(t["exit_date"]), pd.to_datetime(t["entry_date"])
    t["long"] = (t["exit_date"] - t["entry_date"]).dt.days >= 365
    st_carry = lt_carry = 0.0
    out = {}
    for fy, g in t.groupby(t["exit_date"].map(_fy_end)):
        st = g.loc[~g["long"], "pnl"].sum() + st_carry
        lt = g.loc[g["long"], "pnl"].sum() + lt_carry
        st_carry = lt_carry = 0.0
        if st < 0:                       # short-term loss offsets long-term gains, rest carries
            lt, st = lt + st, 0.0
            if lt < 0:
                st_carry, lt = lt, 0.0
        if lt < 0:
            lt_carry, lt = lt, 0.0
        tax = st * EQUITY_STCG + max(lt - LTCG_EXEMPTION_INR, 0.0) * EQUITY_LTCG
        if tax > 0:
            out[min(fy, last_day)] = tax
    return pd.Series(out, dtype=float)


def summarize(name: str, market: str, equity: pd.Series, taxes: pd.Series, periods: int, note: str = "") -> dict:
    after = apply_taxes(equity, taxes)
    return {"name": name, "market": market, "note": note, "before_tax": stats(equity, periods),
            "after_tax": stats(after, periods), "tax_paid_pct_of_start": float(taxes.sum() / equity.iloc[0])}


# ---------------------------------------------------------------- fully invested yardsticks

def timing_curve(close: pd.Series, cost_per_side: float, start_value: float, trend: bool):
    """Position p_t after the close of day t. Timing: p_t = 1 if close > SMA200 at t-1 (one bar of delay), else
    0; buy and hold: p_t = 1 from the window's first close. Equity earns p_(t-1) x the day's return and pays
    cost_per_side on every change of p. Returns the curve and its round trips (the last one liquidated at the
    window end, for tax)."""
    sma = core.sma(close, 200)
    p = (close > sma).astype(float).shift(1).fillna(0.0) if trend else pd.Series(1.0, index=close.index)
    window = close.index >= pd.Timestamp(WINDOW[0])
    close, p = close[window], p[window]
    ret = close.pct_change().fillna(0.0)
    change = p.diff().abs()
    change.iloc[0] = p.iloc[0]
    equity = start_value * ((1 + p.shift(1).fillna(0.0) * ret) * (1 - change * cost_per_side)).cumprod()
    trips, entry = [], None
    for d, x, prev in zip(p.index, p, p.shift(1).fillna(0.0)):
        if x == 1 and prev == 0:
            entry = (d, equity.loc[d])
        elif x == 0 and prev == 1 and entry:
            trips.append({"entry_date": entry[0], "exit_date": d, "pnl": equity.loc[d] - entry[1]})
            entry = None
    if entry:
        trips.append({"entry_date": entry[0], "exit_date": p.index[-1], "pnl": equity.iloc[-1] - entry[1]})
    return equity, pd.DataFrame(trips, columns=["entry_date", "exit_date", "pnl"])


def crypto_basket(root: Path, end: pd.Timestamp, cost_per_side: float):
    """Equal weight in the 10 instruments with the highest 20-day median quote volume (liquid, gate-1 clean,
    not in a delisted piece's last 7 bars), chosen at each week's first close and bought at the next close,
    then held (weights drift) until the next rebalance. A coin that stops trading is valued at its last
    close. Tax upper bound: 31.2% of every positive coin-week, as if each week's gain were realised."""
    from trading_research.data import quality
    btc = binance.read_bars(rc.BENCHMARK, root).set_index("date")["close"]
    calendar = list(pd.date_range(btc.index.min(), end, freq="D"))
    closes, eligible, volume = {}, {}, {}
    for path in sorted((root / "processed" / binance.DATASET).glob("*.parquet")):
        for name, bars, gone in rc.segments(pd.read_parquet(path), path.stem, end):
            mtv = core.median_traded_value(bars["traded_value"], 20)
            ok = (mtv >= rc.MIN_QUOTE_VOLUME) & quality.gate1_series(bars.index, bars["volume"], calendar)
            if gone:
                ok.iloc[-rc.DELIST_NO_SIGNAL_BARS:] = False
            closes[name], eligible[name], volume[name] = bars["close"], ok, mtv
    close = pd.DataFrame(closes).sort_index().loc[:end]
    held_px = close.ffill()                                   # last close stands after a coin stops trading
    rank = pd.DataFrame(volume).reindex(close.index).where(pd.DataFrame(eligible).reindex(close.index).fillna(False).astype(bool))
    days = close.index[close.index >= pd.Timestamp(WINDOW[0])]
    starts = [d for d in s2.week_starts(close.index) if d >= days[0] - pd.Timedelta(days=1)]
    trade_days = [days[days.searchsorted(d + pd.Timedelta(days=1))] for d in starts
                  if days.searchsorted(d + pd.Timedelta(days=1)) < len(days)]
    choice = {t: rank.loc[d].dropna().nlargest(BASKET_SIZE).index for d, t in zip(starts, trade_days)}
    value, curve, taxes, weights = 1.0, {}, {}, pd.Series(dtype=float)
    for d in days[days < trade_days[0]]:
        curve[d] = value
    for k, t in enumerate(trade_days):
        nxt = trade_days[k + 1] if k + 1 < len(trade_days) else days[-1]
        target = pd.Series(1.0 / len(choice[t]), index=choice[t]) if len(choice[t]) else pd.Series(dtype=float)
        turnover = target.subtract(weights, fill_value=0.0).abs().sum()
        value *= 1 - turnover * cost_per_side
        span = days[(days >= t) & (days <= nxt)]
        if len(target):
            rel = held_px.loc[span, target.index] / held_px.loc[t, target.index]
            path = (rel * target).sum(axis=1) * value
            gains = (rel.iloc[-1] - 1) * target * value
            taxes[nxt] = float(gains.clip(lower=0).sum() * CRYPTO_TAX)
            weights = rel.iloc[-1] * target / (rel.iloc[-1] * target).sum()
        else:
            path, weights = pd.Series(value, index=span), pd.Series(dtype=float)
        for d, v in path.items():
            curve[d] = v
        value = float(path.iloc[-1])
    return pd.Series(curve).sort_index(), pd.Series(taxes)


# ---------------------------------------------------------------- capped strategy portfolios

def slice_curve(equity: pd.Series, trades: pd.DataFrame):
    e = equity[(equity.index >= pd.Timestamp(WINDOW[0])) & (equity.index <= pd.Timestamp(WINDOW[1]))]
    t = trades[(pd.to_datetime(trades["exit_date"]) >= e.index[0]) & (pd.to_datetime(trades["exit_date"]) <= e.index[-1])]
    return e, t


def nse_momentum_common(root: Path):
    """EXP-0014's rules over the comparison window (its own runner has no split for it)."""
    rs2.SPLITS["common"] = WINDOW
    start, end, data_end, calendar, nifty, reg, split_calendar = rs2._context("common", root)
    p = s2.Params()
    frames, signals, _ = rs2.load_universe(root, data_end, nifty, calendar, p, ("momentum_weekly",))
    cands, _ = select(signals["momentum_weekly"], reg["trend"], start, end, p, False)
    res = engine.run(frames["momentum_weekly"], cands, split_calendar, load_settings(), EQUITY_START_INR,
                     p.max_holding("momentum_weekly"))
    return res.equity, res.trades


def main(root: Path = REPO_ROOT / "data") -> int:
    end = pd.Timestamp(WINDOW[1])
    rows = []
    # Indian equities
    settings = load_settings()
    nifty = indices.read_index("Nifty 50", date(2016, 1, 1), end.date(), root)["close"]
    nifty_side = leg_costs("buy", 1000.0, 1000, settings["costs"]).total / 1e6 + SLIP
    for trend, label in ((False, "NIFTY 50 buy and hold"), (True, "NIFTY 50 200-day timing")):
        eq, trips = timing_curve(nifty, nifty_side, EQUITY_START_INR, trend)
        rows.append(summarize(label, "India equity", eq, equity_tax(trips, eq.index[-1]), 252,
                              "price index (dividends excluded); fully invested, no stop"))
    for strategy, exp in rs.EXPERIMENTS.items():
        eq = pd.read_csv(REPORT_DIR / f"{exp}-dev-equity.csv", index_col=0, parse_dates=True).iloc[:, 0]
        tr = pd.read_csv(REPORT_DIR / f"{exp}-dev-trades.csv")
        e, t = slice_curve(eq, tr)
        rows.append(summarize(f"{strategy} (capped)", "India equity", e, equity_tax(t, e.index[-1]), 252,
                              f"{exp} portfolio, 1x costs, sliced from the 2013-2025 run"))
    eq, tr = nse_momentum_common(root)
    rows.append(summarize("momentum_weekly (capped)", "India equity", eq, equity_tax(tr, eq.index[-1]), 252,
                          "EXP-0014 rules over the window, 1x costs"))
    # Crypto
    btc = binance.read_bars(rc.BENCHMARK, root).set_index("date")["close"]
    btc = btc[btc.index <= end]
    crypto_side = leg_costs("buy", 1000.0, 1000, rc.CRYPTO_COSTS).total / 1e6 + SLIP
    for trend, label in ((False, "BTC buy and hold"), (True, "BTC 200-day timing")):
        eq, trips = timing_curve(btc, crypto_side, 1.0, trend)
        rows.append(summarize(label, "crypto", eq, crypto_tax(trips), 365, "fully invested, no stop"))
    eq, taxes = crypto_basket(root, end, crypto_side)
    rows.append(summarize("Top-10 liquid coins, equal weight, weekly", "crypto", eq, taxes, 365,
                          "fully invested, no stop; tax is an upper bound (every positive coin-week taxed)"))
    for strategy, exp in rc.EXPERIMENTS.items():
        path = REPORT_DIR / f"{exp}-common-equity.csv"
        if not path.exists():
            continue
        eq = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
        tr = pd.read_csv(REPORT_DIR / f"{exp}-common-trades.csv")
        rows.append(summarize(f"{strategy} (capped)", "crypto", eq, crypto_tax(tr) if len(tr) else pd.Series(dtype=float),
                              365, f"{exp} portfolio over the window, 1x costs"))
    out = {"window": WINDOW, "tax_assumptions": {"crypto": CRYPTO_TAX, "equity_stcg": EQUITY_STCG,
           "equity_ltcg": EQUITY_LTCG, "ltcg_exemption_inr": LTCG_EXEMPTION_INR},
           "cost_per_side": {"india_equity": nifty_side, "crypto": crypto_side}, "rows": rows}
    (REPORT_DIR / "market-comparison.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    for r in rows:
        b, a = r["before_tax"], r["after_tax"]
        print(f"{r['market']:12} {r['name']:44} CAGR {b['cagr']:+.1%} -> {a['cagr']:+.1%} after tax | vol {b['ann_vol']:.1%}"
              f" | Sharpe {b['sharpe_rf0']:.2f} -> {a['sharpe_rf0']:.2f} | maxDD {b['max_drawdown']:.1%} | worst yr"
              f" {b['worst_year']:+.1%} | up yrs {b['positive_years']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
