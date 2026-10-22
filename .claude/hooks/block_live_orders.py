#!/usr/bin/env python3
"""PreToolUse hook: block writes that add live order placement or commit secrets.

Reads the Claude Code hook JSON on stdin. Exit code 2 blocks the tool call and
shows stderr to Claude. Test fixtures under tests/fixtures/ are exempt so the
hook itself can be tested.
"""

import json
import re
import sys

LIVE_ORDER_PATTERNS = [
    r"\bplace_order\s*\(",
    r"\bmodify_order\s*\(",
    r"api\.kite\.trade/orders",
    r"/orders/(regular|amo|co|iceberg|auction)",
    r"\bplace_gtt\s*\(",
]
SECRET_PATTERNS = [
    r"(?i)(api_secret|access_token|totp_secret|password)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]",
]


def text_of(tool_input: dict) -> str:
    parts = [tool_input.get(k, "") for k in ("content", "new_string", "command")]
    for edit in tool_input.get("edits", []) or []:
        parts.append(edit.get("new_string", ""))
    return "\n".join(p for p in parts if isinstance(p, str))


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool_input = event.get("tool_input", {}) or {}
    path = str(tool_input.get("file_path", ""))
    if "tests/fixtures/" in path.replace("\\", "/"):
        return 0
    text = text_of(tool_input)
    for pat in LIVE_ORDER_PATTERNS:
        if re.search(pat, text):
            print(f"Blocked: live order placement pattern {pat!r}. This project is paper-only.", file=sys.stderr)
            return 2
    for pat in SECRET_PATTERNS:
        if re.search(pat, text):
            print("Blocked: looks like a hard-coded secret. Use environment variables.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
