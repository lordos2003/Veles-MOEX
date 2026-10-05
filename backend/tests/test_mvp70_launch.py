"""MVP-7.0 R1 launch-contract checks (item 8 of the acceptance).

Docker itself is not available in this environment, so the delivery contract
is verified statically over the repository files:

- every port published by docker-compose.yml is bound to 127.0.0.1;
- the backend service reads the root ``.env`` and runs Alembic before uvicorn;
- ``.env.example`` ships safe defaults (sandbox ON, live trading OFF).
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _compose_text() -> str:
    return (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_compose_ports_bound_to_localhost_only() -> None:
    text = _compose_text()
    mapped = re.findall(r'"(?P<host>[\d.]+):(?P<host_port>\d+):(?P<container_port>\d+)"', text)
    assert mapped, "docker-compose.yml must publish container ports"
    for host, host_port, _container_port in mapped:
        assert host == "127.0.0.1", f"port {host_port} must bind to 127.0.0.1, got {host}"


def test_compose_backend_reads_env_and_runs_migrations() -> None:
    text = _compose_text()
    services = text.split("services:")[1]
    backend = services.split("backend:")[1]
    assert "env_file:" in backend
    assert ".env" in backend
    assert "alembic upgrade head" in backend
    assert "uvicorn app.main:app" in backend


def test_env_example_safe_defaults() -> None:
    text = (_ROOT / ".env.example").read_text(encoding="utf-8")
    # R1: safe defaults — sandbox enabled, live trading disabled, no secret.
    assert re.search(r"^\s*TINVEST_SANDBOX=true", text, re.MULTILINE)
    assert re.search(r"^\s*LIVE_TRADING_ENABLED=false", text, re.MULTILINE)
    assert re.search(r"^\s*BACKTEST_MAX_CANDLES=\d+", text, re.MULTILINE)
