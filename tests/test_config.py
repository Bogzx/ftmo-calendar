from pathlib import Path

import pytest

from ftmo_calendar.config import ConfigError, load_config


def test_defaults_without_config_file(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "config.toml", env={})
    assert cfg.source.url == "https://ftmo.com/en/trading-updates/"
    assert cfg.llm.provider == "gemini"
    assert cfg.calendar.auth_mode == "oauth"
    assert cfg.calendar.reminders_minutes == (60, 10)
    assert cfg.base_dir == tmp_path
    assert cfg.state_path == tmp_path / "state.json"


def test_toml_overrides(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        """
[llm]
provider = "openai-compatible"
base_url = "https://openrouter.ai/api/v1"
models = ["google/gemini-2.5-flash"]

[calendar]
auth_mode = "service_account"
calendar_id = "abc@group.calendar.google.com"
reminders_minutes = [30]

[events.summaries]
maintenance = "Platform down"
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "config.toml", env={})
    assert cfg.llm.provider == "openai-compatible"
    assert cfg.llm.models == ("google/gemini-2.5-flash",)
    assert cfg.calendar.calendar_id == "abc@group.calendar.google.com"
    assert cfg.calendar.reminders_minutes == (30,)
    assert cfg.events.summaries["maintenance"] == "Platform down"
    assert cfg.events.summaries["other"]  # defaults still merged


def test_api_key_from_env(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "config.toml", env={"LLM_API_KEY": "k1"})
    assert cfg.llm.api_key == "k1"
    legacy = load_config(tmp_path / "config.toml", env={"GEMINI_API_KEY": "k2"})
    assert legacy.llm.api_key == "k2"


def test_service_account_requires_calendar_id(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        '[calendar]\nauth_mode = "service_account"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="calendar_id"):
        load_config(tmp_path / "config.toml", env={})


def test_invalid_provider_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[llm]\nprovider = "magic"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="provider"):
        load_config(tmp_path / "config.toml", env={})


def test_config_with_utf8_bom_loads(tmp_path: Path) -> None:
    """Notepad and PowerShell write UTF-8 with a BOM; tomllib alone rejects it."""
    (tmp_path / "config.toml").write_bytes(b'\xef\xbb\xbf[llm]\nprovider = "gemini"\n')
    cfg = load_config(tmp_path / "config.toml", env={})
    assert cfg.llm.provider == "gemini"


def test_invalid_timezone_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[source]\ntimezone = "Mars/Olympus"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="timezone"):
        load_config(tmp_path / "config.toml", env={})
