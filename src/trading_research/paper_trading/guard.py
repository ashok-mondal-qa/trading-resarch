"""Fail-closed execution guard.

There is no live broker adapter in this project. `get_broker` returns the paper
simulator only, and refuses unless both the config file and the TRADING_MODE
environment variable say "paper". Adding live execution requires a separate,
explicit authorization from the project owner and a new reviewed module; it must
never be added by relaxing this guard.
"""

from __future__ import annotations

import os
from typing import Any

from trading_research.config import load_settings

PAPER = "paper"


class LiveTradingDisabled(RuntimeError):
    """Raised for any attempt to obtain a non-paper execution path."""


def assert_paper_mode(settings: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> None:
    settings = load_settings() if settings is None else settings
    env = os.environ if env is None else env
    config_mode = settings.get("mode")
    env_mode = env.get("TRADING_MODE", PAPER)
    if config_mode != PAPER or env_mode != PAPER:
        raise LiveTradingDisabled(
            f"Execution is paper-only (config mode={config_mode!r}, TRADING_MODE={env_mode!r})."
        )


def get_broker(kind: str = PAPER, settings: dict[str, Any] | None = None, env: dict[str, str] | None = None):
    if kind != PAPER:
        raise LiveTradingDisabled(f"Broker kind {kind!r} is not available; only 'paper' exists.")
    assert_paper_mode(settings, env)
    from trading_research.paper_trading.simulator import PaperBroker

    return PaperBroker()
