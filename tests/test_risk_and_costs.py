import pytest

from trading_research.backtesting.costs import leg_costs, round_trip_cost
from trading_research.config import load_settings
from trading_research.risk.sizing import SizingRejected, size_long_position


@pytest.fixture
def settings():
    return load_settings()


def test_buy_leg_costs_hand_computed(settings):
    # Rs 1,00,000 buy: STT 100, exchange 2.97, SEBI 0.10, stamp 15, GST 18% of 3.07 = 0.5526
    c = leg_costs("buy", 1000.0, 100, settings["costs"])
    assert c.stt == pytest.approx(100.0)
    assert c.exchange_txn == pytest.approx(2.97)
    assert c.sebi_fee == pytest.approx(0.10)
    assert c.stamp_duty == pytest.approx(15.0)
    assert c.gst == pytest.approx(0.5526)
    assert c.dp_charge == 0.0
    assert c.total == pytest.approx(118.6226)


def test_sell_leg_has_dp_charge_and_no_stamp(settings):
    c = leg_costs("sell", 1000.0, 100, settings["costs"])
    assert c.stamp_duty == 0.0
    assert c.dp_charge == pytest.approx(15.34)


def test_sizing_respects_half_percent_cap(settings):
    plan = size_long_position(1_000_000, 1_000_000, entry=500.0, stop=480.0,
                              open_planned_risk_inr=0.0, settings=settings)
    assert plan.planned_risk_inr <= 5_000.0
    assert plan.planned_risk_pct <= 0.5
    # one more share would breach the budget
    slip = settings["execution_model"]["slippage_bps_per_side"] / 10_000
    q = plan.quantity + 1
    risk_next = q * (20.0 + slip * 980.0) + round_trip_cost(500.0, 480.0, q, settings["costs"])
    assert risk_next > 5_000.0


def test_sizing_includes_costs_in_risk(settings):
    plan = size_long_position(1_000_000, 1_000_000, 500.0, 480.0, 0.0, settings)
    naive_qty = int(5_000 // 20)
    assert plan.quantity < naive_qty


def test_sizing_uses_remaining_aggregate_headroom(settings):
    plan = size_long_position(1_000_000, 1_000_000, 500.0, 480.0, open_planned_risk_inr=18_000.0,
                              settings=settings)
    assert plan.planned_risk_inr <= 2_000.0


def test_aggregate_cap_reached_is_rejected(settings):
    with pytest.raises(SizingRejected):
        size_long_position(1_000_000, 1_000_000, 500.0, 480.0, 20_000.0, settings)


@pytest.mark.parametrize("entry,stop", [(500.0, 500.0), (500.0, 510.0), (0.0, 1.0)])
def test_invalid_stops_are_rejected(settings, entry, stop):
    with pytest.raises(SizingRejected):
        size_long_position(1_000_000, 1_000_000, entry, stop, 0.0, settings)


def test_cash_limits_quantity(settings):
    plan = size_long_position(1_000_000, 10_000, 500.0, 499.0, 0.0, settings)
    assert plan.quantity * 500.0 <= 10_000


def test_round_trip_cost_positive(settings):
    assert round_trip_cost(100.0, 110.0, 10, settings["costs"]) > 0
