"""Minimal read-only client for NSE's public MCP servers (streamable HTTP, JSON-RPC 2.0).

Used to cross-check archive bhavcopy bars, not as the primary store. Observed 2026-10-23: the servers sit
behind a load balancer without session affinity, so a call can fail with "Session not found"; the client
re-initialises and retries. Some backends also lack older history and answer
{"error": "Symbol not found: ..."} for dates other backends serve (6 of 10 calls for RELIANCE 2023-10-20),
so tool-level errors are retried too and never read as "no bar".
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Callable

import pandas as pd

BHAVCOPY_URL = "https://mcp.nseindia.in/bhavcopy/cm/mcp"
CM_MARKET_URL = "https://mcp.nseindia.in/cmmkt/mcp"
PROTOCOL_VERSION = "2025-03-26"

# transport(url, payload, session_id) -> (status, headers, body_text)
Transport = Callable[[str, dict, "str | None"], "tuple[int, dict, str]"]


class McpError(RuntimeError):
    pass


def http_transport(url: str, payload: dict, session_id: str | None) -> tuple[int, dict, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read().decode(errors="replace")


def parse_rpc_body(body: str) -> dict:
    """Accept either a plain JSON body or an SSE stream (`data:` lines)."""
    body = body.strip()
    if body.startswith("{"):
        return json.loads(body)
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    raise McpError(f"unrecognised MCP response: {body[:200]!r}")


def call_tool(url: str, name: str, arguments: dict, transport: Transport = http_transport,
              attempts: int = 6, pause_s: float = 1.0) -> str:
    """Call one tool and return its text content. Retries on lost sessions."""
    last_error = ""
    for attempt in range(attempts):
        status, headers, body = transport(url, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "trading-research", "version": "0.1"}},
        }, None)
        session_id = headers.get("mcp-session-id")
        if status != 200 or not session_id:
            last_error = f"initialize failed: HTTP {status}"
        else:
            transport(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
            status, _, body = transport(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                              "params": {"name": name, "arguments": arguments}}, session_id)
            try:
                reply = parse_rpc_body(body)
            except (McpError, json.JSONDecodeError):
                reply = {}
            if "result" in reply:
                result = reply["result"]
                text = "".join(c.get("text", "") for c in result.get("content", []))
                if result.get("isError"):
                    raise McpError(f"{name} returned an error: {text[:300]}")
                return text
            last_error = reply.get("error") or reply.get("message") or f"HTTP {status}"
        if attempt + 1 < attempts and pause_s:
            time.sleep(pause_s)
    raise McpError(f"{name} failed after {attempts} attempts: {last_error}")


def stock_bar(symbol: str, day: date, transport: Transport = http_transport,
              attempts: int = 8, pause_s: float = 1.0) -> dict | None:
    """The MCP server's EOD bar for one symbol on one date, or None if its history has no bar that day.

    Raises McpError if every attempt hit a backend that answered with an error."""
    last_error = ""
    for attempt in range(attempts):
        text = call_tool(BHAVCOPY_URL, "get_stock_history",
                         {"symbol": symbol, "months": 1, "endDate": day.isoformat()}, transport)
        reply = json.loads(text)
        if "error" not in reply:
            for row in reply.get("data", []):
                if row.get("date") == day.isoformat():
                    return row
            return None
        last_error = reply["error"]
        if attempt + 1 < attempts and pause_s:
            time.sleep(pause_s)
    raise McpError(f"get_stock_history {symbol} {day}: {last_error} (after {attempts} attempts)")


def cross_check_day(day: date, symbols: list[str], bars: pd.DataFrame,
                    transport: Transport = http_transport, tolerance: float = 1e-6,
                    pause_s: float = 1.0) -> dict:
    """Compare stored archive bars (series EQ) with the MCP server for the same date."""
    fields = {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
    mismatches, unavailable = [], []
    eq = bars[bars["series"] == "EQ"].set_index("symbol")
    for symbol in symbols:
        try:
            remote = stock_bar(symbol, day, transport, pause_s=pause_s)
        except McpError as exc:
            unavailable.append({"symbol": symbol, "error": str(exc)})
            continue
        if symbol not in eq.index or remote is None:
            mismatches.append({"symbol": symbol, "field": "presence",
                               "archive": symbol in eq.index, "mcp": remote is not None})
            continue
        for ours, theirs in fields.items():
            a, b = float(eq.at[symbol, ours]), float(remote[theirs])
            if abs(a - b) > tolerance * max(1.0, abs(a)):
                mismatches.append({"symbol": symbol, "field": ours, "archive": a, "mcp": b})
    return {
        "source": f"MCP {BHAVCOPY_URL} get_stock_history",
        "checked_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "symbols": symbols,
        "status": "mismatch" if mismatches else ("incomplete" if unavailable else "match"),
        "mismatches": mismatches,
        "unavailable": unavailable,
    }
