import io
import zipfile

import pandas as pd
import pytest

from trading_research.backtesting import run_options as ro
from trading_research.data import fo_bhavcopy
from trading_research.strategies import options as op

DAYS = list(pd.bdate_range("2020-01-01", periods=40))
E1, E2 = DAYS[4], DAYS[25]
STRIKES = range(700, 1301, 50)


def base_price(strike: float) -> float:
    return max(5.0, 50 - abs(strike - 1000) / 5)


def make_rows(overrides=None, untraded=()):
    """Option rows for expiries E1 and E2 and a NIFTY future (lot 50). `overrides[(day, kind, strike)]` sets
    open/close/settle; `untraded` lists (day, kind, strike) with zero OHLC."""
    overrides = overrides or {}
    rows = []
    for day in DAYS:
        for expiry in (E1, E2):
            if day > expiry:
                continue
            for kind in ("CE", "PE"):
                for k in STRIKES:
                    px = overrides.get((day, kind, k), base_price(k))
                    dead = (day, kind, k) in untraded
                    rows.append({"date": day, "instrument": "OPT", "symbol": "NIFTY", "expiry": expiry, "strike": float(k),
                                 "option_type": kind, "open": 0 if dead else px, "high": 0 if dead else px,
                                 "low": 0 if dead else px, "close": 0 if dead else px, "settle": px, "contracts": 10,
                                 "value_lakh": 1.0, "open_interest": 100, "underlying": None, "lot_size": 50,
                                 "traded": not dead})
        rows.append({"date": day, "instrument": "FUT", "symbol": "NIFTY", "expiry": E2, "strike": 0.0,
                     "option_type": "XX", "open": 1000, "high": 1000, "low": 1000, "close": 1000, "settle": 1000,
                     "contracts": 10, "value_lakh": 5.0, "open_interest": 100, "underlying": None, "lot_size": 50,
                     "traded": True})
    return pd.DataFrame(rows)


def nifty_close(at_expiry=1000.0):
    s = pd.Series(1000.0, index=DAYS)
    s[E2] = at_expiry
    return s


def test_fill_and_costs():
    p = op.Params()
    assert op.fill(100, "buy", 50, p, 1)[0] == pytest.approx(101.5)
    assert op.fill(100, "sell", 50, p, 1)[0] == pytest.approx(98.5)
    assert op.fill(10, "sell", 50, p, 2)[0] == pytest.approx(8.0)          # 1 point floor, doubled
    sell, buy = op.leg_cost(100, "sell", 50, p), op.leg_cost(100, "buy", 50, p)
    assert sell > buy                                                     # STT on sells
    assert op.leg_cost(100, "sell", 50, p, 2) == pytest.approx(2 * sell)


def test_iron_condor_all_otm_keeps_credit():
    chain = op.Chain(make_rows())
    t = op.monthly_trades("iron_condor", chain, nifty_close(), DAYS)
    assert len(t) == 1
    row = t.iloc[0]
    assert row["entry_date"] == DAYS[6] and row["signal_date"] == DAYS[5]
    assert row["legs"] == "sell 1100CE;sell 900PE;buy 1200CE;buy 800PE"   # D = 50 + 50
    assert row["payoff"] == 0 and row["pnl"] == pytest.approx(row["credit"] - row["costs"])
    assert row["risk"] == pytest.approx(100 - row["credit"])


def test_strikes_use_only_signal_day_prices():
    later = {(DAYS[6], kind, k): 400.0 for kind in ("CE", "PE") for k in STRIKES}   # t+1 prices jump
    a = op.monthly_trades("iron_condor", op.Chain(make_rows()), nifty_close(), DAYS).iloc[0]
    b = op.monthly_trades("iron_condor", op.Chain(make_rows(later)), nifty_close(), DAYS).iloc[0]
    assert a["legs"] == b["legs"] and a["straddle"] == b["straddle"] and a["credit"] != b["credit"]


def test_settles_at_index_close_on_expiry():
    t = op.monthly_trades("iron_condor", op.Chain(make_rows()), nifty_close(1300.0), DAYS).iloc[0]
    assert t["payoff"] == pytest.approx(100)                              # call spread 1100/1200 fully in the money
    assert t["r_multiple"] < -1                                           # max loss plus exercise STT and costs


def test_untraded_leg_at_entry_skips_the_month():
    rows = make_rows(untraded={(DAYS[6], "PE", 800)})
    assert op.monthly_trades("iron_condor", op.Chain(rows), nifty_close(), DAYS).empty
    assert len(op.monthly_trades("short_strangle", op.Chain(rows), nifty_close(), DAYS)) == 1


def test_strangle_stop_exits_next_open():
    rows = make_rows({(DAYS[10], "CE", 1100): 200.0, (DAYS[11], "CE", 1100): 180.0})
    t = op.monthly_trades("short_strangle", op.Chain(rows), nifty_close(), DAYS).iloc[0]
    assert t["reason"] == "stop" and t["exit_date"] == DAYS[11]
    assert t["payoff"] == pytest.approx(180 * 1.015 + 31.0)               # buy back at open + slippage
    assert t["risk"] == pytest.approx(2 * t["credit"])


def test_covered_call_strike_and_cycle_returns():
    chain = op.Chain(make_rows())
    t = op.monthly_trades("covered_call", chain, nifty_close(1100.0), DAYS)
    assert t.iloc[0]["legs"] == "sell 1050CE" and t.iloc[0]["payoff"] == pytest.approx(50)
    nifty = pd.DataFrame({"close": nifty_close(1100.0)})
    c = ro.covered_call_cycles(chain, nifty, t).iloc[0]
    assert c["hold"] == pytest.approx(0.10)
    assert c["covered_call"] == pytest.approx((100 + t.iloc[0]["pnl"]) / 1000)


def test_long_call_breakout_and_exit():
    close = pd.Series(1000.0, index=DAYS)
    close[DAYS[22]] = 1010.0                                            # breakout above the 20-session high
    close[DAYS[24]] = 990.0                                             # close below the 10-session low
    nifty = pd.DataFrame({"high": close, "low": close, "close": close})
    trend = pd.Series("up", index=DAYS)
    rows = make_rows()
    t = op.long_call_trades(op.Chain(rows), nifty, trend, DAYS, op.Params(lc_min_sessions=2, lc_exit_sessions=0))
    assert len(t) == 1
    row = t.iloc[0]
    assert row["entry_date"] == DAYS[23] and row["exit_date"] == DAYS[25] and row["reason"] == "exit low"
    assert row["legs"] == "buy 1000CE" and row["risk"] > 50


def test_fo_tax_carries_losses_forward():
    pnl = pd.Series([-10.0, 30.0], index=pd.to_datetime(["2020-05-01", "2021-05-01"]))
    out = ro.fo_tax_curve(pnl, start=100.0)
    assert out["years"][2020]["tax"] == 0
    assert out["years"][2021]["tax"] == pytest.approx(0.312 * 20)
    assert out["end_equity"] == pytest.approx(120 - 0.312 * 20)


def test_verdict_rejects_without_enough_trades():
    good = {"trades": 59, "expectancy_r": 0.5, "profit_factor": 2.0, f"ci_{1 - ro.ALPHA:.4f}": (0.1, 0.9)}
    results = {"1x": {s: good for s in ro.SPLITS}, "2x": {s: good for s in ro.SPLITS}}
    assert ro.verdict("iron_condor", results)["status"] == "REJECTED"
    results["1x"]["dev"] = {**good, "trades": 60}
    assert ro.verdict("iron_condor", results)["status"] == "HOLDOUT CANDIDATE"


def test_holdout_not_loadable():
    assert ro.DATA_END.isoformat() < ro.HOLDOUT[0]
    assert all(end < ro.HOLDOUT[0] for _, end in ro.SPLITS.values())


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fo.csv", text)
    return buf.getvalue()


def test_legacy_parse_accepts_two_digit_years():
    header = "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP\n"
    long = header + "OPTIDX,NIFTY,31-May-2012,5000,CE,10,12,9,11,11,5,1.0,100,0,14-May-2012\n"
    short = header + "OPTIDX,NIFTY,31-May-12,5000,CE,10,12,9,11,11,5,1.0,100,0,14-May-12\n"
    for text in (long, short):
        df = fo_bhavcopy.parse(_zip(text), "legacy")
        assert df["date"].iloc[0] == pd.Timestamp("2012-05-14") and df["expiry"].iloc[0] == pd.Timestamp("2012-05-31")
    kept, excluded = fo_bhavcopy.validate(fo_bhavcopy.parse(_zip(short), "legacy"), pd.Timestamp("2012-05-14").date())
    assert len(kept) == 1 and kept["traded"].iloc[0] and not excluded


def test_udiff_parse_scales_turnover_not_contracts():
    header = ("TradDt,FinInstrmTp,TckrSymb,XpryDt,StrkPric,OptnTp,OpnPric,HghPric,LwPric,ClsPric,SttlmPric,"
              "TtlTradgVol,TtlTrfVal,OpnIntrst,UndrlygPric,NewBrdLotQty\n")
    text = header + "2024-08-01,IDO,NIFTY,2024-08-29,25000,CE,100,110,90,105,105,40,1000000,500,24900,25\n"
    df = fo_bhavcopy.parse(_zip(text), "udiff")
    assert df["contracts"].iloc[0] == 40 and df["value_lakh"].iloc[0] == pytest.approx(10.0)
    assert df["instrument"].iloc[0] == "OPT" and df["lot_size"].iloc[0] == 25
