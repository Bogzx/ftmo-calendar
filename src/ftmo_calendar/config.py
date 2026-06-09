"""Configuration loading: config.toml with environment-variable overrides for secrets."""

from __future__ import annotations

import dataclasses
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    """Invalid or missing configuration."""


DEFAULT_SUMMARIES: dict[str, str] = {
    "maintenance": "⚠️ FTMO Platform Maintenance",
    "crypto_closure": "🚫 Crypto Market Closed",
    "holiday_hours": "🕒 Modified Trading Hours",
    "other": "ℹ️ FTMO Trading Update",
}


@dataclass(frozen=True)
class SourceConfig:
    url: str = "https://ftmo.com/en/trading-updates/"
    keywords: tuple[str, ...] = ("maintenance", "market is closed", "ctrader", "holiday", "crypto")
    timezone: str = "Europe/Bucharest"
    max_posts: int = 4
    max_age_days: int = 14


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "gemini"  # "gemini" | "openai-compatible"
    base_url: str = ""  # e.g. https://openrouter.ai/api/v1
    models: tuple[str, ...] = ("gemini-2.5-flash", "gemini-2.0-flash")
    api_key: str = ""  # from LLM_API_KEY / GEMINI_API_KEY env, never from TOML


@dataclass(frozen=True)
class CalendarConfig:
    auth_mode: str = "oauth"  # "oauth" | "service_account"
    name: str = "Trading"
    calendar_id: str = ""  # required for service_account; optional override for oauth
    timezone: str = "Europe/Bucharest"
    reminders_minutes: tuple[int, ...] = (60, 10)
    credentials_file: str = "credentials.json"
    token_file: str = "token.json"
    service_account_file: str = "service_account.json"


@dataclass(frozen=True)
class NotifyConfig:
    on_events: bool = True
    on_errors: bool = True
    heartbeat_hours: int = 0  # 0 = heartbeat disabled
    # Channel secrets come from env vars, never from TOML:
    discord_webhook_url: str = ""  # DISCORD_WEBHOOK_URL
    telegram_bot_token: str = ""  # TELEGRAM_BOT_TOKEN
    telegram_chat_id: str = ""  # TELEGRAM_CHAT_ID


@dataclass(frozen=True)
class EventRules:
    max_duration_hours: int = 48
    max_days_ahead: int = 120
    summaries: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SUMMARIES))


@dataclass(frozen=True)
class AppConfig:
    source: SourceConfig
    llm: LLMConfig
    calendar: CalendarConfig
    events: EventRules
    base_dir: Path
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    @property
    def state_path(self) -> Path:
        return self.base_dir / "state.json"

    def resolve(self, filename: str) -> Path:
        """Resolve a configured filename relative to the config directory."""
        p = Path(filename)
        return p if p.is_absolute() else self.base_dir / p


def _section(cls: type, data: dict, name: str):  # noqa: ANN202 - generic dataclass factory
    raw = data.get(name, {})
    if not isinstance(raw, dict):
        raise ConfigError(f"[{name}] must be a TOML table")
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in raw:
            value = raw[f.name]
            if isinstance(value, list):
                value = tuple(value)
            kwargs[f.name] = value
    try:
        return cls(**kwargs)
    except TypeError as e:
        raise ConfigError(f"invalid [{name}] section: {e}") from e


def _validate(cfg: AppConfig) -> None:
    if cfg.llm.provider not in ("gemini", "openai-compatible"):
        raise ConfigError(
            f"unknown llm provider {cfg.llm.provider!r}; use 'gemini' or 'openai-compatible'"
        )
    if cfg.calendar.auth_mode not in ("oauth", "service_account"):
        raise ConfigError(
            f"unknown auth_mode {cfg.calendar.auth_mode!r}; use 'oauth' or 'service_account'"
        )
    if cfg.calendar.auth_mode == "service_account" and not cfg.calendar.calendar_id:
        raise ConfigError(
            "calendar.calendar_id is required with auth_mode='service_account' — create the "
            "calendar in Google Calendar, share it with the service account email, and put its "
            "ID here"
        )
    if not cfg.llm.models:
        raise ConfigError("llm.models must list at least one model")
    for tz_name in (cfg.source.timezone, cfg.calendar.timezone):
        try:
            ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ConfigError(f"invalid timezone {tz_name!r}: {e}") from e


def load_config(path: Path, env: Mapping[str, str] | None = None) -> AppConfig:
    """Load config from a TOML file (all keys optional) plus env-var secrets.

    A missing file is fine — every setting has a default. The config file's
    directory becomes the base for relative paths (token, state, …).
    """
    env_map = dict(os.environ if env is None else env)
    data: dict = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"cannot parse {path}: {e}") from e

    source = _section(SourceConfig, data, "source")
    llm = _section(LLMConfig, data, "llm")
    calendar = _section(CalendarConfig, data, "calendar")

    events_raw = data.get("events", {})
    if not isinstance(events_raw, dict):
        raise ConfigError("[events] must be a TOML table")
    summaries = {**DEFAULT_SUMMARIES, **events_raw.get("summaries", {})}
    events = EventRules(
        max_duration_hours=events_raw.get("max_duration_hours", EventRules.max_duration_hours),
        max_days_ahead=events_raw.get("max_days_ahead", EventRules.max_days_ahead),
        summaries=summaries,
    )

    api_key = env_map.get("LLM_API_KEY", "") or env_map.get("GEMINI_API_KEY", "")
    llm = dataclasses.replace(llm, api_key=api_key)

    notify = _section(NotifyConfig, data, "notify")
    notify = dataclasses.replace(
        notify,
        discord_webhook_url=env_map.get("DISCORD_WEBHOOK_URL", ""),
        telegram_bot_token=env_map.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=env_map.get("TELEGRAM_CHAT_ID", ""),
    )

    cfg = AppConfig(
        source=source,
        llm=llm,
        calendar=calendar,
        events=events,
        base_dir=path.resolve().parent,
        notify=notify,
    )
    _validate(cfg)
    return cfg
