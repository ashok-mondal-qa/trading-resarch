"""Forward-tracking rule tests (no market data)."""

from datetime import date

import pytest

from trading_research.backtesting import run_forward as rf
from trading_research.backtesting.run_swing_ideas import ci_key


def runs(pt=35, open_=0, pe=0.2, pf=1.3, st=60, ci=(0.01, 0.5), s2=0.1):
    return {"portfolio_2x_costs": {"trades": pt, "open_at_end": open_, "expectancy_r_all_incl_open": pe, "profit_factor": pf},
            "standalone_1x": {"trades": st, "open_at_end": 0, ci_key(rf.ALPHA): ci},
            "standalone_2x_costs": {"expectancy_r_all_incl_open": s2}}


def test_tracking_until_twelve_months_and_thirty_trades():
    assert rf.decide(runs(), 11.9) == "tracking"
    assert rf.decide(runs(pt=20), 13) == "tracking"
    assert rf.decide(runs(pt=20, open_=10), 13).startswith("PASSED")


def test_pass_and_reject_rules():
    assert rf.decide(runs(), 12).startswith("PASSED")
    assert rf.decide(runs(ci=(-0.01, 0.5)), 12) == "REJECTED"
    assert rf.decide(runs(pf=1.05), 12) == "REJECTED"
    assert rf.decide(runs(s2=-0.01), 12) == "REJECTED"
    assert rf.decide(runs(st=40), 12) == "REJECTED"


def test_too_few_trades_after_two_years_is_a_rejection():
    assert rf.decide(runs(pt=10), 24) == "REJECTED"


def test_nothing_before_the_forward_start():
    with pytest.raises(SystemExit):
        rf.run("crypto", date(2026, 10, 25))
    assert rf.months_between(rf.FORWARD_START, date(2027, 10, 26)) == pytest.approx(12, abs=0.05)
