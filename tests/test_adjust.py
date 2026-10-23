"""Split/bonus adjustment tests. All prices are SYNTHETIC fixtures, not NSE data."""

import json

import pandas as pd
import pytest

from trading_research.data import adjust, corporate_actions


def bars(closes, start="2025-01-01", opens=None):
    dates = pd.bdate_range(start, periods=len(closes))
    opens = opens or closes
    return pd.DataFrame({
        "date": dates, "symbol": "TESTA", "series": "EQ",
        "open": opens, "high": [max(o, c) * 1.01 for o, c in zip(opens, closes)],
        "low": [min(o, c) * 0.99 for o, c in zip(opens, closes)], "close": closes,
        "volume": pd.array([1000] * len(closes), dtype="Int64"),
    })


def record(*actions):
    return {"source": "test", "retrieved_at_utc": "2026-10-23T00:00:00+00:00", "from": "2020-01-01",
            "to": "2030-01-01", "actions": [
                {"exDate": d, "actionType": t, "purpose": p, "adjustmentFactor": f} for d, t, p, f in actions]}


def test_bonus_is_adjusted_backward_and_checks_pass():
    raw = bars([200, 202, 101, 102])  # bonus 1:1 effective on the 3rd bar (2025-01-03)
    result = adjust.build_adjusted("TESTA", raw, record(("2025-01-03", "BONUS", "Bonus 1:1", 0.5)))
    adj = result.bars
    assert list(adj["adj_close"]) == [100, 101, 101, 102]
    assert list(adj["close"]) == [200, 202, 101, 102]  # raw kept
    assert list(adj["adj_volume"]) == [2000, 2000, 1000, 1000]
    assert result.manifest["status"] == "ok" and result.manifest["issues"] == []
    assert result.manifest["valid_from"] == "2025-01-01"


def test_same_day_bonus_and_split_multiply():
    raw = bars([1000, 1000, 100, 100])
    result = adjust.build_adjusted("TESTA", raw, record(
        ("2025-01-03", "BONUS", "Bonus 4:1", 0.2), ("2025-01-03", "SPLIT", "Split 2 to 1", 0.5)))
    assert list(result.bars["adj_close"]) == pytest.approx([100, 100, 100, 100])
    assert result.manifest["status"] == "ok"
    assert result.manifest["price_events_applied"][0]["factor"] == pytest.approx(0.1)


def test_dividends_are_not_adjusted():
    raw = bars([100, 101, 99, 100])
    result = adjust.build_adjusted("TESTA", raw, record(("2025-01-03", "DIVIDEND", "Dividend Rs 2", 1.0)))
    assert list(result.bars["adj_close"]) == [100, 101, 99, 100]
    assert result.manifest["status"] == "ok"


def test_factor_that_disagrees_with_prices_cuts_the_series():
    raw = bars([200, 202, 200, 201])  # no price drop although a 1:1 bonus is claimed
    result = adjust.build_adjusted("TESTA", raw, record(("2025-01-03", "BONUS", "Bonus 1:1", 0.5)))
    kinds = {i["kind"] for i in result.manifest["issues"]}
    assert "factor inconsistent with prices" in kinds
    assert result.manifest["status"] == "partial" and result.manifest["valid_from"] == "2025-01-06"
    assert list(result.bars["usable"]) == [False, False, False, True]


def test_missing_corporate_action_is_flagged_as_unexplained_jump():
    raw = bars([200, 202, 101, 102])
    result = adjust.build_adjusted("TESTA", raw, record())
    assert result.manifest["issues"][0]["kind"] == "unexplained jump"
    assert result.manifest["valid_from"] == "2025-01-06"


def test_demerger_with_factor_one_is_flagged_not_guessed():
    raw = bars([200, 202, 190, 191])
    result = adjust.build_adjusted("TESTA", raw, record(("2025-01-03", "OTHER", "Demerger", 1.0)))
    assert result.manifest["issues"][0]["kind"] == "price-changing event not adjusted"
    assert list(result.bars["adj_close"]) == [200, 202, 190, 191]
    assert result.manifest["valid_from"] == "2025-01-06"


def test_error_on_last_bar_means_data_insufficient():
    raw = bars([200, 202, 101])
    result = adjust.build_adjusted("TESTA", raw, record())
    assert result.manifest["status"] == "DATA INSUFFICIENT" and result.manifest["valid_from"] is None
    assert not result.bars["usable"].any()


def test_action_cache_is_reused_and_refreshed_when_range_grows(tmp_path):
    calls = []

    def fake_fetch(symbol, start, end):
        calls.append((start, end))
        return dict(record(), symbol=symbol, **{"from": start.isoformat(), "to": end.isoformat()})

    from datetime import date
    corporate_actions.load_actions("TESTA", date(2024, 1, 1), date(2025, 1, 1), tmp_path, fetch=fake_fetch)
    corporate_actions.load_actions("TESTA", date(2024, 6, 1), date(2024, 12, 1), tmp_path, fetch=fake_fetch)
    assert len(calls) == 1
    corporate_actions.load_actions("TESTA", date(2024, 1, 1), date(2026, 1, 1), tmp_path, fetch=fake_fetch)
    assert len(calls) == 2
    cached = json.loads(corporate_actions.cache_path("TESTA", tmp_path).read_text())
    assert cached["to"] == "2026-01-01"
