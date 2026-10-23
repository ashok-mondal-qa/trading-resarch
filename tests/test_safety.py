import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from trading_research.config import ConfigError, load_settings, validate_settings
from trading_research.paper_trading.guard import LiveTradingDisabled, assert_paper_mode, get_broker

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block_live_orders.py"


@pytest.fixture
def settings():
    return load_settings()


def test_repo_config_is_paper_only(settings):
    assert settings["mode"] == "paper"


def test_get_broker_returns_paper_simulator(settings):
    broker = get_broker(settings=settings, env={"TRADING_MODE": "paper"})
    assert broker.is_paper is True


@pytest.mark.parametrize("kind", ["live", "kite", "zerodha", "LIVE", ""])
def test_live_broker_kinds_are_refused(kind, settings):
    with pytest.raises(LiveTradingDisabled):
        get_broker(kind, settings=settings, env={"TRADING_MODE": "paper"})


def test_env_mode_live_is_refused(settings):
    with pytest.raises(LiveTradingDisabled):
        assert_paper_mode(settings, env={"TRADING_MODE": "live"})


def test_config_mode_live_is_refused(settings):
    bad = {**settings, "mode": "live"}
    with pytest.raises(LiveTradingDisabled):
        assert_paper_mode(bad, env={"TRADING_MODE": "paper"})
    with pytest.raises(ConfigError):
        validate_settings(bad)


@pytest.mark.parametrize("key,value", [
    ("max_risk_per_position_pct", 1.0),
    ("max_aggregate_open_risk_pct", 5.0),
    ("max_new_candidates_per_day", 3),
    ("allow_leverage", True),
    ("allow_averaging_down", True),
    ("allow_stop_widening", True),
])
def test_risk_limits_cannot_be_loosened(settings, key, value):
    bad = copy.deepcopy(settings)
    bad["risk"][key] = value
    with pytest.raises(ConfigError):
        validate_settings(bad)


def run_hook(tool_input):
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_input": tool_input}),
                          capture_output=True, text=True)
    return proc.returncode, proc.stderr


def test_hook_blocks_live_order_code():
    # Built at runtime so this test file itself does not trip the hook.
    snippet = "kite." + "place_order" + "(variety='regular')"
    code, err = run_hook({"file_path": "src/x.py", "content": snippet})
    assert code == 2 and "paper-only" in err


def test_hook_blocks_hardcoded_secret():
    snippet = "api_" + "secret = 'abcd1234efgh5678'"
    code, _ = run_hook({"file_path": "src/x.py", "content": snippet})
    assert code == 2


def test_hook_allows_normal_code():
    code, _ = run_hook({"file_path": "src/x.py", "content": "def atr(df):\n    return df"})
    assert code == 0


def _hook_patterns():
    import importlib.util
    spec = importlib.util.spec_from_file_location("block_live_orders", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LIVE_ORDER_PATTERNS


def test_no_live_order_code_anywhere_in_src():
    import re
    src = Path(__file__).resolve().parents[1] / "src"
    hits = [f"{path.name}: {pattern}" for path in src.rglob("*.py") for pattern in _hook_patterns()
            if re.search(pattern, path.read_text(encoding="utf-8"))]
    assert hits == []


@pytest.mark.parametrize("module", ["simulator.py", "journal.py", "guard.py"])
def test_paper_trading_modules_have_no_network_client(module):
    text = (Path(__file__).resolve().parents[1] / "src" / "trading_research" / "paper_trading" / module).read_text()
    for marker in ("urllib", "requests", "http.client", "socket", "kiteconnect", "websocket"):
        assert marker not in text, f"{module} mentions {marker}"
