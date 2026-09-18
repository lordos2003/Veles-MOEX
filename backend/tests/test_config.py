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
