"""Daily report gates and validator. All inputs are SYNTHETIC fixtures, not market data."""

import copy

import pandas as pd
import pytest

from trading_research.config import load_settings
from trading_research.paper_trading.journal import Journal
from trading_research.paper_trading.simulator import PaperBroker
from trading_research.reporting import daily

DAY = pd.Timestamp("2026-10-22")


@pytest.fixture
def broker(tmp_path):
    return PaperBroker(Journal(tmp_path / "journal"), copy.deepcopy(load_settings()))


def universe(**overrides):
    row = {"candidate": True, "inputs_complete": True, "higher_tf": True, "context_rule": "close > SMA200",
           "setup_ok": True, "confirm_ok": True, "stop": 95.0, "close": 100.0, "rs": 0.1, "exit_signal": False}
    row.update(overrides)
    idx = pd.bdate_range(end=DAY, periods=30)
    f = pd.DataFrame([row] * 30, index=idx)
    bars = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}, index=idx)
    u = daily.Universe()
    u.features[("pa_pullback", "AAA")] = f
    u.bars["AAA"] = bars
    u.gate1["AAA"] = pd.Series(True, index=idx)
    return u


def regime(trend):
    return pd.DataFrame({"trend": [trend]}, index=[DAY])


def test_missing_input_is_data_insufficient(broker):
    (c,) = daily.evaluate_candidates(DAY.date(), universe(inputs_complete=False), regime("up"), broker,
                                     broker.settings)
    assert c["status"] == "DATA INSUFFICIENT" and c["failed_gate"] == 1


def test_regime_not_up_is_rejected(broker):
    (c,) = daily.evaluate_candidates(DAY.date(), universe(), regime("down"), broker, broker.settings)
    assert c["status"] == "REJECTED" and c["failed_gate"] == 2


def test_without_event_screen_a_setup_cannot_become_a_trade_candidate(broker):
    (c,) = daily.evaluate_candidates(DAY.date(), universe(), regime("up"), broker, broker.settings)
    assert c["status"] == "DATA INSUFFICIENT" and c["failed_gate"] == 7
    assert c["gates"][6]["pass"] and c["quantity"] > 0 and c["planned_risk_inr"] <= 5_000
    assert not c["gates"][8]["pass"]  # pa_pullback is REJECTED in the registry


def test_missing_confirmation_is_watchlist(broker):
    (c,) = daily.evaluate_candidates(DAY.date(), universe(confirm_ok=False), regime("up"), broker,
                                     broker.settings)
    assert c["status"] == "WATCHLIST" and c["failed_gate"] == 5


def test_registry_status_lookup():
    assert daily.registry_status("EXP-0006") == "REJECTED"
    assert daily.registry_status("EXP-9999") == "unregistered"


def test_validator_flags_missing_sections_and_banned_phrases():
    good = "\n".join(f"## {s}\ntext" for s in daily.SECTIONS) + "\n**NO TRADE**\n"
    assert daily.validate_report(good) == []
    bad = good.replace("## 7. Gate results", "") + "\nA high probability setup."
    problems = daily.validate_report(bad)
    assert any("Gate results" in p for p in problems) and any("high probability" in p for p in problems)
