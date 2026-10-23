"""Phase 10 end-to-end: a full simulated market, run through the daily pipeline day by day.

Everything is SYNTHETIC (prices, index, corporate actions): no network, no market data. The test builds a
data folder in the same layout as the real loaders, then runs `reporting.daily.run` for three sessions:

  day 1  AAA breaks out -> (with a stand-in event screen and the strategy marked ACCEPTED) TRADE CANDIDATE,
         journalled, simulated order for the next open
  day 2  the paper broker fills at the open; AAA may signal again but is refused (already held)
  day 3  the low touches the stop -> exit at the stop, loss about 1R after costs

With the repository's real gate 7 (no event screen) and real registry, the same day 1 gives NO TRADE.
"""

import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from trading_research.data import bhavcopy, indices
from trading_research.data import symbols as symbol_changes
from trading_research.paper_trading.guard import LiveTradingDisabled
from trading_research.paper_trading.journal import Journal
from trading_research.reporting import daily

DAYS = pd.bdate_range(end="2026-10-23", periods=360)
D1, D2, D3 = DAYS[-3], DAYS[-2], DAYS[-1]
NOW = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)  # 20:30 IST, after the files are out


def series(seed, drift, n=len(DAYS)):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.008, n)))
    open_ = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, 0.002, n))
    df = pd.DataFrame({"open": open_, "close": close}, index=DAYS)
    df["high"] = df[["open", "close"]].max(axis=1) * 1.004
    df["low"] = df[["open", "close"]].min(axis=1) * 0.996
    df["volume"] = 1_000_000.0
    return df


def market():
    aaa = series(1, 0.002)
    prior_high = aaa["high"].iloc[-23:-3].max()
    c1 = prior_high * 1.03                                  # day 1: close above the 20-session high
    aaa.loc[D1] = [aaa["close"].iloc[-4], c1, c1 * 1.002, aaa["close"].iloc[-4] * 0.998, 3_000_000.0]
    aaa.loc[D2] = [c1 * 1.002, c1 * 1.004, c1 * 1.01, c1 * 0.995, 1_000_000.0]
    aaa.loc[D3] = [c1 * 0.99, c1 * 0.85, c1 * 0.995, c1 * 0.84, 1_000_000.0]   # trades through the stop
    return {"AAA": aaa, "BBB": series(2, 0.0)}, series(3, 0.001)["close"] * 200


def write_store(root, stocks, nifty):
    store = bhavcopy.Store(root=root)
    for d in DAYS:
        rows = []
        for i, (sym, df) in enumerate(stocks.items()):
            r = df.loc[d]
            rows.append({"date": d, "symbol": sym, "series": "EQ", "isin": f"INE00000{i}01",
                         "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
                         "last": r["close"], "prev_close": np.nan, "volume": int(r["volume"]),
                         "traded_value": r["volume"] * r["close"], "trades": 1000})
        frame = pd.DataFrame(rows, columns=bhavcopy.COLUMNS)
        path = store.bars_path(d.date())
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        manifest = {"status": "ok", "source_url": "synthetic", "raw_sha256": "0" * 64,
                    "retrieved_at_utc": "2026-10-23T14:00:00+00:00"}
        bhavcopy._write_json(store.manifest_path(d.date()), manifest)
        p = indices.paths(root, d.date())
        p["bars"].parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"date": d, "index": "Nifty 50", "open": nifty[d], "high": nifty[d], "low": nifty[d],
                       "close": nifty[d], "volume": 0.0, "turnover_cr": 0.0, "pe": 0.0, "pb": 0.0,
                       "div_yield": 0.0}], columns=indices.COLUMNS).to_parquet(p["bars"], index=False)
        bhavcopy._write_json(p["manifest"], {"status": "ok"})
    ref = symbol_changes.raw_path(root)
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text("NAME OF THE COMPANY,OLD SYMBOL,NEW SYMBOL,EFFECTIVE DATE\n")


def no_actions(symbol, start, end, root):
    return {"symbol": symbol, "source": "synthetic", "retrieved_at_utc": None, "actions": []}


@pytest.fixture
def world(tmp_path):
    stocks, nifty = market()
    write_store(tmp_path / "data", stocks, nifty)
    return tmp_path


def run_day(world, day, **kw):
    return daily.run(day.date(), root=world / "data", fetch=False, now_utc=NOW,
                     journal=Journal(world / "journal"), report_dir=world / "reports",
                     fetch_actions=no_actions, **kw)


ACCEPT = {"event_screen": lambda s, d: (True, "stand-in event screen (test only)"),
          "status_of": lambda exp: "ACCEPTED" if exp == "EXP-0006" else "REJECTED"}


def test_full_simulated_cycle_signal_order_fill_exit(world):
    day1 = run_day(world, D1, **ACCEPT)
    assert day1["final_status"] == "TRADE CANDIDATE"
    assert {"symbol": "AAA", "strategy": "baseline_trend_breakout", "status": "TRADE CANDIDATE"} in day1["setups"]
    journal = Journal(world / "journal")
    kinds = [r["type"] for r in journal.records()]
    assert "signal" in kinds and kinds[-1] == "order"

    day2 = run_day(world, D2, **ACCEPT)
    fills = [r for r in journal.records() if r["type"] == "fill"]
    assert len(fills) == 1 and fills[0]["data"]["symbol"] == "AAA"
    assert fills[0]["data"]["price"] == pytest.approx(market()[0]["AAA"].loc[D2, "open"] * 1.001)
    assert all(s["status"] != "TRADE CANDIDATE" for s in day2["setups"] if s["symbol"] == "AAA")

    run_day(world, D3, **ACCEPT)
    exits = [r for r in journal.records() if r["type"] == "exit"]
    assert len(exits) == 1 and exits[0]["data"]["reason"] in ("stop", "stop (gap)")
    assert -1.3 < exits[0]["data"]["r_multiple"] < -0.9
    assert journal.verify() == []

    for d in (D1, D2, D3):
        text = (world / "reports" / f"{d.date()}.md").read_text()
        assert daily.validate_report(text) == []
    assert "AAA" in (world / "reports" / f"{D3.date()}.md").read_text()


def test_real_gates_give_no_trade(world):
    out = run_day(world, D1)
    assert out["final_status"] == "NO TRADE"
    aaa = [s for s in out["setups"] if s["symbol"] == "AAA" and s["strategy"] == "baseline_trend_breakout"]
    assert aaa and aaa[0]["status"] == "DATA INSUFFICIENT"   # gate 7: no event screen yet
    assert not [r for r in Journal(world / "journal").records() if r["type"] == "order"]


def test_missing_session_file_gives_data_insufficient(world):
    store = bhavcopy.Store(root=world / "data")
    store.manifest_path(D1.date()).unlink()
    out = run_day(world, D1, **ACCEPT)
    assert out["final_status"] == "DATA INSUFFICIENT" and out["setups"] == []
    text = (world / "reports" / f"{D1.date()}.md").read_text()
    assert daily.validate_report(text) == []


def test_live_mode_refused_before_anything_is_written(world, monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(LiveTradingDisabled):
        run_day(world, D1, **ACCEPT)
    assert not (world / "reports").exists() and not (world / "journal").exists()
