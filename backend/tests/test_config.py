"""Configuration loading tests."""

from __future__ import annotations

from app.core.config import Settings, get_settings


def test_default_settings_load() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.app_name == "Veles-MOEX"


def test_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "Veles-MOEX-Test")
    monkeypatch.setenv("ENVIRONMENT", "test")

    # Cache must be cleared so the new env is picked up.
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.app_name == "Veles-MOEX-Test"
        assert settings.environment == "test"
    finally:
        get_settings.cache_clear()


# --- P3 (MVP-7.3): list fields accept comma-separated string or JSON array ---


def test_cors_origins_json_array(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://a", "http://b"]')
    settings = Settings()
    assert settings.cors_origins == ["http://a", "http://b"]


def test_cors_origins_comma_separated(monkeypatch) -> None:
    # The .env.example value: not JSON — must not crash startup.
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    settings = Settings()
    assert settings.cors_origins == ["http://localhost:5173"]


def test_cors_origins_empty_string(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "")
    settings = Settings()
    assert settings.cors_origins == []


def test_risk_blocked_instruments_json_array(monkeypatch) -> None:
    monkeypatch.setenv("RISK_BLOCKED_INSTRUMENTS", '["BBG004730N88"]')
    settings = Settings()
    assert settings.risk_blocked_instruments == ["BBG004730N88"]


def test_risk_blocked_instruments_empty_string(monkeypatch) -> None:
    # Unset in .env: blank value must not break startup (P3).
    monkeypatch.setenv("RISK_BLOCKED_INSTRUMENTS", "")
    settings = Settings()
    assert settings.risk_blocked_instruments == []
