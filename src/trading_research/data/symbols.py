"""NSE symbol changes (renames), so one company's history is joined across tickers.

Source: NSE's official list nsearchives.nseindia.com/content/equities/symbolchange.csv
(columns: company name, old symbol, new symbol, effective date). A rename is only used to join bars when
our own bhavcopy data confirms it: the old symbol's last bar is before the effective date, the new
symbol's first bar is on/after it, and both carry the same ISIN around the change. Unconfirmed links are
reported, never joined.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from trading_research.config import REPO_ROOT
from trading_research.data import bhavcopy

SYMBOL_CHANGE_URL = f"{bhavcopy.ARCHIVE_HOST}/content/equities/symbolchange.csv"


def raw_path(root: Path) -> Path:
    return root / "raw" / "reference" / "symbolchange.csv"


def manifest_path(root: Path) -> Path:
    return root / "manifests" / "reference" / "symbolchange.json"


def refresh_symbol_changes(root: Path = REPO_ROOT / "data", fetch=bhavcopy.http_fetch) -> dict:
    raw = fetch(SYMBOL_CHANGE_URL)
    if raw is None:
        raise bhavcopy.BhavcopyError(f"{SYMBOL_CHANGE_URL} not found")
    changes = parse_symbol_changes(raw)
    path = raw_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    manifest = {
        "dataset": "nse_symbol_changes",
        "provider": "NSE archive",
        "source_url": SYMBOL_CHANGE_URL,
        "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "rows": int(len(changes)),
        "latest_effective_date": changes["effective_date"].max().date().isoformat() if len(changes) else None,
        "terms": bhavcopy.TERMS_NOTE,
    }
    mpath = manifest_path(root)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_symbol_changes(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="latin-1")
    df.columns = [c.strip().upper() for c in df.columns]
    out = pd.DataFrame({
        "company": df["NAME OF THE COMPANY"].str.strip(),
        "old_symbol": df["OLD SYMBOL"].str.strip().str.upper(),
        "new_symbol": df["NEW SYMBOL"].str.strip().str.upper(),
        "effective_date": pd.to_datetime(df["EFFECTIVE DATE"].str.strip(), format="%d-%b-%Y", errors="coerce"),
    })
    out = out[(out["old_symbol"] != "") & (out["new_symbol"] != "") & out["effective_date"].notna()]
    return out.drop_duplicates().sort_values("effective_date").reset_index(drop=True)


def load_symbol_changes(root: Path = REPO_ROOT / "data") -> pd.DataFrame:
    path = raw_path(root)
    if not path.exists():
        raise bhavcopy.BhavcopyError("symbol change list not downloaded; run refresh_symbol_changes()")
    return parse_symbol_changes(path.read_bytes())


def predecessors(symbol: str, changes: pd.DataFrame, max_depth: int = 10) -> list[dict]:
    """Earlier tickers of `symbol`, newest first, as listed by NSE (not yet confirmed against prices)."""
    chain, current, seen = [], symbol.upper(), {symbol.upper()}
    for _ in range(max_depth):
        rows = changes[changes["new_symbol"] == current]
        if rows.empty:
            break
        row = rows.iloc[-1]  # latest rename into `current`
        if row["old_symbol"] in seen:
            break
        chain.append({"old_symbol": row["old_symbol"], "new_symbol": current,
                      "effective_date": row["effective_date"]})
        seen.add(row["old_symbol"])
        current = row["old_symbol"]
    return chain


@dataclass
class SymbolHistory:
    bars: pd.DataFrame
    links: list[dict]


def join_history(symbol: str, raw: pd.DataFrame, changes: pd.DataFrame,
                 calendar_start: pd.Timestamp | None = None) -> SymbolHistory:
    """Bars of `symbol` plus confirmed predecessors, relabelled to `symbol` (original kept in raw_symbol)."""
    parts = [raw[raw["symbol"] == symbol].assign(raw_symbol=symbol)]
    links = []
    newer = parts[0]
    for link in predecessors(symbol, changes):
        old = raw[raw["symbol"] == link["old_symbol"]]
        eff = link["effective_date"]
        record = {"old_symbol": link["old_symbol"], "new_symbol": link["new_symbol"],
                  "effective_date": eff.date().isoformat()}
        reason = None
        first_loaded = calendar_start if calendar_start is not None else (
            raw["date"].min() if not raw.empty else None)
        if old.empty and first_loaded is not None and eff <= first_loaded:
            record["status"] = "before loaded range"
            links.append(record)
            break
        if old.empty or newer.empty:
            reason = "no bars for one side in loaded data"
        elif not (old["date"].max() < eff <= newer["date"].min()):
            reason = (f"dates do not bracket the change (old last {old['date'].max().date()}, "
                      f"new first {newer['date'].min().date()})")
        else:
            old_isin = old.sort_values("date")["isin"].iloc[-1]
            new_isin = newer.sort_values("date")["isin"].iloc[0]
            if old_isin != new_isin:
                reason = f"ISIN differs ({old_isin} vs {new_isin})"
        record["status"] = "confirmed" if reason is None else "unconfirmed"
        if reason:
            record["reason"] = reason
        links.append(record)
        if reason:
            break  # never join across an unconfirmed link, nor anything older than it
        old = old.assign(raw_symbol=link["old_symbol"])
        parts.append(old)
        newer = old
    bars = pd.concat(parts, ignore_index=True).assign(symbol=symbol)
    return SymbolHistory(bars.sort_values("date").reset_index(drop=True), links)
