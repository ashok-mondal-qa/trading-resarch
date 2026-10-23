"""Append-only paper-trading journal (paper-journal skill).

JSON Lines under `journal/`, one file per month (by the record's UTC timestamp). Each record carries the
hash of the previous record, so any edit or deletion breaks the chain (`verify`). Past records are never
changed: a correction is a new record whose `refers_to` names the original id.

Record types: signal, rejection, order, fill, exit, deviation, lesson. The journal never holds credentials
or account identifiers; it describes simulated (paper) activity only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from trading_research.config import REPO_ROOT

TYPES = ("signal", "rejection", "order", "fill", "exit", "deviation", "lesson")
GENESIS = "0" * 64
DEFAULT_ROOT = REPO_ROOT / "journal"


class JournalError(ValueError):
    pass


def _digest(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class Journal:
    def __init__(self, root: Path = DEFAULT_ROOT):
        self.root = Path(root)

    def files(self) -> list[Path]:
        return sorted(self.root.glob("*.jsonl"))

    def records(self) -> list[dict]:
        out = []
        for path in self.files():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def append(self, kind: str, strategy: str, strategy_version: str, data: dict,
               refers_to: str | None = None, now_utc: datetime | None = None) -> dict:
        if kind not in TYPES:
            raise JournalError(f"unknown record type {kind!r}")
        if not strategy or not strategy_version:
            raise JournalError("strategy and strategy_version are mandatory on every record")
        existing = self.records()
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
        record = {
            "id": f"{now:%Y%m%dT%H%M%SZ}-{len(existing) + 1:06d}",
            "type": kind,
            "recorded_at_utc": now.isoformat(),
            "strategy": strategy,
            "strategy_version": strategy_version,
            "refers_to": refers_to,
            "data": data,
            "prev_hash": existing[-1]["hash"] if existing else GENESIS,
        }
        record["hash"] = _digest(record)
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / f"{now:%Y-%m}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return record

    def get(self, record_id: str) -> dict:
        for record in self.records():
            if record["id"] == record_id:
                return record
        raise JournalError(f"no record {record_id}")

    def verify(self) -> list[str]:
        """Problems found: broken hash chain, or a fill/order/exit without the record it must follow."""
        problems, prev, by_id = [], GENESIS, {}
        for record in self.records():
            if record.get("prev_hash") != prev:
                problems.append(f"{record.get('id')}: prev_hash does not match the previous record")
            if _digest(record) != record.get("hash"):
                problems.append(f"{record.get('id')}: content does not match its hash (edited?)")
            prev = record.get("hash")
            by_id[record["id"]] = record
            ref = by_id.get(record.get("refers_to") or "")
            if record["type"] == "order" and not (
                    ref and ref["type"] == "signal" and ref["data"].get("status") == "TRADE CANDIDATE"):
                problems.append(f"{record['id']}: order does not refer to a TRADE CANDIDATE signal")
            if record["type"] == "fill" and not (ref and ref["type"] == "order"):
                problems.append(f"{record['id']}: fill does not refer to an order")
            if record["type"] == "exit" and not (ref and ref["type"] == "fill"):
                problems.append(f"{record['id']}: exit does not refer to a fill")
        return problems
