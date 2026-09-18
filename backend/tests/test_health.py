"""Backend startup and /api/health tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_backend_starts_and_health_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
