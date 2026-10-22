"""Load and validate config/settings.yaml. Fails closed on anything unexpected."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = REPO_ROOT / "config" / "settings.yaml"


class ConfigError(ValueError):
    pass


def load_settings(path: Path | str = DEFAULT_SETTINGS) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        settings = yaml.safe_load(fh)
    validate_settings(settings)
    return settings


def validate_settings(settings: dict[str, Any]) -> None:
    if settings.get("mode") != "paper":
        raise ConfigError(f"mode must be 'paper', got {settings.get('mode')!r}")
    risk = settings["risk"]
    for flag in ("allow_leverage", "allow_derivatives", "allow_averaging_down", "allow_stop_widening"):
        if risk.get(flag) is not False:
            raise ConfigError(f"risk.{flag} must be false in the paper research phase")
    per_pos = float(risk["max_risk_per_position_pct"])
    aggregate = float(risk["max_aggregate_open_risk_pct"])
    if not 0 < per_pos <= 0.5:
        raise ConfigError("risk.max_risk_per_position_pct must be in (0, 0.5]")
    if not 0 < aggregate <= 2.0 or aggregate < per_pos:
        raise ConfigError("risk.max_aggregate_open_risk_pct must be in (0, 2.0] and >= per-position risk")
    if int(risk["max_new_candidates_per_day"]) > 2:
        raise ConfigError("risk.max_new_candidates_per_day must be <= 2")
