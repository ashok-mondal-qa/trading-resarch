"""Symbol-change tests. Rows are SYNTHETIC fixtures (fake tickers), not NSE data."""

import pandas as pd

from trading_research.data import symbols

CSV = b"""NAME OF THE COMPANY,OLD SYMBOL,NEW SYMBOL,EFFECTIVE DATE
New Co Ltd,MIDCO,NEWCO,10-JAN-2025
Mid Co Ltd,OLDCO,MIDCO,06-JAN-2025
,BLANK1,BLANK2,
Other Ltd,OTHERA,OTHERB,08-JAN-2025
"""


def bars(symbol, dates, isin="INE000TEST01"):
    return pd.DataFrame({"date": pd.to_datetime(dates), "symbol": symbol, "series": "EQ", "isin": isin,
                         "close": 100.0})


def changes():
    return symbols.parse_symbol_changes(CSV)


def test_parse_drops_rows_without_date_and_chains_predecessors():
    c = changes()
    assert len(c) == 3
    chain = symbols.predecessors("NEWCO", c)
    assert [(l["old_symbol"], l["new_symbol"]) for l in chain] == [("MIDCO", "NEWCO"), ("OLDCO", "MIDCO")]


def test_confirmed_renames_are_joined_and_relabelled():
    raw = pd.concat([bars("OLDCO", ["2025-01-02", "2025-01-03"]), bars("MIDCO", ["2025-01-06", "2025-01-09"]),
                     bars("NEWCO", ["2025-01-10", "2025-01-13"])])
    history = symbols.join_history("NEWCO", raw, changes())
    assert [l["status"] for l in history.links] == ["confirmed", "confirmed"]
    assert len(history.bars) == 6 and set(history.bars["symbol"]) == {"NEWCO"}
    assert list(history.bars["raw_symbol"]) == ["OLDCO", "OLDCO", "MIDCO", "MIDCO", "NEWCO", "NEWCO"]


def test_isin_mismatch_is_not_joined():
    raw = pd.concat([bars("MIDCO", ["2025-01-09"], isin="INE999OTHER1"), bars("NEWCO", ["2025-01-10"])])
    history = symbols.join_history("NEWCO", raw, changes())
    assert history.links[0]["status"] == "unconfirmed" and "ISIN" in history.links[0]["reason"]
    assert list(history.bars["raw_symbol"]) == ["NEWCO"]


def test_dates_must_bracket_the_change():
    raw = pd.concat([bars("MIDCO", ["2025-01-13"]), bars("NEWCO", ["2025-01-10"])])
    history = symbols.join_history("NEWCO", raw, changes())
    assert history.links[0]["status"] == "unconfirmed"
    assert len(history.bars) == 1


def test_symbol_without_renames_is_unchanged():
    raw = pd.concat([bars("UNRELATED", ["2025-01-02"]), bars("OTHERB", ["2025-01-10"])])
    history = symbols.join_history("OTHERB", raw, changes())
    assert history.links[0]["reason"] == "no bars for one side in loaded data"
    assert len(history.bars) == 1
    history = symbols.join_history("PLAIN", bars("PLAIN", ["2025-01-10"]), changes())
    assert history.links == [] and len(history.bars) == 1


def test_rename_before_loaded_data_is_not_an_error():
    history = symbols.join_history("NEWCO", bars("NEWCO", ["2025-02-03"]), changes())
    assert history.links[0]["status"] == "before loaded range"
    assert len(history.bars) == 1
