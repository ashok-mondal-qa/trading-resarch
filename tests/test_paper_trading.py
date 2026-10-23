"""Journal and paper broker tests. Prices are SYNTHETIC fixtures, not market data."""

import copy
import json

import pytest

from trading_research.backtesting.costs import leg_costs
from trading_research.config import load_settings
from trading_research.paper_trading.guard import LiveTradingDisabled, get_broker
from trading_research.paper_trading.journal import Journal, JournalError
from trading_research.paper_trading.simulator import PaperBroker, PaperOrderRejected


@pytest.fixture
def settings():
    s = copy.deepcopy(load_settings())
    s["execution_model"]["slippage_bps_per_side"] = 0
    return s


@pytest.fixture
def broker(tmp_path, settings):
    return PaperBroker(Journal(tmp_path / "journal"), settings)


def candidate(journal, symbol="AAA", stop=95.0, status="TRADE CANDIDATE"):
    return journal.append("signal", "test_strategy", "0.1", {
        "symbol": symbol, "signal_date": "2026-10-22", "stop": stop, "status": status})


def bar(o, h, low, c):
    return {"open": o, "high": h, "low": low, "close": c}


def test_hash_chain_detects_edits(tmp_path):
    j = Journal(tmp_path)
    candidate(j)
    j.append("lesson", "test_strategy", "0.1", {"text": "x"})
    assert j.verify() == []
    path = j.files()[0]
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["data"]["stop"] = 90.0
    path.write_text("\n".join([json.dumps(tampered, sort_keys=True)] + lines[1:]) + "\n")
    assert any("hash" in p for p in j.verify())


def test_strategy_version_mandatory_and_types_checked(tmp_path):
    j = Journal(tmp_path)
    with pytest.raises(JournalError):
        j.append("signal", "s", "", {})
    with pytest.raises(JournalError):
        j.append("guess", "s", "0.1", {})


def test_only_trade_candidates_become_orders(broker):
    sig = candidate(broker.journal, status="WATCHLIST")
    with pytest.raises(PaperOrderRejected):
        broker.submit(sig["id"])


def test_fill_at_next_open_then_stop(broker, settings):
    sig = candidate(broker.journal)
    broker.submit(sig["id"])
    broker.process_session("2026-10-23", {"AAA": bar(101, 103, 100, 102)})
    (pos,) = broker.open_positions()
    assert pos.entry == 101 and pos.stop == 95 and pos.planned_risk <= 5_000
    broker.process_session("2026-10-26", {"AAA": bar(100, 101, 94, 96)})
    assert broker.open_positions() == []
    exit_ = [r for r in broker.journal.records() if r["type"] == "exit"][0]["data"]
    qty = pos.qty
    expected = (95 - 101) * qty - leg_costs("buy", 101, qty, settings["costs"]).total \
        - leg_costs("sell", 95, qty, settings["costs"]).total
    assert exit_["reason"] == "stop" and exit_["pnl_inr"] == pytest.approx(expected)
    assert broker.journal.verify() == []


def test_gap_through_stop_fills_at_open(broker):
    broker.submit(candidate(broker.journal)["id"])
    broker.process_session("2026-10-23", {"AAA": bar(101, 103, 100, 102)})
    broker.process_session("2026-10-26", {"AAA": bar(90, 91, 88, 90)})
    exit_ = [r for r in broker.journal.records() if r["type"] == "exit"][0]["data"]
    assert exit_["reason"] == "stop (gap)" and exit_["price"] == 90 and exit_["r_multiple"] < -1


def test_order_cancelled_when_open_below_stop(broker):
    broker.submit(candidate(broker.journal)["id"])
    out = broker.process_session("2026-10-23", {"AAA": bar(94, 96, 93, 95)})
    assert out[0]["type"] == "deviation" and out[0]["data"]["reason"] == "opened at/below stop"
    assert broker.pending_orders() == [] and broker.open_positions() == []


def test_no_averaging_down_and_no_stop_widening(broker):
    sig = candidate(broker.journal)
    broker.submit(sig["id"])
    with pytest.raises(PaperOrderRejected):
        broker.submit(candidate(broker.journal)["id"])
    broker.process_session("2026-10-23", {"AAA": bar(101, 103, 100, 102)})
    (pos,) = broker.open_positions()
    with pytest.raises(PaperOrderRejected):
        broker.raise_stop(pos.fill_id, 90.0)
    broker.raise_stop(pos.fill_id, 98.0)
    assert broker.open_positions()[0].stop == 98.0


def test_exit_due_fills_at_open(broker):
    broker.submit(candidate(broker.journal)["id"])
    broker.process_session("2026-10-23", {"AAA": bar(101, 103, 100, 102)})
    broker.process_session("2026-10-26", {"AAA": bar(104, 105, 103, 104)}, exits_due={"AAA": "exit signal"})
    exit_ = [r for r in broker.journal.records() if r["type"] == "exit"][0]["data"]
    assert exit_["reason"] == "exit signal" and exit_["price"] == 104


def test_split_rescales_stop_and_quantity(broker):
    broker.submit(candidate(broker.journal)["id"])
    broker.process_session("2026-10-23", {"AAA": bar(101, 103, 100, 102)})
    qty = broker.open_positions()[0].qty
    # 1:1 bonus: raw prices halve; without rescaling this would read as a gap through the stop
    broker.process_session("2026-10-26", {"AAA": bar(51, 52, 50.5, 51.5)}, factors={"AAA": 0.5})
    (pos,) = broker.open_positions()
    assert pos.stop == 47.5 and pos.qty == qty * 2 and pos.entry == 50.5


def test_aggregate_cap_allows_four_full_positions(broker):
    for s in "ABCDE":
        broker.submit(candidate(broker.journal, symbol=s)["id"])
    out = broker.process_session("2026-10-23", {s: bar(100, 101, 99, 100) for s in "ABCDE"})
    assert len(broker.open_positions()) == 4
    assert out[-1]["data"]["reason"] == "aggregate cap: no room for a full position"
    assert broker.open_planned_risk() <= 20_000


def test_guard_still_refuses_non_paper():
    with pytest.raises(LiveTradingDisabled):
        get_broker("live")
    assert get_broker().is_paper
