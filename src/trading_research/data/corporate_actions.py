"""Corporate actions (splits, bonuses, dividends, ...) per symbol from the NSE bhavcopy MCP server.

The server's `get_corporate_actions` returns ex-dates and an `adjustmentFactor` (e.g. bonus 1:1 -> 0.5).
Each fetch is cached under data/raw/corporate_actions/ with its retrieval time, and factors are checked
against the raw prices in `adjust.verify_adjustment` before use; they are never taken on trust.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import nse_mcp

ACTION_COLUMNS = ["ex_date", "action_type", "purpose", "factor"]

# Events that change the price per share but for which the server reports factor 1.0 (or none we trust).
# They are not adjusted; the adjustment check flags them so affected windows are excluded, not guessed.
UNADJUSTED_PRICE_EVENTS = ("demerger", "scheme of arrangement", "amalgamation", "rights", "capital reduction")


def cache_path(symbol: str, root: Path = REPO_ROOT / "data") -> Path:
    return root / "raw" / "corporate_actions" / f"{symbol}.json"


def fetch_actions(symbol: str, start: date, end: date, transport: nse_mcp.Transport = nse_mcp.http_transport,
                  attempts: int = 8, pause_s: float = 1.0) -> dict:
    """Raw server reply plus provenance. Backend errors are retried (see nse_mcp)."""
    last_error = ""
    for attempt in range(attempts):
        text = nse_mcp.call_tool(nse_mcp.BHAVCOPY_URL, "get_corporate_actions",
                                 {"symbol": symbol, "fromDate": start.isoformat(), "toDate": end.isoformat()},
                                 transport)
        reply = json.loads(text)
        if "error" not in reply:
            return {
                "symbol": symbol,
                "source": f"MCP {nse_mcp.BHAVCOPY_URL} get_corporate_actions",
                "from": start.isoformat(),
                "to": end.isoformat(),
                "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "actions": reply.get("actions", []),
            }
        last_error = reply["error"]
        if attempt + 1 < attempts and pause_s:
            time.sleep(pause_s)
    raise nse_mcp.McpError(f"get_corporate_actions {symbol}: {last_error} (after {attempts} attempts)")


def load_actions(symbol: str, start: date, end: date, root: Path = REPO_ROOT / "data",
                 refresh: bool = False, fetch=fetch_actions) -> dict:
    """Cached fetch. Re-fetches when asked, or when the cache does not cover [start, end]."""
    path = cache_path(symbol, root)
    if path.exists() and not refresh:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached["from"] <= start.isoformat() and cached["to"] >= end.isoformat():
            return cached
    record = fetch(symbol, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def actions_frame(record: dict) -> pd.DataFrame:
    rows = [{
        "ex_date": pd.Timestamp(a["exDate"]),
        "action_type": str(a.get("actionType", "")).upper(),
        "purpose": str(a.get("purpose", "")),
        "factor": float(a.get("adjustmentFactor", 1.0)),
    } for a in record.get("actions", [])]
    return pd.DataFrame(rows, columns=ACTION_COLUMNS).sort_values("ex_date").reset_index(drop=True)
