import json
from datetime import date, datetime, timezone

import pytest

from trading_research.live import intraday_scan as s

P = s.Params()


def quote(symbol="AAA", ltp=1000.0, o=990.0, h=1001.0, lo=985.0, pc=985.0, value=50.0, ts="2026-11-02 09:33:00",
          series="EQ"):
    return {"symbol": symbol, "series": series, "lastTradedPrice": ltp, "openPrice": o, "highPrice": h,
            "lowPrice": lo, "preClosePrice": pc, "perChange": round((ltp / pc - 1) * 100, 2), "value": value,
            "volume": 1000, "latestTimestamp": ts}


def daily(n=20, close=985.0, rng=60.0):
    """n synthetic daily bars, each with true range `rng`, ending at `close`."""
    bars = [{"date": f"2026-10-{i + 1:02d}", "open": close, "high": close + rng / 2, "low": close - rng / 2,
             "close": close} for i in range(n)]
    bars[-1]["high"] = close + 5
    return bars


def test_quote_screen_applies_each_filter_and_ranks_by_value():
    good = quote("GOOD", value=80)
    also = quote("ALSO", value=20)
    rejects = [quote("THIN", value=5), quote("CHEAP", ltp=50, o=49.5, h=50.1, lo=49, pc=49.2),
               quote("FLAT", ltp=986, o=985, h=986.5, pc=985), quote("GAPPER", o=1012, ltp=1013, h=1013.5, pc=985),
               quote("FADING", ltp=995, h=1005), quote("BELOWOPEN", ltp=995, o=998, h=999),
               quote("NIFTYBEES"), quote("SMEX", series="SM")]
    assert [q["symbol"] for q in s.quote_screen([also, good] + rejects)] == ["GOOD", "ALSO"]


def test_plan_sets_opening_range_levels():
    idea, why = s.plan(quote(), daily(), P)
    assert why == "ok"
    assert idea["entry"] == 1001.55          # 0.05% above 1001, rounded up to the tick
    assert idea["stop"] == 984.95            # one tick under the opening-range low
    assert idea["target"] == pytest.approx(1001.55 + 1.5 * (1001.55 - 984.95), abs=0.05)
    assert idea["atr14"] == round((13 * 60 + 35) / 14, 2)   # last bar: high close+5, low close-30


@pytest.mark.parametrize("q,bars,reason", [
    (quote(pc=980), daily(), "history close"),
    (quote(), daily(n=10), "fewer than 15"),
    (quote(ltp=989, h=989.5), daily(), "not above"),
    (quote(lo=900), daily(), "outside"),                       # range too wide for 0.5 ATR
    (quote(lo=999.5, h=1001), daily(rng=200), "outside"),      # range too narrow for 0.15 ATR
])
def test_plan_rejects(q, bars, reason):
    idea, why = s.plan(q, bars, P)
    assert idea is None and reason in why


def test_quantity_caps_by_risk_and_cash():
    assert s.quantity(1180, 1166, 17600) == 6
    assert s.quantity(9845, 9745, 17600) == 0             # 88 / 100 rounds down to 0
    assert s.quantity(100, 99.9, 10000) == 100               # cash cap, not 500 by risk


def test_grade_resolves_ambiguity_against_the_idea():
    idea = {"symbol": "AAA", "entry": 100.0, "stop": 98.0, "target": 103.0}
    bar = lambda h, lo, c: {"open": 99, "high": h, "low": lo, "close": c}
    assert s.grade(idea, bar(99.9, 97, 98))["outcome"] == "not triggered"
    assert s.grade(idea, bar(104, 97.5, 103))["outcome"] == "stop"          # both touched -> stop
    won = s.grade(idea, bar(104, 98.5, 103))
    assert won["outcome"] == "target" and won["gross_r"] == 1.5 and won["r"] < 1.5
    timed = s.grade(idea, bar(101, 98.5, 101))
    assert timed["outcome"] == "time exit (close)" and timed["gross_r"] == 0.5
    assert s.grade(idea, bar(104, 98.5, 103), cost_mult=2)["r"] < won["r"]


def fake_transport(stocks, history):
    def transport(url, payload, session_id):
        if payload.get("method") != "tools/call":
            return 200, {"mcp-session-id": "x"}, json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        name, args = payload["params"]["name"], payload["params"]["arguments"]
        if name == "cm_get_equity_stocks":
            hits = [q for q in stocks if q["symbol"].startswith(args["symbolFilter"])]
            body = {"returned": len(hits), "stocks": hits}
        else:
            body = {"data": history.get(args["symbol"], [])}
        text = json.dumps(body)
        return 200, {}, json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": text}]}})
    return transport


NOW = datetime(2026, 11, 2, 4, 5, tzinfo=timezone.utc)      # 09:35 IST


def test_scan_end_to_end_caps_ideas_and_sizes():
    stocks = [quote(f"S{i}", value=100 - i) for i in range(4)]
    t = fake_transport(stocks, {f"S{i}": daily() for i in range(4)})
    r = s.scan(NOW, t, capital=100000)
    assert r["status"] == "WATCHLIST" and [i["symbol"] for i in r["ideas"]] == ["S0", "S1"]
    assert r["ideas"][0]["qty"] == 30                          # 500 / 16.6 risk
    assert "WATCHLIST" in s.render(r)


def test_scan_stale_quotes_give_data_insufficient():
    t = fake_transport([quote(ts="2026-10-30 15:29:59")], {})
    r = s.scan(NOW, t)
    assert r["status"] == "DATA INSUFFICIENT" and r["ideas"] == []


def test_scan_with_nothing_passing_is_no_trade():
    t = fake_transport([quote(ltp=986, h=986.5)], {})
    assert s.scan(NOW, t)["status"] == "NO TRADE"


def test_score_reads_that_days_bar():
    ideas = {"ideas": [{"symbol": "AAA", "entry": 100.0, "stop": 98.0, "target": 103.0}]}
    t = fake_transport([], {"AAA": [{"date": "2026-11-02", "open": 99, "high": 103.5, "low": 98.5, "close": 103}]})
    out = s.score(date(2026, 11, 2), ideas, t)
    assert out["graded"][0]["outcome"] == "target" and out["graded"][0]["r_2x_costs"] < out["graded"][0]["r"]
    out = s.score(date(2026, 11, 3), ideas, t)
    assert "no EOD bar" in out["graded"][0]["outcome"]
