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


def test_alembic_revision_ids_fit_version_column() -> None:
    """B2 (MVP-7.1 REV1): revision ids must fit ``alembic_version.version_num``.

    ``version_num`` is ``varchar(32)``; a longer revision id breaks
    ``alembic upgrade head`` on a clean PostgreSQL (StringDataRightTruncationError
    at migration ``0002``). Also check the chain has exactly one head.
    """
    versions_dir = _ROOT / "backend" / "alembic" / "versions"
    scripts = sorted(versions_dir.glob("*.py"))
    assert scripts, "alembic versions dir must contain migration scripts"

    revision_ids: list[str] = []
    down_revisions: list[str] = []
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        revision = re.search(r'^revision:\s*str\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert revision, f"{script.name}: missing revision id"
        assert len(revision.group(1)) <= 32, (
            f"{script.name}: revision id {revision.group(1)!r} is "
            f"{len(revision.group(1))} chars > 32 (alembic_version.version_num)"
        )
        revision_ids.append(revision.group(1))
        down = re.search(r'^down_revision:\s*[^=]*=\s*"([^"]+)"', text, re.MULTILINE)
        if down:
            down_revisions.append(down.group(1))

    heads = set(revision_ids) - set(down_revisions)
    assert len(heads) == 1, f"expected a single alembic head, got {sorted(heads)}"
